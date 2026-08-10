# api-cli 迭代四设计文档（二进制上下传：multipart 上传 + binary 下载 + spec schema 扩展）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-10 |
| 状态 | Draft（待实现，下一步 writing-plans 产出 plan） |
| 项目 | `projects/api-cli/` |
| 基线 | main HEAD `6119cf0`（MVP + iter2 + iter3 完整成果均已入 main） |
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

**后果**：EasyOps `tool_package` 导入导出真调被迫走 Python SDK（`platforms/demo/sdk/easyops_client.py`），是 platforms 唯一保留的「编排侧 SDK 例外」（见 `platforms/demo/systems.yaml` 顶层 `platform_conventions.code.exceptions`）。

**本迭代目标**：让 api-cli 原生支持二进制上下传，消除该例外——清单能声明文件型 verb（上传 `content_type: multipart-form-data`；下载 `response.format: binary`）；api-cli 能构造 multipart 上传请求（文件 + 表单字段）；能把 binary 响应流式落盘（`--output/-o`）；端到端 mock server 跑通。

---

## 2. 范围

### 2.1 P0（本迭代）

| # | 能力 | task |
|---|---|---|
| 1 | spec schema 扩展：`operation.content_type` + `schema.format: binary` + `param.format: binary`，含 lint | T1 |
| 2 | multipart 请求构造（文件 part + 表单字段 part + boundary Content-Type） | T2 |
| 3 | binary 响应落盘（`--output/-o` + 流式写文件，跳过 decodeLoose/Format） | T3 |
| 4 | CLI flag `--output/-o` + `Options.OutputFile` + USAGE 文档 + `examples/binary.yaml` | T4 |
| 5 | 端到端（`httptest.Server` 跑通上传 + 下载） | T5 |

### 2.2 不做（延后）

- **大文件流式上传**：multipart body 仍全量在内存构造（`bytes.Buffer`）；GB 级文件延后用 `multipart.NewWriter` 直写 `io.Pipe` 的 streaming 方案。
- **响应阶段流式落盘**：T3 落盘基于 `do` 已 `io.ReadAll` 的 `body`（写文件零额外内存拷贝之外的优化不做）；未来大文件下载改成 `do` 直流到文件。
- **响应 Content-Type 嗅探**：仅按清单声明（`op.Response.Format == "binary"`）触发落盘，不嗅探响应头（避免误判 + 保持声明式可预测）。
- **断点续传 / 分块上传**（非本迭代）。
- **OpenAPI importer**（iter3 已延后）。

---

## 3. 跨项约定

1. **声明式触发**：是否走二进制路径**只由清单声明决定**（`operation.content_type` / `schema.format`），不靠响应头嗅探或文件扩展名猜。声明在清单，行为可预测、可 lint。
2. **上传字段 = param（`format: binary`）**：文件上传字段复用现有 param 机制声明（`in: formData` + `format: binary`），自动注册成 String flag，值为本地文件路径。不引入独立 `--form` DSL（DRY，与现有 param 注册复用）。
3. **multipart Content-Type 由 engine 设**：构造 multipart body 时 engine 设 `Content-Type: multipart/form-data; boundary=<...>`（含 boundary），清单不声明 boundary。
4. **`--output` 语义 = 输出目标改文件**：`--output <path>` 把输出目标从 stdout 改文件。binary 响应 + `--output` = 二进制落盘；文本响应 + `--output` = 格式化文本写文件。binary 响应无 `--output` 时进 stdout（适合 `> file.bin` 管道，但推荐显式 `--output`）。
5. **backward compatible**：所有新字段零值 = 旧行为（`content_type` 空 = json；`format` 空 = 普通字段/响应）。现有清单/verb 零改动。

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

**lint**（`spec.Parse` 内，err 级，参考现有 `lintParentKey` 模式）：

- `content_type` 非空且 ∉ {`json`, `multipart-form-data`} → parse error。
- `param.format == "binary"` 且 `param.in != "formData"` → parse error（文件字段只能进 formData）。
- `response.format == "binary"` 且 `response` 还声明了 `properties`/`items` → parse error（binary 响应无结构）。
- `response.format == "binary"` 且 operation 有 `pagination` → parse error（binary 响应不分页）。

### 4.2 T2 — multipart 请求构造

**触发**：`resolve` 阶段，若 `op.ContentType == "multipart-form-data"`，走 multipart 分支（文件字段由 `param.format == "binary"` 识别）。

