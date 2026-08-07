package cobracli

import (
	"bytes"
	"io"
	"os"
	"strings"
	"testing"

	"api-cli/internal/spec"

	"github.com/spf13/cobra"
)

// TestHelpFormatJSONSmoke 验证 --help-format=json 的实际行为（controller #4）：
//   - 顶层 resource (inst.read) 反查成功并输出结构化 JSON
//   - child resource (inst.relation.read) 同样能被 locate() 反查命中
//     （验证 Annotations.resource 走递归子树查找，非仅顶层 map）
//   - help-format=text 时回退默认 cobra 帮助（不出 JSON 字段）
//
// smoke 性质，集成测试在 Task 14；保留作 help-format 接入回归。
func TestHelpFormatJSONSmoke(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, type: string, required: true }, fields: { in: query } } }
    children:
      relation:
        path: "/{instance_id}/relations"
        operations:
          read: { path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}

	// 1. 顶层 resource：inst.read
	root1, _ := Build(tr)
	out := captureExecute(root1, []string{"inst", "read", "--help-format=json", "--help"})
	if !strings.Contains(out, `"resource": "inst"`) || !strings.Contains(out, `"verb": "read"`) {
		t.Errorf("顶层 help-format=json 输出缺字段:\n%s", out)
	}

	// 2. child resource：inst relation read（Annotations.resource="relation" 必须在子树里命中）
	root2, _ := Build(tr)
	out2 := captureExecute(root2, []string{"inst", "relation", "read", "--help-format=json", "--help"})
	if !strings.Contains(out2, `"resource": "relation"`) {
		t.Errorf("child help-format=json 未输出 relation 资源（locate 子树递归失败?）:\n%s", out2)
	}

	// 3. help-format=text：回退默认 cobra 帮助，不应出现 resource/verb JSON 字段。
	root3, _ := Build(tr)
	out3 := captureExecute(root3, []string{"inst", "read", "--help"})
	if strings.Contains(out3, `"resource":`) {
		t.Errorf("text 帮助不应输出 JSON 字段:\n%s", out3)
	}
}

// captureExecute 临时把 os.Stdout 重定向到 pipe，异步 drain 后读回全部输出。
func captureExecute(root *cobra.Command, args []string) string {
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	done := make(chan string)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.String()
	}()
	root.SetArgs(args)
	_ = root.Execute()
	w.Close()
	os.Stdout = old
	return <-done
}
