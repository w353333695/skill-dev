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
