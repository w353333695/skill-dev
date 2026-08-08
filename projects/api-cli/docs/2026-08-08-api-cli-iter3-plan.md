# api-cli 迭代三 实现计划（2 bug + LLM 抉择 + N 层 path）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2 个 CLI bug（--help-format 隐含 help、全局 flag 子命令前生效）+ LLM 抉择 description 富化 + N 层 path 祖先链拼接，让 api-cli 对 LLM 更精准、对嵌套 resource 正确。

**Architecture:** 数据结构先行（Task 3 落 `Resource.Description`/`Resource.Parent`/`Operation.Description` + spec 解析回填），再分别富化 MCP description / cobra Short（Task 4）与 ResolveURL 祖先链 + 占位填充（Task 5）。bug 修复（Task 1/2）独立先行。

**Tech Stack:** Go 1.22.5、spf13/cobra、pflag、yaml.v3、net/http。

**对应 design：** `projects/api-cli/docs/2026-08-08-api-cli-iter3-design.md`（design 的 T1→plan Task 1，T2→Task 2，T3 数据结构→Task 3、富化→Task 4，T4→Task 5）。

## Global Constraints

- 中文沟通、中文注释；只改 `projects/api-cli/` 内文件。
- go 不在默认 PATH：每个跑 go 的 step 先 `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin`（go1.22.5）。
- 测试命令统一：`cd projects/api-cli && go test ./...`（全包）或指定包 `go test ./internal/<pkg>/...`。
- TDD 严格：每步先写失败测试 → 跑红 → 写最小实现 → 跑绿 → commit。不允许跳过红/绿。
- 改完**立即手动 commit**（工作空间有 `chore(ai)` 自动提交机制，会扫未提交改动）。
- 本迭代测试用 `auth: none` 的最小清单，不依赖 `~/.api-cli/auth.d` 凭证。
- 严禁写项目工作目录外（AGENTS.md §1）。

---

## File Structure

| 文件 | 责任 | 涉及 task |
|---|---|---|
| `cmd/api-cli/main.go` | 入口；`parseTopFlags`（T2 改）；`run()` 识别 ErrHelpRequested（T1） | 1, 2 |
| `cmd/api-cli/main_test.go` | `parseTopFlags` table 测试（T2 加 case） | 2 |
| `internal/cobracli/build.go` | root 构建（T1 加 PersistentPreRunE+ErrHelpRequested）；cobra Short（T4）；explain（T4） | 1, 4 |
| `internal/cobracli/smoke_test.go` | help-format 行为（T1 加无 --help 的 case） | 1 |
| `internal/cobracli/build_test.go` | cobra Short 用 Description（T4） | 4 |
| `internal/tree/types.go` | `Resource`/`Operation` 数据结构（T3 加字段） | 3 |
| `internal/tree/resolve.go` | ResolveURL + ancestorPaths（T5） | 5 |
| `internal/tree/resolve_test.go` | 祖先链 + 占位填充（T5） | 5 |
| `internal/spec/schema.go` | yaml 中间结构（T3 加 description tag） | 3 |
| `internal/spec/parse.go` | convert（T3 拷贝/回填）；lint（T5） | 3, 5 |
| `internal/spec/parse_test.go` | description 解析 + Parent 回填 + lint（T3, T5） | 3, 5 |
| `internal/mcp/server.go` | MCP tool description 富化（T4） | 4 |
| `internal/mcp/server_test.go` | description 富化测试（T4） | 4 |
| `examples/cmdb.yaml` | 嵌套清单补 description（T6） | 6 |
| `examples/easyops-cmdb.yaml` | 单层清单补 description（T6） | 6 |
| `tests/integration/cmdb_test.go` | relation.read URL 端到端（T6） | 6 |

---

## Task 1: bug1 — `--help-format=json` 隐含 `--help`

**Files:**
- Modify: `projects/api-cli/internal/cobracli/build.go`（root 加 `PersistentPreRunE` + 导出 `ErrHelpRequested`）
- Modify: `projects/api-cli/cmd/api-cli/main.go`（`run()` 识别 `ErrHelpRequested` → exit 0）
- Test: `projects/api-cli/internal/cobracli/smoke_test.go`

