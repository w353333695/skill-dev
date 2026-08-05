# DAG 格式契约（dag schema）

DAG 是 LLM 生成的调用计划，verify_dag 校验它，execute_dag 执行它。单一真相源是 `api_console/schema/dag.py`。

## 完整结构

```json
{
  "goal": "找出关联处理人字段的领域模型",
  "steps": [
    {
      "id": "s1",
      "card": "searchStandardField",
      "purpose": "查处理人字段",
      "params": {"q": "处理人", "page": 1, "pageSize": 100},
      "output": {"bind": "fields", "from": "list_full"},
      "assert": {"fields.length > 0": "未找到处理人字段"},
      "depends": []
    },
    {
      "id": "s2",
      "card": "searchDomainModel",
      "purpose": "查关联这些字段的模型",
      "depends": ["s1"],
      "params": {"standard_field": "${join(s1.fields.instanceId, ',')}"},
      "output": {"bind": "model_ids", "from": "list_ids"}
    },
    {
      "id": "s3",
      "card": "getDomainModel",
      "purpose": "取每个模型详情",
      "depends": ["s2"],
      "foreach": "${s2.model_ids}",
      "params": {"modelId": "${item}"},
      "output": {"bind": "details", "from": "detail"}
    }
  ],
  "result": "${s3.details}"
}
```

## step 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | step 唯一标识（如 s1/s2） |
| `card` | 是 | 卡片 name（须在 registry） |
| `purpose` | 否 | 人读说明 |
| `params` | 否 | 请求参数，值可含 `${}` 表达式或常量 |
| `output` | 否 | `{bind, from}`：bind=本步输出变量名，from=卡片 outputs 锚点名（可为空串 `""`，见「output.bind / from」节） |
| `assert` | 否 | `{condition: message}`，条件不满足终止 DAG |
| `foreach` | 否 | `${}` 引用上游数组，对每个元素执行一次 |
| `depends` | 否 | 依赖的 step id 列表（拓扑序由它推出） |

## `${}` 表达式（4 种合法形式，严格白名单）

| 形式 | 含义 | 例 |
|---|---|---|
| `${<step>.<bind>}` | 取上游 step 的 bind（整体） | `${s1.fields}` |
| `${<step>.<bind>.<field>}` | bind（对象数组）投影取字段，返回数组 | `${s1.fields.instanceId}` → `["id1","id2"]` |
| `${item}` | foreach 当前项（仅 foreach step 内） | `${item}` |
| `${join(<arr>, '<sep>')}` | 数组 → 字符串 | `${join(s1.fields.instanceId, ',')}` → `"id1,id2"` |

**其余形式一律拒绝**（防 LLM 越界）：
- `${s1}`（无 bind）❌
- `${s1.a.b.c}`（层级过深）❌
- `${__import__('os')}`（越界）❌
- `${s1.fields..x}`（双点）❌
- `${join(s1.fields)}`（缺 sep）❌
- `${join(s1.fields, x)}`（sep 非字面量）❌

## output.bind / from

- `bind`：本步输出存入 context 的变量名（下游 `${本step.bind}` 引用）
- `from`：选卡片的哪个 outputs 锚点（**不写 jsonpath**，写锚点名如 `list_full`/`instanceId`/`detail`）
- `from` 可为空串 `""`：表示绑定整个 data，用于文件下载/整体绑定场景（如 export 下载卡片无 outputs 时）；空 anchor 跳过规则 9 的锚点存在性校验
- bind 全局唯一（不同 step 不能重名）

## assert（断言，非分支）

```json
"assert": {"fields.length > 0": "未找到处理人字段"}
```

- MVP-1 仅支持 `<bind>.length > 0` 形式
- 条件不满足 → 立即终止 DAG，抛 ExecutionError（带 message）
- **不是 if/else 分支**——是"条件必须满足否则停"

> 分支（"复用 or 新建"等二选一）由 step.when 实现，见下文「when」节。assert 仅作终止语义。

## foreach（对数组逐个调用）

```json
"foreach": "${s2.model_ids}",
"params": {"modelId": "${item}"}
```

- foreach 引用上游 bind（须是数组）
- 每个元素执行一次，`${item}` 是当前元素
- 并发执行（默认 concurrency=5）
- 结果聚合为本步 output（数组）

## MVP-1.5 写编排

DAG 可选 `side_effect=create/update/delete` 的写卡片。`verify_dag` 不再拒绝写卡片——
规则 6 改为把 `has_write=True` 写进 `VerifyReport`（返回值含 `has_write` 字段，LLM 须把它
透传给 execute）。

**确认闸**（execute 内置）：`execute_dag.execute(dag, cards, adapter, manifest, contracts=None, has_write=False, yes=False, input_fn=input)`——
`has_write=True` 且 `yes` 非 True 时，execute 先打印写计划 + 回滚预案，等用户输入 `y` 才继续；
非 `y` 返回 `None`（取消）。`yes=True` 跳过确认闸（CI/批量场景）。execute 无 CLI 包装，LLM 经
Python 调用传参。

