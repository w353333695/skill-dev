# api-cli 迭代二设计文档（P0+P1：schema 驱动 LLM + 真实翻页 + 体验打磨）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-07 |
| 状态 | Draft（待实现，下一步 writing-plans） |
| 项目 | `projects/api-cli/` |
| 基线 | main HEAD `6424f90`（MVP + cookie/openapi/endpoint.Host 已 merge） |
| 前序 | `2026-08-07-api-cli-design.md`（MVP 设计）、`2026-08-07-api-cli-plan.md`（MVP 计划） |

---

## 1. 背景与目标

MVP 完成后真实对接 EasyOps 暴露三类缺口：

1. **LLM 看不到 body 嵌套结构**：inputSchema 只从扁平 params 生成，`operation.Body` 声明了但没用 → LLM 无法正确构造复杂请求（如 EasyOps 的 `$and/$or` query）。
2. **LLM/人看不到响应字段含义**：响应透传，输出原样 JSON → LLM 拿到 JSON 全靠字段名猜。
3. **真实 API 的 page 在 body**（EasyOps/ES 等），但分页引擎只支持 query → 拉不了全量，分页形同半残。

**本迭代目标**：schema 驱动 LLM 深度理解（input+output 嵌套）+ 真实翻页 + 体验打磨，让 api-cli 对 LLM（MCP）真正可用。

---

## 2. 范围

### 2.1 P0（真实刚需）

| # | 能力 | 说明 |
|---|---|---|
| 1 | inputSchema 展开嵌套 body | `operation.Body` → inputSchema `_body`（完整嵌套 JSON Schema）；MCP args `_body` 直传请求 body |
| 2 | outputSchema 完整 response Schema | `operation.Response` → MCP outputSchema + `--explain` + table 中文表头 |
| 3 | 分页 page-in-body | `pagination.page_in: body`，翻页改 body 不改 query |
| 4 | 分页 --format | table/yaml 缓冲全部 items 再 Format（json 保持流式 NDJSON） |

### 2.2 P1（体验/合规）

| # | 能力 | 说明 |
|---|---|---|
| 5 | dry-run 移 gateWrite 前 | 安全预览不被写闸门拦 |
| 6 | 全局 flag 任意位置 | cobra `TraverseChildren=true` |
| 7 | --timeout | `Options.Timeout` → `http.Client.Timeout` |
| 8 | MCP inputSchema.required | path/body required 聚合成 required 数组 |

### 2.3 不做（后续迭代）

OpenAPI importer / 外部 adapter 化 / 批量 create / 长任务轮询 / 静态代码生成 / 并发分页 / 非 Go adapter SDK（见 MVP spec §16）。

---

## 3. 跨项约定

1. **`_body` 字段名**：body 在 inputSchema / MCP args 的统一字段。path/query 参数扁平在外层（`object_id`、`page` 等），body 嵌套对象放 `_body`。人和 LLM 都用这个约定。
2. **`description` + `example` 是 LLM 理解核心**：尤其动态结构（MongoDB 风格 `$and/$or`、字段名任意），纯 JSON Schema 表达不全，靠 `description` 说规则 + `example` 给完整样例。清单作者必须写好这俩。

---

## 4. P0 设计

### 4.1 inputSchema 展开嵌套 body

**数据结构变更**：
- `tree.Schema` 加 `Example any` + `AdditionalProperties *bool`（动态结构允许任意 key）。

**inputSchema 生成**（`cobracli/help.go` + `mcp/server.go`）：
- 读 `operation.Body`（`*tree.Schema`）→ 递归转 JSON Schema → 放 `inputSchema.properties._body`（完整嵌套展开）。
- path 参数扁平放 `inputSchema.properties`（如 `object_id`），与 `_body` 并列。

**MCP tools/call**（`mcp/server.go` toolsCall）：
- args 里的 `_body`（`map[string]any`）→ `json.Marshal` → 请求 body bytes。
- 其余 args（path/query）按现有 splitArgs 逻辑分。

**engine**（`engine/execute.go`）：
- 接受 body 来源统一：MCP `_body`（marshal 后）/ 人 `--body-file` / 单层 body param flag，都汇到 `req.Body`。

**cobracli `--help-format=json`**：同步含 `_body` 嵌套 schema（LLM 发现命令时看到完整 body 结构）。

### 4.2 outputSchema 完整 response Schema

**数据结构变更**：
- `tree.Operation` 加 `Response *Schema`（复用 Schema 类型，嵌套）。

**spec 解析**（`spec/schema.go` + `spec/parse.go`）：
- operation 加 `response:` 字段，转 `*tree.Schema`。

**MCP outputSchema**（`mcp/server.go`）：
- tool 定义加 `outputSchema`（读 `operation.Response` → JSON Schema）。

