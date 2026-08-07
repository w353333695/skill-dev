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
	if !strings.Contains(err.Error(), "Task 11") {
		t.Fatalf("want Task 11 placeholder error, got %v", err)
	}
}

func TestLoadMissingFile(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	_, err := Load("nope")
	if err == nil {
		t.Fatal("want error for missing config")
	}
}
