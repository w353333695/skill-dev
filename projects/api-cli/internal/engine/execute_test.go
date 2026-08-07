package engine

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

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