**构造**（engine 新增 `buildMultipart(op, flags) (body []byte, contentType string, err error)`）：

```go
import (
    "bytes"
    "io"
    "mime/multipart"
    "os"
    "path/filepath"
)

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
        // query/header param 不进 multipart（仍在 resolve 主流程分发到 req.Query/req.Header）
    }
    if err := w.Close(); err != nil {
        return nil, "", err
    }
    return buf.Bytes(), w.FormDataContentType(), nil
}
```

**接入 resolve**（`request.go` 末尾，bodyParams marshal 分支之后）：

```go
if op.ContentType == "multipart-form-data" {
    body, ct, err := buildMultipart(op, flags)
    if err != nil {
        return nil, err
    }
    req.Body = body
    req.ContentType = ct
    return req, nil
}
```

**`resolvedReq` 加字段** `ContentType string`（`request.go`）；`execute.go` 的 `do()` 在 `for k, v := range req.Header` 之后加：

```go
if req.ContentType != "" {
    httpReq.Header.Set("Content-Type", req.ContentType)
}
```

在 auth header 覆盖之前设（顺序：endpoint header → operation header → Content-Type → auth）；multipart 的 Content-Type 不被 auth 覆盖（auth provider 一般不碰 Content-Type，easyops-openapi 签名按实际 Content-Type 算）。

**dry-run/print-curl 预览**：`renderPreview`（`execute.go:295`）multipart 时 curl 预览改用 `-F file=@path -F kind=xxx`（需在 resolvedReq 携带 multipart 字段信息，或简化为 `--data-binary <omitted>`，T2 先简化、注释 TODO）。

### 4.3 T3 — binary 响应落盘

**触发**：`single()` 阶段，`op.Response != nil && op.Response.Format == "binary"`。

**落盘**（`single()` 开头加分支，在 `decodeLoose` 之前）：

```go
func (e *Engine) single(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options, hc *http.Client) error {
    body, status, err := e.do(ctx, req, hc)
    if err != nil {
        return err
    }
    if status >= 400 {
        return output.NormalizeAPIError(status, body)
    }
    // binary 响应：字节直写，不经 decodeLoose/Format
    if op.Response != nil && op.Response.Format == "binary" {
        return writeOutput(opts, body)
    }
    data := decodeLoose(body)
    if opts.Format == "table" {
        return output.FormatTable(opts.Out, data, responseHeaders(op))
    }
    return output.Format(opts.Out, opts.Format, data)
}

// writeOutput 写到 --output 指定文件（无则 opts.Out=stdout）。
func writeOutput(opts Options, body []byte) error {
    if opts.OutputFile == "" {
        _, err := opts.Out.Write(body)
        return err
    }
    if err := os.WriteFile(opts.OutputFile, body, 0o644); err != nil {
        return &output.APIError{Code: "output_file", Message: err.Error(), ExitCode: output.ExitParamError}
    }
    return nil
}
```

**关键**：binary 路径不经 `decodeLoose`/`Format`（直接写字节）。`iterate`（分页）路径不涉及——T1 lint 已保证 `response.format=binary` × pagination 互斥。

**文本响应 + `--output`**：T3 同时让 `output.Format`/`FormatTable` 的目标可以是文件——通过让 `globalOpts` 在 `--output` 非空且非 binary 时把 `opts.Out` 指向文件（`os.Create`）。简化实现：`globalOpts` 里 `if OutputFile != "" { f, _ := os.Create(OutputFile); opts.Out = f }`，binary 与文本统一走 `opts.Out`。T3 二选一，plan 取"统一 Out 指向文件"方案（更简，binary/文本一致）。

### 4.4 T4 — CLI flag + 文档

**flag**（`flags.go`）：

- `bindGlobalFlags` 加：`root.PersistentFlags().StringP("output", "o", "", "输出到文件（binary 响应落盘 / 文本写文件）")`。
- `globalOpts` 加：`OutputFile: strFlag(f, "output")`；且 `if opts.OutputFile != "" { f, err := os.Create(opts.OutputFile); ...; opts.Out = f }`（覆盖默认 stdout）。
- 上传文件字段：复用 `registerParams`（`param.in=formData` 自动注册成 String flag，值=文件路径），**不新增 flag**。

**`Options` 加字段**：`OutputFile string`。

**USAGE.md**（`docs/USAGE.md`）：

