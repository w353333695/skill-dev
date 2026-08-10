package engine

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"api-cli/internal/output"
	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

// newTree 构造一棵接 httptest 后端的 OperationTree。
// endpoint auth=none → engine 跳过 auth.Apply，避免读 ~/.api-cli/auth.d。
func newTree(t *testing.T) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service:
  name: cmdb
  default_endpoint: backend
  endpoints:
    backend: { base_url: REPLACEME, auth: none, path_prefix: /api/v1 }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { type: string, required: true, in: path } } }
`)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/instances/i-1" {
			w.Write([]byte(`{"id":"i-1","name":"n"}`))
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)
	raw = bytes.ReplaceAll(raw, []byte("REPLACEME"), []byte(srv.URL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return tr
}

// TestExecuteSingleRead 命中 mock 后端，断言输出含 id=i-1。
// 走完整链路：resolve → gateWrite(放行 read) → auth 跳过 → single → output.Format。
func TestExecuteSingleRead(t *testing.T) {
	tr := newTree(t)
	e := New(tr)
	r := tr.Resources["inst"]
	op := r.Operations["read"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, r, op,
		map[string]string{"id": "i-1"}, // pathVals
		map[string]string{},            // flags
		Options{Format: "json", Out: &out})
	if err != nil {
		t.Fatal(err)
	}
	// output.Format 用 json.Encoder.SetIndent → 实际打印 "id": "i-1"（冒号后有空格）。
	if !bytes.Contains(out.Bytes(), []byte(`"id": "i-1"`)) {
		t.Fatalf("output missing id: %s", out.String())
	}
}

// TestDryRunDoesNotCall 不命中 mock（dry-run 不真发），且输出含请求预览。
func TestDryRunDoesNotCall(t *testing.T) {
	tr := newTree(t)
	e := New(tr)
	r := tr.Resources["inst"]
	op := r.Operations["read"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, r, op,
		map[string]string{"id": "i-1"},
		map[string]string{},
		Options{DryRun: true, Out: &out})
	if err != nil {
		t.Fatal(err)
	}
	// 预览应含 DRY-RUN 标记或目标 URL；二者其一即可。
	if !bytes.Contains(out.Bytes(), []byte("DRY-RUN")) && !bytes.Contains(out.Bytes(), []byte("/api/v1/instances/i-1")) {
		t.Fatalf("dry-run should print request, got: %s", out.String())
	}
}

// TestDoHostHeaderFromHeader 验证 auth provider 回传的 "host" header 经 do 转写回 httpReq.Host
// 真正上到 wire（Go client 默认丢弃 Header map 里的 Host，必须显式写 req.Host）。
//
// 触发条件：resolvedReq.Header["host"] 非空（provider 返回 Headers{"host":...}，engine 合并进 req.Header）。
func TestDoHostHeaderFromHeader(t *testing.T) {
	var sawHost string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawHost = r.Host
		w.Write([]byte(`{}`))
	}))
	t.Cleanup(srv.Close)

	e := New(nil)
	req := &resolvedReq{
		Method: "GET",
		URL:    srv.URL + "/api/v1/ping",
		Header: map[string]string{"host": "openapi.easyops-only.com"},
	}
	if _, _, err := e.do(context.Background(), req, e.hc); err != nil {
		t.Fatal(err)
	}
	if sawHost != "openapi.easyops-only.com" {
		t.Fatalf("wire Host = %q, want openapi.easyops-only.com（host header 必须转写回 httpReq.Host）", sawHost)
	}
}

// TestDoHostHeaderFromEndpoint 验证 endpoint.Host（resolvedReq.Host）路径也正确设 httpReq.Host。
// 与上一测试互斥覆盖：两条路径（endpoint YAML host / provider host header）各自可达。
func TestDoHostHeaderFromEndpoint(t *testing.T) {
	var sawHost string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawHost = r.Host
		w.Write([]byte(`{}`))
	}))
	t.Cleanup(srv.Close)

	e := New(nil)
	req := &resolvedReq{
		Method: "GET",
		URL:    srv.URL + "/api/v1/ping",
		Host:   "via-endpoint.example.com",
	}
	if _, _, err := e.do(context.Background(), req, e.hc); err != nil {
		t.Fatal(err)
	}
	if sawHost != "via-endpoint.example.com" {
		t.Fatalf("wire Host = %q, want via-endpoint.example.com", sawHost)
	}
}

// TestDoHostHeaderAuthOverridesEndpoint 验证 auth provider 的 host header 覆盖 endpoint.Host
// （auth 是接入方案的权威声明；若两者都设，以 auth 为准）。
func TestDoHostHeaderAuthOverridesEndpoint(t *testing.T) {
	var sawHost string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawHost = r.Host
		w.Write([]byte(`{}`))
	}))
	t.Cleanup(srv.Close)

	e := New(nil)
	req := &resolvedReq{
		Method: "GET",
		URL:    srv.URL + "/api/v1/ping",
		Host:   "endpoint.example.com",
		Header: map[string]string{"host": "auth.example.com"},
	}
	if _, _, err := e.do(context.Background(), req, e.hc); err != nil {
		t.Fatal(err)
	}
	if sawHost != "auth.example.com" {
		t.Fatalf("wire Host = %q, want auth.example.com（auth host 应覆盖 endpoint.Host）", sawHost)
	}
}

// TestExecutePagingMidwayError 验证翻页中途 mock 返回 500 时 engine.Execute
// 返回非 nil err（且 exit code 非 0）。
//
// 旧实现：paging.Iter 的 do 出错时静默 close channel，engine.iterate 范围结束
// 返回 nil → 用户拿到截断数据、exit 0，完全无感。修复后：Iter 发 Item{Err}，
// engine.iterate 收到后返回归一化 *output.APIError（HTTP 500 → ExitAPIError=3）。
func TestExecutePagingMidwayError(t *testing.T) {
	call := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		call++
		if call == 1 {
			// 第一页 200 + 2 条 + next token，触发翻第二页
			w.Write([]byte(`{"data":{"list":[{"id":"1"},{"id":"2"}]},"next":"p2"}`))
			return
		}
		// 第二页 500
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"boom"}`))
	}))
	t.Cleanup(srv.Close)

	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: be, endpoints: { be: { base_url: BASE, auth: none, path_prefix: /api } } }
