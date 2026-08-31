# api-cli 迭代四设计文档（二进制上下传：multipart 上传 + binary 下载 + spec schema 扩展）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-10 |
| 状态 | 定稿（已评审修订：统一 Out 落盘 / MCP CLI-only binary / renderPreview multipart）— 待实现 |
| 项目 | `projects/api-cli/` |
| 基线 | main HEAD `6119cf0`（MVP + iter2 + iter3 完整成果均已入 main；核实至当前 HEAD `2ec4ca2`，期间 api-cli 代码零改动，引用未失效） |
| 前序 | `2026-08-07-api-cli-design.md`（MVP）、`…-iter2-design.md`（schema 驱动 LLM + 翻页 + 体验）、`2026-08-08-api-cli-iter3-design.md`（2 bug + LLM 抉择 + N 层 path） |
| 分支 | `worktree-api-cli-iter4` |

---

## 1. 背景与目标

api-cli 当前请求、响应两侧**完全 JSON-only**（实测核实，引证见下），导致两类场景做不了：

1. **文件上传**（multipart/formData）：如 EasyOps `tool_package.import` 上传 `.tar.gz` 工具包、附件上传。
2. **文件下载**（binary 响应落盘）：如 `tool_package.export` 下载 `.tar.gz` 流、导出报告/媒体。

**现状证据**（核实于主仓 `6119cf0`，由 Explore 全目录扫描确认）：

- **请求侧**：`internal/engine/request.go:48-69` body 唯一构造——`bodyParams map[string]string` + `json.Marshal`；`internal/engine/execute.go:80-99` 三种 body 来源（resolve / `--body-file` / `BodyBytes`）全 JSON 语义，无 multipart 分支；全仓零 `mime/multipart` import、零 `NewmultipartWriter`。
- **响应侧**：`execute.go:290` `io.ReadAll(resp.Body)` 整体读内存；`execute.go:323-329` `decodeLoose` JSON 解析失败就把字节当 Go 字符串（二进制必然损坏）；输出目标硬编码 stdout（`internal/cobracli/flags.go:126` `Out: stdout()`），只过 json/yaml/table 文本编码器（`flags.go:154-160` `validateFormat`）；生产代码零 `os.Create`/`os.WriteFile`/`io.Copy(file, resp.Body)`。
- **spec schema**：`internal/spec/schema.go:37-75` `yamlOperation`/`yamlParam`/`yamlSchema` 字段只有 `Type/Required/Properties/Items/Description/...`——**无 `contentType`/`encoding`/`format: binary`**，清单层面无法声明文件型 verb。
- **CLI flag**：`flags.go:96-108` persistent flag 清单无 `--form`/`--file`/`--output`/`-o`/`--save`。
- **MCP 通道**：`internal/mcp/server.go:254-268` `toolsCall` 把 `engine.Execute` 写入 `buf` 的内容当 `result.content[0].text`（字符串）返回——二进制字节经此通道会产生无效 UTF-8，损坏 JSON-RPC。

**后果**：EasyOps `tool_package` 导入导出真调被迫走 Python SDK（`platforms/demo/sdk/easyops_client.py`），是 platforms 唯一保留的「编排侧 SDK 例外」（见 `platforms/demo/systems.yaml` 顶层 `platform_conventions.code.exceptions`）。

**本迭代目标**：让 api-cli **CLI** 原生支持二进制上下传，消除该例外——清单能声明文件型 verb（上传 `content_type: multipart-form-data`；下载 `response.format: binary`）；api-cli 能构造 multipart 上传请求（文件 + 表单字段）；能把 binary 响应流式落盘（`--output/-o`）；**MCP 通道显式不支持 binary**（声明 CLI-only，toolsCall 报错 + 工具描述标注 `[CLI-only]`）；端到端 mock server 跑通。

> **范围决策（评审拍板）**：binary 响应是「人的下载」场景，LLM 经 MCP 拿到二进制无意义且损坏 JSON-RPC。故 MCP 不支持 binary（见 §3 约定 6）；将 binary 编 base64 进 MCP text 的方案延后（见 §2.2）。

---

## 2. 范围

### 2.1 P0（本迭代）

