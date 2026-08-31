package output

import (
	"bytes"
	"strings"
	"testing"
)

func TestExitCodeMapping(t *testing.T) {
	if got := ExitCode(nil); got != ExitOK {
		t.Fatal("nil should be OK")
	}
	ae := &APIError{ExitCode: ExitAuthError}
	if got := ExitCode(ae); got != ExitAuthError {
		t.Fatal("auth exit code")
	}
	if got := ExitCode(NormalizeAPIError(401, []byte("no"))); got != ExitAuthError {
		t.Fatalf("401 should map to auth, got %d", got)
	}
}

// TestFormatTableDeterministic 验证 formatTable 表头按 key 排序，
// 相同输入多次运行列序稳定（review Important #1：MapKeys 顺序未定义）。
func TestFormatTableDeterministic(t *testing.T) {
	data := []map[string]any{
		{"b": 2, "a": 1, "c": 3},
		{"a": 10, "c": 30, "b": 20},
	}

	// 跑多轮，每轮输出必须一致且表头按字母序。
	var firstOut string
	for round := 0; round < 20; round++ {
		var buf bytes.Buffer
		if err := Format(&buf, "table", data); err != nil {
			t.Fatalf("round %d Format error: %v", round, err)
		}
		out := buf.String()
		if round == 0 {
			firstOut = out
		} else if out != firstOut {
			t.Fatalf("non-deterministic table output:\nround 0:\n%s\nround %d:\n%s", firstOut, round, out)
		}
	}

	lines := strings.Split(strings.TrimRight(firstOut, "\n"), "\n")
	if len(lines) < 1 {
		t.Fatalf("expected at least header line, got %q", firstOut)
	}
	// 表头必须是 a\tb\tc（排序后），而非 MapKeys 的随机顺序。
	if want := "a\tb\tc"; lines[0] != want {
		t.Fatalf("header not sorted: got %q want %q", lines[0], want)
	}
	// 数据行也应按相同列序对齐。
	if len(lines) < 3 {
		t.Fatalf("expected header + 2 data rows, got %d lines: %q", len(lines), firstOut)
	}
	if lines[1] != "1\t2\t3" {
		t.Fatalf("row 1 column order wrong: got %q", lines[1])
	}
	if lines[2] != "10\t20\t30" {
		t.Fatalf("row 2 column order wrong: got %q", lines[2])
	}
}

func TestPrintErrorHumanReadableByDefault(t *testing.T) {
	var buf bytes.Buffer
	ae := &APIError{Code: "unknown_flag", Message: "unknown flag: --q", ExitCode: ExitParamError}
	PrintError(&buf, ae, false)
	out := buf.String()
	if !strings.Contains(out, "error:") {
		t.Errorf("默认应人类可读含 'error:'，got: %s", out)
	}
	if strings.HasPrefix(strings.TrimSpace(out), "{") {
		t.Errorf("默认不该是 JSON，got: %s", out)
	}
}

func TestPrintErrorJSONWhenJSONMode(t *testing.T) {
	var buf bytes.Buffer
	ae := &APIError{Code: "x", Message: "m", ExitCode: ExitParamError}
	PrintError(&buf, ae, true)
	if !strings.HasPrefix(strings.TrimSpace(buf.String()), "{") {
		t.Errorf("jsonMode 应输出 JSON，got: %s", buf.String())
	}
}
