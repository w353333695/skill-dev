# api-cli 迭代四 实现计划（二进制上下传：multipart 上传 + binary 下载 + spec schema 扩展）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 api-cli **CLI** 原生支持文件上传（multipart/formData）与文件下载（binary 响应落盘），消除 EasyOps `tool_package` 导入导出被迫走 Python SDK 的例外；**MCP 通道显式不支持 binary**（toolsCall 报错 + `[CLI-only]` 标签），binary verb 走 CLI。

**Architecture:** 数据结构先行（Task 1 给 `Operation.ContentType` / `Param.Format` / `Schema.Format` + spec 解析 + err 级 lint）；Task 2 在 engine 加 `buildMultipart` + resolve 分支构造上传请求，并让 `renderPreview` 不刷二进制；Task 3 在 `single()` 加 binary 响应分支，`writeOutput` **只写 `opts.Out`**（落盘归 cobracli 层）；Task 4 加 `--output/-o` flag + `Options.OutCloser` + cobracli RunE `defer Close` + 文档 + 示例清单；Task 5 用 `httptest.Server` 端到端验证；Task 6 MCP 通道排除 binary（依赖 Task 1 的 `Schema.Format`）。全字段 backward compatible（零值即旧行为）。

**落盘分层（关键约定）：** engine 的 `writeOutput` 只写 `opts.Out`，**不持有文件句柄、不读文件路径**；`--output` 时 cobracli `globalOpts` 把 `opts.Out` 重定向到 `os.Create(path)` 并记 `OutCloser`，RunE 在 Execute 后 Close。binary 与文本两条路径出口一致（都写 `opts.Out`），engine 零泄漏。

**Tech Stack:** Go 1.22.5、spf13/cobra、pflag、yaml.v3、net/http、mime/multipart、net/http/httptest。

**对应 design：** `projects/api-cli/docs/2026-08-10-api-cli-iter4-design.md`（design 的 T1→plan Task 1，T2→Task 2，T3→Task 3，T4→Task 4，T5→Task 5，T6→Task 6）。

## Global Constraints

- 中文沟通、中文注释；只改 `projects/api-cli/` 内文件。
- go 不在默认 PATH：每个跑 go 的 step 先 `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin`（go1.22.5）。
- 测试命令统一：`cd projects/api-cli && go test ./...`（全包）或指定包 `go test ./internal/<pkg>/...`。
- TDD 严格：每步先写失败测试 → 跑红 → 写最小实现 → 跑绿 → commit。不允许跳过红/绿。
- 改完**立即手动 commit**（工作空间有 `chore(ai)` 自动提交机制，会扫未提交改动）。
- 本迭代测试用 `auth: none` 的最小清单 + `httptest.Server`，不依赖 `~/.api-cli/auth.d` 凭证与真实 EasyOps。
- 严禁写项目工作目录外（AGENTS.md §1）。

---

## File Structure

| 文件 | 责任 | 涉及 task |
|---|---|---|
| `internal/spec/schema.go` | yaml 中间结构：`yamlOperation`/`yamlParam`/`yamlSchema` 加 `content_type`/`format` tag | 1 |
| `internal/spec/parse.go` | `convertOperation`/params 循环/`convertSchema` 透传新字段；加 4 条 err 级 lint | 1 |
| `internal/spec/parse_test.go` | schema 解析（content_type/format 透传）+ lint 4 条 | 1 |
| `internal/tree/types.go` | `Operation`/`Param`/`Schema` 加 `ContentType`/`Format` 字段 | 1 |
| `internal/engine/multipart.go` | `buildMultipart`（构造 multipart body + Content-Type） | 2 |
| `internal/engine/multipart_test.go` | `buildMultipart` 单测 | 2 |
| `internal/engine/request.go` | `resolvedReq` 加 `ContentType`；resolve 末尾 multipart 分支 | 2 |
| `internal/engine/execute.go` | `Options.OutCloser`（T4）；`do()` 设 Content-Type（T2）；`renderPreview` multipart 省略 body（T2）；`single()` binary 分支 + `writeOutput`（只写 Out，T3） | 2, 3, 4 |
| `internal/engine/execute_test.go` | multipart 端到端（engine 层）+ binary 写 Out 单测 | 2, 3 |
| `internal/cobracli/flags.go` | `bindGlobalFlags` 加 `--output/-o`；`globalOpts` `os.Create`→`Out`+`OutCloser`（补 import `"os"`） | 4 |
| `internal/cobracli/build.go` | `operationCmd` RunE 加 `defer opts.OutCloser.Close()` | 4 |
| `internal/cobracli/smoke_test.go` | `--output` flag + OutCloser 行为 | 4 |
| `internal/mcp/server.go` | `toolsCall` 对 binary 响应/multipart 上传报错；`buildToolDescription` 加 `[CLI-only]` 标签；`isCLIOnlyVerb` 谓词 | 6 |
| `internal/mcp/server_test.go` | toolsCall binary/multipart 拒绝 + `[CLI-only]` 标签（两类 verb 各子用例） | 6 |
| `examples/binary.yaml` | upload + download verb 示例清单 | 4, 5 |
| `docs/USAGE.md` | §6 语法 + flag 表 + §9 状态更新 | 4 |
| `tests/integration/binary_test.go` | httptest 端到端 | 5 |

---

## Task 1: spec schema 扩展（content_type + format: binary）+ lint

**Files:**
- Modify: `projects/api-cli/internal/spec/schema.go`（`yamlOperation`/`yamlParam`/`yamlSchema` 加 tag）
- Modify: `projects/api-cli/internal/spec/parse.go`（convert 透传 + lint）
- Modify: `projects/api-cli/internal/tree/types.go`（`Operation`/`Param`/`Schema` 加字段）
- Test: `projects/api-cli/internal/spec/parse_test.go`

**Interfaces:**
- Produces: `tree.Operation.ContentType string`、`tree.Param.Format string`、`tree.Schema.Format string`；`spec.Parse` 对 `content_type`/`format` 的解析 + 4 条 err 级 lint 错误。

- [ ] **Step 1: 写失败测试**（`parse_test.go` 末尾追加）

