package auth

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"api-cli/pkg/adapter"
)

// writeCleanAuthConfig 在干净 tmpdir 的 HOME 下写一份 auth.d/<name>.yaml。
// 用 t.Setenv 保证子进程（go-plugin 会 exec 子进程）也读到同一个 HOME。
func writeCleanAuthConfig(t *testing.T, name, body string) {
	t.Helper()
	home := t.TempDir()
	dir := filepath.Join(home, ".api-cli", "auth.d")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name+".yaml"), []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", home)
}

// TestLoadBuiltinNotBroken 验证 host 路径（default 分支调 LoadPlugin）引入后
// 不破坏内置 provider：provider=bearer 必须仍走内置、不触发外部二进制装载。
// 外部 adapter 二进制的完整 e2e 测试需要编译示例 adapter，留给 Task 14 集成层。
func TestLoadBuiltinNotBroken(t *testing.T) {
	writeCleanAuthConfig(t, "fe", "provider: bearer\nconfig:\n  token: tk\n")

	p, err := Load("fe")
	if err != nil {
		t.Fatalf("Load(fe) 内置分支应成功，err=%v", err)
	}
	resp, err := p.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if err != nil {
		t.Fatalf("Apply 意外失败: %v", err)
	}
	if got := resp.Headers["Authorization"]; got != "Bearer tk" {
		t.Fatalf("内置 bearer 失效：want %q, got %q", "Bearer tk", got)
	}
}
