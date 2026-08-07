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
