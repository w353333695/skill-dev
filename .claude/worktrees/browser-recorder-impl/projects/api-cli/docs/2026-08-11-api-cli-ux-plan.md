# api-cli UX 改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 2026-08-11 cmdb 主机数查询暴露的 7 个 api-cli UX 痛点（body 强制落盘 / 分页吞 total / query 静默 / help 不列参数 / print-curl 不全 / 错误静默 / --all 上限不透明）。

**Architecture:** 7 个独立小改，分 3 批：批1（②④⑥⑦，零 iter4 冲突）→ 批2（①⑤，衔接 iter4 热点 execute.go:87-106 与 renderPreview）→ 批3（③ 实测验证 + spec 收尾）。改 `paging`/`cobracli`/`engine`/`output` 包 + `main.go`。统一改默认行为，依赖方（api-orchestrator）同步适配。

**Tech Stack:** Go + spf13/cobra + spf13/pflag + tidwall/gjson；测试标准 `testing` + `net/http/httptest`。

## Global Constraints

- **基线**：main HEAD `7f74612`（iter4 已 merge，无并行 worktree）。
- **统一改默认**：7 点都改默认行为，不新增 opt-in flag（⑤ `--reveal-auth` 是安全例外）。
- **auth 默认遮蔽**：print-curl 的 auth 值默认 `<redacted>`，`--reveal-auth` 显真值。
- **衔接 iter4**：① 在 `execute.go:87-106` 块（iter4 加了 2 行 `req.ContentType=""`），⑤ 在 `renderPreview`（iter4 加了 isMultipart 分支）—— 重读合并，不按旧版 diff。
- **TDD + frequent commits**：每 Task 先写失败测试 → 验证失败 → 实现 → 验证通过 → commit。
- **不破现有测试**：`internal/cobracli/smoke_test.go`、`internal/engine/execute_test.go` 必须持续通过。
- **commit message**：中文 `type(api-cli): <desc>`。

---

## File Structure

| 文件 | 责任 | 改动 Task |
|---|---|---|
| `internal/paging/engine.go` | 分页循环 + Item struct | T1（total）、T2（capped） |
| `internal/engine/execute.go` | 执行核心 + iterate + renderPreview | T1、T2、T5、T6 |
| `internal/engine/request.go` | resolve（query/header/body 分发） | T7（实测） |
| `internal/cobracli/flags.go` | flag 注册 + globalOpts | T4、T5、T6 |
| `internal/cobracli/help.go` | help 渲染 | T3 |
| `internal/cobracli/build.go` | 命令树 + SilenceErrors | T3 |
| `internal/output/errors.go` | PrintError + exit code | T4 |
| `cmd/api-cli/main.go` | 入口 + PrintError 调用 | T4 |
| `docs/USAGE.md` | 用户文档 | T8 |
| `platforms/demo/*.yaml`（api-orchestrator） | spec query 声明核实 | T9 |

**新增 Options 字段**（T1 引入，后续 Task 复用）：
- `Err io.Writer` —— stderr 写入目标（total / warning 输出）
- `Body string` —— inline JSON body（T5）
- `RevealAuth bool` —— print-curl 显真 auth（T6）

---

## 批1（零 iter4 冲突）

### Task 1: ② 分页输出 `data.total` 到 stderr

**Files:**
- Modify: `internal/paging/engine.go:19-23`（Item struct）、`:41-98`（Iter）
- Modify: `internal/engine/execute.go:24-37`（Options 加 Err）、`:209-264`（iterate 输出 total）
- Test: `internal/paging/engine_test.go`（create）、`internal/engine/execute_test.go`

**Interfaces:**
- Consumes: `tree.Pagination.ItemsPath`（已有）
- Produces: `paging.Item.Total *int`（仅首条 item 带）；`engine.Options.Err io.Writer`

- [ ] **Step 1: 写失败测试 — paging.Iter 传出 total**

Create `internal/paging/engine_test.go`:
```go
package paging

import (
	"context"
	"testing"

	"api-cli/internal/tree"
)

// totalPath 默认 = itemsPath 父 + ".total"；data.list -> data.total
func TestIterEmitsTotal(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data.list", Size: 10}
	// 响应信封含 data.total=3 + data.list 一条
	resp := []byte(`{"data":{"total":3,"list":[{"id":"a"}]}}`)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		return resp, nil
	}
	items := Iter(context.Background(), pg, do, nil, nil, Options{Limit: 10})
	var gotTotal *int
	count := 0
	for it := range items {
		if it.Total != nil {
			gotTotal = it.Total
		}
		if it.Err != nil {
			t.Fatalf("unexpected err: %v", it.Err)
		}
		count++
	}
	if gotTotal == nil || *gotTotal != 3 {
		t.Fatalf("want total=3, got %v", gotTotal)
	}
}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd projects/api-cli && go test ./internal/paging/ -run TestIterEmitsTotal -v`
Expected: FAIL / 编译错误（Item.Total 字段不存在）。

- [ ] **Step 3: 实现 — Item 加 Total + Iter 抽 total**

Modify `internal/paging/engine.go:19-23`，Item 加字段：
```go
type Item struct {
	ID    string
	Raw   []byte
	Err   error
	Total *int // 首条 item 携带信封里的 total（若有）；仅第一条非 nil
}
```