| # | 能力 | task |
|---|---|---|
| 1 | spec schema 扩展：`operation.content_type` + `schema.format: binary` + `param.format: binary`，含 lint | T1 |
| 2 | multipart 请求构造（文件 part + 表单字段 part + boundary Content-Type） + renderPreview 不刷二进制 | T2 |
| 3 | binary 响应落盘（统一 Out 方案：`--output/-o` 由 globalOpts 重定向 Out，engine `writeOutput` 只写 Out，不经 decodeLoose/Format） | T3 |
| 4 | CLI flag `--output/-o` + `Options.OutCloser` + cobracli RunE Close + USAGE 文档 + `examples/binary.yaml` | T4 |
| 5 | 端到端（`httptest.Server` 跑通上传 + 下载） | T5 |
| 6 | MCP 通道排除 binary 响应 + multipart 上传：`toolsCall` 报错 + `buildToolDescription` 加 `[CLI-only]` 标签 | T6 |

### 2.2 不做（延后）

- **大文件流式上传**：multipart body 仍全量在内存构造（`bytes.Buffer`）；GB 级文件延后用 `multipart.NewWriter` 直写 `io.Pipe` 的 streaming 方案。
- **响应阶段流式落盘**：T3 落盘基于 `do` 已 `io.ReadAll` 的 `body`（写文件零额外内存拷贝之外的优化不做）；未来大文件下载改成 `do` 直流到文件。
- **响应 Content-Type 嗅探**：仅按清单声明（`op.Response.Format == "binary"`）触发落盘，不嗅探响应头（避免误判 + 保持声明式可预测）。
- **MCP binary 支持（base64 编码进 text）**：MCP 主场景是结构化数据，LLM 拿到 base64 串体积翻倍且难直接用；本迭代 MCP 显式排除 binary（§3 约定 6）。base64 + `outputSchema.contentEncoding` 方案留后续 iter（若 LLM 文件处理场景成熟）。
- **断点续传 / 分块上传**（非本迭代）。
- **OpenAPI importer**（iter3 已延后）。

---

## 3. 跨项约定

1. **声明式触发**：是否走二进制路径**只由清单声明决定**（`operation.content_type` / `schema.format`），不靠响应头嗅探或文件扩展名猜。声明在清单，行为可预测、可 lint。
2. **上传字段 = param（`format: binary`）**：文件上传字段复用现有 param 机制声明（`in: formData` + `format: binary`），自动注册成 String flag，值为本地文件路径。不引入独立 `--form` DSL（DRY，与现有 param 注册复用）。
3. **multipart Content-Type 由 engine 设**：构造 multipart body 时 engine 设 `Content-Type: multipart/form-data; boundary=<...>`（含 boundary），清单不声明 boundary。
4. **`--output` 语义 = 输出目标改文件（统一 Out 方案）**：`--output <path>` 由 cobracli `globalOpts` 把 `opts.Out` 从 stdout 重定向到 `os.Create(path)` 打开的文件，并记 `opts.OutCloser` 供 RunE 关闭。binary 响应 + `--output` = 二进制字节写文件；文本响应 + `--output` = 格式化文本写文件（`output.Format`/`FormatTable` 自然写 `opts.Out`）；binary 响应无 `--output` 时进 stdout（适合 `> file.bin` 管道，但推荐显式 `--output`）。**engine 的 `writeOutput` 只写 `opts.Out`，不直接 `os.WriteFile`、不读文件路径**——落盘与否、文件句柄生命周期都归 cobracli 层；engine 零文件句柄、零泄漏。
5. **backward compatible**：所有新字段零值 = 旧行为（`content_type` 空 = json；`format` 空 = 普通字段/响应）。现有清单/verb 零改动。
6. **MCP 不支持文件上传（multipart）与下载（binary 响应）（CLI-only）**：`response.format: binary` 与 `content_type: multipart-form-data` 的 verb 都需要 LLM 无法提供的本地文件系统（下载需落盘、上传需本地文件路径），不经 MCP。`mcp/server.go` `toolsCall` 命中这两种 verb 时返回 error（`-32602`，提示走 CLI：上传用文件路径参数，下载加 `--output`）；`buildToolDescription` 给这两类 verb 加 `[CLI-only]` 标签，让 LLM 在 `tools/list` 即知不宜调用。lint 不拦（清单声明合法，MCP 不支持是运行时通道限制）。

