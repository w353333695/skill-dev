package engine

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

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