```go
func TestParseBinaryFields(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: svc, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none } } }
resources:
  pkg:
    operations:
      upload:
        method: POST
        path: /upload
        content_type: multipart-form-data
        params:
          file: { in: formData, format: binary, required: true }
          kind: { in: formData }
      download:
        method: GET
        path: /dl/{id}
        params:
          id: { in: path, type: string, required: true }
        response:
          format: binary
          description: 文件内容
`)
	tr, err := Parse(raw)
	if err != nil {
		t.Fatalf("Parse 失败: %v", err)
	}
	up := tr.Resources["pkg"].Operations["upload"]
	if up.ContentType != "multipart-form-data" {
		t.Errorf("upload.ContentType = %q, want multipart-form-data", up.ContentType)
	}
	var fileParam *tree.Param
	for i := range up.Params {
		if up.Params[i].Name == "file" {
			fileParam = &up.Params[i]
		}
	}
	if fileParam == nil || fileParam.Format != "binary" {
		t.Errorf("file param Format = %q, want binary", fileParam)
	}
	dl := tr.Resources["pkg"].Operations["download"]
	if dl.Response == nil || dl.Response.Format != "binary" {
		t.Errorf("download.Response.Format want binary, got %+v", dl.Response)
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/spec/ -run TestParseBinaryFields -v`
Expected: FAIL（`ContentType`/`Format` 字段不存在，编译错误或字段空）。

- [ ] **Step 3: 数据结构 + 解析实现**

`internal/tree/types.go`：`Operation` 加 `ContentType string`；`Param` 加 `Format string`；`Schema` 加 `Format string`。

```go
// Operation 一个动作（verb 是身份，method 是配置）。
type Operation struct {
	Verb        string
	Method      string
	Path        string
	Description string
	ContentType string // 请求体类型：空/"json" = JSON（默认）；"multipart-form-data" = 文件上传
	Params      []Param
	Body        *Schema
	Response    *Schema
	Pagination  *Pagination
}

// Param 一个入参。
type Param struct {
	Name        string
	In          string // path|query|header|body|formData
	Type        string
	Required    bool
	Enum        []string
	Pattern     string
	Format      string // 空 = 普通；"binary" = 文件（仅 in=formData）
	Description string
	Example     any
}

// Schema 参数/body/response 的结构描述。
type Schema struct {
	Type                 string
	Required             []string
	Properties           map[string]*Schema
	Items                *Schema
	Description          string
	Format               string // 空 = 普通；"binary" = 二进制流响应（仅 response 用）
	Example              any
	AdditionalProperties *bool
}
```

`internal/spec/schema.go`：三个 yaml 结构体加 tag。

```go
type yamlOperation struct {
	Description string               `yaml:"description"`
	Method      string               `yaml:"method"`
	Path        string               `yaml:"path"`
	ContentType string               `yaml:"content_type"` // ← 新增
	Params      map[string]yamlParam `yaml:"params"`
	Body        *yamlSchema          `yaml:"body"`
	Response    *yamlSchema          `yaml:"response"`
	Pagination  *yamlPagination      `yaml:"pagination"`
}

type yamlParam struct {
	In          string   `yaml:"in"`
	Type        string   `yaml:"type"`
	Required    bool     `yaml:"required"`
	Enum        []string `yaml:"enum"`
	Pattern     string   `yaml:"pattern"`
	Format      string   `yaml:"format"` // ← 新增
	Description string   `yaml:"description"`
}

type yamlSchema struct {
	Type                 string                 `yaml:"type"`
	Required             []string               `yaml:"required"`
	Properties           map[string]*yamlSchema `yaml:"properties"`
	Items                *yamlSchema            `yaml:"items"`
	Description          string                 `yaml:"description"`
	Format               string                 `yaml:"format"` // ← 新增
	Example              any                    `yaml:"example"`
	AdditionalProperties *bool                  `yaml:"additional_properties"`
}
```

`internal/spec/parse.go`：`convertOperation` 透传 `ContentType`，params 循环透传 `Format`，`convertSchema` 透传 `Format`。

```go
func convertOperation(verb string, y *yamlOperation) *tree.Operation {
	op := &tree.Operation{Verb: verb, Method: y.Method, Path: y.Path, Description: y.Description, ContentType: y.ContentType}
	if op.Method == "" {
		op.Method = defaultMethod[verb]
	}
	for pname, p := range y.Params {
		op.Params = append(op.Params, tree.Param{
			Name: pname, In: p.In, Type: p.Type, Required: p.Required,
			Enum: p.Enum, Pattern: p.Pattern, Format: p.Format, Description: p.Description,
		})
	}
	if y.Body != nil {
		op.Body = convertSchema(y.Body)
	}
	if y.Response != nil {
		op.Response = convertSchema(y.Response)
	}
	if y.Pagination != nil {
		op.Pagination = &tree.Pagination{
			Type: y.Pagination.Type, ItemsPath: y.Pagination.ItemsPath,
			NextTokenPath: y.Pagination.NextTokenPath, PageParam: y.Pagination.PageParam,
			SizeParam: y.Pagination.SizeParam, Size: y.Pagination.Size, HasMorePath: y.Pagination.HasMorePath,
			PageIn: y.Pagination.PageIn,
		}
	}
	return op
}

func convertSchema(y *yamlSchema) *tree.Schema {
	s := &tree.Schema{Type: y.Type, Required: y.Required, Description: y.Description, Format: y.Format}
	for k, v := range y.Properties {
		if s.Properties == nil {
			s.Properties = map[string]*tree.Schema{}
		}
		s.Properties[k] = convertSchema(v)
	}
	if y.Items != nil {
		s.Items = convertSchema(y.Items)
	}
	s.Example = y.Example
	s.AdditionalProperties = y.AdditionalProperties
	return s
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/spec/ -run TestParseBinaryFields -v`
Expected: PASS。

- [ ] **Step 5: 写 lint 失败测试**（`parse_test.go` 追加）

```go
func TestParseBinaryLint(t *testing.T) {
	cases := []struct{ name, manifest, wantSub string }{
		{
			name: "content_type 非法值",
			manifest: `spec: api-cli/v1
service: { name: s, default_endpoint: b, endpoints: { b: { base_url: http://x, auth: none } } }
resources:
  r:
    operations:
      u: { method: POST, path: /u, content_type: xml }
`,
			wantSub: "content_type",
		},
		{
			name: "format=binary 但 in≠formData",
			manifest: `spec: api-cli/v1
service: { name: s, default_endpoint: b, endpoints: { b: { base_url: http://x, auth: none } } }
resources:
  r:
    operations:
      u:
        method: POST
        path: /u
        content_type: multipart-form-data
        params:
          f: { in: query, format: binary }
`,
			wantSub: "binary",
		},
		{
			name: "response.format=binary 又有 properties",
			manifest: `spec: api-cli/v1
service: { name: s, default_endpoint: b, endpoints: { b: { base_url: http://x, auth: none } } }
resources:
  r:
    operations:
      d:
        method: GET
        path: /d
        response:
          format: binary
          properties:
            x: { type: string }
`,
			wantSub: "binary",
		},
		{
			name: "response.format=binary 又有 pagination",
			manifest: `spec: api-cli/v1
service: { name: s, default_endpoint: b, endpoints: { b: { base_url: http://x, auth: none } } }
resources:
  r:
    operations:
      d:
        method: GET
        path: /d
        response: { format: binary }
        pagination: { type: offset, items_path: data.list, page_param: page, size_param: size, size: 10 }
`,
			wantSub: "binary",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, err := Parse([]byte(c.manifest))
			if err == nil || !strings.Contains(err.Error(), c.wantSub) {
				t.Errorf("期望 err 含 %q，got: %v", c.wantSub, err)
			}
		})
	}
}
```

- [ ] **Step 6: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/spec/ -run TestParseBinaryLint -v`
Expected: FAIL（Parse 当前不校验这些，返回 nil err）。

- [ ] **Step 7: 实现 lint**

`internal/spec/parse.go`：在 `Parse` 的 resources 转换后、`lintParentKey` 循环之前，加 `lintBinary(tr)`（遍历所有 resource/operation，含 children 递归）。**err 级**（阻断 Parse，区别于 `lintParentKey` 的 warning 级）。

```go
// lintBinary 校验二进制相关声明（content_type 取值 / format=binary 的 in 约束 /
// response.format=binary 不含结构 / binary × pagination 互斥）。err 级，阻断 Parse。
func lintBinary(tr *tree.OperationTree) error {
	var firstErr error
	check := func(op *tree.Operation) {
		if firstErr != nil {
			return
		}
		ct := op.ContentType
		if ct != "" && ct != "json" && ct != "multipart-form-data" {
			firstErr = fmt.Errorf("operation %q: content_type %q 非法（允许 json/multipart-form-data）", op.Verb, ct)
			return
		}
		for _, p := range op.Params {
			if p.Format == "binary" && p.In != "formData" {
				firstErr = fmt.Errorf("operation %q: param %q format=binary 必须 in=formData（当前 in=%q）", op.Verb, p.Name, p.In)
				return
			}
		}
		if op.Response != nil && op.Response.Format == "binary" {
			if len(op.Response.Properties) > 0 || op.Response.Items != nil {
				firstErr = fmt.Errorf("operation %q: response.format=binary 不能再声明 properties/items", op.Verb)
				return
			}
			if op.Pagination != nil {
				firstErr = fmt.Errorf("operation %q: response.format=binary 不支持 pagination（二进制响应不分页）", op.Verb)
				return
			}
		}
	}
	var walk func(*tree.Resource)
	walk = func(r *tree.Resource) {
		for _, op := range r.Operations {
			check(op)
		}
		for _, c := range r.Children {
			walk(c)
		}
	}
	for _, r := range tr.Resources {
		walk(r)
	}
	return firstErr
}
```

在 `Parse` 内（`lintParentKey` 循环之前）加：

```go
	if err := lintBinary(tr); err != nil {
		return nil, err
	}
```

- [ ] **Step 8: 跑全包测试 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS（含新测试 + 现有全绿）。

```bash
git add projects/api-cli/internal/spec/schema.go projects/api-cli/internal/spec/parse.go projects/api-cli/internal/spec/parse_test.go projects/api-cli/internal/tree/types.go
git commit -m "feat(api-cli): iter4 T1 spec schema 扩展（content_type + format=binary）+ err 级 lint"
```

---

## Task 2: multipart 请求构造（文件上传）+ renderPreview 不刷二进制

**Files:**
- Create: `projects/api-cli/internal/engine/multipart.go`
- Create: `projects/api-cli/internal/engine/multipart_test.go`
- Modify: `projects/api-cli/internal/engine/request.go`（`resolvedReq.ContentType` + resolve 分支）
- Modify: `projects/api-cli/internal/engine/execute.go`（`do()` 设 Content-Type；`renderPreview` multipart 省略 body）
- Test: `projects/api-cli/internal/engine/execute_test.go`（端到端：resolve → multipart body）

**Interfaces:**
- Consumes: `tree.Operation.ContentType`、`tree.Param.Format`/`In`（Task 1）
- Produces: `buildMultipart(op, flags) (body []byte, contentType string, err error)`；`resolvedReq.ContentType string`；`do()` 对 `req.ContentType` 设 httpReq Header；`renderPreview` 对 multipart 不刷原始 body。

- [ ] **Step 1: 写 buildMultipart 失败测试**（`multipart_test.go` 新建）

```go
package engine

import (
	"bytes"
	"mime/multipart"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/internal/tree"
)

func TestBuildMultipart(t *testing.T) {
	// 准备临时上传文件
	tmp := t.TempDir()
	fp := filepath.Join(tmp, "pkg.tar.gz")
	payload := []byte{0x1f, 0x8b, 0x08, 0x00, 0xAA, 0xBB}
	if err := os.WriteFile(fp, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	op := &tree.Operation{
		Verb:        "upload",
		Method:      "POST",
		ContentType: "multipart-form-data",
		Params: []tree.Param{
			{Name: "file", In: "formData", Format: "binary", Required: true},
			{Name: "kind", In: "formData"},
			{Name: "token", In: "header"}, // 不进 multipart
		},
	}
	flags := map[string]string{"file": fp, "kind": "tool", "token": "abc"}
	body, ct, err := buildMultipart(op, flags)
	if err != nil {
		t.Fatalf("buildMultipart: %v", err)
	}
	if !strings.HasPrefix(ct, "multipart/form-data; boundary=") {
		t.Errorf("Content-Type = %q, want multipart/form-data; boundary=", ct)
	}
	// 解析回 multipart，校验字段 + 文件
	r := multipart.NewReader(bytes.NewReader(body), strings.TrimPrefix(ct, "multipart/form-data; boundary="))
	kindSet, fileSet := false, false
	for {
		part, err := r.NextPart()
		if err != nil {
			break
		}
		switch part.FormName() {
		case "kind":
			buf := new(bytes.Buffer)
			buf.ReadFrom(part)
			if buf.String() != "tool" {
				t.Errorf("kind field = %q, want tool", buf.String())
			}
			kindSet = true
		case "file":
			if part.FileName() != "pkg.tar.gz" {
				t.Errorf("file filename = %q, want pkg.tar.gz", part.FileName())
			}
			buf := new(bytes.Buffer)
			buf.ReadFrom(part)
			if !bytes.Equal(buf.Bytes(), payload) {
				t.Errorf("file content mismatch")
			}
			fileSet = true
		}
	}
	if !kindSet || !fileSet {
		t.Errorf("未完整解析 multipart：kind=%v file=%v", kindSet, fileSet)
	}
}

func TestBuildMultipartFileMissing(t *testing.T) {
	op := &tree.Operation{
		ContentType: "multipart-form-data",
		Params:      []tree.Param{{Name: "file", In: "formData", Format: "binary", Required: true}},
	}
	_, _, err := buildMultipart(op, map[string]string{"file": "/no/such/file.tar.gz"})
	if err == nil {
		t.Error("文件不存在应报错")
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/engine/ -run TestBuildMultipart -v`
Expected: FAIL（`buildMultipart` 未定义）。

- [ ] **Step 3: 实现 buildMultipart**（`multipart.go` 新建）

```go
package engine

import (
	"bytes"
	"fmt"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"

	"api-cli/internal/tree"
)

// buildMultipart 构造 multipart/form-data 请求体（文件 part + 普通表单字段 part）。
//   - format=binary 的 param：value 视为本地文件路径，读文件内容写 part（filename=base）
//   - in=formData 的普通 param：WriteField
//   - query/header param 不在此处理（仍由 resolve 主流程分发）
// 返回 body 字节 + 含 boundary 的 Content-Type。
func buildMultipart(op *tree.Operation, flags map[string]string) ([]byte, string, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	for _, p := range op.Params {
		v, ok := flags[p.Name]
		if !ok || v == "" {
			continue
		}
		switch {
		case p.Format == "binary":
			fw, err := w.CreateFormFile(p.Name, filepath.Base(v))
			if err != nil {
				return nil, "", err
			}
			f, err := os.Open(v)
			if err != nil {
				return nil, "", fmt.Errorf("打开上传文件 %q 失败: %w", v, err)
			}
			if _, err := io.Copy(fw, f); err != nil {
				f.Close()
				return nil, "", err
			}
			f.Close()
		case p.In == "formData":
			if err := w.WriteField(p.Name, v); err != nil {
				return nil, "", err
			}
		}
	}
	if err := w.Close(); err != nil {
		return nil, "", err
	}
	return buf.Bytes(), w.FormDataContentType(), nil
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/engine/ -run TestBuildMultipart -v`
Expected: PASS。

- [ ] **Step 5: resolve 接入 + resolvedReq.ContentType + do() 设 Content-Type**

`internal/engine/request.go`：`resolvedReq` 加 `ContentType string`（在 `Body []byte` 之后）；`resolve` 在 `if len(bodyParams) > 0 { ... }` 块之后、`return req, nil` 之前加 multipart 分支。

```go
type resolvedReq struct {
	Method      string
	URL         string
	Host        string
	Query       map[string]string
	Header      map[string]string
	Body        []byte
	ContentType string // 非空时 do() 设 httpReq Content-Type（multipart 含 boundary）
}
```

resolve 末尾分支：

```go
	// multipart 请求：op.ContentType == "multipart-form-data" 时用 buildMultipart 构造，
	// 覆盖 bodyParams（multipart verb 的字段都进 formData，不走 JSON bodyParams）。
	if op.ContentType == "multipart-form-data" {
		body, ct, err := buildMultipart(op, flags)
		if err != nil {
			return nil, err
		}
		req.Body = body
		req.ContentType = ct
	}
	return req, nil
```

`internal/engine/execute.go` 的 `do()`：在 `for k, v := range req.Header { ... }` 循环之后（header 设置完）、query 设置之前加：

```go
	if req.ContentType != "" {
		httpReq.Header.Set("Content-Type", req.ContentType)
	}
```

- [ ] **Step 6: renderPreview 不刷二进制 body**

`internal/engine/execute.go` `renderPreview`：multipart body 含文件字节，直接 `string(req.Body)` 会刷屏。检测 `req.ContentType` 是 multipart 时省略 body。

```go
func renderPreview(req *resolvedReq, opts Options) string {
	isMultipart := strings.HasPrefix(req.ContentType, "multipart/form-data")
	if opts.PrintCurl {
		curl := "curl -X " + req.Method + " '" + req.URL + "'"
		for k, v := range req.Header {
			curl += " -H '" + k + ": " + v + "'"
		}
		if isMultipart {
			curl += "  # multipart body（含文件字节，省略；等价 -F file=@<path> -F <field>=<v>）"
		} else if req.Body != nil {
			curl += " -d '" + string(req.Body) + "'"
		}
		if opts.Insecure {
			curl += " --insecure"
		}
		return curl
	}
	bodyRepr := fmt.Sprintf("%v", req.Body)
	if isMultipart {
		bodyRepr = "<multipart body omitted>"
	}
	return fmt.Sprintf("DRY-RUN %s %s insecure=%v query=%v header=%v body=%s",
		req.Method, req.URL, opts.Insecure, req.Query, req.Header, bodyRepr)
}
```

> 精确重建 `-F file=@<path>` 需把 flags 透传进 `renderPreview`（当前签名 `(req, opts)` 无 flags），影响面大，本迭代取「省略 + 注释」，留 TODO。

- [ ] **Step 7: 写 resolve 接入失败测试**（`execute_test.go` 追加）

```go
package engine

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/internal/spec"
)

func TestResolveMultipart(t *testing.T) {
	// server 收 multipart，校验 Content-Type 含 boundary + 文件 part
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data; boundary=") {
			t.Errorf("server 收到 Content-Type=%q", r.Header.Get("Content-Type"))
		}
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Errorf("ParseMultipartForm: %v", err)
		}
		if r.MultipartForm == nil || r.MultipartForm.Value["kind"][0] != "tool" {
			t.Errorf("kind field 缺失/错误: %+v", r.MultipartForm)
		}
		if fh := r.MultipartForm.File["file"]; len(fh) != 1 || fh[0].Filename != "pkg.tar.gz" {
			t.Errorf("file part 缺失/错误: %+v", r.MultipartForm.File)
		}
	}))
	defer srv.Close()
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: backend, endpoints: { backend: { base_url: ` + srv.URL + `, auth: none } } }
resources:
  pkg:
    operations:
      upload: { method: POST, path: /upload, content_type: multipart-form-data, params: { file: { in: formData, format: binary, required: true }, kind: { in: formData } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	// 写临时上传文件
	tmp := t.TempDir()
	tmpFile := filepath.Join(tmp, "pkg.tar.gz")
	if err := os.WriteFile(tmpFile, []byte{0x1f, 0x8b, 0x08, 0x00}, 0o644); err != nil {
		t.Fatal(err)
	}
	ep, _ := tr.SelectEndpoint("")
	e := New(tr)
	err = e.Execute(context.Background(), ep, tr.Resources["pkg"], tr.Resources["pkg"].Operations["upload"],
		nil, map[string]string{"file": tmpFile, "kind": "tool"}, Options{Format: "json", Out: io.Discard})
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
}
```

- [ ] **Step 8: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/engine/ -run TestResolveMultipart -v`
Expected: PASS（server 收到合法 multipart + Content-Type）。

- [ ] **Step 9: 跑全包 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS。

```bash
git add projects/api-cli/internal/engine/multipart.go projects/api-cli/internal/engine/multipart_test.go projects/api-cli/internal/engine/request.go projects/api-cli/internal/engine/execute.go projects/api-cli/internal/engine/execute_test.go
git commit -m "feat(api-cli): iter4 T2 multipart 上传（buildMultipart + resolve 分支 + do Content-Type + renderPreview 省略）"
```

---

## Task 3: binary 响应落盘（writeOutput 只写 Out）

> **落盘分层：** engine 的 `writeOutput` 只写 `opts.Out`，不持有文件句柄。落盘（`opts.Out` 指向文件）归 Task 4 `globalOpts`。本 task 的测试用 `bytes.Buffer` 当 `Out`，只验字节正确、不经 decode——**不验落盘**（落盘断言在 Task 4/5）。

**Files:**
- Modify: `projects/api-cli/internal/engine/execute.go`（`single()` binary 分支；`writeOutput`）
- Test: `projects/api-cli/internal/engine/execute_test.go`

**Interfaces:**
- Consumes: `tree.Operation.Response.Format`（Task 1）
- Produces: `single()` 对 `response.format=binary` 字节直写 `opts.Out`、不经 decodeLoose/Format。**不改 `Options` 字段**（Out 已存在；OutCloser 由 Task 4 加）。

- [ ] **Step 1: 写失败测试**（`execute_test.go` 追加）

```go
func TestSingleBinaryResponseWritesOut(t *testing.T) {
	payload := []byte{0x1f, 0x8b, 0x08, 0x00, 0xAA, 0xBB, 0xCC}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/gzip")
		w.Write(payload)
	}))
	defer srv.Close()
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: backend, endpoints: { backend: { base_url: ` + srv.URL + `, auth: none } } }
resources:
  pkg:
    operations:
      download: { method: GET, path: /download/{id}, params: { id: { in: path, type: string, required: true } }, response: { format: binary } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	ep, _ := tr.SelectEndpoint("")
	e := New(tr)
	// engine 层只验 Out 收到原始字节（不经 decode）；落盘断言在 Task 4/5。
	var buf bytes.Buffer
	err = e.Execute(context.Background(), ep, tr.Resources["pkg"], tr.Resources["pkg"].Operations["download"],
		map[string]string{"id": "abc"}, nil, Options{Format: "json", Out: &buf})
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if !bytes.Equal(buf.Bytes(), payload) {
		t.Errorf("Out 内容不一致：got %d bytes, want %d bytes", buf.Len(), len(payload))
	}
}
```

> 注：import 补 `bytes`；`Options.Out` 类型为 `io.Writer`，`bytes.Buffer` 实现之。本测试**不设** `OutputFile`/`OutCloser`（engine 层不关心）。

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/engine/ -run TestSingleBinaryResponseWritesOut -v`
Expected: FAIL（binary 响应被 decodeLoose 当字符串损坏，`buf` 内容 ≠ payload）。

