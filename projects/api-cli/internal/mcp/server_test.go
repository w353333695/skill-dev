// Package mcp 的测试：把 OperationTree 暴露为 MCP tools（stdio JSON-RPC 2.0 最小子集）。
package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"

	"api-cli/internal/spec"
)

// cmdbYAML 测试用的最小 cmdb 清单：单资源 inst + 单 operation read。
const cmdbYAML = `
spec: api-cli/v1
service:
  name: cmdb
  default_endpoint: backend
  endpoints:
    backend: { base_url: "http://x", auth: none, path_prefix: /api/v1 }
resources:
  inst:
    path: /instances
    operations:
      read:
        path: "/{id}"
        params:
          id: { in: path, required: true, type: string }
`

// TestToolsList 验证 ToolsList 把 inst.read 枚举为 cmdb_inst_read。
func TestToolsList(t *testing.T) {
	tr, _ := spec.Parse([]byte(cmdbYAML))
	s := New(tr)
	tools := s.ToolsList()
	if len(tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(tools))
	}
	if tools[0].Name != "cmdb_inst_read" {
		t.Fatalf("tool name want cmdb_inst_read, got %s", tools[0].Name)
	}
	b, err := json.Marshal(tools[0])
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if string(b) == "" {
		t.Fatal("tool not serializable")
	}
	// InputSchema 必须含 properties.id（path 参数）。
	s2 := tools[0].InputSchema
	props, ok := s2["properties"].(map[string]any)
	if !ok {
		t.Fatalf("properties not map: %T", s2["properties"])
	}
	if _, ok := props["id"]; !ok {
		t.Fatalf("properties missing id: %v", props)
	}
}

// TestToolsListNested 验证嵌套 children 资源也被枚举（tool name 含完整 resource 链）。
func TestToolsListNested(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service:
  name: cmdb
  default_endpoint: backend
  endpoints:
    backend: { base_url: "http://x", auth: none, path_prefix: /api/v1 }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, required: true } } }
    children:
      relation:
        path: /relations
        operations:
          read: { path: "/{rid}", params: { rid: { in: path, required: true } } }
`)
	tr, _ := spec.Parse(raw)
	s := New(tr)
	tools := s.ToolsList()
	names := map[string]bool{}
	for _, tt := range tools {
		names[tt.Name] = true
	}
	if !names["cmdb_inst_read"] {
		t.Errorf("missing cmdb_inst_read in %v", names)
	}
	if !names["cmdb_inst_relation_read"] {
		t.Errorf("missing cmdb_inst_relation_read in %v", names)
	}
}

// TestServeInitialize 验证 initialize 响应含 protocolVersion + serverInfo。
func TestServeInitialize(t *testing.T) {
	tr, _ := spec.Parse([]byte(cmdbYAML))
	s := New(tr)
	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}` + "\n")
	var out bytes.Buffer
	if err := s.Serve(context.Background(), in, &out); err != nil {
		t.Fatal(err)
	}
	var resp map[string]any
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v (out=%s)", err, out.String())
	}
	if resp["jsonrpc"] != "2.0" {
		t.Errorf("jsonrpc want 2.0, got %v", resp["jsonrpc"])
	}
	if resp["id"] != float64(1) {
		t.Errorf("id want 1, got %v", resp["id"])
	}
	result, ok := resp["result"].(map[string]any)
	if !ok {
		t.Fatalf("result missing: %v", resp)
	}
	if result["protocolVersion"] != "2024-11-05" {
		t.Errorf("protocolVersion want 2024-11-05, got %v", result["protocolVersion"])
	}
	si, ok := result["serverInfo"].(map[string]any)
	if !ok || si["name"] != "cmdb-mcp" {
		t.Errorf("serverInfo.name want cmdb-mcp, got %v", result["serverInfo"])
	}
}

// TestServeToolsList 验证 tools/list 响应结构（result.tools 数组）。
func TestServeToolsList(t *testing.T) {
	tr, _ := spec.Parse([]byte(cmdbYAML))
	s := New(tr)
	in := strings.NewReader(`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}` + "\n")
	var out bytes.Buffer
	if err := s.Serve(context.Background(), in, &out); err != nil {
		t.Fatal(err)
	}
	var resp struct {
		Result struct {
			Tools []Tool `json:"tools"`
		} `json:"result"`
	}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v (out=%s)", err, out.String())
	}
	if len(resp.Result.Tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(resp.Result.Tools))
	}
	if resp.Result.Tools[0].Name != "cmdb_inst_read" {
		t.Errorf("tool name want cmdb_inst_read, got %s", resp.Result.Tools[0].Name)
	}
}

// TestServeMethodNotFound 验证未知方法返回 -32601。
func TestServeMethodNotFound(t *testing.T) {
	tr, _ := spec.Parse([]byte(cmdbYAML))
	s := New(tr)
	in := strings.NewReader(`{"jsonrpc":"2.0","id":3,"method":"nope","params":{}}` + "\n")
	var out bytes.Buffer
	_ = s.Serve(context.Background(), in, &out)
	var resp map[string]any
	_ = json.Unmarshal(out.Bytes(), &resp)
	errObj, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatalf("error missing: %v", resp)
	}
	if code, _ := errObj["code"].(float64); code != -32601 {
		t.Errorf("code want -32601, got %v", errObj["code"])
	}
}

// TestToolsListBodySchema 验证 operation.Body 嵌套 Schema 被展开进
// inputSchema.properties._body（让 LLM 看到完整的 body 字段结构）。
func TestToolsListBodySchema(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: e, endpoints: { e: { base_url: http://h, auth: none, path_prefix: "" } } }
resources:
  inst:
    path: /inst
    operations:
      search:
        method: POST
        path: ""
        params:
          object_id: { in: path, type: string, required: true }
        body:
          type: object
          required: [q]
          description: 搜索请求
          properties:
            q: { type: string, description: 关键词 }
`)
	tr, _ := spec.Parse(raw)
	s := New(tr)
	tools := s.ToolsList()
	if len(tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(tools))
	}
	props, ok := tools[0].InputSchema["properties"].(map[string]any)
	if !ok {
		t.Fatal("inputSchema.properties 缺失")
	}
	body, ok := props["_body"].(map[string]any)
	if !ok {
		t.Fatal("inputSchema.properties._body 缺失（嵌套 body 未展开）")
	}
	if body["description"] != "搜索请求" {
		t.Fatalf("_body.description want 搜索请求, got %#v", body["description"])
	}
	bodyProps, _ := body["properties"].(map[string]any)
	if bodyProps["q"] == nil {
		t.Fatal("_body.properties.q 缺失")
	}
}

// TestServeToolsCallDryRun 用未知 tool 名触发 -32602，验证 tools/call 路由 + 错误码。
// 真发链路（命中 mock 后端）由 engine 包自己测；mcp 层只验路由/反查/分参。
func TestServeToolsCallDryRun(t *testing.T) {
	tr, _ := spec.Parse([]byte(cmdbYAML))
	s := New(tr)
	in := strings.NewReader(`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"cmdb_inst_nonexist","arguments":{}}}` + "\n")
	var out bytes.Buffer
	_ = s.Serve(context.Background(), in, &out)
	var resp map[string]any
	_ = json.Unmarshal(out.Bytes(), &resp)
	errObj, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatalf("unknown tool should error: %v", resp)
	}
	if code, _ := errObj["code"].(float64); code != -32602 {
		t.Errorf("code want -32602, got %v", errObj["code"])
	}
}
