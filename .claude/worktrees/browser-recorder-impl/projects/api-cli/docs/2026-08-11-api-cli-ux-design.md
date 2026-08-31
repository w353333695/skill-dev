# api-cli UX 改造设计（查询体验 + 错误可见性 + 完整预览）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-11 |
| 状态 | 定稿—待实现 |
| 项目 | `projects/api-cli/` |
| 基线 | main HEAD `7f74612`（iter4 已 merge，无并行 worktree） |
| 前序 | MVP `2026-08-07-api-cli-design.md`、iter2 `…-iter2-design.md`（schema 驱动 LLM+翻页+体验）、iter3 `2026-08-08-api-cli-iter3-design.md`（2 bug+LLM 抉择+N 层 path）、iter4 `2026-08-10-api-cli-iter4-design.md`（二进制上下传） |
| 来源 | 2026-08-11 用 api-orchestrator 查 easyops cmdb 主机数，端到端暴露 7 个 UX 痛点 |

---

## 1. 背景与目标

一次"统计 org 18832008 下 HOST 模型实例数"的简单查询，本应 1 次调用出结果，实际花了 9 次 bash 试错。根因不在调用方，而在 api-cli 自身的反馈缺失与参数入口模糊。本次改造消除这 7 个痛点：

1. **body 强制落盘**：仅 `--body-file`，无内联/stdin → 一行 body 被迫写临时文件，且因 cwd/相对路径污染了 skill 目录。
2. **分页吞 `data.total`**：`has_paging` operation 把 `data.list` 流式逐行输出，`data.total` 被丢 → 统计类查询被迫 `--all` 拉全计数。
3. **query 参数静默失效**：`list --q 主机` 既不报错也不进 URL。
4. **text help 不列 verb 参数**：`search --help` 不显示 `object_id` 是 positional、body 走 `--body-file` → 新手只能试错。
5. **`--print-curl` 输出不完整**：缺 Host/Content-Type/auth → 拿输出手动 curl 必失败。
6. **未知参数静默**：cobra `SilenceErrors+SilenceUsage`，错误只写 stderr JSON，盯 stdout 等于没有。
7. **`--all` 硬上限不透明**：`MaxItems=10000/MaxPages=1000`，触顶无提示。

**目标**：让简单查询一步到位、错误即时可见、预览完整可复现。

## 2. 约束与决策（评审拍板）

| 决策 | 选择 | 理由 |
|---|---|---|
| 兼容策略 | **统一改默认** | 7 点都改默认行为，依赖方（api-orchestrator）同步适配；⑥⑤本质是 bug 该修，②默认带 total 更友好 |
| ⑤ auth 凭证 | **默认遮蔽 + `--reveal-auth`** | Host/CT 等非敏感头全显；auth 值 `<redacted>`，`--reveal-auth` 显真值；防凭证泄露到工单/日志 |
| 实施切分 | **方案 A（按冲突/依赖）** | 批1 零 iter4 冲突先行；批2 集中啃 iter4 热点；批3 spec 收尾 |

## 3. 改造点总览

| # | 改造点 | 现状（file:line） | 批次 | iter4 冲突 |
|---|---|---|---|---|
| ① | body inline/stdin | `flags.go:106` 仅 `--body-file`；`execute.go:87-97` 无 stdin | 批2 | 同块（iter4 加 2 行 CT-clear） |
| ② | 分页保留 total | `paging/engine.go:66` 丢信封；Item struct 19-23 | 批1 | 无 |
| ③ | query 正确传递 | `flags.go registerParams/bag.values` + `request.go:55-63` | 批3 | 无 |
| ④ | text help 列参数 | `help.go:66` 回落 cobra 模板 | 批1 | 无 |
| ⑤ | print-curl 完整 | `execute.go:316-339` renderPreview | 批2 | **真冲突**（iter4 加 isMultipart） |
| ⑥ | 错误可见化 | `build.go:34-35` SilenceErrors | 批1 | 无 |
| ⑦ | --all 触顶提示 | `paging/engine.go:42-47,84-86` | 批1 | 无 |

净结论：仅 ⑤ 真冲突，① 同块衔接，②③④⑥⑦ 对 iter4 零依赖。

## 4. 详细设计

### 4.1 批1（②④⑥⑦，零 iter4 冲突）

**② 分页保留 `data.total`**
- 现状：`paging/engine.go:66` `gjson.GetBytes(respBody, pg.ItemsPath).Array()` 只抽 items，整个信封（含 `data.total`）丢；`Item` struct（19-23）仅 ID/Raw/Err。
- 做法：
  - `paging.Iter` 从信封抽 total——`total_path` 默认 = `<items_path 父>.total`（`data.list`→`data.total`），可被 `operation.pagination.total_path` 覆盖。
  - `Item` 加 `Total *int`（仅首条带指针）。
  - `execute.go iterate` 把 total 打到 **stderr**（`{"_meta":{"total":N,"page_size":...}}`）；stdout 纯 NDJSON item 不变 → 向后兼容。
- 测试：单测 `Iter` 传 total；集成测分页 verb stderr 有 total。

**④ text help 列 verb 参数**
- 现状：`help.go:66` text 分支回落 cobra 默认模板；path 参数被 `registerParams` 跳过不注册 → 不列。
- 做法：text 分支调 `locate` 拿 op（与 `emitHelpJSON` 同源），渲染分类块——`Path params (positional, in order)` / `Query params` / `Body (指明 --body-file|--body)`；`build.go operationCmd.Use` 从裸 `verb` 改 `verb [args]`。
- 测试：golden test 各 verb text help。