**Interfaces:**
- Produces: `cobracli.ErrHelpRequested`（sentinel error，main 用 `errors.Is` 识别）

- [ ] **Step 1: 写失败测试**（`smoke_test.go` 末尾追加）

```go
// TestHelpFormatJSONWithoutHelpFlag 验证 bug1 修复：单独 --help-format=json
// （不带 --help、也不带必填 path 参数）应触发 helpFunc 输出 JSON，
// 不再走到 RunE 的 resolve 报"缺少 path 参数"。
func TestHelpFormatJSONWithoutHelpFlag(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, type: string, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, _ := Build(tr)
	// 单独 --help-format=json，不带 --help、不带 id → 旧行为 RunE 报错；新行为输出 JSON help
	out := captureExecute(root, []string{"inst", "read", "--help-format=json"})
	if !strings.Contains(out, `"resource": "inst"`) || !strings.Contains(out, `"verb": "read"`) {
		t.Errorf("单独 --help-format=json 应输出 JSON help，got:\n%s", out)
	}
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/cobracli/ -run TestHelpFormatJSONWithoutHelpFlag -v`
Expected: FAIL（旧行为走 RunE，输出不含 `"resource": "inst"` JSON 字段）。

- [ ] **Step 3: 实现**（`build.go`）

在 `import` 块加 `"errors"`。在 `Build` 内的 root 命令加 `PersistentPreRunE`，并在包级声明 `ErrHelpRequested`：

```go
// ErrHelpRequested 表示 --help-format != text 触发了 help（非错误，main 据此 exit 0）。
// cobra 的内置 --help 检查在 PersistentPreRunE 之前，无法靠它；改为在此主动拦截：
// help-format 非 text 时调 cmd.Help()（复用 helpFunc）并返回 sentinel，让 cobra 跳过 RunE。
var ErrHelpRequested = errors.New("help requested via --help-format")
```

root 命令结构体加字段（紧挨 `TraverseChildren: true,` 之后）：

```go
		TraverseChildren: true, // 全局 flag（--insecure/--spec）可放子命令前
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			hf, _ := cmd.Flags().GetString("help-format")
			if hf != "text" {
				if err := cmd.Help(); err != nil {
					return err
				}
				return ErrHelpRequested
			}
			return nil
		},
```

- [ ] **Step 4: 改 `main.go` `run()` 识别 sentinel**

`main.go` 的 `import` 块加 `"errors"` 和 `"api-cli/internal/cobracli"`（若未导入）。把 `run()` 末尾的 `return root.Execute()` 改为：

```go
	if err := root.Execute(); err != nil {
		if errors.Is(err, cobracli.ErrHelpRequested) {
			return nil // help 正常退出（exit 0），不打印错误
		}
		return err
	}
	return nil
```