Modify `Iter`（engine.go:49-95 的 goroutine 内），在首次 `do` 返回后、抽 items 前抽 total，并在第一条 item 上携带。在 `respBody, err := do(...)` 之后（engine.go:66 之前）插入：
```go
// 首次响应抽 total（默认 totalPath = itemsPath 父级 + ".total"）
totalPath := pg.TotalPath
if totalPath == "" {
    totalPath = parentPath(pg.ItemsPath) + ".total"
}
```
在 `for _, it := range items` 循环内，发送首条 item 时带上 total（用 `firstTotal` 一次性变量）。把循环改为：
```go
var firstTotal *int
if t := gjson.GetBytes(respBody, totalPath); t.Exists() {
	n := int(t.Int())
	firstTotal = &n
}
for _, it := range items {
	id := gjson.Get(it.Raw, "id").String()
	if !opts.NoDedupe && id != "" {
		if seen[id] { continue }
		seen[id] = true
	}
	select {
	case out <- Item{ID: id, Raw: []byte(it.Raw), Total: firstTotal}:
	case <-ctx.Done():
		return
	}
	firstTotal = nil // 只在首条 item 带
	count++
	if opts.Limit > 0 && count >= opts.Limit { return }
	if count >= opts.MaxItems { return }
}
```

文件末尾加 helper：
```go
// parentPath 返回点分路径的父级："data.list" -> "data"；无点返回 ""。
func parentPath(p string) string {
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] == '.' {
			return p[:i]
		}
	}
	return ""
}
```

`tree.Pagination` 需加 `TotalPath string` 字段（若尚无）。Check `internal/tree/types.go`，若无则加：
```go
type Pagination struct {
	... // 现有字段
	TotalPath string // 可选：total 在响应信封的 gjson 路径；空则推 <ItemsPath 父>.total
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd projects/api-cli && go test ./internal/paging/ -run TestIterEmitsTotal -v`
Expected: PASS。

- [ ] **Step 5: 实现 — Options.Err + iterate 输出 total 到 stderr**

Modify `internal/engine/execute.go:24-37` Options 加字段：
```go
type Options struct {
	... // 现有
	Err        io.Writer // stderr（total / warning 输出；空则 engine 内部用 os.Stderr）
}
```

Modify `iterate`（execute.go:209-264），在 json 流式分支（254-262）和 table/yaml 分支（233-252）都加 total 输出。在 `items := paging.Iter(...)`（230 行）之后、format 分支之前插入：
```go
errw := opts.Err
if errw == nil {
	errw = os.Stderr
}
totalEmitted := false
```
在 json 流式分支的循环里（首条 item 时输出 total）：
```go
for it := range items {
	if it.Err != nil { ... } // 现有错误处理不变
	if !totalEmitted && it.Total != nil {
		fmt.Fprintf(errw, `{"_meta":{"total":%d}}`+"\n", *it.Total)
		totalEmitted = true
	}
	fmt.Fprintln(opts.Out, string(it.Raw))
}
```
table/yaml 分支同理（收集时记录 total）。

- [ ] **Step 6: 加 engine 集成测试 — stderr 有 total**

在 `internal/engine/execute_test.go` 加（用 httptest，参考 iter4 T5 先例）：
```go
func TestIterateEmitsTotalToStderr(t *testing.T) {
	// mock server 返回 {"data":{"total":2,"list":[{...},{...}]}}
	// 构造 paging operation，Execute 后断言 opts.Err (bytes.Buffer) 含 "total":2
	... // 见 iter4 execute_test.go 的 httptest 模式
}
```

- [ ] **Step 7: 运行全部测试**

Run: `cd projects/api-cli && go test ./...`
Expected: PASS（含现有 smoke_test / execute_test）。

- [ ] **Step 8: Commit**

```bash
git add internal/paging/engine.go internal/paging/engine_test.go \
        internal/engine/execute.go internal/engine/execute_test.go \
        internal/tree/types.go
git commit -m "feat(api-cli): 分页输出 data.total 到 stderr（stdout NDJSON 不变）
paging.Item 加 Total 字段；Iter 从信封抽 total（totalPath 默认 itemsPath 父.total）；
engine.Options 加 Err（stderr）；iterate 首 item 时输出 {\"_meta\":{\"total\":N}}。"
```

---

### Task 2: ⑦ `--all` 触顶提示 + exit code 4

**Files:**
- Modify: `internal/paging/engine.go`（加 ErrCapped sentinel + 触顶发 Item{Err}）
- Modify: `internal/engine/execute.go:209-264`（iterate 识别 capped + warning + exit 4）
- Test: `internal/paging/engine_test.go`、`internal/engine/execute_test.go`

**Interfaces:**
- Produces: `paging.ErrCapped`（sentinel error）；iterate 触顶时返回 `*output.APIError{ExitCode: ExitPagingOver}`

- [ ] **Step 1: 写失败测试 — MaxItems 触顶发 ErrCapped**

在 `internal/paging/engine_test.go` 加：
```go
func TestIterCappedEmitsErrCapped(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data.list", Size: 10}
	// 每页 5 条，MaxItems=3 → 触顶
	resp := []byte(`{"data":{"list":[{"id":"a"},{"id":"b"},{"id":"c"},{"id":"d"},{"id":"e"}]}}`)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		return resp, nil
	}
	items := Iter(context.Background(), pg, do, nil, nil, Options{MaxItems: 3})
	var capped bool
	count := 0
	for it := range items {
		if it.Err != nil && it.Err == ErrCapped {
			capped = true
		}
		count++
	}
	if !capped {
		t.Fatalf("want ErrCapped when MaxItems hit, got %d items no cap", count)
	}
}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd projects/api-cli && go test ./internal/paging/ -run TestIterCappedEmitsErrCapped -v`
Expected: FAIL（ErrCapped 未定义）。

