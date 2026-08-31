package cobracli

import (
	"bytes"
	"strings"
	"testing"

	"api-cli/internal/tree"
)

func TestTextHelpListsParams(t *testing.T) {
	tr := &tree.OperationTree{
		Service: tree.Service{Name: "svc"},
		Resources: map[string]*tree.Resource{
			"foo": {Name: "foo", Operations: map[string]*tree.Operation{
				"read": {Verb: "read", Method: "GET", Path: "/foo/{id}",
					Description: "读取一个 foo",
					Params: []tree.Param{
						{Name: "id", In: "path", Required: true, Description: "ID"},
						{Name: "q", In: "query", Description: "关键词"},
					}},
			}},
		},
	}
	root, err := Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	root.SetOut(&buf)
	root.SetArgs([]string{"foo", "read", "--help"})
	_ = root.Execute() // --help 触发 helpFunc（text 分支默认）
	out := buf.String()
	for _, want := range []string{"Usage:", "Path params", "id", "Query params", "q"} {
		if !strings.Contains(out, want) {
			t.Errorf("text help 缺 %q；输出: %s", want, out)
		}
	}
}
