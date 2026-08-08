package spec

import (
	"os"
	"testing"
)

func TestParseDefaultsAndEnv(t *testing.T) {
	raw, _ := os.ReadFile("testdata/cmdb.yaml")
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if tr.Service.Name != "cmdb" {
		t.Fatal("name")
	}
	// read 省 method → 默认 GET
	if m := tr.Resources["inst"].Operations["read"].Method; m != "GET" {
		t.Fatalf("read method want GET, got %s", m)
	}
	// delete 省 method → 默认 DELETE
	if m := tr.Resources["inst"].Operations["delete"].Method; m != "DELETE" {
		t.Fatalf("delete method want DELETE, got %s", m)
	}
	// create 显式 POST
	if m := tr.Resources["inst"].Operations["create"].Method; m != "POST" {
		t.Fatalf("create method want POST, got %s", m)
	}
	// pagination 物化
	pg := tr.Resources["inst"].Operations["search"].Pagination
	if pg == nil || pg.Type != "cursor" || pg.ItemsPath != "data.list" {
		t.Fatalf("pagination not parsed: %+v", pg)
	}
}

func TestExpandEnv(t *testing.T) {
	os.Setenv("CMDB_TEST_URL", "http://env.example.com")
	defer os.Unsetenv("CMDB_TEST_URL")
	raw := []byte("spec: api-cli/v1\nservice:\n  name: x\n  default_endpoint: e\n  endpoints:\n    e: { base_url: \"${CMDB_TEST_URL}\", auth: a, path_prefix: /p }\nresources: {}\n")
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := tr.Service.Endpoints["e"].BaseURL; got != "http://env.example.com" {
		t.Fatalf("env not expanded: %q", got)
	}
}

func TestParseIter2Fields(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: http://h, auth: none, path_prefix: "" } } }
resources:
  r:
    path: /r
    operations:
      search:
        method: POST
        path: ""
        body:
          type: object
          example: { q: "foo" }
          additional_properties: true
          properties:
            q: { type: string, description: 关键词 }
        response:
          type: object
          properties:
            data: { type: array, description: 结果列表 }
        pagination:
          type: offset
          page_in: body
          items_path: data
          page_param: page
          size_param: page_size
          size: 10
`)
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	op := tr.Resources["r"].Operations["search"]
	// Schema 新字段
	if op.Body == nil || op.Body.Example == nil {
		t.Fatal("body.example 未解析")
	}
	if op.Body.AdditionalProperties == nil || !*op.Body.AdditionalProperties {
		t.Fatal("body.additional_properties 未解析")
	}
	// Operation.Response
	if op.Response == nil || op.Response.Properties["data"] == nil {
		t.Fatal("response 未解析")
	}
	// Pagination.PageIn
	if op.Pagination == nil || op.Pagination.PageIn != "body" {
		t.Fatalf("page_in want body, got %q", ternary(op.Pagination == nil, "<nil>", op.Pagination.PageIn))
	}
}

func ternary(b bool, a, c string) string {
	if b {
		return a
	}
	return c
}

func TestParseResourceAndOperationDescription(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    description: 实例资源
    path: /instances
    operations:
      read: { description: 读取单个实例, path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := tr.Resources["inst"].Description; got != "实例资源" {
		t.Errorf("resource description: want %q got %q", "实例资源", got)
	}
	if got := tr.Resources["inst"].Operations["read"].Description; got != "读取单个实例" {
		t.Errorf("operation description: want %q got %q", "读取单个实例", got)
	}
}

func TestParseParentBackfill(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    path: /instances
    parent_key: instance_id
    children:
      relation:
        path: "/{instance_id}/relations"
        operations:
          read: { path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	rel := tr.Resources["inst"].Children["relation"]
	if rel.Parent == nil || rel.Parent.Name != "inst" {
		t.Errorf("child.Parent 未回填到 inst，got %v", rel.Parent)
	}
}
