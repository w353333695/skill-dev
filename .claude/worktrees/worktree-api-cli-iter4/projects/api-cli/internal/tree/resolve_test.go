package tree

import "testing"

// sampleTree 构造一棵用于 resolve 系列测试的最小 OperationTree。
// 注意：本测试断言的 URL 含 resource.Path（/instances），因此 ResolveURL
// 必须把 resource.Path 拼进 URL（controller 修正后的签名）。
func sampleTree() *OperationTree {
	return &OperationTree{
		Service: Service{DefaultEndpoint: "backend",
			Endpoints: map[string]*Endpoint{
				"backend":  {Name: "backend", BaseURL: "https://cmdb.example.com", PathPrefix: "/api/v1", Auth: "bk"},
				"frontend": {Name: "frontend", BaseURL: "https://cmdb.example.com", PathPrefix: "/web/api/v1", Auth: "fe"},
			}},
		Resources: map[string]*Resource{
			"inst": {Name: "inst", Path: "/instances",
				Operations: map[string]*Operation{
					"read": {Verb: "read", Method: "GET", Path: "/{id}",
						Params: []Param{{Name: "id", In: "path", Required: true}}},
				}},
		},
	}
}

// TestResolveURL 验证物化后的 URL 含 resource.Path（/instances），
// 形如 https://cmdb.example.com/web/api/v1/instances/i-123。
// 因此 ResolveURL 签名为 (ep, r, op, vals) —— op 不持有 resource 引用。
func TestResolveURL(t *testing.T) {
	tr := sampleTree()
	ep, _ := tr.SelectEndpoint("frontend")
	r := tr.Resources["inst"]
	op := r.Operations["read"]
	url, err := tr.ResolveURL(ep, r, op, map[string]string{"id": "i-123"})
	if err != nil {
		t.Fatal(err)
	}
	want := "https://cmdb.example.com/web/api/v1/instances/i-123"
	if url != want {
		t.Fatalf("got %q want %q", url, want)
	}
}

func TestSelectEndpointDefault(t *testing.T) {
	tr := sampleTree()
	ep, err := tr.SelectEndpoint("") // 空名 → 默认 endpoint
	if err != nil {
		t.Fatal(err)
	}
	if ep.Name != "backend" {
		t.Fatalf("want default backend, got %s", ep.Name)
	}
}

func TestFindOperation(t *testing.T) {
	tr := sampleTree()
	r, op, err := tr.FindOperation([]string{"inst", "read"})
	if err != nil {
		t.Fatal(err)
	}
	if r.Name != "inst" || op.Verb != "read" {
		t.Fatal("locate failed")
	}
}

// TestJoinPathNormalization 校验 joinPath 的斜杠归一化：
// scheme:// 双斜杠必须保留，中间多余的斜杠要合并。
// TestResolveURLAncestorChainAndParentKey 验证 N 层 path 的两个修复：
//  1. ResolveURL 沿祖先链拼 path（不只拼叶子 r.Path）——relation 是 inst 的 child，
//     拼出的 URL 必须含 inst.Path（/instances）。
//  2. {param} 填充改为遍历 vals（而非 op.Params）——parent_key（instance_id）由
//     命令位置注入到 vals、但不在 relOp.Params，遍历 vals 才能命中。
func TestResolveURLAncestorChainAndParentKey(t *testing.T) {
	tr := &OperationTree{
		Service: Service{Endpoints: map[string]*Endpoint{
			"be": {Name: "be", BaseURL: "http://x", PathPrefix: "/api/v1"},
		}},
		Resources: map[string]*Resource{},
	}
	inst := &Resource{Name: "inst", Path: "/instances", ParentKey: "instance_id",
		Operations: map[string]*Operation{}, Children: map[string]*Resource{}}
	rel := &Resource{Name: "relation", Path: "/{instance_id}/relations", Parent: inst,
		Operations: map[string]*Operation{}, Children: map[string]*Resource{}}
	inst.Children["relation"] = rel
	tr.Resources["inst"] = inst
	relOp := &Operation{Verb: "read", Method: "GET", Path: "/{id}",
		Params: []Param{{Name: "id", In: "path", Required: true}}}
	rel.Operations["read"] = relOp

	ep := tr.Service.Endpoints["be"]
	// instance_id 由命令位置注入（不在 relOp.Params），靠 vals 填充
	vals := map[string]string{"instance_id": "INST1", "id": "REL1"}
	got, err := tr.ResolveURL(ep, rel, relOp, vals)
	if err != nil {
		t.Fatalf("ResolveURL err: %v", err)
	}
	want := "http://x/api/v1/instances/INST1/relations/REL1"
	if got != want {
		t.Errorf("ancestor chain + parent_key URL:\n want %q\n got  %q", want, got)
	}
}

func TestJoinPathNormalization(t *testing.T) {
	cases := []struct {
		name string
		segs []string
		want string
	}{
		{"single segment", []string{"https://x.com"}, "https://x.com"},
		{"two abs segments", []string{"https://x.com", "/a", "/b"}, "https://x.com/a/b"},
		{"trailing/leading slashes", []string{"https://x.com/", "/a/", "b"}, "https://x.com/a/b"},
	}
	for _, c := range cases {
		if got := joinPath(c.segs...); got != c.want {
			t.Errorf("case %q: joinPath got %q want %q", c.name, got, c.want)
		}
	}
}