- [ ] **Step 5: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/cobracli/ ./cmd/api-cli/ -run 'TestHelpFormatJSON|TestRunSpec' -v`
Expected: PASS（新测试绿；既有 `TestRunSpec*` 不回归——它们用 `--help-format=json --help`，PersistentPreRunE 在 help 后仍跑但 help-format!=text 会再触发一次 Help，需确认不回归；若回归，见 Step 6 注）。

- [ ] **Step 6: 若 Step 5 中既有 `TestRunSpec*` 回归——补丁**

`--help --help-format=json` 同时给时：cobra 内置 `--help` 已触发 helpFunc 输出 JSON 并返回 `flag.ErrHelp`（cobra 内部，**早于** PersistentPreRunE），故 PersistentPreRunE 不会执行。应无回归。若仍回归，在 PersistentPreRunE 开头加短路：`if help, _ := cmd.Flags().GetBool("help"); help { return nil }`。

- [ ] **Step 7: Commit**

```bash
cd projects/api-cli && git add internal/cobracli/build.go cmd/api-cli/main.go internal/cobracli/smoke_test.go
git commit -m "fix(api-cli): --help-format=json 单独给隐含 --help（root PersistentPreRunE 拦截）"
```

---

## Task 2: bug2 — 全局 flag 放子命令前生效

**Files:**
- Modify: `projects/api-cli/cmd/api-cli/main.go`（`parseTopFlags` 删 `isFlagToken` 分支与函数）
- Test: `projects/api-cli/cmd/api-cli/main_test.go`（`TestParseTopFlags` 加 case）

**Interfaces:**
- Produces: `parseTopFlags`（行为变更：遇非 `--spec/--mcp` token 立即停止）

- [ ] **Step 1: 写失败测试**（`main_test.go` 的 `TestParseTopFlags` cases 切片里追加两条）

```go
		{
			name: "global flag before subcommand kept for cobra (bug2)",
			args: []string{"--spec", "/a.yaml", "--endpoint", "backend", "inst", "read"},
			spec: "/a.yaml",
			rest: []string{"--endpoint", "backend", "inst", "read"},
		},
		{
			name: "multiple global flags before subcommand",
			args: []string{"--spec", "/a.yaml", "--insecure", "--format", "yaml", "inst", "read", "i1"},
			spec: "/a.yaml",
			rest: []string{"--insecure", "--format", "yaml", "inst", "read", "i1"},
		},
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./cmd/api-cli/ -run TestParseTopFlags -v`
Expected: FAIL（旧行为 `isFlagToken` 把 `--endpoint` 丢掉、`backend` 当子命令起点，rest 不含 `--endpoint`）。

- [ ] **Step 3: 实现**（`main.go` `parseTopFlags`）

把 `parseTopFlags` 的 `case isFlagToken(a):` 分支**删除**，改为遇任何非 `--spec/--mcp/--` token 走 `default` 立即停止。完整新函数：

```go
func parseTopFlags(args []string) (specPath string, mcpMode bool, rest []string) {
	i := 0
	for i < len(args) {
		a := args[i]
		switch {
		case a == "--":
			// POSIX 分隔符：之后全部是 positional，top 段结束
			rest = args[i+1:]
			return
		case a == "--mcp" || a == "--mcp=true":
			mcpMode = true
			i++
		case a == "--mcp=false":
			mcpMode = false
			i++
		case a == "--spec":
			// 下一个 token 是值；末尾无值则当作未给（loadSpec/env 兜底）
			if i+1 < len(args) {
				specPath = args[i+1]
				i += 2
			} else {
				i++
			}
		case strings.HasPrefix(a, "--spec="):
			specPath = strings.TrimPrefix(a, "--spec=")
			i++
		default:
			// 任何其他 token（flag 或子命令）= top 段结束，原样交还 cobra。
			// 全局 persistent flag（--endpoint/--insecure/--format 等）在子命令前，
			// 由 cobra 的 TraverseChildren 自行解析（root 已设该字段）。
			rest = args[i:]
			return
		}
	}
	rest = nil
	return
}
```

同时**删除** `isFlagToken` 函数（已无引用）。删除：

```go
// isFlagToken 判断一个 token 是否是 flag（以 "-" 开头，但不只是 "-"）。
func isFlagToken(a string) bool {
	return len(a) > 1 && a[0] == '-'
}
```

并删除 `main.go` 包注释里提到 isFlagToken 的旧行为描述（如有），更新注释为"遇非 --spec/--mcp token 立即停止"。

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./cmd/api-cli/ -v`
Expected: PASS（新 case 绿；既有 7 个 case 不回归）。

- [ ] **Step 5: Commit**

```bash
cd projects/api-cli && git add cmd/api-cli/main.go cmd/api-cli/main_test.go
git commit -m "fix(api-cli): 全局 flag 放子命令前生效（parseTopFlags 遇非 --spec/--mcp 立即停止）"
```

---

## Task 3: tree 模型扩展（Description + Parent）

**Files:**
- Modify: `projects/api-cli/internal/tree/types.go`（`Resource` 加 `Description`/`Parent`；`Operation` 加 `Description`）
- Modify: `projects/api-cli/internal/spec/schema.go`（`yamlResource`/`yamlOperation` 加 `description` tag）
- Modify: `projects/api-cli/internal/spec/parse.go`（`convertResource`/`convertOperation` 拷贝 + 回填 Parent）
- Test: `projects/api-cli/internal/spec/parse_test.go`

**Interfaces:**
- Produces: `tree.Resource.Description string`、`tree.Resource.Parent *Resource`、`tree.Operation.Description string`；spec 解析后 `child.Parent` 指向父。供 Task 4（祖先链 description）与 Task 5（ResolveURL 祖先链）消费。

