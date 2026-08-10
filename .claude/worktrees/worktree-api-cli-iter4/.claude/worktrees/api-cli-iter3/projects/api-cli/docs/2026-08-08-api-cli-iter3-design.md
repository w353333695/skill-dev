# api-cli 迭代三设计文档（P0：2 bug 修复 + LLM 抉择富化 + N 层相对 path）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-08 |
| 状态 | Draft（待实现，下一步 writing-plans） |
| 项目 | `projects/api-cli/` |
| 基线 | main HEAD `b0cae1b`（MVP + iter2 完整成果 + gofmt 已在 main） |
| 前序 | `2026-08-07-api-cli-design.md`（MVP）、`2026-08-07-api-cli-iter2-design.md`（schema 驱动 LLM + 翻页 + 体验） |
| 分支 | `worktree-api-cli-iter3` |

---

## 1. 背景与目标

iter2 完成并进入 main 后（注：iter2 成果随大文件清理重建 commit 历史进入 main，原 hash 已变，但代码内容与两个 final fix 完整在 main，11 包测试绿），实测与复盘暴露 4 个 P0 缺口：

1. **bug1 `--help-format=json` 不隐含 `--help`**：`--help-format` 是 root PersistentFlag（默认 `text`），仅 cobra 内置 `--help` 触发 `helpFunc` 时才被读取；单独给 `--help-format=json`（无 `--help`）走到 RunE → resolve 报错。必须 `--help --help-format=json` 才输出 JSON help。违背"help-format 即 help 修饰"的直觉。
2. **bug2 全局 flag 放子命令前 → root help**：`--spec xxx --endpoint backend object_instance search` 输出 root help 而非执行。根因在 `main.go` `parseTopFlags` 的 `isFlagToken` 分支（`:134`）：遇 `--endpoint` 只 `i++` 跳过本身、不吞值 → `--endpoint` 被丢、`backend` 被当成子命令起点 → `rest` 残缺 → cobra 回落 root help。`TraverseChildren=true` 没救（args 到 cobra 时已坏）。
3. **LLM 抉择弱**：MCP `tools/list` 的 tool description 仅 `verb + " " + singular`（如 `"search instance"`），不含 resource 用途链、operation 用途、行为（写/分页）→ LLM 难仅凭 description 精准抉择，需反复探查 inputSchema。
4. **N 层 path 缺陷（双重）**：`ResolveURL`（`resolve.go:41`）只拼 `base + prefix + 叶子 r.Path + op.Path`，**漏拼祖先 resource.Path**；且 `{param}` 填充只遍历 `op.Params`，**parent_key 占位（命令位置注入、不在 child 的 `op.Params`）漏填**。对嵌套 child resource（如 `cmdb.yaml` 的 `inst>relation`），URL 既缺父级段（`/instances`）又留未填的 `{instance_id}` → 调用错误。现状潜伏：实际对接的 `easyops-cmdb.yaml` 是单层 resource，未暴露。

**本迭代目标**：修 2 bug（CLI 体验）+ LLM 抉择富化（tool description 含用途链 + 行为标签）+ N 层 path 祖先链拼接（嵌套 resource URL 正确）。

---

## 2. 范围

### 2.1 P0（本迭代）

| # | 能力 | task |
|---|---|---|
| 1 | bug1 `--help-format=json` 隐含 `--help` | T1 |
| 2 | bug2 全局 flag 放子命令前生效 | T2 |
| 3 | LLM 抉择：tool description 富化 + `Resource`/`Operation` 加 `Description` + cobra Short 用 `Description` | T3 |
| 4 | N 层 path：`ResolveURL` 祖先链拼接 + `Parent` 回填 + lint | T4 |

### 2.2 不做（延后）

- **P2 生态**：OpenAPI importer / 外部 adapter 化 / 批量 create / 长任务轮询。
- **累积 Minor**：FormatTable nil 单测 / iterate `json.Unmarshal` 静默丢弃 / bumpBodyPage 文档偏差 / responseHeaders list.Items nil fallback / 网络错误 exit code 细分等。

---

## 3. 跨项约定

1. **children 仅用于 URL 真嵌套**：child 真实 URL 必须等于 parent URL + child 段。非嵌套结构（兄弟/异构）用平级顶层 resource，不用 children。children 同时决定"命令嵌套"与"URL 祖先链"，是命令层级与 URL 拼接的**唯一耦合点**。
2. **resource 的 operations（verb）层与 children 无关**：`inst` 的 CRUD（create/read/update/delete）URL 规不规范都**不影响命令层级**，用户永远是 `inst <verb>`；每个 operation 独立声明 method+path、各自拼接。
3. **description 可选、行为标签自动推断**：`Resource`/`Operation` 的 `Description` 可选（缺则回退旧文案）；行为标签（写操作/可分页）从 `method`、`Pagination` 字段自动推断，不需清单额外声明。
4. **行为标签只进 MCP description（给 LLM），不进 cobra Short**：人看 help 时从 flag 即知行为，cobra Short 聚焦用途、保持简洁。