resources:
  item:
    path: /items
    operations:
      list:
        method: GET
        path: /list
        pagination: { type: cursor, items_path: data.list, next_token_path: next }
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	e := New(tr)
	r := tr.Resources["item"]
	op := r.Operations["list"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	execErr := e.Execute(context.Background(), ep, r, op,
		map[string]string{}, // pathVals
		map[string]string{}, // flags
		Options{Format: "json", All: true, Out: &out})
	if execErr == nil {
		t.Fatalf("翻页中途 500 应返回非 nil err，got nil；stdout=%s", out.String())
	}
	if ec := output.ExitCode(execErr); ec == 0 {
		t.Fatalf("exit code 应非 0（HTTP 500 → ExitAPIError），got %d（err=%v）", ec, execErr)
	}
	// 错误应归一化成 *output.APIError（携带 500 状态码）
	if ae, ok := execErr.(*output.APIError); !ok || ae.StatusCode != 500 {
		t.Fatalf("错误应归一化成 *output.APIError{StatusCode:500}，got %#v", execErr)
	}
}

// TestExecuteBodyBytes 验证 MCP _body 注入路径：Options.BodyBytes（嵌套对象 marshal 后的字节）
// 直接成为请求 body，绕过单层 body flag（resolve 里的 bodyParams 仅支持 flat string map）。
//
// 触发条件：Options.BodyBytes 非空 → Execute 覆盖 req.Body（优先级高于 --body-file 和 body flag）。
// 服务端回显收到的 body，断言嵌套结构（$and/$or/$like）原样到达。
func TestExecuteBodyBytes(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		// 回显收到的 body，验证嵌套结构原样到达
		w.Write([]byte(`{"echo":` + string(body) + `}`))
	}))
	defer srv.Close()
	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources:
  r: { path: /r, operations: { create: { method: POST, path: "" } } }
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["create"]
	r := tr.Resources["r"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	nestedBody := []byte(`{"query":{"$and":[{"$or":[{"x":{"$like":"%a%"}}]}]},"page":1}`)
	err := e.Execute(context.Background(), ep, r, op, nil, nil, Options{
		Format: "json", Out: &out, BodyBytes: nestedBody, Yes: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(out.Bytes(), []byte(`"$and"`)) {
		t.Fatalf("嵌套 body 未到达服务端: %s", out.String())
	}
}

// TestDryRunSkipsGateWrite update --dry-run 非 TTY：dry-run 应在 gateWrite 前拦截，不应报"需 --yes"。
// dry-run 是安全预览（不发请求），不该被写闸门拦。
func TestDryRunSkipsGateWrite(t *testing.T) {
	// update --dry-run 非 TTY：dry-run 应在 gateWrite 前拦截，不应报"需 --yes"
	called := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { update: { method: PUT, path: "/{id}", params: { id: { in: path, required: true } } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["update"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, map[string]string{"id": "1"}, nil,
		Options{DryRun: true, Out: &out}) // 不传 Yes
	if err != nil {
		t.Fatalf("dry-run 不应被 gateWrite 拦（应直接预览）: %v", err)
	}
	if called {
		t.Fatal("dry-run 不应真发请求")
	}
}

// TestIterateFormatTable 验证分页 + format=table 走缓冲路径（收集所有 items 再 FormatTable），
// 输出 tab 分隔的表格（含表头），而非默认的流式 NDJSON（每行一个 JSON）。
//
// 触发条件：op 有 pagination 且 opts.Format=="table" → iterate 分支缓冲 collected []map[string]any。
// 旧实现：iterate 无视 format 强制 NDJSON（fmt.Fprintln 每行 it.Raw），无 tab → 测试 FAIL。
func TestIterateFormatTable(t *testing.T) {
	// mock 分页：2 条，format=table → 输出表格（含表头），非 NDJSON
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":{"list":[{"id":"1","name":"a"},{"id":"2","name":"b"}]}}`))
	}))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { list: { method: GET, path: "", pagination: { type: offset, items_path: data.list, page_param: page, size_param: size, size: 10 } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["list"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, nil, map[string]string{}, Options{Format: "table", Out: &out, Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	// table 输出应是表格（多列 tab 分隔），非每行一个 JSON
	if !bytes.Contains(out.Bytes(), []byte("\t")) {
		t.Fatalf("format=table 未生效（无 tab）: %s", out.String())
	}
}

// TestExecuteTimeout 验证 --timeout 生效：mock 慢响应（200ms）+ Options.Timeout=50ms
// → ctx 在 50ms 到期，http.Do 尊重 ctx deadline 返回 net 错误，归一化成 *output.APIError{ExitCode:ExitNetTimeout}。
//
// 触发条件：Options.Timeout > 0 → Execute 开头用 context.WithTimeout 包装 ctx。
// 旧实现：Options 无 Timeout 字段；http.Client 无 deadline → 请求等满 200ms 才返回，超时机制缺失。
func TestExecuteTimeout(t *testing.T) {
	// mock 慢响应（>100ms），--timeout=50ms → 超时错误
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { read: { method: GET, path: "/{id}", params: { id: { in: path, required: true } } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["read"]
	ep, _ := tr.SelectEndpoint("")
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, map[string]string{"id": "1"}, nil,
		Options{Format: "json", Out: &bytes.Buffer{}, Timeout: 50 * time.Millisecond})
	if err == nil {
		t.Fatal("应超时报错")
	}
	ae, ok := err.(*output.APIError)
	if !ok || ae.ExitCode != output.ExitNetTimeout {
		t.Fatalf("应是 net timeout，got %#v", err)
	}
}

// TestResolveMultipart 验证端到端 multipart 上传：resolve 接入 buildMultipart →
// do() 设 Content-Type（含 boundary）→ 服务端 ParseMultipartForm 成功拿到 file part + 表单字段。
//
// 触发条件：op.ContentType == "multipart-form-data" → resolve 末尾分支调 buildMultipart，
// 覆盖 bodyParams；resolvedReq.ContentType 经 do() 写入 httpReq Header。
func TestResolveMultipart(t *testing.T) {
	// server 收 multipart，校验 Content-Type 含 boundary + 文件 part
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data; boundary=") {
			t.Errorf("server 收到 Content-Type=%q", r.Header.Get("Content-Type"))
		}
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Errorf("ParseMultipartForm: %v", err)
		}
		if r.MultipartForm == nil || r.MultipartForm.Value["kind"][0] != "tool" {
			t.Errorf("kind field 缺失/错误: %+v", r.MultipartForm)
		}
		if fh := r.MultipartForm.File["file"]; len(fh) != 1 || fh[0].Filename != "pkg.tar.gz" {
			t.Errorf("file part 缺失/错误: %+v", r.MultipartForm.File)
		}
	}))
	defer srv.Close()
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: backend, endpoints: { backend: { base_url: ` + srv.URL + `, auth: none } } }
resources:
  pkg:
    operations:
      upload: { method: POST, path: /upload, content_type: multipart-form-data, params: { file: { in: formData, format: binary, required: true }, kind: { in: formData } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	// 写临时上传文件
	tmp := t.TempDir()
	tmpFile := filepath.Join(tmp, "pkg.tar.gz")
	if err := os.WriteFile(tmpFile, []byte{0x1f, 0x8b, 0x08, 0x00}, 0o644); err != nil {
		t.Fatal(err)
	}
	ep, _ := tr.SelectEndpoint("")
	e := New(tr)
	err = e.Execute(context.Background(), ep, tr.Resources["pkg"], tr.Resources["pkg"].Operations["upload"],
		nil, map[string]string{"file": tmpFile, "kind": "tool"}, Options{Format: "json", Out: io.Discard})
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
}