- [ ] **Step 1: 写失败测试**（`parse_test.go` 追加）

```go
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
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/spec/ -run 'TestParseResourceAndOperationDescription|TestParseParentBackfill' -v`
Expected: FAIL（`tree.Resource` 无 `Description`/`Parent` 字段，编译错；或字段零值）。

- [ ] **Step 3: 加字段**（`types.go`）

`Resource` 结构体加两个字段（`Parent` 放末尾，含注释）：

```go
// Resource 资源定义（命令树节点）。
type Resource struct {
	Name        string
	Description string // 资源用途（LLM 抉择 + cobra Short）；空 = 回退旧文案
	Path        string
	Singular    string
	ParentKey   string                // 父 ID 注入到子命令 path 模板的键名
	Operations  map[string]*Operation
	Children    map[string]*Resource // 递归 → N 层
	Parent      *Resource             // 祖先链上溯指针（spec.Parse 回填）；顶层 resource 为 nil
}
```

`Operation` 结构体加 `Description`：

```go
// Operation 一个动作（verb 是身份，method 是配置）。
type Operation struct {
	Verb        string
	Method      string // 内部模型永远必填（parse 阶段对标准 verb 填默认值）
	Path        string // 相对 resource.Path，含 {param} 模板
	Description string // 操作用途（LLM 抉择 + cobra Short）；空 = 回退 verb+singular
	Params      []Param
	Body        *Schema     // nil = 无 body
	Response    *Schema     // nil = 无 response schema（outputSchema）
	Pagination  *Pagination // nil = 无分页
}
```

- [ ] **Step 4: 加 yaml tag**（`schema.go`）

`yamlResource` 加 `Description`：

```go
type yamlResource struct {
	Description string                    `yaml:"description"`
	Path        string                    `yaml:"path"`
	Singular    string                    `yaml:"singular"`
	ParentKey   string                    `yaml:"parent_key"`
	Operations  map[string]*yamlOperation `yaml:"operations"`
	Children    map[string]*yamlResource  `yaml:"children"`
}
```

`yamlOperation` 加 `Description`（在 `Method`/`Path` 旁，参考现有字段顺序）。

- [ ] **Step 5: 改 convert**（`parse.go`）

`convertResource` 拷贝 Description + 回填 child.Parent：

```go
func convertResource(name string, y *yamlResource) *tree.Resource {
	r := &tree.Resource{
		Name: name, Description: y.Description, Path: y.Path, Singular: y.Singular, ParentKey: y.ParentKey,
		Operations: map[string]*tree.Operation{}, Children: map[string]*tree.Resource{},
	}
	for verb, op := range y.Operations {
		r.Operations[verb] = convertOperation(verb, op)
	}
	for cname, c := range y.Children {
		child := convertResource(cname, c)
		child.Parent = r // 回填祖先链指针（T4 ResolveURL 与 T3 description 富化共用）
		r.Children[cname] = child
	}
	return r
}
```

`convertOperation` 拷贝 Description（首行）：

```go
	op := &tree.Operation{Verb: verb, Method: y.Method, Path: y.Path, Description: y.Description}
```

- [ ] **Step 6: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./... `
Expected: PASS（新测试绿；全包不回归——新增字段零值即旧行为）。

- [ ] **Step 7: Commit**

```bash
cd projects/api-cli && git add internal/tree/types.go internal/spec/schema.go internal/spec/parse.go internal/spec/parse_test.go
git commit -m "feat(api-cli): tree 模型加 Resource.Description/Parent + Operation.Description（spec 解析回填）"
```

---

## Task 4: T3 LLM 抉择（MCP description 富化 + cobra Short + explain）

**Files:**
- Modify: `projects/api-cli/internal/mcp/server.go`（`buildToolDescription` 替换 line 58）
- Modify: `projects/api-cli/internal/cobracli/build.go`（`desc()` / `operationCmd` Short 用 Description；`explainCmd` 加 description）
- Test: `projects/api-cli/internal/mcp/server_test.go`、`projects/api-cli/internal/cobracli/build_test.go`

**Interfaces:**
- Consumes: `tree.Resource.Description`、`tree.Resource.Parent`、`tree.Operation.Description`（Task 3）
- Produces: MCP tool `description` = `祖先链 · op用途 · [行为标签]`；cobra Short 优先 Description

- [ ] **Step 1: 写失败测试**（`server_test.go` 追加）

```go
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
```

（`server_test.go` 顶部若未 import `strings`/`api-cli/internal/spec`，补上。）

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/mcp/ -run TestToolDescriptionEnrichment -v`
Expected: FAIL（旧 description 仅 `search instance`，不含用途链/标签）。