**`--explain`**（cobracli 新子命令）：
- `api-cli explain <resource> <verb>`：输出该 operation 的 input + output schema（人读，含 description/example）。

**table 中文表头**（`output/format.go`）：
- table 输出用 Response 字段的 `description` 做表头；无 description 回退字段名。

### 4.3 分页 page-in-body

**数据结构变更**：
- `tree.Pagination` 加 `PageIn string`（`"query"` 默认 / `"body"`）。

**paging 引擎**（`paging/engine.go`）：
- `DoFunc` 协议扩展：接 body bytes（不只 query map），签名改为 `func(ctx, body []byte, query map[string]string) ([]byte, error)`。
- `planNext` 按 `PageIn` 分支：
  - `query`（默认）：page 放 query（当前行为）。
  - `body`：翻页时 unmarshal body → `body[page_param]` 自增 → marshal 回去（不动 query）。
- `Iter` 把 pagination 的 PageIn/PageParam/SizeParam 传进翻页逻辑。

**清单声明示例**：
```yaml
pagination:
  type: offset
  page_in: body            # 新字段：page 在 body（默认 query）
  items_path: data.list
  page_param: page
  size_param: page_size
  size: 20
```

### 4.4 分页 --format

**engine iterate**（`engine/execute.go`）：
- `format == "json"`（默认）：流式 NDJSON（大列表不爆内存，当前行为保留）。
- `format == "table" | "yaml"`：缓冲全部 items 到 slice → `output.Format` 一次输出。
- 判断：`opts.Format` 分支。

---

## 5. P1 设计

### 5.1 dry-run 移 gateWrite 前
execute 流程调整：`resolve → body-file → dry-run/print-curl（拦截）→ gateWrite → auth → 选 client → 分页/单次`。dry-run 是安全预览（不发请求），不该被写闸门拦（非 TTY 下 `update --dry-run` 当前竟要 `--yes`）。

### 5.2 全局 flag 任意位置
root 命令 `TraverseChildren: true`（cobra）。`--insecure`/`--spec` 等全局 flag 放最前（`api-cli --insecure ... search`）也生效，符合"全局 flag 放最前"的直觉。

### 5.3 --timeout
- `engine.Options.Timeout time.Duration`。
- `http.Client{Timeout: opts.Timeout}`（New 时默认 0=不限；Execute 按 opts 选 client 时设 Timeout，或 insecure/secure client 各带 Timeout）。
- cobracli `--timeout`（pflag Duration，如 `--timeout 30s`，默认 0）。

### 5.4 MCP inputSchema.required
inputSchema 生成时：path 参数的 required + body schema 的 `required` 数组 → 聚合成 `inputSchema.required`（去重）。LLM 据此知道哪些参数必填。

---

## 6. 数据结构变更汇总

| 类型 | 字段 | 用途 |
|---|---|---|
| `tree.Schema` | `Example any` | 动态结构示例（LLM 理解） |
| `tree.Schema` | `AdditionalProperties *bool` | 允许任意 key（MongoDB query 等） |
| `tree.Operation` | `Response *Schema` | 响应 schema（outputSchema） |
| `tree.Pagination` | `PageIn string` | page 在 query 还是 body |
| `engine.Options` | `Timeout time.Duration` | HTTP 超时 |

`spec` schema.go 对应加 yaml tag；parse.go 转换。

---

## 7. 测试策略

| 层 | 范围 |
|---|---|
| **单测** | Schema example/additionalProperties 序列化 / inputSchema 嵌套生成（_body 展开）/ outputSchema 生成 / page-in-body 翻页（body.page 自增）/ format 分支（json 流式 vs table 缓冲）/ dry-run 在 gateWrite 前 / TraverseChildren / timeout 生效 / required 聚合 |
| **集成** | easyops-cmdb search 走 MCP（_body 嵌套传 query）+ page-in-body 翻多页 + table 中文表头 + `--explain` 输出 |
| **契约** | MCP tool inputSchema（含 _body/required）+ outputSchema 结构正确 |

mock server 需扩展：page-in-body 的分页响应（page 在请求 body）。

---

## 8. 文档位置

- 本 spec：`projects/api-cli/docs/2026-08-07-api-cli-iter2-design.md`
- plan：`projects/api-cli/docs/2026-08-07-api-cli-iter2-plan.md`（writing-plans 产出）
- 遵循项目文档隔离（AGENTS.md §1：项目内 docs/）。

---

## 9. 实施前置

1. main 干净（`6424f90`），测试绿（11 包）。
2. 走 feature 分支 `api-cli-iter2`，subagent-driven 逐 task 实施（P0 先、P1 后）。
3. 实施时更新 examples/easyops-cmdb.yaml 的 search（补完整嵌套 body schema + response schema + page_in: body），作为端到端验证用例。