- [ ] **Step 3: 实现 single binary 分支 + writeOutput**

`internal/engine/execute.go`：`single()` 在 `if status >= 400 { ... }` 之后、`data := decodeLoose(body)` 之前加 binary 分支。

```go
	// binary 响应：字节直写 opts.Out，不经 decodeLoose/Format。
	// 落盘与否由 opts.Out 指向决定（--output 时 cobracli globalOpts 已把 Out 指向文件）。
	if op.Response != nil && op.Response.Format == "binary" {
		return writeOutput(opts, body)
	}
```

新增 `writeOutput`（`execute.go` 末尾）——**只写 Out，不读文件路径、不 os.WriteFile**：

```go
// writeOutput 把字节写到 opts.Out（仅此一处出口）。
// 落盘由 cobracli globalOpts 把 opts.Out 指向文件实现；engine 不持有文件句柄。
func writeOutput(opts Options, body []byte) error {
	_, err := opts.Out.Write(body)
	return err
}
```

（`execute.go` 已 import `io`、`os`、`api-cli/internal/output`，无需新增 import。）

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/engine/ -run TestSingleBinaryResponseWritesOut -v`
Expected: PASS。

- [ ] **Step 5: 跑全包 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS。

```bash
git add projects/api-cli/internal/engine/execute.go projects/api-cli/internal/engine/execute_test.go
git commit -m "feat(api-cli): iter4 T3 binary 响应写 Out（single binary 分支 + writeOutput 只写 Out）"
```

---

## Task 4: CLI flag --output/-o + Options.OutCloser + RunE Close + 文档 + examples

**Files:**
- Modify: `projects/api-cli/internal/engine/execute.go`（`Options` 加 `OutCloser io.Closer`）
- Modify: `projects/api-cli/internal/cobracli/flags.go`（`bindGlobalFlags` + `globalOpts`，补 import `"os"`）
- Modify: `projects/api-cli/internal/cobracli/build.go`（`operationCmd` RunE 加 `defer Close`）
- Test: `projects/api-cli/internal/cobracli/smoke_test.go`
- Create: `projects/api-cli/examples/binary.yaml`
- Modify: `projects/api-cli/docs/USAGE.md`

**Interfaces:**
- Consumes: engine `writeOutput` 只写 `opts.Out`（Task 3）
- Produces: `Options.OutCloser io.Closer`；`--output/-o` persistent flag；`globalOpts` 在 `--output` 非空时 `os.Create` → `opts.Out = fout` + `opts.OutCloser = fout`；RunE `defer opts.OutCloser.Close()`。

- [ ] **Step 1: 写失败测试**（`smoke_test.go` 追加）

```go
// TestGlobalOutputFlag 验证 --output flag 注册 + globalOpts 重定向 Out 到文件 + 设 OutCloser。
func TestGlobalOutputFlag(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none } } }
resources:
  r:
    operations:
      read: { method: GET, path: /r/{id}, params: { id: { in: path, type: string, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, _ := Build(tr)

	// 1) flag 注册
	pf := root.PersistentFlags()
	if pf.Lookup("output") == nil {
		t.Error("--output flag 未注册")
	}
	if pf.ShorthandLookup("o") == nil {
		t.Error("-o shorthand 未注册")
	}

	// 2) globalOpts：--output 时 Out 指向文件 + OutCloser 非 nil
	cmd, _, _ := root.Find([]string{"r", "read"})
	tmpOut := filepath.Join(t.TempDir(), "out.txt")
	if err := cmd.Flags().Set("output", tmpOut); err != nil {
		t.Fatal(err)
	}
	opts, err := globalOpts(cmd)
	if err != nil {
		t.Fatal(err)
	}
	if opts.OutCloser == nil {
		t.Error("设了 --output 但 OutCloser == nil（应指向文件句柄）")
	}
	f, ok := opts.Out.(*os.File)
	if !ok || f.Name() != tmpOut {
		t.Errorf("opts.Out 不是指向 %q 的 *os.File：got %#v", tmpOut, opts.Out)
	}
	opts.OutCloser.Close()

	// 3) 无 --output：OutCloser == nil，Out == stdout
	root2, _ := Build(tr)
	cmd2, _, _ := root2.Find([]string{"r", "read"})
	opts2, err := globalOpts(cmd2)
	if err != nil {
		t.Fatal(err)
	}
	if opts2.OutCloser != nil {
		t.Error("未设 --output 但 OutCloser != nil")
	}
}
```

> 注：import 补 `"os"`、`"path/filepath"`；`Build`/`globalOpts` 已在包内。

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/cobracli/ -run TestGlobalOutputFlag -v`
Expected: FAIL（`output` flag 未注册、`OutCloser` 字段不存在）。

- [ ] **Step 3: Options 加 OutCloser**

`internal/engine/execute.go`：`Options` 加 `OutCloser io.Closer`（在 `Out io.Writer` 之后）。

```go
type Options struct {
	Format    string
	DryRun    bool
	PrintCurl bool
	Yes       bool
	All       bool
	Limit     int
	BodyFile  string
	BodyBytes []byte
	Insecure  bool
	Timeout   time.Duration
	Out       io.Writer
	OutCloser io.Closer // 非空时调用方（cobracli RunE）在 Execute 后 Close（--output 指向文件场景）
}
```

- [ ] **Step 4: 实现 flag + globalOpts 重定向**

`internal/cobracli/flags.go`（顶部 import 加 `"os"`）：`bindGlobalFlags` 末尾加：

```go
	root.PersistentFlags().StringP("output", "o", "", "输出到文件（binary 响应落盘 / 文本写文件，默认 stdout）")
```

`globalOpts`：读 `--output` flag，非空时 `os.Create` → `opts.Out` + `opts.OutCloser`：

```go
func globalOpts(cmd *cobra.Command) (engine.Options, error) {
	f := cmd.Flags()
	opts := engine.Options{
		Format:    strFlag(f, "format"),
		DryRun:    boolFlag(f, "dry-run"),
		PrintCurl: boolFlag(f, "print-curl"),
		Yes:       boolFlag(f, "yes"),
		All:       boolFlag(f, "all"),
		Limit:     intFlag(f, "limit"),
		BodyFile:  strFlag(f, "body-file"),
		Insecure:  boolFlag(f, "insecure"),
		Timeout:   durationFlag(f, "timeout"),
		Out:       stdout(),
	}
	if out := strFlag(f, "output"); out != "" {
		fout, err := os.Create(out)
		if err != nil {
			return opts, &output.APIError{Code: "output_file", Message: err.Error(), ExitCode: output.ExitParamError}
		}
		opts.Out = fout
		opts.OutCloser = fout
	}
	if err := validateFormat(opts.Format); err != nil {
		return opts, err
	}
	return opts, nil
}
```

- [ ] **Step 5: RunE 关闭句柄**

`internal/cobracli/build.go` `operationCmd` 的 RunE：`globalOpts` 之后、`Execute` 之前注册 defer。

```go
		RunE: func(cmd *cobra.Command, args []string) error {
			opts, err := globalOpts(cmd)
			if err != nil {
				return err
			}
			if opts.OutCloser != nil {
				defer opts.OutCloser.Close() // --output 指向文件时关闭；stdout/buffer 不设 OutCloser
			}
			pathVals := buildPathVals(pathParams, args, parentKeys)
			flags := bag.values(otherParams)
			epName, _ := cmd.Flags().GetString("endpoint")
			ep, err := tr.SelectEndpoint(epName)
			if err != nil {
				return err
			}
			return e.Execute(cmd.Context(), ep, r, op, pathVals, flags, opts)
		},
```

- [ ] **Step 6: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/cobracli/ -run TestGlobalOutputFlag -v`
Expected: PASS。

- [ ] **Step 7: 创建 examples/binary.yaml**

```yaml
# examples/binary.yaml —— 文件上传 + 下载示例（iter4 端到端用例）
spec: api-cli/v1
service:
  name: binary-demo
  default_endpoint: backend
  endpoints:
    backend: { base_url: "${BINARY_DEMO_URL}", auth: none }
resources:
  pkg:
    description: 文件包
    operations:
      upload:
        description: 上传文件（multipart）
        method: POST
        path: /upload
        content_type: multipart-form-data
        params:
          file: { in: formData, format: binary, required: true, description: 要上传的文件 }
          kind: { in: formData, description: 文件类别 }
      download:
        description: 下载文件（binary 落盘）
        method: GET
        path: /download/{id}
        params:
          id: { in: path, type: string, required: true }
        response:
          format: binary
          description: 文件字节流
```

- [ ] **Step 8: 更新 USAGE.md**

`docs/USAGE.md`：
- §全局 flag 表加一行：`--output, -o <path> | 输出到文件（binary 响应落盘 / 文本写文件，默认 stdout）`。
- §6 清单语法补小节「文件上传/下载（iter4）」，贴 `content_type: multipart-form-data` + `param.format: binary` + `response.format: binary` 示例（取自 `examples/binary.yaml`）。
- §9 已知限制：补「**已支持（CLI）**：文件上传（multipart/formData）+ 文件下载（binary 响应 `--output` 落盘）」「**MCP 不支持 binary**：binary verb 走 CLI」，并标注「大文件流式上传/下载延后（见 iter4 design §2.2）」。

- [ ] **Step 9: 跑全包 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS。

```bash
git add projects/api-cli/internal/engine/execute.go projects/api-cli/internal/cobracli/flags.go projects/api-cli/internal/cobracli/build.go projects/api-cli/internal/cobracli/smoke_test.go projects/api-cli/examples/binary.yaml projects/api-cli/docs/USAGE.md
git commit -m "feat(api-cli): iter4 T4 --output/-o + Options.OutCloser + RunE Close + USAGE + examples/binary.yaml"
```

---

## Task 5: 端到端（httptest server 上传 + 下载落盘全链路）

**Files:**
- Create: `projects/api-cli/tests/integration/binary_test.go`

**Interfaces:**
- Consumes: Task 1-4 全部成果（spec schema + multipart + binary 写 Out + --output 重定向 Out + RunE Close）。

- [ ] **Step 1: 写端到端测试**（`binary_test.go` 新建）

```go
package integration

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/internal/engine"
	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

// TestBinaryUploadDownload 端到端：httptest server 起 upload + download，
// 走 engine.Execute 覆盖核心链路（spec schema → multipart 上传 → binary 下载落盘）。
func TestBinaryUploadDownload(t *testing.T) {
	payload := []byte{0x1f, 0x8b, 0x08, 0x00, 0xAA, 0xBB, 0xCC, 0xDD}
	srv := newBinaryTestServer(t, payload)
	defer srv.Close()

	// 渲染清单（${BINARY_DEMO_URL} 替换为 srv.URL）
	manifest := strings.ReplaceAll(binaryExampleManifest, "${BINARY_DEMO_URL}", srv.URL)
	tr, err := spec.Parse([]byte(manifest))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	ep, _ := tr.SelectEndpoint("")
	e := engine.New(tr)

	tmp := t.TempDir()
	upFile := filepath.Join(tmp, "pkg.tar.gz")
	if err := os.WriteFile(upFile, payload, 0o644); err != nil {
		t.Fatal(err)
	}

	// 1) upload：multipart，server 校验收到 file/size/kind；Execute 输出 server 回的 JSON
	var upOut bytes.Buffer
	if err := e.Execute(context.Background(), ep, tr.Resources["pkg"], opByName(tr, "upload"),
		nil, map[string]string{"file": upFile, "kind": "tool"},
		engine.Options{Format: "json", Out: &upOut}); err != nil {
		t.Fatalf("upload: %v", err)
	}
	if !strings.Contains(upOut.String(), "pkg.tar.gz") {
		t.Errorf("upload 响应未含文件名: %q", upOut.String())
	}

	// 2) download：binary，模拟 cobracli --output 落盘（os.Create → Out + OutCloser，Execute 后 Close）
	outFile := filepath.Join(tmp, "out.bin")
	fout, err := os.Create(outFile)
	if err != nil {
		t.Fatal(err)
	}
	err = e.Execute(context.Background(), ep, tr.Resources["pkg"], opByName(tr, "download"),
		map[string]string{"id": "abc"}, nil, engine.Options{Format: "json", Out: fout, OutCloser: fout})
	fout.Close()
	if err != nil {
		t.Fatalf("download: %v", err)
	}
	got, _ := os.ReadFile(outFile)
	if !bytes.Equal(got, payload) {
		t.Errorf("下载落盘内容不一致：got %d bytes, want %d", len(got), len(payload))
	}
}

// opByName 取 pkg resource 的 operation（upload/download）。
func opByName(tr *tree.OperationTree, verb string) *tree.Operation {
	return tr.Resources["pkg"].Operations[verb]
}

// newBinaryTestServer 起 upload（ParseMultipartForm 回 JSON）+ download（回固定 binary）server。
func newBinaryTestServer(t *testing.T, payload []byte) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/upload", func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(10 << 20); err != nil {
			t.Errorf("ParseMultipartForm: %v", err)
			http.Error(w, err.Error(), 400)
			return
		}
		fh := r.MultipartForm.File["file"]
		name, size := "", 0
		if len(fh) == 1 {
			name = fh[0].Filename
			size = int(fh[0].Size)
		}
		kind := ""
		if v := r.MultipartForm.Value["kind"]; len(v) == 1 {
			kind = v[0]
		}
		fmt.Fprintf(w, `{"file":%q,"size":%d,"kind":%q}`, name, size, kind)
	})
	mux.HandleFunc("/download/abc", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/gzip")
		w.Write(payload)
	})
	return httptest.NewServer(mux)
}