**⑥ 错误可见化**
- 现状：`build.go:34-35` `SilenceUsage+SilenceErrors`；错误走 `main.go:28 output.PrintError` 以 JSON 写 stderr。
- 做法：保留 `SilenceUsage`（不刷屏）；错误默认打**人类可读到 stderr**（`error: <msg>`），仅 `--json` 模式输出 JSON；自定义 cobra `FlagErrorFunc` 让 unknown flag 也走人类可读 → `--q`（未声明）报 `error: unknown flag --q; verb 'list' declares no query param (see --help)`。
- 测试：未知 flag / 必填缺失 → stderr 可读错误 + exit code。

**⑦ `--all` 触顶提示**
- 现状：`paging/engine.go:42-47` MaxItems=10000/MaxPages=1000；触顶（84-86）`return` 无提示；预留 `ExitPagingOver=4`（errors.go:15）从未使用。
- 做法：`Iter` 触顶返回 `hitCap` 信号；`iterate` 收到 → stderr `warning: hit paging cap (MaxItems=10000), results may be incomplete` + exit code 4（复用 `ExitPagingOver`）。
- 测试：mock 超 MaxItems 源 → warning + exit 4。

### 4.2 批2（①⑤，衔接 iter4 热点）

**① body inline / stdin**
- 现状：`flags.go:106` 仅 `--body-file`；`execute.go:87-97` `os.ReadFile`，传 `-` 当文件名报 not exist。iter4 在 87-106 块加 2 行 CT-clear。
- 做法：
  - 加 `--body string` flag；优先级 `--body` > `--body-file` > stdin（`--body-file -`）。
  - `--body` → 复用 MCP 的 `BodyBytes` 通道（execute.go:32,102-106）。
  - `--body-file -` → `io.ReadAll(os.Stdin)`。
  - `--body` 与 `--body-file` 互斥校验。
  - 衔接 iter4：inline/stdin 分支处理 ContentType（JSON→`application/json`），与 iter4 CT-clear 协调（重读 87-106 块合并，不按旧版 diff）。
- 测试：`--body '{...}'`、stdin、互斥报错、CT 正确。

**⑤ print-curl 完整 header（默认遮蔽 auth）**
- 现状：`renderPreview`（execute.go:316-339，iter4 加 isMultipart）只遍历 `req.Header`（org/user）；缺 Host（`resolvedReq.Host` 独立字段）、Content-Type（`resolvedReq.ContentType`）、auth（`auth.Apply` 在 122-139，dry-run 在 110-113 提前 return 跳过）。
- 做法：
  - auth.Apply 提前到 preview 之前——dry-run/print-curl 分支也跑 auth（不再在 execute.go:110-113 提前 return 跳过），让 renderPreview 看到完整鉴权头。
  - renderPreview 补：Host（`-H 'Host: <host>'`）、Content-Type、auth 头（默认 `<redacted>`）。
  - 新 flag `--reveal-auth`：显真值。
  - 衔接 iter4：保留 isMultipart 省略 body 分支。
  - 副作用 guard：cookie/openapi AK:SK 无副作用；oauth2 可能触发 token 刷新——dry-run 模式跳过实际刷新（auth provider 加 `DryRun bool` 或只取已加载凭证）。
- 测试：print-curl 含 Host/CT、auth 默认 `<redacted>`、`--reveal-auth` 显真值、isMultipart 仍省略 body。

### 4.3 批3（③ query 正确传递）

**矛盾**：spec（`easyops-cmdb.yaml`）声明了 list 的 query 参数 q/page（`--help-format json` 可见），但实测 `--q 主机` 静默不进 URL。说明 `registerParams→bag.values→resolve` 链路有断点，或 `--q` 根本没注册成功（被 ⑥ SilenceErrors 掩盖）。

- 落点：`cobracli/flags.go`(registerParams/bag.values) + `engine/request.go resolve`(55-63) + ⑥ 配合。
- 做法：
  - 实测定位断点：registerParams 是否注册 `q`？bag.values 收集到没？resolve `case "query"` 执行没？
  - 修复断点（flag 名映射 / positional 抢占 / 注册失败）。
  - spec 端：核实 list/search verb 的 query 参数声明完整（`platforms/demo/*.yaml`，**onboarding 模式 + lint**）。
  - 依赖：⑥ 改完后未声明参数立即报可见错误，辅助定位。
- 测试：`list --q 主机` → URL 含 `?q=主机`；未声明参数 → 可见错误。

## 5. 横切

**测试策略**：每点单测（paging/flags/help/output 包）+ httptest 端到端（iter4 T5 先例）+ golden test（help、print-curl）+ 现有 `smoke_test.go` 不破。

**文档**：更新 `projects/api-cli/docs/USAGE.md`——新增 `--body`/`--reveal-auth`/stderr total/help 新格式/错误格式。

**api-orchestrator 适配**（统一改默认的代价）：
- `SKILL.md` 执行段：`--body` 可用、print-curl 默认遮蔽、错误可见、total 在 stderr。
- 解析 api-cli 输出的脚本：适配 stderr total / 人类可读错误。
- platforms 资料：批3 spec 补声明（onboarding + lint）。

## 6. 不做（YAGNI）

- **stdout 末尾带 total**：会破 NDJSON 管道，stderr 已够。
- **交互式 tty 检测**（tty 时 stdout 显示 summary）：复杂，YAGNI。
- **print-curl 的 `--resolve` 替代 `-H Host`**：`-H 'Host:'` 更直观够用。
- **oauth2 dry-run 刷新的完整方案**：easyops 不涉及，guard 即可，完整方案延后。
- **常用模型速查表入 README**：动态数据会腐烂，靠 ③ 修复 query 查询替代。
