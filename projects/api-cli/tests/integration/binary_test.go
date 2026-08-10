// Package integration 的 binary_test.go：iter4 Task 5 端到端 gate。
// 用 httptest.Server 起 upload（multipart 校验）+ download（固定 binary 返回），
// 走 engine.Execute 覆盖核心链路：spec schema → multipart 上传 → binary 下载落盘。
//
// 设计要点：
//
//  1. 不拉起完整 cobra 命令树（cobra 粘合已在 internal/cobracli/smoke_test 覆盖），
//     直接调 engine.Execute，专注 multipart/binary/落盘 三件套的端到端验证。
//
//  2. download 落盘模拟 cobracli globalOpts 的 --output 重定向：
//     os.Create(outFile) → 传 Options{Out: fout, OutCloser: fout} →
//     Execute 后 fout.Close()。证明 Task 4 的 Out/OutCloser 分层落盘生效。
//
//  3. binaryExampleManifest 是 block-style YAML（多行），path: /download/{id}
//     在此风格下安全（{id} 占位 bug 只在 flow style 触发）。server 注册
//     /download/abc 匹配 {id} → abc。
package integration

import (
	"bytes"
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/internal/engine"
	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

// TestBinaryUploadDownload 端到端：httptest server 起 upload + download，
// 走 engine.Execute 覆盖核心链路（spec schema → multipart 上传 → binary 下载落盘）。
func TestBinaryUploadDownload(t *testing.T) {
	payload := []byte{0x1f, 0x8b, 0x08, 0x00, 0xAA, 0xBB, 0xCC, 0xDD}
	srv := newBinaryTestServer(t, payload)
	defer srv.Close()

	// 渲染清单（${BINARY_DEMO_URL} 替换为 srv.URL）
	manifest := strings.ReplaceAll(binaryExampleManifest, "${BINARY_DEMO_URL}", srv.URL)
	tr, err := spec.Parse([]byte(manifest))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	ep, _ := tr.SelectEndpoint("")
	e := engine.New(tr)

	tmp := t.TempDir()
	upFile := filepath.Join(tmp, "pkg.tar.gz")
	if err := os.WriteFile(upFile, payload, 0o644); err != nil {
		t.Fatal(err)
	}

	// 1) upload：multipart，server 校验收到 file/size/kind；Execute 输出 server 回的 JSON
	var upOut bytes.Buffer
	if err := e.Execute(context.Background(), ep, tr.Resources["pkg"], opByName(tr, "upload"),
		nil, map[string]string{"file": upFile, "kind": "tool"},
		engine.Options{Format: "json", Out: &upOut}); err != nil {
		t.Fatalf("upload: %v", err)
	}
	if !strings.Contains(upOut.String(), "pkg.tar.gz") {
		t.Errorf("upload 响应未含文件名: %q", upOut.String())
	}

	// 2) download：binary，模拟 cobracli --output 落盘（os.Create → Out + OutCloser，Execute 后 Close）
	outFile := filepath.Join(tmp, "out.bin")
	fout, err := os.Create(outFile)
	if err != nil {
		t.Fatal(err)
	}
	err = e.Execute(context.Background(), ep, tr.Resources["pkg"], opByName(tr, "download"),
		map[string]string{"id": "abc"}, nil, engine.Options{Format: "json", Out: fout, OutCloser: fout})
	fout.Close()
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	got, _ := os.ReadFile(outFile)
	if !bytes.Equal(got, payload) {
		t.Errorf("下载落盘内容不一致：got %d bytes, want %d", len(got), len(payload))
	}
}

// opByName 取 pkg resource 的 operation（upload/download）。
func opByName(tr *tree.OperationTree, verb string) *tree.Operation {
	return tr.Resources["pkg"].Operations[verb]
}

// newBinaryTestServer 起 upload（ParseMultipartForm 回 JSON）+ download（回固定 binary）server。
func newBinaryTestServer(t *testing.T, payload []byte) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/upload", func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Errorf("ParseMultipartForm: %v", err)
			http.Error(w, err.Error(), 400)
			return
		}
		fh := r.MultipartForm.File["file"]
		name, size := "", 0
		if len(fh) == 1 {
			name = fh[0].Filename
			size = int(fh[0].Size)
		}
		kind := ""
		if v := r.MultipartForm.Value["kind"]; len(v) == 1 {
			kind = v[0]
		}
		fmt.Fprintf(w, `{"file":%q,"size":%d,"kind":%q}`, name, size, kind)
	})
	mux.HandleFunc("/download/abc", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/gzip")
		w.Write(payload)
	})
	return httptest.NewServer(mux)
}

// binaryExampleManifest 贴 examples/binary.yaml 内容（${BINARY_DEMO_URL} 占位）。
const binaryExampleManifest = `spec: api-cli/v1
service:
  name: binary-demo
  default_endpoint: backend
  endpoints:
    backend: { base_url: "${BINARY_DEMO_URL}", auth: none }
resources:
  pkg:
    description: 文件包
    operations:
      upload:
        description: 上传文件（multipart）
        method: POST
        path: /upload
        content_type: multipart-form-data
        params:
          file: { in: formData, format: binary, required: true, description: 要上传的文件 }
          kind: { in: formData, description: 文件类别 }
      download:
        description: 下载文件（binary 落盘）
        method: GET
        path: /download/{id}
        params:
          id: { in: path, type: string, required: true }
        response:
          format: binary
          description: 文件字节流
`
