# api-cli 迭代二 Implementation Plan（P0+P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 api-cli 对 LLM（MCP）真正可用——input/output 嵌套 schema 驱动 + 真实翻页（page-in-body）+ 体验打磨。

**Architecture:** P0 给 LLM 看完整 input(_body)/output schema + 修真实翻页；P1 打磨体验（dry-run 顺序/flag 位置/timeout/required）。tree 加字段、spec 解析、mcp/cobracli/engine 消费。

**Tech Stack:** Go 1.22 / cobra / gjson / net/http / MCP stdio JSON-RPC

## Global Constraints

- **Go**：1.22.5，沙箱 `/usr/local/go/bin` **不在 PATH**，跑 go 前必须 `export PATH=$PATH:/usr/local/go/bin`
- **module**：`api-cli`；`GOPROXY=https://goproxy.cn,direct`
- **命名**：英文标识符 + 中文注释/文档/错误消息
- **基线**：main `6424f90`；走 feature 分支 `api-cli-iter2`
- **TDD + frequent commit**：每 task 末尾 commit，`feat(api-cli):`/`fix(api-cli):`/`refactor(api-cli):` 前缀 + body 末尾 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **改完立即 commit**：工作空间有自动 `chore(ai)` 提交机制，别留未提交改动跑长任务
- **⚠️ 严禁写项目工作目录外**（AGENTS.md §1）：凭证在 `projects/api-cli/.local/`（gitignore），用 `API_CLI_AUTH_D=$PWD/.local/auth.d`
- **`_body` 约定**：body 在 inputSchema/MCP args 的统一字段名（path/query 扁平在外层，body 嵌套对象放 `_body`）
- **description + example 是 LLM 理解核心**：动态结构（MongoDB query 等）靠这俩，清单作者必须写好
- **spec 来源**：`projects/api-cli/docs/2026-08-07-api-cli-iter2-design.md`

---

## File Structure

| 文件 | 职责 | task |
|---|---|---|
| `internal/tree/types.go` | Schema 加 Example/AdditionalProperties；Operation 加 Response；Pagination 加 PageIn | T1 |
| `internal/tree/jsonschema.go` | `Schema.ToJSONSchema()` 递归转 JSON Schema（新文件） | T2 |
| `internal/spec/schema.go` + `parse.go` | 解析 example/response/page_in（yaml tag + 转换） | T1 |
| `internal/mcp/server.go` | Tool 加 OutputSchema；inputSchema 读 Body→_body + required；toolsCall 识别 _body→body bytes | T3,T4,T5,T12 |
| `internal/cobracli/help.go` | `--help-format=json` 含 _body；inputSchema 生成读 Body | T3 |
| `internal/cobracli/build.go` | root `TraverseChildren=true`；新增 `explain` 子命令 | T6,T10 |
| `internal/engine/execute.go` | 接受 body from _body；dry-run 移 gateWrite 前；iterate format 分支；Options.Timeout | T4,T8,T9,T11 |
| `internal/engine/request.go` | `_body` flag/args → req.Body | T4 |
| `internal/paging/engine.go` | DoFunc 协议加 body；planNext PageIn=body 分支 | T7 |
| `internal/output/format.go` | table 用 Response 字段 description 做表头 | T6 |
| `examples/easyops-cmdb.yaml` | search 补完整嵌套 body schema + response schema + page_in: body | T6,T7 |
| `tests/integration/` | _body/page-in-body/format/explain 端到端 | T7,T8 |

---

## Task 1: tree 数据结构加字段 + spec 解析

**Files:**
- Modify: `internal/tree/types.go`（Schema/Operation/Pagination 加字段）
- Modify: `internal/spec/schema.go`（yaml tag）+ `internal/spec/parse.go`（转换）
- Test: `internal/spec/parse_test.go`（新增用例）

**Interfaces:**
- Consumes: 现有 tree/spec 结构
- Produces: `tree.Schema{Example any, AdditionalProperties *bool}`、`tree.Operation{Response *Schema}`、`tree.Pagination{PageIn string}`；spec 能解析 `example`/`response`/`page_in`

- [ ] **Step 1: 写失败测试**

追加到 `internal/spec/parse_test.go`：
```go
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

func ternary(b bool, a, c string) string { if b { return a }; return c }
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd projects/api-cli && export PATH=$PATH:/usr/local/go/bin && go test ./internal/spec/`
Expected: FAIL — `op.Body.Example` 等 undefined/nil

- [ ] **Step 3: 改 tree/types.go（加字段）**

`internal/tree/types.go` 把三个 struct 改为：
```go
// Schema 参数/body/response 的结构描述。
type Schema struct {
	Type                string
	Required            []string
	Properties          map[string]*Schema
	Items               *Schema // type=array 时
	Description         string
	Example             any   // 动态结构示例（LLM 理解核心）
	AdditionalProperties *bool // 允许任意 key（MongoDB query 等）；nil = 不出现该字段
}

// Operation 一个动作（verb 是身份，method 是配置）。
type Operation struct {
	Verb       string
	Method     string
	Path       string
	Params     []Param
	Body       *Schema     // nil = 无 body
	Response   *Schema     // nil = 无 response schema（outputSchema）
	Pagination *Pagination // nil = 无分页
}

// Pagination 分页声明。
type Pagination struct {
	Type          string // cursor|offset|implicit
	ItemsPath     string
	NextTokenPath string
	PageParam     string
	SizeParam     string
	Size          int
	HasMorePath   string
	PageIn        string // page 在哪：空/"query" 默认 / "body"
}
```

- [ ] **Step 4: 改 spec/schema.go（yaml tag）**

`yamlSchema` 加 `Example any \`yaml:"example"\`` + `AdditionalProperties *bool \`yaml:"additional_properties"\``；`yamlOperation` 加 `Response *yamlSchema \`yaml:"response"\``；`yamlPagination` 加 `PageIn string \`yaml:"page_in"\``。

- [ ] **Step 5: 改 spec/parse.go（转换）**