- [ ] **Step 3: 实现 MCP 富化**（`server.go`）

import 块加 `"strings"`。新增 `buildToolDescription` + `isWriteMethod`，并替换 `ToolsList` 内 `desc := verb + " " + orDefault(r.Singular, r.Name)` 为 `desc := buildToolDescription(r, op)`：

```go
// buildToolDescription 富化 tool description：祖先链用途 · operation 用途 · [行为标签]。
// 祖先链沿 r.Parent 上溯（无 Description 的层用 Name，确保链不断）；行为标签从
// method（写操作）与 Pagination（可分页）自动推断，不需清单额外声明。
func buildToolDescription(r *tree.Resource, op *tree.Operation) string {
	// 祖先链：叶→顶收集，再翻转为顶→叶
	var chain []string
	for cur := r; cur != nil; cur = cur.Parent {
		chain = append(chain, orDefault(cur.Description, cur.Name))
	}
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	ancestor := strings.Join(chain, " > ")

	opDesc := orDefault(op.Description, op.Verb+" "+orDefault(r.Singular, r.Name))
	s := ancestor + " · " + opDesc

	var tags []string
	if isWriteMethod(op.Method) {
		tags = append(tags, "[写操作]")
	}
	if op.Pagination != nil {
		tags = append(tags, "[可分页]")
	}
	if len(tags) > 0 {
		s += " " + strings.Join(tags, " ")
	}
	return s
}

// isWriteMethod 判断是否写操作（用于行为标签推断）。
func isWriteMethod(m string) bool {
	switch strings.ToUpper(m) {
	case "POST", "PUT", "PATCH", "DELETE":
		return true
	}
	return false
}
```

- [ ] **Step 4: 写 cobra Short 失败测试**（`build_test.go` 追加；若 `build_test.go` 不存在则新建，`package cobracli`）

```go
func TestResourceShortUsesDescription(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    description: CMDB 实例
    path: /instances
    operations:
      read: { description: 读取实例, path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, _ := Build(tr)
	// inst 子命令的 Short 应是 Description，而非 "instance 资源"
	inst := findChild(root, "inst")
	if inst == nil {
		t.Fatal("未找到 inst 子命令")
	}
	if inst.Short != "CMDB 实例" {
		t.Errorf("inst Short 应为 Description %q，got %q", "CMDB 实例", inst.Short)
	}
	readCmd := findChild(inst, "read")
	if readCmd == nil {
		t.Fatal("未找到 read 子命令")
	}
	if readCmd.Short != "读取实例" {
		t.Errorf("read Short 应为 operation Description %q，got %q", "读取实例", readCmd.Short)
	}
}

// findChild 在 cmd 的子命令里按名字找一个。
func findChild(parent *cobra.Command, name string) *cobra.Command {
	for _, c := range parent.Commands() {
		if c.Name() == name {
			return c
		}
	}
	return nil
}
```

（`build_test.go` 顶部 import `"testing"`、`"api-cli/internal/spec"`、`"github.com/spf13/cobra"`。）

- [ ] **Step 5: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/cobracli/ -run TestResourceShortUsesDescription -v`
Expected: FAIL（旧 `desc()` 返回 `"instance 资源"`，operationCmd Short 返回 `"read instance"`）。

- [ ] **Step 6: 实现 cobra Short**（`build.go`）

改 `desc()` 优先用 Description：

```go
// desc 给 resource 命令拼一句中文短描述。
// 有 Description 时直接用（不再加"资源"后缀）；否则回退 singular/name + "资源"。
func desc(r *tree.Resource) string {
	if r.Description != "" {
		return r.Description
	}
	if r.Singular != "" {
		return r.Singular + " 资源"
	}
	return r.Name + " 资源"
}
```

`operationCmd` 内 `Short: op.Verb + " " + r.Singular,` 改为：

```go
		Short: opShort(op, r),