---

## 4. P0 设计

### 4.1 T1 — bug1 `--help-format=json` 隐含 `--help`

**现状**：见 §1。`--help-format` 是 flag，不触发 helpFunc；单独给非 text 值走 RunE。

**方案**：root 加 `PersistentPreRunE`。cobra 执行流程为 `ParseFlags → help flag 判断 → PersistentPreRun → RunE`。在 `PersistentPreRunE` 内读 `help-format`，若 `!= "text"` 则调 `cmd.Help()`（复用现有 `helpFunc`，已支持 json 叶子输出 + 非叶子默认帮助），返回 sentinel error（如 `errSilentHelp`）静默退出（`SilenceErrors`/`SilenceUsage` 已设 true），跳过 RunE。

- **覆盖面**：PersistentPreRunE 被所有子命令继承；当前无子命令自定义 PersistentPreRunE，不冲突。若未来子命令需自定义，须复用此逻辑。
- **helpFunc 不动**：T1 只补"触发"环节，helpFunc 现有 json 反查逻辑照旧。
- **备选（不采用）**：在 args 阶段注入 `--help` token——hacky，且与 `parseTopFlags` 交互复杂。

### 4.2 T2 — bug2 全局 flag 放子命令前

**现状根因**：`parseTopFlags`（`main.go:108`）的 `isFlagToken` 分支（`:134`）遇非 `--spec`/`--mcp` flag 时"只 `i++` 跳过本身"，对需值的 flag（`--endpoint backend`）错误：`--endpoint` 被丢、`backend` 当子命令。

**方案**：`parseTopFlags` 改为**只消费 `--spec`/`--mcp`（含其值），遇任何其他 token（flag 或非 flag）立即停止，剩余原样交还 cobra**。依赖 root 已设的 `TraverseChildren=true`，cobra 自行解析子命令前的 persistent flag。

```
i := 0
for i < len(args) {
    a := args[i]
    switch {
    case a == "--":                  rest = args[i+1:]; return        // POSIX 分隔
    case a=="--mcp"||a=="--mcp=true":  mcpMode=true; i++
    case a=="--mcp=false":             i++
    case a=="--spec":                  specPath=args[i+1]（若存在）; i+=2 或 i++
    case strings.HasPrefix(a,"--spec="): specPath=...; i++
    default:                          rest = args[i:]; return         // 其他 token = top 段结束
    }
}
rest = nil
```

- **删除** `isFlagToken` 分支与函数（若无他用）。
- **语义依据**：`--spec`/`--mcp` 是入口选择（决定加载哪份清单 / 是否走 MCP），逻辑上必须在最前；其他全局 flag（`--endpoint`/`--insecure`/`--format` 等）交 cobra 处理。

### 4.3 T3 — LLM 抉择（description 富化）

**数据来源**：`Resource.Description` / `Operation.Description`（§5 新增），清单解析；行为标签从 `method`、`Pagination` 推断。

**MCP tool description**（替换 `mcp/server.go:58` 的 `verb + " " + singular`）：
- **祖先链用途**：从 `r` 沿 `Parent` 上溯，收集各级 `Resource.Description`（顶→叶）；某层无 Description 则用 Name，确保链不断。格式 `"A > B > C"`。
- **operation 用途**：`op.Description`，缺则回退 `verb + " " + singular`。
- **行为标签**：`[写操作]`（`method ∈ POST/PUT/PATCH/DELETE`）、`[可分页]`（`op.Pagination != nil`）。
- **拼接**：`<祖先链> · <operation 用途> [标签...]`；仅当存在标签时附标签。

```yaml
# 清单
inst:
  description: CMDB 对象实例
  operations:
    search:
      description: 按条件搜索实例（MongoDB 风格 query）
      method: POST
      path: /_search
      pagination: { type: offset, ... }
# → MCP tool description:
#   "CMDB 对象实例 · 按条件搜索实例（MongoDB 风格 query） [写操作] [可分页]"
```

**cobra Short**（`build.go` `desc()` + `operationCmd`）：
- resource Short：`r.Description` 非空则用它（**不再加"资源"后缀**），否则回退旧 `desc()`。
- operation Short：`op.Description` 非空则用它，否则回退 `verb + " " + singular`。
- root Short 不变（`Service` 本迭代不加 Description 字段）。
- **行为标签不进 cobra Short**（约定 §3.4）。

**`--explain`**（`build.go explainCmd`）：输出 map 补 `resource_description` / `operation_description`，给人/LLM 更完整语义。

### 4.4 T4 — N 层 path（祖先链拼接 + 占位填充修复）

**Parent 回填**：`convertResource`（`spec/parse.go`）递归 children 时 `child.Parent = r`。