**回滚**：写步骤执行成功后被记入 `executed_writes`；任一下游步骤失败（抛 `ExecutionError`）时，
execute 按卡片 `rollback` 声明对 `executed_writes` **逆序回滚**，回滚日志挂
`ExecutionError.rollback_log`（失败时）/ `ExecutionResult.rollback_log`（成功时空 list）。
卡片未声明 `rollback` 则静默跳过；回滚本身 best-effort（回滚调用失败不中断，记 `status: "failed"`）。

> foreach 写步骤当前不参与回滚（bound 是 list，best-effort 跳过），留后续 MVP 补齐。

## when（条件跳过）

step 可选 `when` 字段（字符串），条件为假则跳过该步（记入 `ExecutionResult.skipped`，不写 context，
下游 `${本步.bind}` 引用按缺失键处理 → null）。空串 = 无条件执行。

**仅四种受批准形式**（`eval_when` 用正则预校验，其余形式抛 `ValueError` 被 verify 规则 11 拒绝）：

| 形式 | 为真（执行）条件 |
|---|---|
| `${bind} == null` | bind 为 null / 不存在 |
| `${bind} != null` | bind 已存在（非 null） |
| `${bind} == '字面量'` | bind 等于字面量（单引号） |
| `${bind}` | bind 为真值 |

其中 `${bind}` 是任意 `${...}` 表达式（如 `${s0.found}` / `${s0.found.state}`）。

**互补 when 二选一示例**（"不存在则新建 / 存在则更新"）：

```json
{
  "steps": [
    {"id": "s0", "card": "getForm", "params": {"formId": "f1"},
     "output": {"bind": "found", "from": "detail"}},
    {"id": "s1", "card": "createForm", "depends": ["s0"],
     "params": {"name": "f1"},
     "when": "${s0.found} == null"},
    {"id": "s2", "card": "updateForm", "depends": ["s0"],
     "params": {"formId": "${s0.found.formId}"},
     "when": "${s0.found} != null"}
  ]
}
```

`s1` 与 `s2` 互补 when：`s0.found` 存在则 `s1` 跳过、`s2` 执行（更新）；不存在则 `s1` 执行（新建）、`s2` 跳过。

## verify_dag 12 条校验（5/8 合入 3）

| 规则 | 内容 |
|---|---|
| 1 卡片存在性 | card 在 registry/_index.yaml |
| 2 依赖闭环 | depends 无环（DFS 三色标记） |
| 3 参数引用合法 | `${}` 引用的 step/bind 存在（含表达式 parse） |
| 4 必填参数覆盖 | params 覆盖 card.request.required |
| 5 类型粗校 | 合入规则 3 |
| 6 写卡片标记 has_write | 写卡片不拒绝，置 `VerifyReport.has_write=True` |
| 7 assert 语法 | `<bind>.length > 0` 合法 + bind 存在 |
| 8 foreach 类型 | 合入规则 3 |
| 9 锚点存在 | output.from 在 card.outputs 有定义（空串 `""` 除外——表示绑定整个 data，用于文件下载/整体绑定场景） |
| 10 bind 重名 | 不同 step 的 output.bind 不重名 |
| 11 when 语法 | step.when 若非空，须为四种受批准形式（见「when」节） |
| 12 rollback 引用 + 参数完备性 | rollback.api 须在 registry 存在；每条 `from_output` 须等于本步 output.bind 或锚点名；`params.param_key` 集合须 == 目标卡片 path 占位符集合（多参数 path 如 `/form/{formId}/version/{versionId}` 须全覆盖，防回滚静默失败） |

## execute_dag 执行流程

按拓扑序执行每个 step：
1. 解析 params 的 `${}`（从已执行 step 的 context 取值）
2. 若 foreach：对 array 逐个实例化 params，并发调用
3. 发 HTTP（cookie 注入，url = api_base + card.path，path 参数替换）
4. 校验响应（HTTP 200 + body.code == 0）
5. 按 output.from（锚点名）查 card.outputs 取 jsonpath → extract_jsonpath 提取
6. assert 校验，失败终止
7. 写 context[step_id][bind] = 提取值

全部完成 → 按 `result` 的 `${}` 聚合输出。

## 错误分类（6 类）

| 错误层 | 例子 | 处理 |
|---|---|---|
| DAG 生成错 | 选了不存在的卡片/有环 | verify 拒绝 → 回传 LLM 重试（上限2）→ 仍失败终止 |
| assert 断言失败 | "未找到处理人字段" | 立即终止（预期内的查不到，非 bug） |
| HTTP 错误 | 超时/500 | execute_dag 重试（指数退避，上限3）→ 仍失败终止 |
| 业务码错 | body.code != 0 | 不重试 → 终止，记录 codeExplain/error |
| 鉴权失效 | 401/302→login | 立即终止，提示重提 cookie |
| 结果提取失败 | 锚点抽空 | 终止，提示"卡片 outputs 锚点可能过时"（卡片质量问题） |