```

新增 helper（紧邻 `desc`）：

```go
// opShort 给 operation 子命令拼短描述：优先 operation.Description，否则回退 verb + singular。
func opShort(op *tree.Operation, r *tree.Resource) string {
	if op.Description != "" {
		return op.Description
	}
	return op.Verb + " " + orDefaultCobra(r.Singular, r.Name)
}

// orDefaultCobra 空字符串回落（cobracli 包内的本地版，避免依赖 mcp 包）。
func orDefaultCobra(s, d string) string {
	if s == "" {
		return d
	}
	return s
}
```

- [ ] **Step 7: explain 加 description**（`build.go` `explainCmd`）

把 `doc := map[string]any{...}` 改为含 description 字段：

```go
			doc := map[string]any{
				"resource":              r.Name,
				"resource_description":  r.Description,
				"verb":                  op.Verb,
				"operation_description": op.Description,
				"method":                op.Method,
				"path":                  op.Path,
				"params":                op.Params,
			}
```

- [ ] **Step 8: 跑全包测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS（新测试绿；既有 cobracli/mcp 测试不回归——无 Description 时回退旧文案）。

- [ ] **Step 9: Commit**

```bash
cd projects/api-cli && git add internal/mcp/server.go internal/mcp/server_test.go internal/cobracli/build.go internal/cobracli/build_test.go
git commit -m "feat(api-cli): LLM 抉择富化（MCP description 祖先链+行为标签，cobra Short 用 Description，explain 补语义）"
```

---

## Task 5: T4 N 层 path（ResolveURL 祖先链 + 占位填充 + lint）

**Files:**
- Modify: `projects/api-cli/internal/tree/resolve.go`（新增 `ancestorPaths` + 改 `ResolveURL`）
- Modify: `projects/api-cli/internal/spec/parse.go`（`Parse` 末尾加 lint）
- Test: `projects/api-cli/internal/tree/resolve_test.go`、`projects/api-cli/internal/spec/parse_test.go`

**Interfaces:**
- Consumes: `tree.Resource.Parent`（Task 3 回填）
- Produces: `ResolveURL` 沿祖先链拼 path + 遍历 vals 填占位；`spec.Parse` 对缺 parent_key 占位的 child 发警告

- [ ] **Step 1: 写失败测试**（`resolve_test.go` 追加）

```go
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
```

- [ ] **Step 2: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/tree/ -run TestResolveURLAncestorChainAndParentKey -v`
Expected: FAIL（旧 ResolveURL 只拼叶子 → `http://x/api/v1/{instance_id}/relations/REL1`，缺 `/instances` 且 `{instance_id}` 未填）。

- [ ] **Step 3: 实现 ResolveURL 祖先链 + 占位填充**（`resolve.go`）

新增 `ancestorPaths`，并重写 `ResolveURL` 的拼接与填充段：

```go
// ancestorPaths 返回顶→叶顺序的祖先 resource.Path 段（不含 r 自身）。
// 沿 r.Parent 上溯收集后翻转；顶层 resource（Parent==nil）返回 nil。
func ancestorPaths(r *Resource) []string {
	var segs []string
	for cur := r.Parent; cur != nil; cur = cur.Parent {
		segs = append(segs, cur.Path)
	}
	for i, j := 0, len(segs)-1; i < j; i, j = i+1, j-1 {
		segs[i], segs[j] = segs[j], segs[i]
	}
	return segs
}
```

`ResolveURL` 内，把 `full := joinPath(ep.BaseURL, ep.PathPrefix, r.Path, op.Path)` 与后续填充循环替换为：