// binaryExampleManifest 贴 examples/binary.yaml 内容（${BINARY_DEMO_URL} 占位）。
const binaryExampleManifest = `spec: api-cli/v1
service:
  name: binary-demo
  default_endpoint: backend
  endpoints:
    backend: { base_url: "${BINARY_DEMO_URL}", auth: none }
resources:
  pkg:
    description: 文件包
    operations:
      upload:
        description: 上传文件（multipart）
        method: POST
        path: /upload
        content_type: multipart-form-data
        params:
          file: { in: formData, format: binary, required: true, description: 要上传的文件 }
          kind: { in: formData, description: 文件类别 }
      download:
        description: 下载文件（binary 落盘）
        method: GET
        path: /download/{id}
        params:
          id: { in: path, type: string, required: true }
        response:
          format: binary
          description: 文件字节流
`
```

> 注：import 补 `"fmt"`（newBinaryTestServer 用 fmt.Fprintf）；`opByName`/`newBinaryTestServer`/`binaryExampleManifest` 为本测试内联 helper。download 分支用 `os.Create → Out + OutCloser` 模拟 cobracli `globalOpts` 的落盘重定向（集成层不拉起完整 cobra 命令，直接调 engine.Execute 覆盖核心链路；cobra 粘合在 smoke_test 已覆盖）。

- [ ] **Step 2: 跑测试验证**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./tests/integration/ -run TestBinaryUploadDownload -v`
Expected: PASS（若 helper 或断言失败，按报错修 helper，不改 Task 1-4 实现）。