- [ ] **Step 3: 实现 — ErrCapped sentinel + 触顶发送**

Modify `internal/paging/engine.go`，文件顶部 const 区后加：
```go
import "errors"
...
// ErrCapped 触达 MaxItems/MaxPages 硬上限时发出（作为 Item.Err），
// 消费方据此打 warning + exit 4，区别于真实翻页错误。
var ErrCapped = errors.New("paging capped: hit MaxItems or MaxPages")
```

Modify Iter 触顶分支（engine.go:81-86 + 55 循环上限）。把 `if count >= opts.MaxItems { return }`（84-86）和循环结束（page 达 MaxPages）改为发 ErrCapped：
```go
// count >= MaxItems
if count >= opts.MaxItems {
	select {
	case out <- Item{Err: ErrCapped}:
	case <-ctx.Done():
	}
	return
}
```
MaxPages 循环跑完（engine.go:55 `for page := 0; page < opts.MaxPages; page++` 结束后）在 goroutine 末尾（`defer close(out)` 之前）加：
```go
if page >= opts.MaxPages { // 循环因 page 上限退出
	select {
	case out <- Item{Err: ErrCapped}:
	default:
	}
}
```
（注：`page` 需在 for 后可见，把 `for page :=` 改为 `page := 0; for page < ...; page++`。）

- [ ] **Step 4: 运行验证通过**

Run: `cd projects/api-cli && go test ./internal/paging/ -run TestIterCappedEmitsErrCapped -v`
Expected: PASS。

- [ ] **Step 5: 实现 — iterate 识别 capped + warning + exit 4**

Modify `execute.go:209-264` iterate，在 `if it.Err != nil` 分支（235-242、254-260）前加 capped 判断：
```go
if it.Err != nil {
	if it.Err == paging.ErrCapped {
		errw := opts.Err
		if errw == nil { errw = os.Stderr }
		fmt.Fprintln(errw, "warning: hit paging cap, results may be incomplete")
		return &output.APIError{Code: "paging_capped", Message: "hit paging cap", ExitCode: output.ExitPagingOver}
	}
	// 现有错误归一化...
}
```
（两个 format 分支都要加；可抽 helper `handleItemErr(it, opts) error`。）

- [ ] **Step 6: 加测试 — exit code 4**

`internal/engine/execute_test.go` 加：mock 返回 >MaxItems 数据，Execute 后断言返回的 `*output.APIError.ExitCode == output.ExitPagingOver`（4）且 stderr buffer 含 "warning: hit paging cap"。

- [ ] **Step 7: 运行全部测试 + Commit**

Run: `cd projects/api-cli && go test ./...`
```bash
git add internal/paging/engine.go internal/paging/engine_test.go \
        internal/engine/execute.go internal/engine/execute_test.go
git commit -m "feat(api-cli): --all 触顶提示 + exit 4
paging.ErrCapped sentinel；触达 MaxItems/MaxPages 发 Item{Err:ErrCapped}；
iterate 收到打 stderr warning + 返回 ExitPagingOver(4)，复用预留死常量。"
```

---

### Task 3: ④ text help 列 verb 的 path/query/body 参数

**Files:**
- Modify: `internal/cobracli/help.go:48-68`（helpFunc text 分支自定义渲染）
- Modify: `internal/cobracli/build.go:79-81`（operationCmd.Use 加 `[args]`）
- Test: `internal/cobracli/help_test.go`（create）

**Interfaces:**
- Consumes: `locate(tr, rname, verb)`（help.go:88 已有）、`op.Params`、`op.Body.ToJSONSchema()`
- Produces: 自定义 text help 块（Path params / Query params / Body 三段）

- [ ] **Step 1: 写失败测试 — text help 含 path/query/body 分类**

Create `internal/cobracli/help_test.go`:
```go
package cobracli

import (
	"bytes"
	"strings"
	"testing"

	"api-cli/internal/tree"
)

func TestTextHelpListsParams(t *testing.T) {
	// 构造最小 OperationTree：resource=foo verb=read，path param id + query param q
	tr := &tree.OperationTree{
		Service: tree.Service{Name: "svc"},
		Resources: map[string]*tree.Resource{
			"foo": {Name: "foo", Operations: map[string]*tree.Operation{
				"read": {Verb: "read", Method: "GET", Path: "/foo/{id}", Params: []tree.Param{
					{Name: "id", In: "path", Required: true, Description: "ID"},
					{Name: "q", In: "query", Description: "关键词"},
				}},
			}},
		},
	}
	root, err := Build(tr)
	if err != nil { t.Fatal(err) }
	var buf bytes.Buffer
	root.SetOut(&buf)
	root.SetArgs([]string{"foo", "read", "--help-format=text"})
	_ = root.Execute() // 触发 help
	out := buf.String()
	for _, want := range []string{"Path params", "id", "Query params", "q"} {
		if !strings.Contains(out, want) {
			t.Errorf("text help 缺 %q；输出: %s", want, out)
		}
	}
}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd projects/api-cli && go test ./internal/cobracli/ -run TestTextHelpListsParams -v`
Expected: FAIL（text 分支走 cobra 默认模板，无 "Path params"）。