---

## 4. P0 设计

### 4.1 T1 — spec schema 扩展（数据结构先行）

清单新增三类声明能力（示例见 `examples/binary.yaml`）：

```yaml
resources:
  pkg:
    operations:
      # 文件上传 verb
      upload:
        method: POST
        path: /upload
        content_type: multipart-form-data        # ← 新增：请求体类型
        params:
          file:                                    # ← 文件字段
            in: formData
            format: binary                         # ← 新增：标记文件
            required: true
            description: "要上传的文件"
          kind:                                     # ← 普通表单字段
            in: formData
            description: "文件类别"
      # 文件下载 verb
      download:
        method: GET
        path: /download/{id}
        params:
          id: { in: path, type: string, required: true }
        response:
          format: binary                           # ← 新增：二进制流响应
          description: "下载的文件内容"
```

**结构体变更**（`schema.go` + `tree/types.go`）：

| 结构体 | 新增字段 | yaml tag |
|---|---|---|
| `yamlOperation` / `tree.Operation` | `ContentType string` | `content_type` |
| `yamlParam` / `tree.Param` | `Format string` | `format` |
| `yamlSchema` / `tree.Schema` | `Format string` | `format` |

`parse.go`：`convertOperation`/`convertParam`（当前内联在 `convertOperation` 的 params 循环里）/`convertSchema` 透传新字段。

> 注：`tree.Param` 现有 `Example any` 字段（`types.go:63`），但 `yamlParam` 无对应 tag、`convertOperation` 未透传——是 iter4 之前就存在的死字段，**本迭代不顺手修**（YAGNI，聚焦二进制）。

**lint**（`spec.Parse` 内，**err 级**——阻断 Parse，区别于 `lintParentKey` 的 warning 级）：

- `content_type` 非空且 ∉ {`json`, `multipart-form-data`} → parse error。
- `param.format == "binary"` 且 `param.in != "formData"` → parse error（文件字段只能进 formData）。
- `response.format == "binary"` 且 `response` 还声明了 `properties`/`items` → parse error（binary 响应无结构）。
- `response.format == "binary"` 且 operation 有 `pagination` → parse error（binary 响应不分页）。

### 4.2 T2 — multipart 请求构造

**触发**：`resolve` 阶段，若 `op.ContentType == "multipart-form-data"`，走 multipart 分支（文件字段由 `param.format == "binary"` 识别）。

**构造**（engine 新增 `buildMultipart(op, flags) (body []byte, contentType string, err error)`，新文件 `internal/engine/multipart.go`）：

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

> 注：`resolve`（`request.go:54-61`）的 switch 只分发 query/header/body，**不分发 formData**——formData 参数值留在 `flags` 里由 `buildMultipart` 取。链路：formData 值 → flags → buildMultipart。multipart verb 的字段都不进 JSON bodyParams。

**接入 resolve**（`request.go`：`resolvedReq` 加 `ContentType string`；`if len(bodyParams) > 0 { ... }` 块之后、`return req, nil` 之前）：

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

`execute.go` 的 `do()` 在 `for k, v := range req.Header { ... }` 循环之后（header 设置完）、query 设置之前加：

```go
    if req.ContentType != "" {
        httpReq.Header.Set("Content-Type", req.ContentType)
    }
```

在 auth header 覆盖之前设（顺序：endpoint header → operation header → Content-Type → auth）；multipart 的 Content-Type 不被 auth 覆盖（auth provider 一般不碰 Content-Type，easyops-openapi 签名按实际 Content-Type 算）。

**renderPreview 不刷二进制**（`execute.go:295` `renderPreview`）：multipart body 含文件字节，直接 `string(req.Body)` 会把整个文件刷到 stdout（dry-run 大文件灾难）。`renderPreview` 检测 `strings.HasPrefix(req.ContentType, "multipart/form-data")`，是则 body 段输出 `<multipart body omitted>`（curl 模式加注释 `# multipart body（含文件字节，省略）`），不刷原始字节。精确重建 `-F file=@<path>` 需把 flags 透传进 `renderPreview`，影响面大，本迭代取「省略 + 注释」，留 TODO。

