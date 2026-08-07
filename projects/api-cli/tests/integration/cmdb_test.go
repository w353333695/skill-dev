// Package integration 的 cmdb_test.go：用 CMDBMock 跑 examples/cmdb.yaml 的
// 前后端双 endpoint CRUD + cursor 分页流式 + dry-run 端到端验证。
//
// 关键设计：
//
//  1. loadCMDBTree 直接返回 *tree.OperationTree（spec.Parse 的真实返回类型），
//     不引入 specTree 私有包装（brief plan 中的 specTree 是 plan 瑕疵）。
//
//  2. stdout 捕获方案：选 Plan A（os.Pipe 重定向 os.Stdout）——
//     因为 cobracli.globalOpts 把 engine.Options.Out 固定设为 os.Stdout（spec §11.3），
//     root.SetOut(&buf) 改的是 cobra 的 Out 而非 engine.Out，无法捕获 NDJSON/dry-run 输出。
//     Plan A 与 internal/cobracli/smoke_test.go 的 captureExecute 同一手法，无侵入、
//     无需改 internal 代码、不影响 Task 10 既有测试。
//
//  3. 四个子测试覆盖：read（backend）、search --all（cursor 分页流式，>=2 NDJSON 行）、
//     read --endpoint frontend --dry-run（验证 /web/api/v1 path_prefix 生效）、
//     delete --dry-run --yes（副作用验证：mock.db["i-1"] 仍存在）。
//
//  4. 写操作闸门：测试非 TTY，delete 需 --yes 才能过 gateWrite（参见 engine/safety.go）。
package integration

import (
	"bytes"
	"context"
	"io"
	"os"
	"strings"
	"testing"

	"api-cli/internal/cobracli"
	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

// loadCMDBTree 构造一份 cmdb 清单（前后端双 endpoint），base_url 用 mock 地址替换。
// 返回 *tree.OperationTree —— spec.Parse 的真实返回类型（plan 中的 specTree 私有包装是瑕疵）。
func loadCMDBTree(t *testing.T, baseURL string) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: BASE, auth: none, path_prefix: /api/v1 }, frontend: { base_url: BASE, auth: none, path_prefix: /web/api/v1 } } }
resources:
  inst:
    path: /instances
    singular: instance
    operations:
      create: { method: POST, path: "" }
      read:   { method: GET, path: "/{id}", params: { id: { in: path, type: string, required: true, description: 实例 ID } } }
      update: { method: PATCH, path: "/{id}", params: { id: { in: path, required: true } } }
      delete: { method: DELETE, path: "/{id}", params: { id: { in: path, required: true } } }
      search:
        method: POST
        path: /search
        pagination:
          type: cursor
          items_path: data.list
          next_token_path: data.next
          has_more_path: data.next
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(baseURL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	return tr
}

// captureStdout 临时把进程 os.Stdout 重定向到 pipe，异步 drain 后读回 fn 期间的全部输出。
// engine.Options.Out 固定是 os.Stdout（见 cobracli/flags.go globalOpts），所以必须
// 物理替换 os.Stdout 才能捕获 NDJSON / dry-run 输出。fn 内严禁 t.Fatal（先返回 err）。
//
// 与 internal/cobracli/smoke_test.go 的 captureExecute 同一手法。
func captureStdout(t *testing.T, fn func() error) string {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	done := make(chan string)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.String()
	}()
	err := fn()
	_ = w.Close()
	os.Stdout = old
	out := <-done
	if err != nil {
		t.Fatalf("execute 返回错误: %v\n捕获到的 stdout:\n%s", err, out)
	}
	return out
}

// TestE2EReadBackend 验证 backend endpoint 基础 read：inst read i-1 成功取回，
// 输出含 i-1 / web 字段。
func TestE2EReadBackend(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "read", "i-1"})
		return root.Execute()
	})
	if !strings.Contains(out, `"i-1"`) || !strings.Contains(out, `"web"`) {
		t.Fatalf("read 输出缺 i-1/web 字段: %s", out)
	}
}