- §6 清单语法补 `content_type` / `format: binary` 说明 + 上传/下载示例。
- 全局 flag 表补 `--output/-o`。
- §9 已知限制：补"现支持文件上下传（multipart 上传 / binary 下载）"，移除隐含的"不支持"假设。

**examples**：新增 `examples/binary.yaml`（upload + download verb，T5 端到端用例）。

### 4.5 T5 — 端到端（test server）

`tests/integration/binary_test.go`：用 `net/http/httptest` 起 server：

- `POST /upload`：`r.ParseMultipartForm`，回 JSON `{file: <name>, size: <n>, kind: <v>}` 校验收到 multipart。
- `GET /download/{id}`：回固定二进制（如 `[]byte{0x1f, 0x8b, 0x08, 0x00, ...}` 模拟 gzip 头）。

用 `examples/binary.yaml`（base_url 指向 test server），api-cli 跑：

- 上传：`api-cli --spec binary.yaml pkg upload --file test.tar.gz --kind tool` → 校验 server 回 JSON 含正确 file/size。
- 下载：`api-cli --spec binary.yaml pkg download abc --output out.bin` → 校验 `out.bin` 字节 == server 固定二进制。

---

## 5. 数据结构变更汇总

| 类型 | 字段 | 用途 | task |
|---|---|---|---|
| `tree.Operation` | `ContentType string` | 请求体类型（json/multipart） | T1 |
| `tree.Param` | `Format string` | binary 标记（文件字段） | T1 |
| `tree.Schema` | `Format string` | binary 标记（文件响应） | T1 |
| `engine.Options` | `OutputFile string` | 落盘路径 | T3/T4 |
| `engine.resolvedReq` | `ContentType string` | 请求 Content-Type（含 boundary） | T2 |

- `spec/schema.go`：`yamlOperation`/`yamlParam`/`yamlSchema` 加对应 yaml tag。
- `spec/parse.go`：`convertOperation`/params 循环/`convertSchema` 透传；加 4 条 lint（§4.1）。
- `engine/request.go`：`resolvedReq` 加 `ContentType`；resolve 末尾加 multipart 分支。
- `engine/execute.go`：`Options` 加 `OutputFile`；`do()` 设 Content-Type；`single()` 加 binary 分支 + `writeOutput`。
- `cobracli/flags.go`：`bindGlobalFlags` 加 `--output/-o`；`globalOpts` 透传 + Out 指向文件。
- 全字段 backward compatible（零值即旧行为）。

---

## 6. 测试策略

| 层 | 用例 |
|---|---|
| **T1 单测** | schema 解析：`content_type`/`format: binary` 正确透传到 `tree.*`；lint 4 条：`content_type` 非法值报错、`format=binary`+`in≠formData` 报错、`response.format=binary`+有 properties 报错、`response.format=binary`+pagination 报错 |
| **T2 单测** | `buildMultipart`：含文件 part（filename + 内容）+ 表单字段；Content-Type 含 boundary；空 flags → 空 body；文件不存在报错；resolve 接入：`content_type=multipart` 时 `req.Body` 是 multipart、`req.ContentType` 含 boundary；`do()` 设了 Content-Type |
| **T3 单测** | `single` + `response.format=binary`：body 原样写 `opts.Out`（不经 decode）；`--output` 写文件、内容字节一致；文本响应 + `--output` 写格式化文本 |
| **T4 单测** | `bindGlobalFlags` 含 `--output/-o`；`globalOpts` 透传 `OutputFile` 且 `--output` 时 `Out` 指向文件 |
| **T5 集成** | httptest server：upload multipart 正确解析（file/size/kind）、download 二进制字节逐一致 |

---

## 7. 清单 + 文档更新

- `examples/binary.yaml`（新）：upload + download verb（T5 端到端用例）。
- `docs/USAGE.md`：§6 补 `content_type`/`format: binary` 语法 + 示例；全局 flag 表补 `--output/-o`；§9 更新二进制支持状态。
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
2. 在 worktree `worktree-api-cli-iter4`（基于 main）实施，T1（数据结构）→ T2（multipart）→ T3（binary 落盘）→ T4（flag+文档）→ T5（端到端）。T2/T3 依赖 T1 的字段；T5 依赖 T2/T3/T4。
3. T5 端到端用 `examples/binary.yaml` + `httptest.Server`，无需真实 EasyOps 环境。