### 4.3 T3 — binary 响应落盘（统一 Out 方案）

**触发**：`single()` 阶段，`op.Response != nil && op.Response.Format == "binary"`。

**落盘**（`single()` 在 `if status >= 400 { ... }` 之后、`data := decodeLoose(body)` 之前加分支）：

```go
func (e *Engine) single(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options, hc *http.Client) error {
    body, status, err := e.do(ctx, req, hc)
    if err != nil {
        return err
    }
    if status >= 400 {
        return output.NormalizeAPIError(status, body)
    }
    // binary 响应：字节直写 opts.Out，不经 decodeLoose/Format。
    // 落盘与否由 opts.Out 指向决定（--output 时 cobracli globalOpts 已把 Out 指向文件）。
    if op.Response != nil && op.Response.Format == "binary" {
        return writeOutput(opts, body)
    }
    data := decodeLoose(body)
    if opts.Format == "table" {
        return output.FormatTable(opts.Out, data, responseHeaders(op))
    }
    return output.Format(opts.Out, opts.Format, data)
}

// writeOutput 把字节写到 opts.Out（仅此一处出口）。
// 落盘由 cobracli globalOpts 把 opts.Out 指向文件实现；engine 不持有文件句柄。
func writeOutput(opts Options, body []byte) error {
    _, err := opts.Out.Write(body)
    return err
}
```

**关键**：binary 路径不经 `decodeLoose`/`Format`（直接写字节），且 `writeOutput` **不读 `OutputFile`、不 `os.WriteFile`**——落盘统一由 `opts.Out` 指向文件实现（§4.4 globalOpts 负责）。这样 binary 与文本两条路径出口一致（都写 `opts.Out`），engine 零文件句柄、零泄漏。`iterate`（分页）路径不涉及——T1 lint 已保证 `response.format=binary` × pagination 互斥。

**文本响应 + `--output`**：靠 §4.4 `globalOpts` 把 `opts.Out` 指向文件，`output.Format`/`FormatTable` 自然写文件——无需 T3 额外处理。

### 4.4 T4 — CLI flag + OutCloser 生命周期 + 文档

**flag**（`flags.go`）：

- `bindGlobalFlags` 加：`root.PersistentFlags().StringP("output", "o", "", "输出到文件（binary 响应落盘 / 文本写文件，默认 stdout）")`。
- `globalOpts`：读 `--output` flag，非空时 `os.Create` → `opts.Out = fout`、`opts.OutCloser = fout`（文件句柄交 RunE 关）。
- 上传文件字段：复用 `registerParams`（`param.in=formData` 自动注册成 String flag，值=文件路径），**不新增 flag**。

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

（`flags.go` 需补 import `"os"`。）

**RunE 关闭句柄**（`build.go` `operationCmd` 的 RunE，`globalOpts` 之后、`Execute` 之前注册 defer）：

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

**`Options` 字段调整**：**加** `OutCloser io.Closer`（nil = stdout/buffer，无需关）。**不引入** `OutputFile`——统一 Out 方案后 engine 只写 `opts.Out`、无需知道文件路径（落盘靠 cobracli `Out` 重定向 + `OutCloser`）。

**USAGE.md**（`docs/USAGE.md`）：

- §6 清单语法补 `content_type` / `format: binary` 说明 + 上传/下载示例。
- 全局 flag 表补 `--output/-o`。
- §9 已知限制：补「现支持文件上下传（CLI：multipart 上传 / binary 下载 `--output` 落盘；**MCP 不支持文件上传（multipart）与下载（binary），binary/multipart verb 走 CLI**）」，移除隐含的"不支持"假设。

**examples**：新增 `examples/binary.yaml`（upload + download verb，T5 端到端用例）。

### 4.5 T5 — 端到端（test server）

`tests/integration/binary_test.go`：用 `net/http/httptest` 起 server：

- `POST /upload`：`r.ParseMultipartForm`，回 JSON `{file: <name>, size: <n>, kind: <v>}` 校验收到 multipart。
- `GET /download/{id}`：回固定二进制（如 `[]byte{0x1f, 0x8b, 0x08, 0x00, ...}` 模拟 gzip 头）。