`convertSchema` 末尾加 `s.Example = y.Example; s.AdditionalProperties = y.AdditionalProperties`；`convertOperation` 加 `if y.Response != nil { op.Response = convertSchema(y.Response) }`；`convertPagination` 内加 `pg.PageIn = y.PageIn`。

- [ ] **Step 6: 运行，确认通过**

Run: `go test ./internal/spec/ && go test ./...`
Expected: `ok`（spec + 全包绿）

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/tree/ projects/api-cli/internal/spec/
git commit -m "feat(api-cli): tree 加 Schema.Example/AdditionalProperties + Operation.Response + Pagination.PageIn（迭代二基础）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: tree.Schema.ToJSONSchema() 转换方法

把 tree.Schema 递归转成 JSON Schema（map[string]any），供 inputSchema/outputSchema 生成复用。

**Files:**
- Create: `internal/tree/jsonschema.go`
- Test: `internal/tree/jsonschema_test.go`

**Interfaces:**
- Consumes: Task 1 的 tree.Schema（含 Example/AdditionalProperties）
- Produces: `(*Schema).ToJSONSchema() map[string]any`

- [ ] **Step 1: 写失败测试**

Create `internal/tree/jsonschema_test.go`:
```go
package tree

import (
	"reflect"
	"testing"
)

func TestSchemaToJSONSchema(t *testing.T) {
	b := true
	s := &Schema{
		Type:        "object",
		Description: "搜索请求",
		Required:    []string{"q"},
		Example:     map[string]any{"q": "foo"},
		AdditionalProperties: &b,
		Properties: map[string]*Schema{
			"q": {Type: "string", Description: "关键词"},
			"tags": {Type: "array", Items: &Schema{Type: "string"}},
		},
	}
	got := s.ToJSONSchema()
	want := map[string]any{
		"type":        "object",
		"description": "搜索请求",
		"required":    []string{"q"},
		"example":     map[string]any{"q": "foo"},
		"additionalProperties": true,
		"properties": map[string]any{
			"q":    map[string]any{"type": "string", "description": "关键词"},
			"tags": map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ToJSONSchema mismatch\n got: %#v\nwant: %#v", got, want)
	}
}

func TestSchemaToJSONSchemaNil(t *testing.T) {
	var s *Schema
	if got := s.ToJSONSchema(); got != nil {
		t.Fatalf("nil Schema want nil, got %#v", got)
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/tree/`
Expected: FAIL — `s.ToJSONSchema undefined`

- [ ] **Step 3: 实现 jsonschema.go**

Create `internal/tree/jsonschema.go`:
```go
package tree

// ToJSONSchema 把 Schema 递归转成 JSON Schema（map[string]any），
// 供 mcp/cobracli 生成 inputSchema/outputSchema 复用。nil Schema 返回 nil。
//
// 约定：example 仅非 nil 时输出；additionalProperties 仅指针非 nil 时输出
// （区分"未声明"与"显式 false"）。
func (s *Schema) ToJSONSchema() map[string]any {
	if s == nil {
		return nil
	}
	m := map[string]any{}
	if s.Type != "" {
		m["type"] = s.Type
	}
	if s.Description != "" {
		m["description"] = s.Description
	}
	if len(s.Required) > 0 {
		m["required"] = s.Required
	}
	if s.Example != nil {
		m["example"] = s.Example
	}
	if s.AdditionalProperties != nil {
		m["additionalProperties"] = *s.AdditionalProperties
	}
	if len(s.Properties) > 0 {
		props := map[string]any{}
		for k, v := range s.Properties {
			props[k] = v.ToJSONSchema()
		}
		m["properties"] = props
	}
	if s.Items != nil {
		m["items"] = s.Items.ToJSONSchema()
	}
	return m
}
```

- [ ] **Step 4: 运行，确认通过**

Run: `go test ./internal/tree/`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/tree/jsonschema.go projects/api-cli/internal/tree/jsonschema_test.go
git commit -m "feat(api-cli): tree.Schema.ToJSONSchema() 递归转 JSON Schema

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: inputSchema 读 Body → _body（mcp + cobracli help）

inputSchema 生成时把 operation.Body（嵌套 Schema）转 JSON Schema 放 `inputSchema.properties._body`。

**Files:**
- Modify: `internal/mcp/server.go`（ToolsList 的 inputSchema 加 _body）
- Modify: `internal/cobracli/help.go`（emitHelpJSON 输出含 _body）
- Test: `internal/mcp/server_test.go`、`internal/cobracli/build_test.go`

**Interfaces:**
- Consumes: Task 1/2 的 Operation.Body + ToJSONSchema
- Produces: inputSchema.properties._body = body 嵌套 JSON Schema

- [ ] **Step 1: 写失败测试（mcp）**

追加到 `internal/mcp/server_test.go`：
```go
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
```
（import 如缺补 `"api-cli/internal/spec"`）

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/mcp/`
Expected: FAIL — `_body 缺失`

- [ ] **Step 3: 改 mcp/server.go ToolsList**

把 `ToolsList` 里构建 `props` 的循环后，加：
```go
		// body schema 展开 → _body（嵌套完整结构给 LLM）
		if op.Body != nil {
			props["_body"] = op.Body.ToJSONSchema()
		}
