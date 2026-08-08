package main

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// captureStdoutRun 把 os.Stdout 重定向到 pipe，跑 fn，读回全部输出 + fn 的 error。
// cobra 的 help 经 cmd.OutOrStdout() 写到 os.Stdout，所以必须物理替换 os.Stdout。
// （与 internal/cobracli/smoke_test.go 的 captureExecute 同一手法。）
func captureStdoutRun(t *testing.T, fn func() error) (string, error) {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	type res struct {
		out string
		err error
	}
	done := make(chan res)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- res{out: buf.String()}
	}()
	err := fn()
	_ = w.Close()
	os.Stdout = old
	got := <-done
	return got.out, err
}

// writeTmpSpec 写一份最小 spec 到临时文件，返回路径。
// endpoint auth=none → engine 不读 ~/.api-cli/auth.d；read 命令带可识别的自定义参数描述。
func writeTmpSpec(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	p := filepath.Join(dir, "myspec.yaml")
	if err := os.WriteFile(p, []byte(`
spec: api-cli/v1
service: { name: mysvc, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none, path_prefix: /api } } }
resources:
  widget:
    path: /widgets
    operations:
      read: { method: GET, path: "/{wid}", params: { wid: { in: path, type: string, required: true, description: widget-id-sentinel } } }
`), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// TestRunSpecFlagLoadsSpec 验证 --spec flag 真正生效：
// 在 os.Args 里给 --spec <临时清单>，run() 必须加载该清单并构建命令树。
// 用 --help-format=json 让 help 走 stdout（api-cli 的 helpFunc 把 text 帮助
// 路由到 stderr，只有 json 走 stdout，便于捕获）；JSON 含 params 描述，
// 断言含清单里写的自定义参数 "widget-id-sentinel"（只有真 load 了这份 spec 才会出现）。
func TestRunSpecFlagLoadsSpec(t *testing.T) {
	specPath := writeTmpSpec(t)
	t.Setenv("API_CLI_SPEC", "") // 清 env，确保走 flag 而非 env/默认搜索

	old := os.Args
	os.Args = []string{"api-cli", "--spec", specPath, "widget", "read", "--help-format=json", "--help"}
	defer func() { os.Args = old }()

	out, err := captureStdoutRun(t, func() error { return run() })
	if err != nil {
		t.Fatalf("run() 应成功（--help 正常返回），got err: %v\nstdout=%s", err, out)
	}
	if !strings.Contains(out, "widget-id-sentinel") {
		t.Fatalf("--spec 未生效：help JSON 缺清单中的自定义参数描述\nstdout=%s", out)
	}
	if !strings.Contains(out, `"resource": "widget"`) {
		t.Fatalf("help JSON 缺 resource 字段，树未正确构建\nstdout=%s", out)
	}
}

// TestRunSpecEnvFallback 验证 --spec 缺省时回退到 API_CLI_SPEC 环境变量
// （保留既有行为，不回归）。
func TestRunSpecEnvFallback(t *testing.T) {
	specPath := writeTmpSpec(t)
	t.Setenv("API_CLI_SPEC", specPath)

	old := os.Args
	os.Args = []string{"api-cli", "widget", "read", "--help-format=json", "--help"}
	defer func() { os.Args = old }()

	out, err := captureStdoutRun(t, func() error { return run() })
	if err != nil {
		t.Fatalf("run() err: %v", err)
	}
	if !strings.Contains(out, "widget-id-sentinel") {
		t.Fatalf("API_CLI_SPEC 回退失效\nstdout=%s", out)
	}
}

// TestRunSpecFlagPrecedenceOverEnv 验证同时给 flag 和 env 时 flag 优先。
// 用两份不同 sentinel 的 spec：flag 指向 flag-sentinel，env 指向 env-sentinel。
// 输出应含 flag-sentinel 而非 env-sentinel。
func TestRunSpecFlagPrecedenceOverEnv(t *testing.T) {
	dir := t.TempDir()
	flagSpec := filepath.Join(dir, "flag.yaml")
	envSpec := filepath.Join(dir, "env.yaml")
	mk := func(p, sentinel string) {
		os.WriteFile(p, []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none, path_prefix: /api } } }
resources:
  widget:
    path: /widgets
    operations:
      read: { method: GET, path: "/{wid}", params: { wid: { in: path, required: true, description: `+sentinel+` } } }
`), 0o600)
	}
	mk(flagSpec, "flag-sentinel")
	mk(envSpec, "env-sentinel")

	t.Setenv("API_CLI_SPEC", envSpec)
	old := os.Args
	os.Args = []string{"api-cli", "--spec", flagSpec, "widget", "read", "--help-format=json", "--help"}
	defer func() { os.Args = old }()

	out, err := captureStdoutRun(t, func() error { return run() })
	if err != nil {
		t.Fatalf("run() err: %v", err)
	}
	if !strings.Contains(out, "flag-sentinel") || strings.Contains(out, "env-sentinel") {
		t.Fatalf("--spec 应优先于 API_CLI_SPEC\nstdout=%s", out)
	}
}

// TestParseTopFlags table-driven 验证顶层 flag 抽取：
//   - --spec / --mcp 只在首个子命令（首个非 flag token）之前生效
//   - --spec 支持 --spec <val> 与 --spec=<val>
//   - --mcp 支持 --mcp 与 --mcp=true（任意 top 位置，修 M5：不再只认 os.Args[1]）
//   - 其余 token（子命令 + 其 flag）原样进 rest
func TestParseTopFlags(t *testing.T) {
	cases := []struct {
		name string
		args []string
		spec string
		mcp  bool
		rest []string
	}{
		{
			name: "spec+subcommand",
			args: []string{"--spec", "/a/b.yaml", "inst", "read", "i-1"},
			spec: "/a/b.yaml",
			rest: []string{"inst", "read", "i-1"},
		},
		{
			name: "spec=eq form",
			args: []string{"--spec=/x/y.yaml", "inst", "read"},
			spec: "/x/y.yaml",
			rest: []string{"inst", "read"},
		},
		{
			name: "mcp before spec (not only os.Args[1])",
			args: []string{"--spec", "/p.yaml", "--mcp"},
			spec: "/p.yaml",
			mcp:  true,
			rest: nil,
		},
		{
			name: "mcp=true explicit",
			args: []string{"--mcp=true"},
			mcp:  true,
			rest: nil,
		},
		{
			name: "no top flags: all pass to rest",
			args: []string{"inst", "read", "--fields", "f", "i-1"},
			rest: []string{"inst", "read", "--fields", "f", "i-1"},
		},
		{
			name: "spec after subcommand NOT consumed (left for cobra)",
			args: []string{"inst", "read", "--spec", "late.yaml"},
			spec: "",
			rest: []string{"inst", "read", "--spec", "late.yaml"},
		},
		{
			name: "double dash terminates top segment",
			args: []string{"--spec", "/p.yaml", "--", "inst"},
			spec: "/p.yaml",
			rest: []string{"inst"},
		},
		{
			name: "global flag before subcommand kept for cobra (bug2)",
			args: []string{"--spec", "/a.yaml", "--endpoint", "backend", "inst", "read"},
			spec: "/a.yaml",
			rest: []string{"--endpoint", "backend", "inst", "read"},
		},
		{
			name: "multiple global flags before subcommand",
			args: []string{"--spec", "/a.yaml", "--insecure", "--format", "yaml", "inst", "read", "i1"},
			spec: "/a.yaml",
			rest: []string{"--insecure", "--format", "yaml", "inst", "read", "i1"},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			spec, mcp, rest := parseTopFlags(c.args)
			if spec != c.spec {
				t.Errorf("spec: want %q got %q", c.spec, spec)
			}
			if mcp != c.mcp {
				t.Errorf("mcp: want %v got %v", c.mcp, mcp)
			}
			if !sliceEq(rest, c.rest) {
				t.Errorf("rest: want %v got %v", c.rest, rest)
			}
		})
	}
}

func sliceEq(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