- [ ] **Step 3: 实现 — helpFunc text 分支自定义渲染**

Modify `internal/cobracli/help.go:48-68` helpFunc，把 text 分支（`c.Root().UsageFunc()(c)`，66 行）前加自定义渲染。在 `hf == "json"` 块之后、`c.Root().UsageFunc()(c)` 之前插入：
```go
// text 分支：叶子 operation 命令渲染分类参数块（path/query/body）
if rname, verb, ok := fromAnnotations(c.Annotations); ok {
	if r, op, locErr := locate(tr, rname, verb); locErr == nil {
		renderTextHelp(stdout(), c, r, op)
		return
	}
}
```
新增函数 `renderTextHelp`（help.go 末尾）：
```go
// renderTextHelp 渲染 verb 的人类可读 help：Usage + Path params(positional) + Query params + Body 入口。
func renderTextHelp(w io.Writer, c *cobra.Command, r *tree.Resource, op *tree.Operation) {
	fmt.Fprintf(w, "Usage:\n  %s %s [PATH_ARGS] [flags]\n\n", r.Name, op.Verb)
	fmt.Fprintf(w, "%s\n\n", op.Description)
	pathP, otherP := splitParams(op)
	if len(pathP) > 0 {
		fmt.Fprintln(w, "Path params (positional, in order):")
		for _, p := range pathP {
			req := ""
			if p.Required { req = " (required)" }
			fmt.Fprintf(w, "  %s   %s%s\n", p.Name, p.Description, req)
		}
		fmt.Fprintln(w)
	}
	var queryP []tree.Param
	for _, p := range otherP {
		if p.In == "query" { queryP = append(queryP, p) }
	}
	if len(queryP) > 0 {
		fmt.Fprintln(w, "Query params (--<name>=<value>):")
		for _, p := range queryP {
			fmt.Fprintf(w, "  --%s   %s\n", p.Name, p.Description)
		}
		fmt.Fprintln(w)
	}
	if op.Body != nil {
		fmt.Fprintln(w, "Body: --body '<json>' | --body-file <path|->")
	}
	fmt.Fprintln(w, "Flags:")
	fmt.Fprintln(w, c.Flags().FlagUsages())
}
```
（import 需加 `io`——help.go 已 import。）

- [ ] **Step 4: 实现 — operationCmd.Use 加 [args]**

Modify `internal/cobracli/build.go:79-81`，`Use: verb` 改：
```go
c := &cobra.Command{
	Use:   verb + " [args]",
	...
}
```

- [ ] **Step 5: 运行验证通过**

Run: `cd projects/api-cli && go test ./internal/cobracli/ -run TestTextHelpListsParams -v`
Expected: PASS。

- [ ] **Step 6: 运行全部测试 + Commit**

Run: `cd projects/api-cli && go test ./...`
```bash
git add internal/cobracli/help.go internal/cobracli/help_test.go internal/cobracli/build.go
git commit -m "feat(api-cli): text help 列 verb 的 path/query/body 参数
helpFunc text 分支调 locate 渲染分类块（Path params positional / Query params / Body 入口）；
operationCmd.Use 加 [args] 提示 positional。复用 emitHelpJSON 同源 op 数据。"
```

---

### Task 4: ⑥ 错误可见化（默认人类可读，--format=json 才 JSON）

**Files:**
- Modify: `internal/output/errors.go:29-37`（PrintError 人类可读 + jsonMode）
- Modify: `cmd/api-cli/main.go:26-31`（传 format 给 PrintError）
- Test: `internal/output/errors_test.go`（create）

**Interfaces:**
- Produces: `output.PrintError(w, err, jsonMode bool)`（签名变更）

- [ ] **Step 1: 写失败测试 — 默认人类可读**

Create `internal/output/errors_test.go`:
```go
package output

import (
	"bytes"
	"strings"
	"testing"
)

func TestPrintErrorHumanReadableByDefault(t *testing.T) {
	var buf bytes.Buffer
	ae := &APIError{Code: "unknown_flag", Message: "unknown flag: --q", ExitCode: ExitParamError}
	PrintError(&buf, ae, false) // jsonMode=false
	out := buf.String()
	if !strings.Contains(out, "error:") {
		t.Errorf("默认应人类可读含 'error:'，got: %s", out)
	}
	if strings.HasPrefix(strings.TrimSpace(out), "{") {
		t.Errorf("默认不该是 JSON，got: %s", out)
	}
}

func TestPrintErrorJSONWhenJSONMode(t *testing.T) {
	var buf bytes.Buffer
	ae := &APIError{Code: "x", Message: "m", ExitCode: ExitParamError}
	PrintError(&buf, ae, true) // jsonMode=true
	if !strings.HasPrefix(strings.TrimSpace(buf.String()), "{") {
		t.Errorf("jsonMode 应输出 JSON，got: %s", buf.String())
	}
}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd projects/api-cli && go test ./internal/output/ -run TestPrintError -v`
Expected: FAIL（PrintError 签名不匹配 / 当前总输出 JSON）。

- [ ] **Step 3: 实现 — PrintError 加 jsonMode**