```
（`op.Body.ToJSONSchema()` 来自 Task 2；`tree` 已 import）

- [ ] **Step 4: 运行，确认通过**

Run: `go test ./internal/mcp/`
Expected: `ok`

- [ ] **Step 5: 改 cobracli/help.go emitHelpJSON 同步 _body**

`emitHelpJSON` 当前序列化 `{resource,verb,method,path,params,has_paging}`。加 `body`（op.Body.ToJSONSchema()）：
```go
func emitHelpJSON(w io.Writer, r *tree.Resource, op *tree.Operation) error {
	doc := map[string]any{
		"resource":   r.Name,
		"verb":       op.Verb,
		"method":     op.Method,
		"path":       op.Path,
		"params":     op.Params,
		"has_paging": op.Pagination != nil,
	}
	if op.Body != nil {
		doc["body"] = op.Body.ToJSONSchema()
	}
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(doc)
}
```

- [ ] **Step 6: 全量测试**

Run: `go test ./... && go vet ./...`
Expected: 全绿 + vet clean

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/mcp/ projects/api-cli/internal/cobracli/
git commit -m "feat(api-cli): inputSchema 展开 operation.Body → _body（嵌套 JSON Schema，给 LLM）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: MCP tools/call _body 直传 + engine 接受 body from _body

MCP args 的 `_body`（嵌套对象）→ json.Marshal → 请求 body bytes，绕过单层 flag。

**Files:**
- Modify: `internal/mcp/server.go`（toolsCall 提取 _body → 传 engine）
- Modify: `internal/engine/execute.go`（Options 加 BodyBytes；execute 用它）
- Modify: `internal/engine/request.go`（注释：BodyBytes 优先级）
- Test: `internal/mcp/server_test.go`、`internal/engine/execute_test.go`

**Interfaces:**
- Consumes: Task 3 的 _body 约定
- Produces: `engine.Options.BodyBytes []byte`（MCP _body marshal 后注入；优先级高于 --body-file 和 body flag）

- [ ] **Step 1: 写失败测试（engine 接受 BodyBytes）**

追加到 `internal/engine/execute_test.go`：
```go
func TestExecuteBodyBytes(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		// 回显收到的 body，验证嵌套结构原样到达
		w.Write([]byte(`{"echo":` + string(body) + `}`))
	}))
	defer srv.Close()
	raw := []byte(`
spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources:
  r: { path: /r, operations: { create: { method: POST, path: "" } } }
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["create"]
	r := tr.Resources["r"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	nestedBody := []byte(`{"query":{"$and":[{"$or":[{"x":{"$like":"%a%"}}]}]},"page":1}`)
	err := e.Execute(context.Background(), ep, r, op, nil, nil, Options{
		Format: "json", Out: &out, BodyBytes: nestedBody, Yes: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(out.Bytes(), []byte(`"$and"`)) {
		t.Fatalf("嵌套 body 未到达服务端: %s", out.String())
	}
}
```
（import 补 `io`）

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/engine/`
Expected: FAIL — `Options.BodyBytes undefined`

- [ ] **Step 3: engine.Options 加 BodyBytes + execute 用它**

`internal/engine/execute.go` Options 加字段：
```go
	BodyBytes []byte // 请求 body 字节（MCP _body marshal 后注入；优先级最高，覆盖 --body-file/body flag）
```
Execute 里 body-file 覆盖逻辑后，加（在 gateWrite 前）：
```go
	// BodyBytes（MCP _body）：最高优先级，覆盖 --body-file 和 body 参数
	if len(opts.BodyBytes) > 0 {
		req.Body = opts.BodyBytes
	}
```
（放在 `if opts.BodyFile != ""` 块之后）

- [ ] **Step 4: 运行 engine 测试**

Run: `go test ./internal/engine/`
Expected: `ok`

- [ ] **Step 5: 改 mcp/server.go toolsCall 提取 _body**

`toolsCall` 里 `splitArgs` 后、调 Execute 前，加 _body 提取：
```go
	// _body（嵌套对象）→ marshal 成 body bytes，绕过单层 flag
	var bodyBytes []byte
	if bb, ok := p.Arguments["_body"]; ok {
		bodyBytes, _ = json.Marshal(bb)
	}
```
Execute 调用加 `BodyBytes: bodyBytes`：
```go
	if err := s.e.Execute(ctx, ep, r, op, pathVals, flags, engine.Options{
		Format:    "json",
		BodyBytes: bodyBytes,
		Out:       &buf,
	}); err != nil {
```

- [ ] **Step 6: 全量测试**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/engine/ projects/api-cli/internal/mcp/
git commit -m "feat(api-cli): MCP tools/call _body → body bytes 直传（engine.Options.BodyBytes）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: MCP outputSchema（tool 加 OutputSchema，读 operation.Response）

**Files:**
- Modify: `internal/mcp/server.go`（Tool 加 OutputSchema；ToolsList 读 Response）
- Test: `internal/mcp/server_test.go`

**Interfaces:**
- Consumes: Task 1/2 的 Operation.Response + ToJSONSchema
- Produces: `Tool.OutputSchema map[string]any`

- [ ] **Step 1: 写失败测试**

追加到 `internal/mcp/server_test.go`：
```go
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
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/mcp/`
Expected: FAIL — `outputSchema 缺失`

- [ ] **Step 3: 改 mcp/server.go**

Tool struct 加字段：
```go
type Tool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
	OutputSchema map[string]any `json:"outputSchema,omitempty"`
}
```
ToolsList 构建 Tool 时，在 InputSchema 后加：
```go
			OutputSchema: op.Response.ToJSONSchema(), // nil 时 ToJSONSchema 返回 nil，omitempty 不出现
```

- [ ] **Step 4: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/mcp/
git commit -m "feat(api-cli): MCP tool 加 outputSchema（读 operation.Response，给 LLM 解释响应）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: --explain 子命令 + table 中文表头

**Files:**
- Modify: `internal/cobracli/build.go`（新增 explain 子命令）
- Modify: `internal/output/format.go`（FormatTable 接 headers 表头映射）
- Modify: `internal/engine/execute.go`（single/iterate format=table 时传 Response headers）
- Test: `internal/cobracli/build_test.go`、`internal/output/format_test.go`

**Interfaces:**
- Consumes: Task 1/2 Response + ToJSONSchema；现有 output.Format
- Produces: `output.FormatTable(w, data, headers)`；`api-cli explain <res> <verb>` 子命令

- [ ] **Step 1: 写失败测试（FormatTable headers）**

追加到 `internal/output/format_test.go`：
```go
func TestFormatTableWithHeaders(t *testing.T) {
	var buf bytes.Buffer
	data := []map[string]any{{"id": "i-1", "name": "n"}}
	headers := map[string]string{"id": "实例ID", "name": "名称"}
	if err := FormatTable(&buf, data, headers); err != nil {
		t.Fatal(err)
	}
	// 表头用 headers 的中文（按 key 升序：id < name）
	if !bytes.Contains(buf.Bytes(), []byte("实例ID")) || !bytes.Contains(buf.Bytes(), []byte("名称")) {
		t.Fatalf("表头未用中文: %s", buf.String())
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/output/`
Expected: FAIL — `FormatTable undefined`（签名变了）

- [ ] **Step 3: 改 output/format.go**

把 `formatTable` 重构为导出的 `FormatTable`，接 headers：
```go
// FormatTable 把 slice of map 打成表格；headers[key]=中文表头（无则用 key）。
// 非 slice/非 map 回退 json。表头按 key 字典序（确定性，复用 sort.Strings）。
func FormatTable(w io.Writer, data any, headers map[string]string) error {
	// 与原 formatTable 逻辑一致，但表头列用 headers[key]（无则 key），列顺序按 key 升序
	v := reflect.ValueOf(data)
	if v.Kind() != reflect.Slice {
		return Format(w, "json", data)
	}
	if v.Len() == 0 {
		return nil
	}
	first := v.Index(0)
	if first.Kind() != reflect.Map {
		return Format(w, "json", data)
	}
	keys := []string{}
	for _, k := range first.MapKeys() {
		keys = append(keys, k.String())
	}
	sort.Strings(keys)
	headRow := make([]string, len(keys))
	for i, k := range keys {
		if h, ok := headers[k]; ok && h != "" {
			headRow[i] = h
		} else {
			headRow[i] = k
		}
	}
	fmt.Fprintln(w, joinRow(headRow))
	for i := 0; i < v.Len(); i++ {
		row := make([]string, len(keys))
		m := v.Index(i)
		for j, k := range keys {
			vv := m.MapIndex(reflect.ValueOf(k))
			if vv.IsValid() {
				row[j] = fmt.Sprint(vv.Interface())
			}
		}
		fmt.Fprintln(w, joinRow(row))
	}
	return nil
}
```
`Format` 的 `case "table"` 改调 `FormatTable(w, data, nil)`（向后兼容：无 headers 用字段名）。加 `"sort"` import。

- [ ] **Step 4: 运行，确认通过**

Run: `go test ./internal/output/`
Expected: `ok`

- [ ] **Step 5: engine format=table 时传 Response headers**

`internal/engine/execute.go` 加 helper（从 op.Response 抽 headers）：
```go
// responseHeaders 从 op.Response 的顶层 properties 抽 字段→description 映射（table 中文表头）。
func responseHeaders(op *tree.Operation) map[string]string {
	h := map[string]string{}
	if op.Response == nil || op.Response.Properties == nil {
		return h
	}
	// 响应若是 {data:{list:[{...}]}}，取 list 元素的 properties；否则取 Response 顶层
	target := op.Response
	if d := op.Response.Properties["data"]; d != nil && d.Properties != nil {
		if lst := d.Properties["list"]; lst != nil && lst.Items != nil {
			target = lst.Items
		}
	}
	for k, v := range target.Properties {
		if v.Description != "" {
			h[k] = v.Description
		}
	}
	return h
}
```
`single` 里 `output.Format(opts.Out, opts.Format, data)` 改：
```go
	if opts.Format == "table" {
		return output.FormatTable(opts.Out, data, responseHeaders(op))
	}
	return output.Format(opts.Out, opts.Format, data)
```
（single 签名需能拿到 op —— 当前 single(ctx, req, opts, hc) 无 op；改 single 签名加 op，或 Execute 传。最简：single 加 op 参数，Execute 调 `e.single(ctx, req, op, opts, hc)`）

- [ ] **Step 6: 改 cobracli/build.go 加 explain 子命令**

`Build` 里 root.AddCommand 循环后，加 explain：
```go
	root.AddCommand(explainCmd(tr))
```
新增：
```go
// explainCmd: api-cli explain <resource> <verb> → 输出 operation 的 input+output schema（json）。
func explainCmd(tr *tree.OperationTree) *cobra.Command {
	return &cobra.Command{
		Use:   "explain [resource] [verb]",
		Short: "输出某 operation 的 input/output schema（给人/LLM）",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			r, ok := tr.Resources[args[0]]
			if !ok {
				return fmt.Errorf("资源 %q 不存在", args[0])
			}
			op, ok := r.Operations[args[1]]
			if !ok {
				return fmt.Errorf("操作 %q 不存在", args[1])
			}
			doc := map[string]any{
				"resource": r.Name, "verb": op.Verb, "method": op.Method, "path": op.Path,
				"params": op.Params,
			}
			if op.Body != nil {
				doc["input_body"] = op.Body.ToJSONSchema()
			}
			if op.Response != nil {
				doc["output"] = op.Response.ToJSONSchema()
			}
			enc := json.NewEncoder(os.Stdout)
			enc.SetIndent("", "  ")
			return enc.Encode(doc)
		},
	}
}
```
import 补 `"encoding/json"`、`"os"`、`"fmt"`、`"github.com/spf13/cobra`。

- [ ] **Step 7: 全量测试 + 烟雾**

Run: `go test ./... && go vet ./...`
Expected: 全绿

烟雾（手动，不入自动化）：
```bash
export PATH=$PATH:/usr/local/go/bin && export API_CLI_AUTH_D=$PWD/.local/auth.d
go run ./cmd/api-cli --spec examples/easyops-cmdb.yaml explain object_instance search | head -20
```

- [ ] **Step 8: Commit**

```bash
git add projects/api-cli/internal/output/ projects/api-cli/internal/engine/ projects/api-cli/internal/cobracli/
git commit -m "feat(api-cli): --explain 子命令 + table 中文表头（response schema.description）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 分页 page-in-body（paging DoFunc 协议 + planNext body 分支）

**最复杂的 task**：page 在 body 时翻页改 body 不改 query。涉及 paging 公共 API 改签名（internal，不影响外部）。

**Files:**
- Modify: `internal/paging/engine.go`（DoFunc 加 body；Iter 签名加 firstBody；planNext 按 PageIn 改 body）
- Modify: `internal/engine/execute.go`（iterate 传 body；do 闭包用 body+query）
- Modify: `internal/paging/engine_test.go`（DoFunc/Iter 签名更新 + 新增 page-in-body 用例）
- Modify: `internal/engine/execute_test.go`（iterate 适配）

**Interfaces:**
- Consumes: Task 1 的 Pagination.PageIn
- Produces: `paging.DoFunc func(ctx, body []byte, query map[string]string) ([]byte, error)`；`paging.Iter(ctx, pg, do, firstBody []byte, firstQuery map[string]string, opts)`

- [ ] **Step 1: 写失败测试（page-in-body 翻页）**

追加到 `internal/paging/engine_test.go`：
```go
func TestPageInBodyPaging(t *testing.T) {
	// page 在 body：do 收 body，按 body.page 翻页；3 页（page=1→2→3），第 3 页返回 < size 终止
	pages := map[string][]string{
		"1": {"a", "b"},
		"2": {"c", "d"},
		"3": {"e"}, // < size=2 → 终止
	}
	pg := &tree.Pagination{Type: "offset", PageIn: "body", ItemsPath: "data", PageParam: "page", SizeParam: "page_size", Size: 2}
	do := func(ctx context.Context, body []byte, query map[string]string) ([]byte, error) {
		page := gjson.GetBytes(body, "page").String()
		if page == "" {
			page = "1"
		}
		items := pages[page]
		s := `{"data":[`
		for i, id := range items {
			if i > 0 { s += "," }
			s += fmt.Sprintf(`{"id":%q}`, id)
		}
		s += `]}`
		return []byte(s), nil
	}
	var got []string
	for it := range Iter(context.Background(), pg, do, []byte(`{"page":1,"page_size":2}`), map[string]string{}, Options{MaxPages: 10}) {
		got = append(got, it.ID)
	}
	want := []string{"a", "b", "c", "d", "e"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}
```
import 补 `"reflect"`、`"github.com/tidwall/gjson"`。

- [ ] **Step 2: 运行，确认失败（签名变 + PageIn 未支持）**

Run: `go test ./internal/paging/`
Expected: FAIL — DoFunc/Iter 签名不匹配

- [ ] **Step 3: 改 paging/engine.go（DoFunc + Iter + planNext）**

DoFunc 改签名：
```go
// DoFunc 执行一次请求，返回响应 body。body/query 是可变翻页参数（PageIn 决定改哪个）。
type DoFunc func(ctx context.Context, body []byte, query map[string]string) ([]byte, error)
```
Iter 改签名（firstBody + firstQuery）：
```go
func Iter(ctx context.Context, pg *tree.Pagination, do DoFunc, firstBody []byte, firstQuery map[string]string, opts Options) <-chan Item {
	if opts.MaxPages == 0 { opts.MaxPages = 1000 }
	if opts.MaxItems == 0 { opts.MaxItems = 10000 }
	out := make(chan Item, 100)
	go func() {
		defer close(out)
		body := append([]byte(nil), firstBody...) // 拷贝，翻页改副本
		req := copyMap(firstQuery)
		seen := map[string]bool{}
		count := 0
		for page := 0; page < opts.MaxPages; page++ {
			respBody, err := do(ctx, body, req)
			if err != nil {
				select {
				case out <- Item{Err: err}:
				case <-ctx.Done():
				}
				return
			}
			items := gjson.GetBytes(respBody, pg.ItemsPath).Array()
			for _, it := range items {
				id := gjson.Get(it.Raw, "id").String()
				if !opts.NoDedupe && id != "" {
					if seen[id] { continue }
					seen[id] = true
				}
				select {
				case out <- Item{ID: id, Raw: []byte(it.Raw)}:
				case <-ctx.Done(): return
				}
				count++
				if opts.Limit > 0 && count >= opts.Limit { return }
				if count >= opts.MaxItems { return }
			}
			nextBody, nextReq, more := planNext(respBody, items, pg, body, req)
			if !more { return }
			body = nextBody
			req = nextReq
		}
	}()
	return out
}
```
planNext 改（接 body，按 PageIn 分支）：
```go
func planNext(respBody []byte, items []gjson.Result, pg *tree.Pagination, body []byte, req map[string]string) ([]byte, map[string]string, bool) {
	nextReq := copyMap(req)
	switch pg.Type {
	case "cursor":
		token := gjson.GetBytes(respBody, pg.NextTokenPath).String()
		if token == "" { return body, nextReq, false }
		nextReq["page_token"] = token
		return body, nextReq, true
	case "offset":
		// 终止判断（隐式：条数 < size）
		if pg.Size > 0 && len(items) < pg.Size { return body, nextReq, false }
		// 翻页参数位置：body 还是 query
		if pg.PageIn == "body" {
			nextBody := bumpBodyPage(body, pg.PageParam)
			return nextBody, nextReq, true
		}
		cur := 0
		fmt.Sscanf(req[pg.PageParam], "%d", &cur)
		nextReq[pg.PageParam] = fmt.Sprintf("%d", cur+1)
		return body, nextReq, true
	case "implicit":
		if pg.Size > 0 && len(items) < pg.Size { return body, nextReq, false }
		if len(items) == 0 { return body, nextReq, false }
		return body, nextReq, true
	}
	return body, nextReq, false
}

// bumpBodyPage 把 body JSON 里 page_param 的数字 +1（page-in-body 翻页）。
func bumpBodyPage(body []byte, pageParam string) []byte {
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil { return body }
	cur := 0
	switch v := m[pageParam].(type) {
	case float64: cur = int(v)
	case string: fmt.Sscanf(v, "%d", &cur)
	}
	m[pageParam] = cur + 1
	out, err := json.Marshal(m)
	if err != nil { return body }
	return out
}
```
import 补 `"encoding/json"`。

- [ ] **Step 4: 更新现有 paging 测试（DoFunc/Iter 签名）**

`TestCursorPaging`、`TestImplicitPaging`、`TestLimitTruncation` 里：
- DoFunc 签名改 `func(ctx, body []byte, req map[string]string) ([]byte, error)`（忽略 body）。
- `Iter(ctx, pg, do, nil, firstReq, opts)`（firstBody=nil，firstQuery=原 firstReq）。
- 原 do 闭包用 req（query）的逻辑不变（cursor/implicit 不用 body）。

- [ ] **Step 5: 改 engine/execute.go iterate 适配**

`iterate` 改：
```go
func (e *Engine) iterate(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options, hc *http.Client) error {
	first := copySS(req.Query)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		r2 := *req
		r2.Query = q
		if len(body) > 0 { r2.Body = body } // page-in-body 翻页改 body
		b, status, err := e.do(ctx, &r2, hc)
		if err != nil { return nil, err }
		if status >= 400 { return nil, output.NormalizeAPIError(status, b) }
		return b, nil
	}
	limit := opts.Limit
	if opts.All { limit = 0 }
	items := paging.Iter(ctx, op.Pagination, do, req.Body, first, paging.Options{Limit: limit})
	for it := range items {
		if it.Err != nil {
			if _, ok := it.Err.(*output.APIError); ok { return it.Err }
			return &output.APIError{Code: "paging", Message: it.Err.Error(), ExitCode: output.ExitNetTimeout}
		}
		fmt.Fprintln(opts.Out, string(it.Raw))
	}
	return nil
}
```

- [ ] **Step 6: 更新 engine 现有 iterate 测试 + 全量**

检查 `internal/engine/execute_test.go` + `tests/integration/`：分页相关测试若 mock 用旧 DoFunc 签名，更新（engine 层 DoFunc 是内部闭包，测试不直接调 paging.DoFunc，应不受影响；但跑全量确认）。

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/paging/ projects/api-cli/internal/engine/
git commit -m "feat(api-cli): 分页 page-in-body 支持（paging DoFunc 加 body + planNext 按 PageIn 分支）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 分页 --format（table/yaml 缓冲，json 流式 NDJSON）

**Files:**
- Modify: `internal/engine/execute.go`（iterate 按 format 分支）
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Consumes: Task 6 的 FormatTable + responseHeaders
- Produces: iterate 支持 table/yaml（缓冲）

- [ ] **Step 1: 写失败测试**

追加到 `internal/engine/execute_test.go`：
```go
func TestIterateFormatTable(t *testing.T) {
	// mock 分页：2 条，format=table → 输出表格（含表头），非 NDJSON
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":{"list":[{"id":"1","name":"a"},{"id":"2","name":"b"}]}}`))
	}))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { list: { method: GET, path: "", pagination: { type: offset, items_path: data.list, page_param: page, size_param: size, size: 10 } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["list"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, nil, map[string]string{}, Options{Format: "table", Out: &out, Limit: 10})
	if err != nil { t.Fatal(err) }
	// table 输出应是表格（多列 tab 分隔），非每行一个 JSON
	if !bytes.Contains(out.Bytes(), []byte("\t")) {
		t.Fatalf("format=table 未生效（无 tab）: %s", out.String())
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/engine/`
Expected: FAIL — table 无 tab（当前 iterate 强制 NDJSON）

- [ ] **Step 3: 改 iterate（format 分支）**

iterate 的 `for it := range items` 循环改为按 format 分支：
```go
	limit := opts.Limit
	if opts.All { limit = 0 }
	items := paging.Iter(ctx, op.Pagination, do, req.Body, first, paging.Options{Limit: limit})
	// json：流式 NDJSON（默认，大列表不爆内存）；table/yaml：缓冲全部再 Format
	if opts.Format == "table" || opts.Format == "yaml" {
		var collected []map[string]any
		for it := range items {
			if it.Err != nil {
				if _, ok := it.Err.(*output.APIError); ok { return it.Err }
				return &output.APIError{Code: "paging", Message: it.Err.Error(), ExitCode: output.ExitNetTimeout}
			}
			var m map[string]any
			if err := json.Unmarshal(it.Raw, &m); err == nil {
				collected = append(collected, m)
			}
		}
		if opts.Format == "table" {
			return output.FormatTable(opts.Out, collected, responseHeaders(op))
		}
		return output.Format(opts.Out, "yaml", collected)
	}
	// 默认 json：流式 NDJSON
	for it := range items {
		if it.Err != nil {
			if _, ok := it.Err.(*output.APIError); ok { return it.Err }
			return &output.APIError{Code: "paging", Message: it.Err.Error(), ExitCode: output.ExitNetTimeout}
		}
		fmt.Fprintln(opts.Out, string(it.Raw))
	}
	return nil
```
import 补 `"encoding/json"`（execute.go 已有）。

- [ ] **Step 4: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/engine/
git commit -m "feat(api-cli): 分页 --format 支持（json 流式 NDJSON / table-yaml 缓冲）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: dry-run 移到 gateWrite 前

**Files:**
- Modify: `internal/engine/execute.go`（流程顺序）
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Consumes: 现有 execute 流程
- Produces: `update/delete --dry-run` 非 TTY 不再要 `--yes`（dry-run 安全预览先拦截）

- [ ] **Step 1: 写失败测试**

追加到 `internal/engine/execute_test.go`：
```go
func TestDryRunSkipsGateWrite(t *testing.T) {
	// update --dry-run 非 TTY：dry-run 应在 gateWrite 前拦截，不应报"需 --yes"
	called := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { update: { method: PUT, path: "/{id}", params: { id: { in: path, required: true } } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["update"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, map[string]string{"id": "1"}, nil,
		Options{DryRun: true, Out: &out}) // 不传 Yes
	if err != nil {
		t.Fatalf("dry-run 不应被 gateWrite 拦（应直接预览）: %v", err)
	}
	if called {
		t.Fatal("dry-run 不应真发请求")
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/engine/`
Expected: FAIL — `dry-run 不应被 gateWrite 拦`（当前 gateWrite 在 dry-run 前）

- [ ] **Step 3: 改 execute.go（dry-run 块移到 gateWrite 前）**

把 Execute 里 `// dry-run / print-curl` 块整体移到 `// 写操作闸门 gateWrite` 之前。最终顺序：
```go
	req, err := resolve(e.tr, ep, r, op, pathVals, flags)
	...
	// body-file
	if opts.BodyFile != "" { ... }
	// BodyBytes
	if len(opts.BodyBytes) > 0 { req.Body = opts.BodyBytes }

	// dry-run / print-curl（安全预览，先于写闸门）
	if opts.DryRun || opts.PrintCurl {
		fmt.Fprintln(opts.Out, renderPreview(req, opts))
		return nil
	}

	// 写操作闸门
	if err := gateWrite(op.Verb, opts); err != nil { return err }

	// auth.Apply
	...
```

- [ ] **Step 4: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿（既有 execute 测试不破坏）

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/engine/
git commit -m "fix(api-cli): dry-run 移 gateWrite 前（安全预览不被写闸门拦）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: 全局 flag 任意位置（root TraverseChildren）

**Files:**
- Modify: `internal/cobracli/build.go`（root 加 TraverseChildren）
- Test: `tests/integration/cmdb_test.go`（新增 --insecure 最前用例）

**Interfaces:**
- Consumes: 现有 cobra root
- Produces: `--insecure`/`--spec` 等全局 flag 放最前（`api-cli --insecure ... search`）也生效

- [ ] **Step 1: 写失败测试（集成）**

追加到 `tests/integration/cmdb_test.go`：
```go
func TestGlobalFlagTraverseChildren(t *testing.T) {
	// --insecure 放最前（root 位置）应生效（TraverseChildren=true）
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil { t.Fatal(err) }
	// 断言 root 开了 TraverseChildren
	if !root.TraverseChildren {
		t.Fatal("root.TraverseChildren 应为 true")
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./tests/integration/`
Expected: FAIL — `root.TraverseChildren 应为 true`

- [ ] **Step 3: 改 build.go**

`Build` 里 root 构造加 `TraverseChildren: true`：
```go
	root := &cobra.Command{
		Use:               tr.Service.Name,
		Short:             tr.Service.Name + " CLI（声明式生成）",
		SilenceUsage:      true,
		SilenceErrors:     true,
		TraverseChildren:  true, // 全局 flag（--insecure/--spec）可放子命令前
	}
```

- [ ] **Step 4: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/cobracli/ projects/api-cli/tests/integration/
git commit -m "feat(api-cli): root TraverseChildren（全局 flag 任意位置）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: --timeout

**Files:**
- Modify: `internal/engine/execute.go`（Options.Timeout + Execute 用 context.WithTimeout）
- Modify: `internal/cobracli/flags.go`（--timeout flag + globalOpts）
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Consumes: 现有 execute
- Produces: `Options.Timeout time.Duration`；Execute 超时返回 ExitNetTimeout；cobracli `--timeout`

- [ ] **Step 1: 写失败测试**

追加到 `internal/engine/execute_test.go`：
```go
func TestExecuteTimeout(t *testing.T) {
	// mock 慢响应（>100ms），--timeout=50ms → 超时错误
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	raw := []byte(`spec: api-cli/v1
service: { name: x, default_endpoint: e, endpoints: { e: { base_url: BASE, auth: none, path_prefix: "" } } }
resources: { r: { path: /r, operations: { read: { method: GET, path: "/{id}", params: { id: { in: path, required: true } } } } } }`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(srv.URL))
	tr, _ := spec.Parse(raw)
	e := New(tr)
	op := tr.Resources["r"].Operations["read"]
	ep, _ := tr.SelectEndpoint("")
	err := e.Execute(context.Background(), ep, tr.Resources["r"], op, map[string]string{"id": "1"}, nil,
		Options{Format: "json", Out: &bytes.Buffer{}, Timeout: 50 * time.Millisecond})
	if err == nil { t.Fatal("应超时报错") }
	ae, ok := err.(*output.APIError)
	if !ok || ae.ExitCode != output.ExitNetTimeout {
		t.Fatalf("应是 net timeout，got %#v", err)
	}
}
```
import 补 `"time"`。

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/engine/`
Expected: FAIL — `Options.Timeout undefined`

- [ ] **Step 3: 改 execute.go（Options.Timeout + Execute 用 ctx）**

Options 加：
```go
	Timeout time.Duration // HTTP 超时（0 = 不限）
```
Execute 开头（Out 检查后）加：
```go
	ctx := ctx // shadow 避免改入参？不，直接用
	if opts.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, opts.Timeout)
		defer cancel()
	}
```
（参数名 ctx 不变；在函数体开头加 context.WithTimeout 包装）

- [ ] **Step 4: 改 cobracli/flags.go（--timeout flag）**

bindGlobalFlags 加：
```go
	root.PersistentFlags().Duration("timeout", 0, "HTTP 超时（如 30s；0=不限）")
```
globalOpts 的 Options 加：
```go
		Timeout:   durationFlag(f, "timeout"),
```
新增 helper：
```go
func durationFlag(f *pflag.FlagSet, name string) time.Duration {
	v, _ := f.GetDuration(name)
	return v
}
```
import 补 `"time"`。

- [ ] **Step 5: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add projects/api-cli/internal/engine/ projects/api-cli/internal/cobracli/
git commit -m "feat(api-cli): --timeout（Options.Timeout + context.WithTimeout）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: MCP inputSchema.required

**Files:**
- Modify: `internal/mcp/server.go`（ToolsList 聚合 required）
- Test: `internal/mcp/server_test.go`

**Interfaces:**
- Consumes: 现有 ToolsList
- Produces: inputSchema.required = path required + body required（去重）

- [ ] **Step 1: 写失败测试**

追加到 `internal/mcp/server_test.go`：
```go
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
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/mcp/`
Expected: FAIL — `inputSchema.required 缺失`

- [ ] **Step 3: 改 ToolsList 聚合 required**

ToolsList 构建 Tool 时，InputSchema map 加 required 聚合：
```go
			InputSchema: map[string]any{
				"type":       "object",
				"properties": props,
				"required":   collectRequired(op), // 新增
			},
```
新增 helper：
```go
// collectRequired 聚合 path 参数 required + body schema required（去重）。
func collectRequired(op *tree.Operation) []string {
	seen := map[string]bool{}
	var req []string
	for _, p := range op.Params {
		if p.Required && !seen[p.Name] {
			seen[p.Name] = true
			req = append(req, p.Name)
		}
	}
	if op.Body != nil {
		for _, r := range op.Body.Required {
			if !seen[r] {
				seen[r] = true
				req = append(req, r)
			}
		}
	}
	return req // 可空；MCP 客户端容忍空数组
}
```

- [ ] **Step 4: 运行，确认通过 + 全量**

Run: `go test ./... && go vet ./...`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/mcp/
git commit -m "feat(api-cli): MCP inputSchema.required（path + body required 聚合）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13（收尾）: 补全 examples/easyops-cmdb.yaml + 集成验证

**Files:**
- Modify: `projects/api-cli/examples/easyops-cmdb.yaml`（search 补完整嵌套 body schema + response schema + page_in: body）
- Test: `tests/integration/cmdb_test.go`（_body + page-in-body + table 端到端）

- [ ] **Step 1: 补全 easyops-cmdb.yaml search**

search operation 改为：
```yaml
      search:
        method: POST
        path: /_search
        params:
          object_id: { in: path, type: string, required: true, description: 对象模型 ID }
        body:
          type: object
          required: [page, page_size]
          description: CMDB 实例搜索请求
          properties:
            fields: { type: array, items: { type: string }, description: 返回字段 }
            page: { type: integer, description: 页码（从1起） }
            page_size: { type: integer, description: 每页条数 }
            sort: { type: array, description: 排序，order=-1降序, items: { type: object, properties: { key: { type: string }, order: { type: integer } } } }
            query:
              type: object
              description: 查询条件，MongoDB 风格（$and/$or 组合，字段名做 key，操作符 $like/$eq 等）
              additional_properties: true
              example: { "$and": [{ "$or": [{ "namespaceId": { "$like": "%easyops.%" } }] }] }
            relation_limit: { type: integer }
        response:
          type: object
          properties:
            data: { type: object, description: 响应数据, properties: { list: { type: array, description: 实例列表, items: { type: object, properties: { instanceId: { type: string, description: 实例ID }, name: { type: string, description: 名称 }, namespaceId: { type: string, description: 命名空间ID } } } }, total: { type: integer, description: 总条数 } } }
        pagination:
          type: offset
          page_in: body
          items_path: data.list
          page_param: page
          size_param: page_size
          size: 20
```

- [ ] **Step 2: 集成测试（_body + page-in-body + table）**

追加到 `tests/integration/cmdb_test.go`：
```go
func TestE2EMCPBodySchemaAndPaging(t *testing.T) {
	// 通过 MCP tools/call：_body 嵌套 + page-in-body 翻 2 页 + table 表头中文
	mock := NewCMDBMock() // 扩展 mock 支持 page-in-body 分页
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	srv := mcp.New(tr)
	// tools/list 验证 _body + required + outputSchema
	tools := srv.ToolsList()
	// （断言 _body 嵌套 / required 含 object_id,page / outputSchema 在）
	// tools/call 验证 _body 直传 + 翻页
	_ = tools
}
```
（mock 扩展 page-in-body 分页响应；断言细化由实施者按 mock 能力补全）

- [ ] **Step 3: 全量验证 + gofmt**

Run: `export PATH=$PATH:/usr/local/go/bin && gofmt -w . && go test ./... && go vet ./... && go build ./...`
Expected: 全绿 + gofmt 干净 + build 通过

- [ ] **Step 4: Commit**

```bash
git add projects/api-cli/examples/ projects/api-cli/tests/integration/
git commit -m "feat(api-cli): easyops-cmdb 示例补全嵌套 body/response schema + page_in + 集成验证

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 自检

- [ ] **Spec 覆盖**：P0-1 inputSchema 嵌套 body（T2/T3/T4）✓；P0-2 outputSchema（T5）+ --explain/table（T6）✓；P0-3 page-in-body（T1 PageIn 字段 + T7）✓；P0-4 分页 format（T8）✓；P1-5 dry-run 顺序（T9）✓；P1-6 flag 位置（T10）✓；P1-7 timeout（T11）✓；P1-8 required（T12）✓。
- [ ] **占位符**：无 TBD/TODO；T13 的集成断言标注"按 mock 能力补全"——实施者扩展 mock 后写具体断言（mock 扩展是 T13 Step 2 的明确子任务，非占位）。
- [ ] **类型一致**：`Schema.ToJSONSchema()`（T2 定义，T3/T5/T6 用）；`Operation.Response`/`Pagination.PageIn`（T1 定义，T5/T7 用）；`Options.BodyBytes`（T4 定义）/`Options.Timeout`（T11 定义）；`paging.DoFunc`/`Iter` 新签名（T7 定义，T8 复用）；`output.FormatTable(w,data,headers)`（T6 定义，T8 用）。

---

## Execution Handoff

Plan complete and saved to `projects/api-cli/docs/2026-08-07-api-cli-iter2-plan.md`. Two execution options:

1. **Subagent-Driven（推荐）**：每 task 派全新 subagent，task 间两阶段 review（P0 先、P1 后）。
2. **Inline Execution**：当前会话 executing-plans 批量执行 + checkpoint。

**选哪种？**