```go
	// 1. 拼接 base + prefix + 祖先链（顶→叶）+ 叶子 r.Path + op.Path
	segs := []string{ep.BaseURL, ep.PathPrefix}
	segs = append(segs, ancestorPaths(r)...)
	segs = append(segs, r.Path, op.Path)
	full := joinPath(segs...)

	// 2. 必填校验：op.Params 里 path 参数缺值且必填 → 报错
	for _, p := range op.Params {
		if p.In != "path" {
			continue
		}
		if _, ok := vals[p.Name]; !ok && p.Required {
			return "", fmt.Errorf("缺少 path 参数 %s", p.Name)
		}
	}
	// 3. 填充：遍历 vals 填所有已知占位（含 parent_key 命令位置注入值——
	//    它不在 op.Params 里，必须遍历 vals 才能命中祖先链/r.Path 里的 {parent_key}）。
	for name, v := range vals {
		full = strings.ReplaceAll(full, "{"+name+"}", v)
	}
	return full, nil
```

保留函数开头的 ep/r/op nil 校验不动。

- [ ] **Step 4: 跑测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/tree/ -v`
Expected: PASS（新测试绿；既有 resolve_test 不回归——单层 resource `ancestorPaths` 返回 nil，行为不变）。

- [ ] **Step 5: 写 lint 失败测试**（`parse_test.go` 追加）

```go
func TestParseLintMissingParentKeyPlaceholder(t *testing.T) {
	// relation 的 path 漏了 {instance_id}（inst.ParentKey=instance_id）
	raw := []byte(`
spec: api-cli/v1
service: { name: s, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    path: /instances
    parent_key: instance_id
    children:
      relation:
        path: /relations
        operations:
          read: { path: "/{id}", params: { id: { in: path, required: true } } }
`)
	var stderr bytes.Buffer
	orig := os.Stderr
	r, w, _ := os.Pipe()
	os.Stderr = w
	done := make(chan string)
	go func() {
		var b bytes.Buffer
		_, _ = io.Copy(&b, r)
		done <- b.String()
	}()
	_, err := Parse(raw)
	_ = w.Close()
	os.Stderr = orig
	captured := <-done
	if err != nil {
		t.Fatalf("Parse err: %v", err)
	}
	if !strings.Contains(captured, "instance_id") || !strings.Contains(captured, "relation") {
		t.Errorf("应警告 relation 缺 {instance_id} 占位，stderr=\n%s", captured)
	}
}
```

（`parse_test.go` 顶部补 import `"bytes"`、`"io"`、`"os"`、`"strings"` 若缺。）

- [ ] **Step 6: 跑测试验证失败**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./internal/spec/ -run TestParseLintMissingParentKeyPlaceholder -v`
Expected: FAIL（旧 Parse 无 lint，stderr 空）。

- [ ] **Step 7: 实现 lint**（`parse.go`）

import 块加 `"os"`（若未导入）。`Parse` 的 `return tr, nil` 之前插入：

```go
	// lint：child resource 缺 parent_key 占位 → 警告（URL 可能缺父 ID）
	for _, r := range tr.Resources {
		lintParentKey(r, os.Stderr)
	}
```

新增函数：

```go
// lintParentKey 递归检查：对每个有 ParentKey 的 resource，其每个 child 的 Path
// 应含 {<ParentKey>} 占位（否则祖先链拼出的 URL 会缺父 ID，且无报错——声明式静默错）。
func lintParentKey(r *tree.Resource, w io.Writer) {
	for _, c := range r.Children {
		if r.ParentKey != "" && !strings.Contains(c.Path, "{"+r.ParentKey+"}") {
			fmt.Fprintf(w, "警告: resource %q 的 parent_key %q 未在子资源 %q 的 path %q 中出现（URL 可能缺父 ID）\n",
				r.Name, r.ParentKey, c.Name, c.Path)
		}
		lintParentKey(c, w)
	}
}
```

import 块确保有 `"fmt"`、`"io"`、`"os"`、`"strings"`（`strings` 已有；`io` 需加）。