用 `examples/binary.yaml`（base_url 指向 test server），api-cli 跑：

- 上传：`api-cli --spec binary.yaml pkg upload --file test.tar.gz --kind tool` → 校验 server 回 JSON 含正确 file/size。
- 下载：`api-cli --spec binary.yaml pkg download abc --output out.bin` → 校验 `out.bin` 字节 == server 固定二进制（验证 §4.4 globalOpts 重定向 Out + RunE Close 全链路）。

### 4.6 T6 — MCP 通道排除 binary 响应 + multipart 上传（CLI-only）

> **谓词（final-review 扩展）**：CLI-only = `(response.format=binary) OR (content_type=multipart-form-data)`——两者都需要 LLM 无法提供的本地文件系统。binary 损坏 JSON-RPC；multipart 在 api-cli 宿主 `os.Open(file)` 必失败。toolsCall 与 buildToolDescription 共用此谓词（`isCLIOnlyVerb`），声明层 + 执行层双保险。

**toolsCall 报错**（`mcp/server.go` `toolsCall`，反查 r/op 命中 nil 检查之后、`SelectEndpoint` 之前）：

```go
    r, op := s.findByToolName(p.Name)
    if r == nil || op == nil {
        return map[string]any{"error": map[string]any{"code": -32602, "message": "tool not found: " + p.Name}}
    }
    // CLI-only verb 不经 MCP（两者都需要 LLM 无法提供的本地文件系统）：
    //   - binary 响应（下载）：二进制字节塞进 JSON-RPC text 产生无效 UTF-8 损坏响应。
    //   - multipart 上传：splitArgs 把 file 参数塞进 flags → buildMultipart → osOpen 在 api-cli 宿主上必失败。
    // 引导调用方走 CLI（上传用文件路径参数，下载加 --output 落盘）。
    if (op.Response != nil && op.Response.Format == "binary") || op.ContentType == "multipart-form-data" {
        return map[string]any{"error": map[string]any{"code": -32602, "message": "该操作涉及文件传输（上传或下载二进制），MCP 不支持；请用 CLI 调用（上传用文件路径参数，下载加 --output 落盘）"}}
    }
```

**`[CLI-only]` 标签**（`mcp/server.go` `buildToolDescription`，复用现有 tags 机制加一行）：

```go
    var tags []string
    if isWriteMethod(op.Method) {
        tags = append(tags, "[写操作]")
    }
    if op.Pagination != nil {
        tags = append(tags, "[可分页]")
    }
    if (op.Response != nil && op.Response.Format == "binary") || op.ContentType == "multipart-form-data" {
        tags = append(tags, "[CLI-only]")
    }
```

LLM 在 `tools/list` 即看到 `[CLI-only]`，不会贸然调用；即便调用，toolsCall 明确报错（声明式可预测，不静默损坏）。

---

## 5. 数据结构变更汇总

| 类型 | 字段 | 用途 | task |
|---|---|---|---|
| `tree.Operation` | `ContentType string` | 请求体类型（json/multipart） | T1 |
| `tree.Param` | `Format string` | binary 标记（文件字段） | T1 |
| `tree.Schema` | `Format string` | binary 标记（文件响应） | T1 |
| `engine.Options` | `OutCloser io.Closer`（**新增**） | --output 文件句柄，RunE Execute 后 Close | T4 |
| `engine.resolvedReq` | `ContentType string` | 请求 Content-Type（含 boundary） | T2 |

> 注：**不引入** `Options.OutputFile`。统一 Out 方案后 engine 只写 `opts.Out`、无需知道文件路径（落盘靠 cobracli `Out` 重定向 + `OutCloser`）。