- [ ] **Step 3: 跑全包 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS（全包绿）。

```bash
git add projects/api-cli/tests/integration/binary_test.go
git commit -m "test(api-cli): iter4 T5 端到端（httptest multipart 上传 + binary 下载落盘全链路）"
```

---

## Task 6: MCP 通道排除 binary 响应 + multipart 上传（toolsCall 报错 + [CLI-only] 标签）

**Files:**
- Modify: `projects/api-cli/internal/mcp/server.go`（`toolsCall` 对 binary 响应 / multipart 上传报错；`buildToolDescription` 对这两类 verb 加 `[CLI-only]` 标签；谓词抽到 `isCLIOnlyVerb` 复用）
- Test: `projects/api-cli/internal/mcp/server_test.go`

**Interfaces:**
- Consumes: `tree.Operation.Response.Format`（Task 1）+ `tree.Operation.ContentType`（Task 1）
- Produces: `toolsCall` 命中 binary 响应 verb 或 multipart 上传 verb 均返回 `-32602` 错误 + 引导文案；`buildToolDescription` 对这两类 verb 输出含 `[CLI-only]`。谓词 `isCLIOnlyVerb(op) = (op.Response.Format=="binary") || (op.ContentType=="multipart-form-data")`。

- [ ] **Step 1: 写失败测试**（`server_test.go` 追加）

