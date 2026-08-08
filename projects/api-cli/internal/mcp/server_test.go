// Package mcp 的测试：把 OperationTree 暴露为 MCP tools（stdio JSON-RPC 2.0 最小子集）。
package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
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

// TestToolsListOutputSchema 验证 operation.Response 被展开进 tool.outputSchema，
// 让 LLM 看到响应字段结构（复用 Schema.ToJSONSchema，nil 时 omitempty 不出现）。
func TestToolsListOutputSchema(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: e, endpoints: { e: { base_url: http://h, auth: none, path_prefix: "" } } }
resources:
  inst:
    path: /inst
    operations:
      read: { method: GET, path: "/{id}", params: { id: { in: path, required: true } },
              response: { type: object, properties: { id: { type: string, description: 实例ID }, name: { type: string, description: 名称 } } } }
`)
	tr, _ := spec.Parse(raw)
	tools := New(tr).ToolsList()
	if tools[0].OutputSchema == nil {
		t.Fatal("outputSchema 缺失")
	}
	props, _ := tools[0].OutputSchema["properties"].(map[string]any)
	if props["id"] == nil {
		t.Fatal("outputSchema.properties.id 缺失")
	}
}

// TestInputSchemaRequired 验证 inputSchema.required 聚合 path 参数 required +
// body schema required（去重）。LLM 据此判断必填字段，缺失会导致 tool 调用漏参。
func TestInputSchemaRequired(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: http://h, auth: none, path_prefix: "" } } }
resources:
  r:
    path: /r
    operations:
      search: { method: POST, path: "",
        params: { object_id: { in: path, required: true } },
        body: { type: object, required: [q, page], properties: { q: { type: string }, page: { type: integer } } } }
`)
	tr, _ := spec.Parse(raw)
	tools := New(tr).ToolsList()
	req, ok := tools[0].InputSchema["required"].([]string)
	if !ok {
		t.Fatalf("inputSchema.required 缺失，got %#v", tools[0].InputSchema["required"])
	}
	// path required (object_id) + body required (q, page)，去重
	want := map[string]bool{"object_id": true, "q": true, "page": true}
	for _, r := range req {
		delete(want, r)
	}
	if len(want) != 0 {
		t.Fatalf("required 不全，缺 %v，got %v", want, req)
	}
}

// TestInputSchemaRequiredOmittedWhenEmpty 验证 operation 无必填字段时
// inputSchema 不含 required 字段（而非 "required":null，违反 JSON Schema）。
//
// 回归点：collectRequired 返回 nil；旧实现直接塞进 map →
// json.Marshal 出 "required":null（JSON Schema 要求 required 必须是数组）。
// 修法：ToolsList 里 len(req)>0 才设该字段。
// 这里直接序列化整个 Tool 走 JSON 路径，断言字符串里不含 "required"，
// 比 map 层断言更贴近 wire 真相（map 里没 key 不代表 marshal 后也不出现）。
func TestInputSchemaRequiredOmittedWhenEmpty(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: http://h, auth: none, path_prefix: "" } } }
resources:
  r:
    path: /r
    operations:
      list: { method: GET, path: "", params: { q: { in: query, type: string } } }
`)
	tr, _ := spec.Parse(raw)
	tools := New(tr).ToolsList()
	if len(tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(tools))
	}
	if _, present := tools[0].InputSchema["required"]; present {
		t.Fatalf("无必填字段时 inputSchema 不应有 required key, got %#v", tools[0].InputSchema)
	}
	// 走 JSON wire 路径再确认一次（防 omitempty/自定义 marshal 等盲点）
	b, err := json.Marshal(tools[0])
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte("required")) {
		t.Fatalf("无必填字段时序列化后不应出现 required, got %s", b)
	}
}

// TestToolDescriptionEnrichment 验证 MCP tool description 富化：
//   - 祖先链用途 + operation 用途（让 LLM 看到语义链而非干 verb）
//   - 行为标签：写操作（POST/PUT/PATCH/DELETE）→ [写操作]，有 pagination → [可分页]
//
// 这是 LLM 抉择的关键信号：description 越具体，LLM 选 tool 越准。
func TestToolDescriptionEnrichment(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    description: CMDB 实例
    path: /instances
    operations:
      search:
        description: 按条件搜索实例
        method: POST
        path: /search
        pagination: { type: offset, items_path: data.list, page_param: page, size_param: page_size, size: 20 }
      read:
        description: 读取单个实例
        method: GET
        path: /{id}
        params: { id: { in: path, required: true } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	tools := New(tr).ToolsList()
	byName := map[string]Tool{}
	for _, tl := range tools {
		byName[tl.Name] = tl
	}
	st, ok := byName["cmdb_inst_search"]
	if !ok {
		t.Fatalf("未找到 search tool，got tools: %v", tools)
	}
	// 祖先链用途 + operation 用途
	if !strings.Contains(st.Description, "CMDB 实例") || !strings.Contains(st.Description, "按条件搜索实例") {
		t.Errorf("search description 缺用途链: %q", st.Description)
	}
	// 行为标签：POST → [写操作]，有 pagination → [可分页]
	if !strings.Contains(st.Description, "[写操作]") || !strings.Contains(st.Description, "[可分页]") {
		t.Errorf("search description 缺行为标签: %q", st.Description)
	}
	// read（GET）不应有 [写操作]
	rd := byName["cmdb_inst_read"]
	if strings.Contains(rd.Description, "[写操作]") {
		t.Errorf("read（GET）不应标 [写操作]: %q", rd.Description)
	}
}

// TestServeToolsCallBodyDirect 验证 tools/call 收到嵌套 _body 对象时，经 server marshal
// 成字节、经 engine.Options.BodyBytes 直传到请求 body（绕过单层 body flag）。
//
// mock 后端回显收到的 body；断言嵌套结构（$and/$or）原样到达 wire。
func TestServeToolsCallBodyDirect(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Write([]byte(`{"echo":` + string(body) + `}`))
	}))
	t.Cleanup(srv.Close)

	raw := strings.NewReader(strings.NewReplacer("BASE", srv.URL).Replace(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources:
  r: { path: /r, operations: { search: { method: POST, path: "" } } }
`))
	rawBytes, _ := io.ReadAll(raw)
	tr, _ := spec.Parse(rawBytes)
	s := New(tr)

	// _body 是嵌套对象（含 $and/$or）—— resolve 的单层 body flag 无法表达。
	args := map[string]any{
		"_body": map[string]any{
			"query": map[string]any{
				"$and": []any{
					map[string]any{"$or": []any{map[string]any{"x": map[string]any{"$like": "%a%"}}}},
				},
			},
			"page": 1,
		},
	}
	params, _ := json.Marshal(map[string]any{
		"jsonrpc": "2.0",
		"id":      5,
		"method":  "tools/call",
		"params":  map[string]any{"name": "x_r_search", "arguments": args},
	})
	in := bytes.NewReader(append(params, '\n'))
	var out bytes.Buffer
	if err := s.Serve(context.Background(), in, &out); err != nil {
		t.Fatal(err)
	}
	var resp struct {
		Result struct {
			Content []struct {
				Text string `json:"text"`
			} `json:"content"`
		} `json:"result"`
	}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v (out=%s)", err, out.String())
	}
	if len(resp.Result.Content) == 0 {
		t.Fatalf("result.content 空: %s", out.String())
	}
	// 嵌套结构必须原样到达服务端（被回显进 text）。
	if !strings.Contains(resp.Result.Content[0].Text, `"$and"`) {
		t.Fatalf("嵌套 body 未到达服务端: %s", resp.Result.Content[0].Text)
	}
}