- [ ] **Step 8: 跑全包测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./...`
Expected: PASS（lint 测试绿；既有清单 relation.path 含 `{instance_id}`，不触发警告，不回归）。

- [ ] **Step 9: Commit**

```bash
cd projects/api-cli && git add internal/tree/resolve.go internal/tree/resolve_test.go internal/spec/parse.go internal/spec/parse_test.go
git commit -m "fix(api-cli): N 层 path 祖先链拼接 + parent_key 占位填充 + 缺占位 lint"
```

---

## Task 6: 清单补 description + 端到端集成验证

**Files:**
- Modify: `projects/api-cli/examples/cmdb.yaml`（resource/operation 补 description）
- Modify: `projects/api-cli/examples/easyops-cmdb.yaml`（补 description）
- Test: `projects/api-cli/tests/integration/cmdb_test.go`（加 relation.read URL 断言）

**Interfaces:** 无（消费前序 task 全部能力）

- [ ] **Step 1: 给 cmdb.yaml 补 description**

`examples/cmdb.yaml` 的 `inst` 加 `description: CMDB 实例`；`relation` 加 `description: 实例的关系`；`read`/`search` 等关键 operation 加 description（参考 `easyops-cmdb.yaml` 风格）。例：

```yaml
  inst:
    description: CMDB 实例
    path: /instances
    singular: instance
    operations:
      create: { method: POST, path: "" }
      read:   { method: GET, path: "/{id}", description: 读取单个实例, params: { id: { in: path, type: string, required: true, description: 实例 ID } } }
      ...
    children:
      relation:
        description: 实例的关系
        path: "/{instance_id}/relations"
        parent_key: instance_id
        operations:
          ...
```

- [ ] **Step 2: 给 easyops-cmdb.yaml 补 description**

`object_instance` 加 `description: CMDB 对象实例`；`search` 加 `description: 按条件搜索实例（MongoDB 风格 query）`。

- [ ] **Step 3: 写集成测试**（`tests/integration/cmdb_test.go` 追加；先读现有文件确认 helper 与 mock server 模式）

构造一个最小 mock：`inst` POST `/api/v1/instances`、`relation` GET `/api/v1/instances/{instance_id}/relations/{id}`。用 `cmdb.yaml` 解析 + engine 跑 `relation read`，断言 mock 收到的请求路径含 `/instances/INST1/relations/REL1`。

```go
func TestIntegrationRelationReadAncestorURL(t *testing.T) {
	// 读 examples/cmdb.yaml（或内联同结构清单），起 mock server：
	// GET /api/v1/instances/{iid}/relations/{rid} → 200 {"id":"REL1"}
	// 跑 engine.Execute(relation, read, vals={instance_id:INST1,id:REL1})
	// 断言 mock 收到的 request.URL.Path == "/api/v1/instances/INST1/relations/REL1"
	t.Skip("按现有 cmdb_test.go 的 mock helper 填充；断言祖先链 URL 正确")
}
```

（具体 mock 复用 `cmdb_test.go` 现有 setup；若不存在 mock，则用 `httptest.Server` 起一个，endpoint.base_url 指向它。）

- [ ] **Step 4: 跑集成测试验证通过**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./tests/integration/ -v`
Expected: PASS（relation.read 请求路径含完整祖先链 `/instances/INST1/relations/REL1`）。

- [ ] **Step 5: 跑全包 + 清单解析冒烟**

Run: `export PATH=$PATH:/home/knodo/.local/go-parent/go/bin && cd projects/api-cli && go test ./... && go run ./cmd/api-cli --spec examples/easyops-cmdb.yaml explain object_instance search`
Expected: 全包 PASS；explain 输出含 `resource_description`/`operation_description`。

- [ ] **Step 6: Commit**

```bash
cd projects/api-cli && git add examples/cmdb.yaml examples/easyops-cmdb.yaml tests/integration/cmdb_test.go
git commit -m "test(api-cli): cmdb/easyops 清单补 description + relation.read 祖先链 URL 集成验证"
```

---

## Self-Review（写完后自检结果）

**1. Spec 覆盖：** design 的 T1→Task1，T2→Task2，T3 数据结构→Task3、富化→Task4，T4→Task5，清单/集成→Task6。全覆盖。

**2. Placeholder：** Task 6 Step 3 的集成测试用了 `t.Skip` + 注释指引（因未读 `cmdb_test.go` 现有 mock helper）——执行时须读现有文件填实，不留 skip 进 main。其余 step 均含完整代码。

**3. 类型一致性：** `ErrHelpRequested`（Task1 定义，main 用）、`Resource.Description/Parent`、`Operation.Description`（Task3 定义，Task4/5 消费）、`buildToolDescription`/`isWriteMethod`（Task4）、`ancestorPaths`（Task5）、`opShort`/`orDefaultCobra`/`desc`（Task4）——命名跨 task 一致。