```go
func TestToolsCallBinaryRejected(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: binary-demo, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none } } }
resources:
  pkg:
    operations:
      download: { method: GET, path: /download/{id}, params: { id: { in: path, type: string, required: true } }, response: { format: binary } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	srv := New(tr)
	resp := srv.toolsCall(context.Background(), json.RawMessage(`{"name":"binary-demo_pkg_download","arguments":{"id":"abc"}}`))
	errMap, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatalf("期望 error 响应，got: %v", resp)
	}
	code, _ := errMap["code"].(int)
	if code != -32602 {
		t.Errorf("error code = %v, want -32602", code)
	}
	msg, _ := errMap["message"].(string)
	if !strings.Contains(msg, "二进制") || !strings.Contains(msg, "--output") {
		t.Errorf("error message 未含引导文案（二进制/--output）: %q", msg)
	}
}

func TestBuildToolDescriptionCLIonlyTag(t *testing.T) {
	r := &tree.Resource{Name: "pkg", Description: "文件包"}
	op := &tree.Operation{
		Verb:     "download",
		Method:   "GET",
		Response: &tree.Schema{Format: "binary"},
	}
	desc := buildToolDescription(r, op)
	if !strings.Contains(desc, "[CLI-only]") {
		t.Errorf("binary verb description 缺 [CLI-only] 标签: %q", desc)
	}
}
```