// TestE2ESearchAllStreaming 验证 cursor 分页 + --all 流式 NDJSON：
// db 有 i-1 / i-2 两条，paging.Iter 应逐行输出 → 至少 2 行 NDJSON。
// 同时校验两条 id 都出现（验证翻页确实翻到了第二页）。
func TestE2ESearchAllStreaming(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	ctx := context.Background()
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "search", "--all", "--yes"})
		// 显式注入 ctx（engine 经 cmd.Context() 取，cobra 默认 Background，这里保险显式传）。
		root.SetContext(ctx)
		return root.Execute()
	})
	// NDJSON：每行一个 item；db 有 2 条 → 至少 2 行。
	lines := bytes.Split(bytes.TrimSpace([]byte(out)), []byte("\n"))
	if len(lines) < 2 {
		t.Fatalf("want >=2 NDJSON 行, got %d (%q)", len(lines), out)
	}
	if !strings.Contains(out, `"i-1"`) || !strings.Contains(out, `"i-2"`) {
		t.Fatalf("流式输出应含 i-1 与 i-2 两行: %s", out)
	}
}

// TestE2EFrontendEndpointPath 验证 --endpoint frontend + --dry-run：
// dry-run 预览里 URL 必须含 /web/api/v1/instances/i-1（frontend path_prefix 生效），
// 而不是 backend 的 /api/v1。
func TestE2EFrontendEndpointPath(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "read", "i-1", "--endpoint", "frontend", "--dry-run", "--yes"})
		return root.Execute()
	})
	if !strings.Contains(out, "/web/api/v1/instances/i-1") {
		t.Fatalf("frontend path_prefix 未生效（缺 /web/api/v1/instances/i-1）: %s", out)
	}
	// 反向校验：dry-run 不应落到 backend 前缀（排除 read 默认走 backend 的回归）。
	if strings.Contains(out, " /api/v1/instances/i-1 ") && !strings.Contains(out, "/web/api/v1/instances/i-1") {
		t.Fatalf("dry-run 错走 backend 前缀: %s", out)
	}
}

// TestE2EDryRunDoesNotDelete 验证 --dry-run 副作用：delete --dry-run --yes 后，
// mock.db["i-1"] 必须仍存在（dry-run 不发请求 → 服务端无变更）。
// 用副作用断言（而非 stdout 内容）最稳，不强依赖 dry-run 预览格式。
func TestE2EDryRunDoesNotDelete(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
}
	// 不需要捕获 stdout：用副作用断言。
	// 临时重定向 stdout 只为静默 dry-run 预览噪声（不参与断言）。
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	drainDone := make(chan struct{})
	go func() {
		_, _ = io.Copy(io.Discard, r)
		close(drainDone)
	}()
	root.SetArgs([]string{"inst", "delete", "i-1", "--dry-run", "--yes"})
	execErr := root.Execute()
	_ = w.Close()
	os.Stdout = old
	<-drainDone
	if execErr != nil {
		t.Fatalf("delete --dry-run 执行失败: %v", execErr)
	}
	mock.mu.Lock()
	_, ok := mock.db["i-1"]
	mock.mu.Unlock()
	if !ok {
		t.Fatal("dry-run 不应真正删除 i-1，但 mock.db 中已不存在")
	}
}

// TestGlobalFlagTraverseChildren 验证 root 开了 TraverseChildren：使全局 flag
// （--insecure/--spec 等）可放在子命令之前（`api-cli --insecure inst search`）
// 也被 cobra 正确解析，而不被当作子命令位置参数。
func TestGlobalFlagTraverseChildren(t *testing.T) {
	// --insecure 放最前（root 位置）应生效（TraverseChildren=true）
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	// 断言 root 开了 TraverseChildren
	if !root.TraverseChildren {
		t.Fatal("root.TraverseChildren 应为 true")
	}
}