**ResolveURL 改造**（`resolve.go:30`）—— 同时修两个缺陷：
- **祖先链拼接**：新增 `ancestorPaths(r *Resource) []string`，沿 `r.Parent` 上溯到顶层、收集各 `Resource.Path`、反转为顶→叶；拼接改为 `joinPath(ep.BaseURL, ep.PathPrefix, 祖先链顶→叶…, r.Path, op.Path)`。
- **parent_key 占位填充**（现状 bug）：现状 `{param}` 填充只遍历 `op.Params`（`resolve.go:43`），而 `parent_key`（如 `instance_id`）由命令位置注入进 `vals`、**不在 child operation 的 `op.Params` 里**（见 `cmdb.yaml` `relation.read` 只有 `id`）→ 占位 `{instance_id}` 漏填。T4 改：**必填校验仍遍历 `op.Params`**（保留 path 参数 required 检查），**填充阶段改为遍历 `vals`**——对每个 `vals[name]=v` 做 `strings.ReplaceAll(full, "{"+name+"}", v)`，parent_key 注入值即可命中祖先链/`r.Path` 里的占位。
- **签名不变**（仍传单个 `r`）→ engine 调用方（`request.go:32`）零改动。

**lint**（`spec.Parse` 内）：对每个 child resource `c`（`c.Parent != nil`），设 `pk = c.Parent.ParentKey`；若 `pk != ""` 且 `c.Path` 不含 `{<pk>}` 占位 → parse warning。catch "child 漏占位 → URL 静默缺父 id"。

**清单 path 约定**（写入文档）：child 的 `Path` 写**自己段 + `{parent_key}` 占位**，不含父级纯段（如 `/{instance_id}/relations`，父级 `/instances` 由祖先链补）。

---

## 5. 数据结构变更汇总

| 类型 | 字段 | 用途 | task |
|---|---|---|---|
| `tree.Resource` | `Description string` | resource 用途 | T3 |
| `tree.Operation` | `Description string` | operation 用途 | T3 |
| `tree.Resource` | `Parent *Resource` | 祖先链上溯指针 | T4 |

- `spec/schema.go`：`yamlResource`/`yamlOperation` 加 `description` yaml tag。
- `spec/parse.go`：`convertResource`/`convertOperation` 拷贝 `Description`；`convertResource` 回填 `child.Parent = r`。
- 全字段 backward compatible（零值即旧行为）。

---

## 6. 测试策略

| 层 | 用例 |
|---|---|
| **T1 单测** | `--help-format=json` 单独给叶子命令 → 输出 JSON help、不 RunE、不 resolve 报错；默认 `text` 行为不变；非叶子命令 `--help-format=json` 走默认帮助 |
| **T2 单测** | `parseTopFlags`：`--spec a --endpoint b sub`→rest=`[--endpoint,b,sub]`；`--spec a sub`→rest=`[sub]`；`--mcp --spec a`→mcpMode+specPath；`--` 分隔符；端到端 `--spec x --endpoint y inst read` 跑通（mock） |
| **T3 单测** | MCP description：多层 children + Description 祖先链串联；无 Description 回退 Name；行为标签（写/分页）正确；cobra Short 用 Description（无则回退）；`--explain` 含 description |
| **T4 单测** | `ResolveURL`：多层 child URL 含全部祖先段 + parent_key 占位填充（vals 遍历，非仅 op.Params）；lint：child `c.Path` 缺 `{c.Parent.ParentKey}` 占位 → 警告 |
| **集成** | `cmdb.yaml` 嵌套 `inst>relation`：`relation read` URL 正确含 `/instances/{id}/relations`；MCP `tools/list` description 含链+标签；`easyops-cmdb` search description 富化 |
| **契约** | MCP tool description 结构（`链 · 用途 · [标签]`）；`ResolveURL` 多层 URL 正确 |

---

## 7. 清单 + 文档更新

- `examples/cmdb.yaml`（有 children）：resource/operation 补 description（验证 T3 + T4 端到端）。
- `examples/easyops-cmdb.yaml`（单层）：`object_instance`/`search` 补 description（验证 T3）。
- 本 design：`projects/api-cli/docs/2026-08-08-api-cli-iter3-design.md`。
- **不破坏现有清单**：description 可选；T4 方案 A 不改 path 写法。

---

## 8. 文档位置

- 本 spec：`projects/api-cli/docs/2026-08-08-api-cli-iter3-design.md`
- plan：`projects/api-cli/docs/2026-08-08-api-cli-iter3-plan.md`（writing-plans 产出）
- 遵循项目文档隔离（AGENTS.md §1：项目内 docs/）。

---

## 9. 实施前置

1. main（`b0cae1b`）干净，api-cli 11 包测试绿（已验证）。
2. 在 worktree `worktree-api-cli-iter3`（已基于 main）实施，T1→T2→T3→T4 串行（T3/T4 都改 `tree.Resource`）。
3. 实施时更新 `examples/cmdb.yaml` + `easyops-cmdb.yaml` 的 description，作为端到端验证用例。
