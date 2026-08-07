package auth

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/pkg/adapter"
)

// writeAuthConfig 在临时 HOME 下写一份 auth.d/<name>.yaml，返回 auth.d 路径。
func writeAuthConfig(t *testing.T, name, yaml string) {
	t.Helper()
	dir := filepath.Join(t.TempDir(), ".api-cli", "auth.d")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name+".yaml"), []byte(yaml), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", strings.TrimSuffix(dir, filepath.Join(".api-cli", "auth.d")))
}

func TestLoadBearer(t *testing.T) {
	writeAuthConfig(t, "mybear", `
provider: bearer
config:
  token: tk-from-yaml
`)
	p, err := Load("mybear")
	if err != nil {
		t.Fatal(err)
	}
	resp, err := p.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Headers["Authorization"] != "Bearer tk-from-yaml" {
		t.Fatalf("want Bearer tk-from-yaml, got %q", resp.Headers["Authorization"])
	}
}

func TestLoadUnknownProvider(t *testing.T) {
	writeAuthConfig(t, "ext", `
provider: custom-foo
config:
  k: v
`)
	_, err := Load("ext")
	if err == nil {
		t.Fatal("want error for unknown provider")
	}
	// default 分支已接入 LoadPlugin；找不到外部二进制时应在错误中带 provider 名。
	if strings.Contains(err.Error(), "Task 11") {
		t.Fatalf("default 分支不应再返回 Task 11 占位错误：got %v", err)
	}
	if !strings.Contains(err.Error(), "custom-foo") {
		t.Fatalf("错误应包含 provider 名 custom-foo：got %v", err)
	}
}

func TestLoadMissingFile(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	_, err := Load("nope")
	if err == nil {
		t.Fatal("want error for missing config")
	}
}

// TestLoadReturnsCachedInstance 验证 provider cache：同名（同配置路径）多次 Load
// 必须返回同一实例，避免外部 go-plugin adapter 每次 Load 启新子进程泄漏
// （engine.Execute 每个请求都调 auth.Load）。
func TestLoadReturnsCachedInstance(t *testing.T) {
	writeCleanAuthConfig(t, "cacheprobe", "provider: bearer\nconfig:\n  token: tk\n")
	p1, err := Load("cacheprobe")
	if err != nil {
		t.Fatalf("首次 Load 失败: %v", err)
	}
	p2, err := Load("cacheprobe")
	if err != nil {
		t.Fatalf("第二次 Load 失败: %v", err)
	}
	if p1 != p2 {
		t.Fatalf("Load 同名应返回同一缓存实例（避免子进程泄漏），got 不同指针: %p vs %p", p1, p2)
	}
}

// TestLoadDifferentPathNotCached 验证 cache 按配置路径隔离：
// 不同 HOME 下同名 provider 应各自构造（缓存键含路径，不跨 HOME 串台）。
// 这同时保证既有测试在引入全局 cache 后不被串扰。
func TestLoadDifferentPathNotCached(t *testing.T) {
	// 第一份配置
	writeCleanAuthConfig(t, "iso", "provider: bearer\nconfig:\n  token: one\n")
	p1, err := Load("iso")
	if err != nil {
		t.Fatal(err)
	}
	resp1, _ := p1.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	// 换一个 HOME（writeCleanAuthConfig 重新 t.Setenv 到新 tempdir），同名为 iso
	writeCleanAuthConfig(t, "iso", "provider: bearer\nconfig:\n  token: two\n")
	p2, err := Load("iso")
	if err != nil {
		t.Fatal(err)
	}
	resp2, _ := p2.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if p1 == p2 {
		t.Fatalf("不同配置路径不应命中同一缓存实例（应按路径隔离）")
	}
	if resp1.Headers["Authorization"] != "Bearer one" || resp2.Headers["Authorization"] != "Bearer two" {
		t.Fatalf("配置隔离失败: resp1=%v resp2=%v", resp1, resp2)
	}
}