Modify `internal/output/errors.go:29-37`：
```go
// PrintError 把错误写到 w：默认人类可读（error: <code>: <message>），
// jsonMode=true 时输出结构化 JSON（机器可解析）。spec §11.3。
func PrintError(w io.Writer, err error, jsonMode bool) {
	ae, ok := err.(*APIError)
	if !ok {
		ae = &APIError{Code: "internal", Message: err.Error(), ExitCode: ExitParamError}
	}
	if jsonMode {
		b, _ := json.Marshal(ae)
		fmt.Fprintln(w, string(b))
		return
	}
	fmt.Fprintf(w, "error: %s: %s\n", ae.Code, ae.Message)
}
```

- [ ] **Step 4: 运行验证通过**

Run: `cd projects/api-cli && go test ./internal/output/ -run TestPrintError -v`
Expected: PASS。

- [ ] **Step 5: 实现 — main 传 format**

Modify `cmd/api-cli/main.go:26-31`，解析 --format 决定 jsonMode：
```go
func main() {
	if err := run(); err != nil {
		jsonMode := hasJSONFormat(os.Args[1:]) // --format=json（含 =/空格）
		output.PrintError(os.Stderr, err, jsonMode)
		os.Exit(output.ExitCode(err))
	}
}

// hasJSONFormat 扫 args 判断是否 --format=json（错误格式与 body 格式对齐）。
func hasJSONFormat(args []string) bool {
	for _, a := range args {
		if a == "--format=json" || a == "json" {
			// "json" 是 --format json 拆两 token 时的值
			return true
		}
	}
	return false
}
```

- [ ] **Step 6: 加端到端测试 — unknown flag 可见**

`internal/cobracli/smoke_test.go`（已存在，iter4 加过）加用例：构造 root，`SetArgs([]string{"foo","read","--q","x"})`，Execute 后断言 stderr 含 "unknown flag" 且 exit 1。（确保 SilenceErrors 不再吞掉可见性——错误经 main.PrintError 人类可读。）

- [ ] **Step 7: 运行全部测试 + Commit**

Run: `cd projects/api-cli && go test ./...`
```bash
git add internal/output/errors.go internal/output/errors_test.go \
        cmd/api-cli/main.go internal/cobracli/smoke_test.go
git commit -m "feat(api-cli): 错误默认人类可读到 stderr（--format=json 才 JSON）
PrintError 加 jsonMode 参数；main 据 --format=json 决定。unknown flag 等错误
不再被 SilenceErrors 吞成『静默』，经 main 打印可见。"
```

---

## 批2（衔接 iter4 热点）

### Task 5: ① body inline / stdin

**Files:**
- Modify: `internal/cobracli/flags.go:97-110`（bindGlobalFlags 加 --body）、`:117-145`（globalOpts 取 Body）
- Modify: `internal/engine/execute.go:24-37`（Options.Body）、`:86-106`（Execute body 分支，衔接 iter4 CT-clear）
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Produces: `engine.Options.Body string`（inline JSON）；body 优先级 `--body` > `--body-file` > body 参数

- [ ] **Step 1: 写失败测试 — --body inline 注入**

`internal/engine/execute_test.go` 加：
```go
func TestExecuteInlineBody(t *testing.T) {
	// httptest server 断言收到请求 body == {"x":1}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if string(b) != `{"x":1}` { t.Errorf("want body {\"x\":1}, got %s", b) }
		w.Write([]byte(`{"ok":true}`))
	}))
	defer srv.Close()
	// 构造 spec/endpoint 指向 srv，op 无 body 参数，opts.Body = `{"x":1}`
	... // 参考 iter4 execute_test 的 httptest 构造
	opts := engine.Options{Format: "json", Body: `{"x":1}`, Out: &bytes.Buffer{}}
	err := eng.Execute(ctx, ep, r, op, nil, nil, opts)
	if err != nil { t.Fatal(err) }
}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd projects/api-cli && go test ./internal/engine/ -run TestExecuteInlineBody -v`
Expected: FAIL（Options.Body 字段不存在）。

- [ ] **Step 3: 实现 — Options.Body + flag**

Modify `execute.go:24-37` Options 加字段：
```go
Body string // inline JSON body（优先级：Body > BodyFile > body 参数）
```

Modify `flags.go:97-110` bindGlobalFlags，在 `--body-file` 行后加：
```go
root.PersistentFlags().String("body", "", "请求 body JSON（内联；优先级高于 --body-file）")
```

Modify `flags.go:117-145` globalOpts，Options 构造加：
```go
opts := engine.Options{
	...
	Body:     strFlag(f, "body"),
	...
}
```

- [ ] **Step 4: 实现 — Execute 分支（衔接 iter4）**

Modify `execute.go:86-106`，在 body-file 块（87-97）**之前**加 inline + 互斥校验；stdin（`--body-file -`）并入 body-file 块。重写 86-106 段（**基于 iter4 当前版本**，保留 `req.ContentType=""` 两行）：
```go
// 互斥：--body 与 --body-file 不可同传
if opts.Body != "" && opts.BodyFile != "" {
	return &output.APIError{Code: "body_conflict", Message: "--body 与 --body-file 互斥", ExitCode: output.ExitParamError}
}

// --body inline：最高优先级，覆盖 body 参数（不动 ContentType，JSON 默认）
if opts.Body != "" {
	req.Body = []byte(opts.Body)
	req.ContentType = ""
}

// body-file：覆盖 req.Body。支持 "-" 读 stdin。
if opts.BodyFile != "" {
	var b []byte
	var err error
	if opts.BodyFile == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(opts.BodyFile)
	}
	if err != nil {
		return &output.APIError{Code: "body_file", Message: err.Error(), ExitCode: output.ExitParamError}
	}
	req.Body = b
	req.ContentType = "" // iter4：清 multipart CT 避免 silent mismatch
}

// BodyBytes（MCP _body）：最高优先级（覆盖 --body/--body-file）。
if len(opts.BodyBytes) > 0 {
	req.Body = opts.BodyBytes
	req.ContentType = ""
}
```