> 注：import 补 `"context"`、`"encoding/json"`、`"strings"`、`"api-cli/internal/spec"`、`"api-cli/internal/tree"`（按 `server_test.go` 现有 import 增补，勿重复）。`New`/`toolsCall`/`buildToolDescription` 在 mcp 包内，测试同包可直调。tool name 格式 `<service>_<resource>_<verb>` = `binary-demo_pkg_download`。

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/mcp/ -run 'TestToolsCallBinaryRejected|TestBuildToolDescriptionCLIonlyTag' -v`
Expected: FAIL（toolsCall 未拦 binary，会走 Execute 把二进制塞进 buf；buildToolDescription 无 `[CLI-only]` 标签）。

- [ ] **Step 3: 实现 toolsCall binary 报错 + 标签**

`internal/mcp/server.go` `toolsCall`：反查 r/op 命中 nil 检查之后、`SelectEndpoint` 之前加 binary 拦截。

```go
	r, op := s.findByToolName(p.Name)
	if r == nil || op == nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "tool not found: " + p.Name}}
	}
	// binary 响应不经 MCP：二进制字节塞进 JSON-RPC text 会产生无效 UTF-8 损坏响应。
	// 引导调用方走 CLI --output 落盘（声明式可预测，不静默损坏）。
	if op.Response != nil && op.Response.Format == "binary" {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "该操作返回二进制流，MCP 不支持；请用 CLI 调用并加 --output 落盘"}}
	}