- `spec/schema.go`：`yamlOperation`/`yamlParam`/`yamlSchema` 加对应 yaml tag。
- `spec/parse.go`：`convertOperation`/params 循环/`convertSchema` 透传；加 4 条 err 级 lint（§4.1）。
- `engine/multipart.go`（新）：`buildMultipart`。
- `engine/request.go`：`resolvedReq` 加 `ContentType`；resolve 末尾加 multipart 分支。
- `engine/execute.go`：**加** `Options.OutCloser`（T4）；`do()` 设 Content-Type（T2）；`single()` 加 binary 分支 + `writeOutput`（只写 Out，T3）；`renderPreview` multipart 省略 body（T2）。不引入 `Options.OutputFile`（统一 Out 方案后 engine 无需文件路径）。
- `cobracli/flags.go`：`bindGlobalFlags` 加 `--output/-o`；`globalOpts` 读 flag → `os.Create` → `Out`+`OutCloser`（补 import `"os"`）。
- `cobracli/build.go`：`operationCmd` RunE 加 `defer opts.OutCloser.Close()`。
- `mcp/server.go`：`toolsCall` binary 报错；`buildToolDescription` 加 `[CLI-only]` 标签。
- 全字段 backward compatible（零值即旧行为）。

---

## 6. 测试策略

| 层 | 用例 |
|---|---|
| **T1 单测** | schema 解析：`content_type`/`format: binary` 正确透传到 `tree.*`；lint 4 条：`content_type` 非法值报错、`format=binary`+`in≠formData` 报错、`response.format=binary`+有 properties 报错、`response.format=binary`+pagination 报错 |
| **T2 单测** | `buildMultipart`：含文件 part（filename + 内容）+ 表单字段；Content-Type 含 boundary；空 flags → 空 body；文件不存在报错；resolve 接入：`content_type=multipart` 时 `req.Body` 是 multipart、`req.ContentType` 含 boundary；`do()` 设了 Content-Type；`renderPreview` multipart 不刷原始 body |
| **T3 单测** | `single` + `response.format=binary`：body 原样写 `opts.Out`（buffer，不经 decode）——**engine 层只验 Out 字节正确，不验落盘**（落盘归 T4/T5） |
| **T4 单测** | `bindGlobalFlags` 含 `--output/-o`；`globalOpts` 设 `--output` 时 `opts.Out` 是 `*os.File` 指向该路径、`opts.OutCloser != nil`；未设时 `OutCloser == nil`、`Out == stdout`（RunE `defer Close` 是配套一行，落盘全链路在 T5 集成覆盖） |
| **T5 集成** | httptest server：upload multipart 正确解析（file/size/kind）、download `--output` 落盘字节逐一致 |
| **T6 单测** | `toolsCall` 命中 binary 响应 verb 或 multipart 上传 verb 均返回 `-32602` + 引导文案；`buildToolDescription` 对这两类 verb 输出含 `[CLI-only]` |

---

## 7. 清单 + 文档更新

- `examples/binary.yaml`（新）：upload + download verb（T5 端到端用例）。
- `docs/USAGE.md`：§6 补 `content_type`/`format: binary` 语法 + 示例；全局 flag 表补 `--output/-o`；§9 更新二进制支持状态（CLI 支持 / MCP 不支持文件上传 multipart + 下载 binary）。
- 本 design + 对应 plan。
- **不破坏现有清单**：新字段全可选、零值即旧行为；`examples/*.yaml` 现有清单零改动。

---

## 8. 文档位置

- design：`projects/api-cli/docs/2026-08-10-api-cli-iter4-design.md`（本文件）
- plan：`projects/api-cli/docs/2026-08-10-api-cli-iter4-plan.md`（writing-plans 产出）
- 遵循项目文档隔离（AGENTS.md §1：项目内 docs/）。

---

## 9. 实施前置

1. main（`6119cf0`）干净，api-cli 测试绿（`cd projects/api-cli && go test ./...`）。
2. 在 worktree `worktree-api-cli-iter4`（基于 main）实施，顺序：T1（数据结构 + lint）→ T2（multipart + renderPreview）→ T3（binary 落盘，engine 层只写 Out）→ T4（flag + OutCloser + RunE Close + 文档）→ T5（端到端，含落盘全链路）→ T6（MCP 排除 binary，依赖 T1 的 `Schema.Format`）。T2/T3 依赖 T1 字段；T4 的 OutCloser 与 T3 的 writeOutput 配套；T5 依赖 T2/T3/T4；T6 依赖 T1。
3. T5 端到端用 `examples/binary.yaml` + `httptest.Server`，无需真实 EasyOps 环境。