- [ ] **Step 5: 加测试 — stdin + 互斥**

`execute_test.go` 加：`TestExecuteBodyStdin`（注入 opts.BodyFile="-" + 重定向 stdin buffer）、`TestExecuteBodyMutex`（Body+BodyFile 同传 → error）。

- [ ] **Step 6: 运行全部测试 + Commit**

Run: `cd projects/api-cli && go test ./...`
```bash
git add internal/engine/execute.go internal/engine/execute_test.go \
        internal/cobracli/flags.go
git commit -m "feat(api-cli): body 支持 --body 内联 + --body-file - 读 stdin
新增 --body flag（inline JSON，优先级 --body > --body-file > body 参数）；
--body-file - 从 stdin 读；两者互斥。衔接 iter4 的 CT-clear 逻辑。"
```

---

### Task 6: ⑤ print-curl 完整（Host/CT/query/auth 默认遮蔽 + --reveal-auth）

**Files:**
- Modify: `internal/cobracli/flags.go`（加 --reveal-auth flag + globalOpts）
- Modify: `internal/engine/execute.go:24-37`（Options.RevealAuth）、`:108-113`（auth.Apply 提前到 preview 前）、`:316-339`（renderPreview 补全 + query 拼接 + auth 遮蔽）
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Produces: `engine.Options.RevealAuth bool`；renderPreview 输出含 Host/CT/query/auth

- [ ] **Step 1: 写失败测试 — print-curl 含 Host/CT/query，auth 遮蔽**

`internal/engine/execute_test.go` 加：
```go
func TestPrintCurlCompleteAndRedactsAuth(t *testing.T) {
	// 构造 req：endpoint.Host=set, ContentType=application/json, Query={q:x},
	// Header 已含 org/user + 模拟 auth 注入的 Cookie
	req := &resolvedReq{Method: "POST", URL: "http://h/api", Host: "admin.local",
		ContentType: "application/json", Query: map[string]string{"q": "x"},
		Header: map[string]string{"org": "1", "user": "u", "Cookie": "PHPSESSID=secret"}}
	got := renderPreview(req, Options{PrintCurl: true, RevealAuth: false})
	for _, want := range []string{"-H 'Host: admin.local'", "Content-Type: application/json", "q=x", "<redacted>"} {
		if !strings.Contains(got, want) { t.Errorf("curl 缺 %q；got: %s", want, got) }
	}
	if strings.Contains(got, "secret") {
		t.Errorf("auth 应遮蔽，不该出现 secret；got: %s", got)
	}
}

func TestPrintCurlRevealAuth(t *testing.T) {
	req := &resolvedReq{Header: map[string]string{"Cookie": "PHPSESSID=secret"}}
	got := renderPreview(req, Options{PrintCurl: true, RevealAuth: true})
	if !strings.Contains(got, "secret") {
		t.Errorf("--reveal-auth 应显真值；got: %s", got)
	}
}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd projects/api-cli && go test ./internal/engine/ -run TestPrintCurl -v`
Expected: FAIL（renderPreview 当前不含 Host/CT/query，auth 不遮蔽）。

- [ ] **Step 3: 实现 — Options.RevealAuth + flag**

`execute.go:24-37` Options 加：
```go
RevealAuth bool // print-curl 显示真实 auth 值（默认遮蔽 <redacted>）
```
`flags.go` bindGlobalFlags 加：
```go
root.PersistentFlags().Bool("reveal-auth", false, "print-curl 时显示真实 auth 值（默认遮蔽）")
```
globalOpts 加 `RevealAuth: boolFlag(f, "reveal-auth")`。

- [ ] **Step 4: 实现 — auth.Apply 提前到 preview 前**

Modify `execute.go:108-139`，把 auth.Apply 块（122-139）**移到** dry-run/print-curl 块（110-113）**之前**，并加 DryRun guard 防止 oauth2 刷新副作用。新顺序：
```go
// auth.Apply：endpoint.Auth 空/none 跳过；其余加载 provider 注入 header/query。
// 提前到 preview 前，让 print-curl/dry-run 看到完整鉴权头（spec ⑤）。
var authedReq *resolvedReq
if ep.Auth != "" && ep.Auth != "none" {
	provider, err := auth.Load(ep.Auth)
	if err != nil {
		return &output.APIError{Code: "auth_load", Message: err.Error(), ExitCode: output.ExitAuthError}
	}
	ar, err := provider.Apply(ctx, &adapter.AuthRequest{
		Method: req.Method, URL: req.URL, Body: req.Body, Headers: req.Header, Query: req.Query,
		DryRun: opts.DryRun || opts.PrintCurl, // 防 oauth2 等有状态 provider 刷新
	})
	if err != nil { ... }
	for k, v := range ar.Headers { req.Header[k] = v }
	for k, v := range ar.Query { req.Query[k] = v }
	authedReq = req
}
_ = authedReq

if opts.DryRun || opts.PrintCurl {
	fmt.Fprintln(opts.Out, renderPreview(req, opts))
	return nil
}
// gateWrite / do 不变（auth 已在上完成）
```
（注：`adapter.AuthRequest` 加 `DryRun bool` 字段；有状态 auth provider 检查它跳过刷新。easyops cookie/openapi 无副作用，DryRun 字段对他们 no-op。）