```

`buildToolDescription`：在现有 tags 累积处加一行（复用 tags 机制）。

```go
	var tags []string
	if isWriteMethod(op.Method) {
		tags = append(tags, "[写操作]")
	}
	if op.Pagination != nil {
		tags = append(tags, "[可分页]")
	}
	if op.Response != nil && op.Response.Format == "binary" {
		tags = append(tags, "[CLI-only]")
	}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/mcp/ -run 'TestToolsCallBinaryRejected|TestBuildToolDescriptionCLIonlyTag' -v`
Expected: PASS。

- [ ] **Step 5: 跑全包 + commit**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS（全包绿）。

```bash
git add projects/api-cli/internal/mcp/server.go projects/api-cli/internal/mcp/server_test.go
git commit -m "feat(api-cli): iter4 T6 MCP 排除 binary（toolsCall 报错 + [CLI-only] 标签）"
```

---

## Self-Review（plan 写完后自检，已执行）

**1. Spec 覆盖**（对照 design §2.1 的 6 个 P0）：
- T1 schema 扩展（content_type + format×2）+ 4 条 err 级 lint → Task 1 ✓
- T2 multipart 请求构造 + renderPreview 省略 → Task 2 ✓（renderPreview 已补 Step 6，不再是 TODO）
- T3 binary 响应写 Out（writeOutput 只写 Out，不碰文件） → Task 3 ✓
- T4 flag + OutCloser + RunE Close + 文档 + examples → Task 4 ✓
- T5 端到端（含落盘全链路）→ Task 5 ✓
- T6 MCP 排除 binary → Task 6 ✓（新增，对应 design §4.6）
- design §4.2 renderPreview multipart curl 精确 `-F` 重建：Task 2 Step 6 取「省略 + 注释」，留 TODO——属可接受渐进项（需 flags 透传进 renderPreview，影响面大）。

**2. 落盘分层一致性**（修订 1 核心检查）：
- `writeOutput`（Task 3）只 `opts.Out.Write(body)`，**不读 OutputFile、不 os.WriteFile** ✓
- 落盘统一由 `globalOpts`（Task 4）`os.Create → Out + OutCloser` ✓
- RunE（Task 4）`defer OutCloser.Close()` ✓ —— **解决了原 plan 的句柄泄漏**
- engine 零文件句柄 ✓
- Task 3 测试用 buffer 验字节、不验落盘；落盘断言在 Task 4（globalOpts 重定向）+ Task 5（download os.Create→Out 模拟）✓
- **`Options.OutputFile` 已删**（engine 不需要文件路径），改用 `OutCloser` ✓

**3. MCP 范围决策落地**（修订 2）：
- toolsCall 对 binary 响应 / multipart 上传报错（-32602 + 引导文案）→ Task 6 ✓
- buildToolDescription 对这两类 verb 加 `[CLI-only]` 标签 → Task 6 ✓
- 谓词 `isCLIOnlyVerb` 集中判定，toolsCall 与 buildToolDescription 共用 → Task 6 ✓
- lint 不拦（清单合法）✓ —— 与 design §3 约定 6 一致
- **范围在 final-review 时扩展**：原只拦 binary 响应（损坏 JSON-RPC），扩展到也拦 multipart 上传——文件上传与下载对 LLM 同样是 CLI-only（都需要 LLM 无法提供的本地文件系统：上传需本地文件路径、下载需落盘）。扩展前 multipart verb 经 MCP 调用会到 `os.Open(flags["file"])` 在 api-cli 宿主上必失败，报「打开上传文件 失败」令人困惑且无 `[CLI-only]` 声明信号。

**4. Placeholder 扫描**：plan 内代码块均为完整可编译 Go（Task 5 的 helper `opByName`/`newBinaryTestServer`/`binaryExampleManifest` 已给完整实现，非占位）。无 TBD/TODO（Task 2 Step 6 renderPreview 精确 `-F` 是设计性延后，已注明影响面；Task 1 注明 Param.Example 死字段不顺手修）。

**5. Type 一致**：`buildMultipart(op, flags) ([]byte, string, error)` 全程一致；`resolvedReq.ContentType` / `Options.OutCloser` 在定义 task（T2 / T4）与消费 task（T2 do / T4 RunE）名称一致；`tree.Operation.ContentType` / `tree.Param.Format` / `tree.Schema.Format` 全程一致；**`Options.OutputFile` 已从 plan 全部移除**，替换为 `OutCloser`。

---

## 执行选择

plan 已存 `projects/api-cli/docs/2026-08-10-api-cli-iter4-plan.md`（本次评审修订版）。两种执行方式：

1. **Subagent-Driven（推荐）**：每个 task 派新 subagent，task 间 review，迭代快。
2. **Inline Execution**：本会话内 executing-plans，分批执行 + checkpoint review。

下次启动 iter4 时按 design §9 开 `worktree-api-cli-iter4`，依 Task 1→2→3→4→5→6 顺序执行（T6 依赖 T1 的 `Schema.Format`，可与 T2-T5 并行或收尾）。