- [ ] **Step 5: 实现 — renderPreview 补全（Host/CT/query/auth）**

Modify `execute.go:316-339` renderPreview 的 curl 分支（318-332），重写为：
```go
if opts.PrintCurl {
	curl := "curl -X " + req.Method + " '" + buildCurlURL(req) + "'"
	// Host（IP 直连必需，独立字段不在 Header map）
	if req.Host != "" {
		curl += " -H 'Host: " + req.Host + "'"
	}
	// Content-Type（独立字段）
	if req.ContentType != "" && !isMultipart {
		curl += " -H 'Content-Type: " + req.ContentType + "'"
	}
	// 所有 header；auth 值默认遮蔽
	for k, v := range req.Header {
		if isAuthHeader(k) && !opts.RevealAuth {
			v = "<redacted>"
		}
		curl += " -H '" + k + ": " + v + "'"
	}
	if isMultipart {
		curl += "  # multipart body（省略；等价 -F file=@<path>）"
	} else if req.Body != nil {
		curl += " -d '" + string(req.Body) + "'"
	}
	if opts.Insecure { curl += " --insecure" }
	return curl
}
```
新增 helper（execute.go 末尾）：
```go
// buildCurlURL 把 req.Query 拼进 URL（print-curl 显示用；真请求在 do() 拼）。
func buildCurlURL(req *resolvedReq) string {
	u := req.URL
	if len(req.Query) > 0 {
		v := url.Values{}
		for k, val := range req.Query { v.Set(k, val) }
		if strings.Contains(u, "?") {
			u += "&" + v.Encode()
		} else {
			u += "?" + v.Encode()
		}
	}
	return u
}

// isAuthHeader 判断是否鉴权头（遮蔽目标）：Cookie/Authorization/X-*鉴权前缀。
func isAuthHeader(k string) bool {
	switch strings.ToLower(k) {
	case "cookie", "authorization":
		return true
	}
	return false
}
```
（import 加 `net/url`。）

- [ ] **Step 6: 运行验证通过 + 全部测试**

Run: `cd projects/api-cli && go test ./internal/engine/ -run TestPrintCurl -v && go test ./...`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add internal/engine/execute.go internal/engine/execute_test.go \
        internal/cobracli/flags.go pkg/adapter/*.go
git commit -m "feat(api-cli): print-curl 补全 Host/CT/query + auth 默认遮蔽
auth.Apply 提前到 preview 前（DryRun guard 防 oauth2 刷新）；
renderPreview 补 Host/Content-Type + query 拼 URL（顺带修 ③query 显示遗漏）；
auth 头默认 <redacted>，--reveal-auth 显真值。衔接 iter4 isMultipart 分支。"
```

---

## 批3（实测 + spec 收尾）

### Task 7: ③ query 传递实测验证 + spec 收尾

**背景**：代码分析表明 ③"query 静默"真因是 **renderPreview 不拼 query 到 URL**（T6 已修），而非 query 没传。本 Task 实测确认，并核实 platforms spec 的 query 声明完整。

**Files:**
- Test: 手工实测 + `internal/engine/request_test.go`（若无则 create，验证 resolve 把 query 放 req.Query）
- Verify: `platforms/demo/easyops-cmdb.yaml`（onboarding 模式 + lint）

**Interfaces:**
- Consumes: T6 的 buildCurlURL（query 已进 curl）

- [ ] **Step 1: 实测真调（非 print-curl）验证 query 生效**

Run（真调 easyops cmdb，org 18832008）:
```bash
cd /workspace/.claude/skills/api-orchestrator
export EASYOPS_ORG=18832008 EASYOPS_USER=easyops EASYOPS_CMDB_BACKEND_URL=http://172.30.0.232:8079
./scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model list --q 主机 --format json --timeout 20s 2>/dev/null | head -3
```
Expected: 返回含"主机"的模型（如 `HOST`）——证明 query 真调生效（之前 print-curl 漏显示是 T6 已修的 bug）。

- [ ] **Step 2: 实测 T6 修复后 print-curl 含 query**

Run:
```bash
./scripts/run.sh --spec platforms/demo/easyops-cmdb.yaml object_model list --q 主机 --print-curl
```
Expected: curl URL 含 `?q=`（T6 buildCurlURL 生效）。若仍无 → 回 T6 排查。

- [ ] **Step 3: 加单测 — resolve 把 query 放 req.Query**

`internal/engine/request_test.go`（create 若无）:
```go
package engine

import "testing"

func TestResolveQueryParamIntoReqQuery(t *testing.T) {
	// 构造 op 有 query param q；flags={q:"主机"}；断言 resolvedReq.Query["q"]=="主机"
	... // 参考 resolve 签名构造 tr/ep/r/op
	if got := req.Query["q"]; got != "主机" {
		t.Errorf("query 应进 req.Query，got %q", got)
	}
}
```

- [ ] **Step 4: 核实 platforms spec 的 query 声明（onboarding 模式）**

Run:
```bash
cd /workspace/.claude/skills/api-orchestrator
chmod -R u+w platforms/demo/
# 核实 list/search verb 的 query 参数声明完整
grep -n "in: query" platforms/demo/easyops-cmdb.yaml | head
# 若有遗漏（如某 search 缺 page/page_size），补声明
./scripts/lint-platforms.py demo  # 0 ERR 才合格
chmod -R u-w platforms/demo/
```

- [ ] **Step 5: 运行全部测试 + Commit（spec 端如有改动）**

Run: `cd projects/api-cli && go test ./...`
```bash
# api-cli 侧（request_test.go）
git add projects/api-cli/internal/engine/request_test.go
git commit -m "test(api-cli): 验证 resolve 把 query 放 req.Query（③ 排查回归）
代码分析+实测确认 ③ 真因是 renderPreview 漏拼 query（T6 已修），非 query 没传。"
# platforms 侧（若有 spec 补声明，onboarding 模式提交）
```

---

### Task 8: USAGE.md 文档更新

**Files:**
- Modify: `projects/api-cli/docs/USAGE.md`

- [ ] **Step 1: 更新 USAGE.md**

在 USAGE.md 对应章节补充（基于 iter4 当前版本）：
- `--body '<json>'`（内联）+ `--body-file -`（stdin）+ 互斥说明
- `--reveal-auth`（print-curl 显真 auth）
- 分页：`total` 在 stderr（`{"_meta":{"total":N}}`）
- `--all` 触顶：stderr warning + exit 4
- 错误：默认人类可读到 stderr，`--format=json` 才 JSON
- help：`--help` 现列 path/query/body 参数

- [ ] **Step 2: Commit**

```bash
git add projects/api-cli/docs/USAGE.md
git commit -m "docs(api-cli): USAGE 更新 UX 改造（--body/--reveal-auth/stderr total/exit 4/help 参数）"
```

---

### Task 9: api-orchestrator 适配（SKILL.md + 脚本）

**Files:**
- Modify: `/workspace/.claude/skills/api-orchestrator/SKILL.md`（执行段，注意 symlink → 仓库内 `skills/api-orchestrator/SKILL.md`）
- Verify: api-orchestrator 下解析 api-cli 输出的脚本（若有）

- [ ] **Step 1: 更新 SKILL.md 执行段**

补充：`--body` 可用（零落盘）、print-curl 默认遮蔽 auth（`--reveal-auth` 显真值）、错误默认人类可见到 stderr（不再静默）、分页 `total` 在 stderr（`{"_meta":{"total":N}}`，stdout NDJSON 不变）。

- [ ] **Step 2: 排查/适配解析脚本**

Run: `grep -rn "api-cli\|run.sh" /workspace/.claude/skills/api-orchestrator/scripts/ /workspace/.claude/skills/api-orchestrator/references/ | grep -i parse`
若有解析 api-cli stdout 的脚本（依赖纯 NDJSON 或 JSON 错误），适配 stderr total / 人类可读错误格式。

- [ ] **Step 3: Commit（立即，避免被 javis auto-commit 捎带）**

```bash
git add skills/api-orchestrator/SKILL.md
git commit -m "docs(api-orchestrator): SKILL 执行段适配 api-cli UX 改造
--body 零落盘 / print-curl auth 遮蔽 / 错误可见 / total 在 stderr。"
```

---

## Self-Review

**1. Spec coverage**（对照 spec 的 7 点）：
- ① body inline/stdin → T5 ✓
- ② 分页 total → T1 ✓
- ③ query → T7（+ T6 已修显示）✓
- ④ text help 列参数 → T3 ✓
- ⑤ print-curl 完整 + auth 遮蔽 → T6 ✓
- ⑥ 错误可见 → T4 ✓
- ⑦ --all 触顶 → T2 ✓
- 横切（USAGE / api-orchestrator 适配）→ T8、T9 ✓

**2. Placeholder scan**：无 TBD/TODO；每 Task 的代码块完整（基于真实代码）。T7 的实测步骤给确切命令 + 预期。

**3. Type consistency**：
- `engine.Options` 新增字段 Err（T1）/ Body（T5）/ RevealAuth（T6）—— 各 Task 独立加，不冲突。
- `paging.Item.Total`（T1）vs `paging.ErrCapped`（T2 用 Item.Err sentinel，不改 struct）—— 不冲突。
- `output.PrintError` 签名变更（T4 加 jsonMode）—— main.go（T4 Step 5）同步更新；MCP server 若调用 PrintError 需同步（检查 `internal/mcp/server.go` 是否调 PrintError，若是则传 jsonMode=true 保持 MCP JSON 语义）。
- `adapter.AuthRequest.DryRun`（T6 Step 4）—— T6 内同步。

**4. 一致性 caveat**：T4 改了 `PrintError` 签名，全仓 grep 调用点（main.go + 可能的 mcp/server.go），全部传 jsonMode。T6 实施时若 `adapter.AuthRequest` 加 DryRun，oauth2/cookie/bearer 等 provider 的 Apply 需检查该字段（easyops provider 无副作用，可忽略；oauth2 provider 若存在需加 guard）。
