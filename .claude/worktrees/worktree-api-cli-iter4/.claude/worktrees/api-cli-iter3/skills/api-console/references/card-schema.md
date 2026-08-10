# 卡片格式契约（card schema）

卡片是 registry 的核心单元——LLM 选它、verify/execute 执行它。单一真相源是 `api_console/schema/card.py` 的 `Card` dataclass。

## 完整字段（以 createDomainModel 为例）

```yaml
name: createDomainModel                  # operationId，全局唯一
module: domain_model                     # 功能域（见下）
method: POST
path: /api/flowable_service/v1/domain_model        # 已归一化（brace style）的后端真实路径
gateway_path: /next/api/gateway/logic.flowable_service/api/flowable_service/v1/domain_model  # 前端原始，调试用
service: logic.flowable_service          # 后端服务名（带 logic. 前缀，与契约一致）
auth: session_cookie                     # 鉴权类型（对应 manifest.auth_type）
side_effect: create                      # read | create | update | delete
path_source: backend_contract            # backend_contract | gateway_strip | frontend_raw
path_confidence: high                    # high | medium | low

tags: [领域模型, 创建]                    # LLM 关键词定位
summary: 新建领域模型并关联标准字段        # 一句话用途
description: |                           # 详细说明
  创建领域模型，需指定 key/name 并关联标准字段。

request:                                 # 契约（确定性从 openapi 抽）
  required: [key, name, standardFieldIds]
  properties:
    key: {type: string, desc: "唯一标识"}
    standardFieldIds: {type: array, desc: "关联标准字段 instanceId 列表"}

outputs:                                 # 预定义锚点（确定性提取规则）
  instanceId: {jsonpath: $.data.instanceId, desc: "新建资源 id"}
  detail: {jsonpath: $.data, desc: "详情全量"}

requires:                                # 前置条件（LLM 补，低置信）
  - "standardFieldIds 每个 id 须是已存在的标准字段 instanceId"

rollback:                                # 回滚引用（MVP-1.5 用，多参数版）
  api: deleteDomainModel                 # 回滚目标卡片名
  params:                                # 参数映射列表（≥1 条）
  - param_key: modelId                   # 目标卡片参数名（path 占位符名）
    from_output: instanceId              # 本步 output 锚点/bind 名（verify 校验引用）
    from_field: ""                       # 标量锚点留空；对象锚点填字段名
# 多参数 path 示例（如 deleteFormVersion 的 /form/{formId}/version/{versionId}）：
# rollback:
#   api: deleteFormVersion
#   params:
#   - {param_key: formId,    from_output: detail, from_field: formId}
#   - {param_key: versionId, from_output: detail, from_field: versionId}
# from_output 指向一个对象锚点（detail=$.data.lastestVersion），from_field 从中取各字段。
# 旧格式（顶层 param_key + param_from_output 单值）from_dict 自动迁移，存量卡片无需手改。

examples:                                # 参考示例
  - {key: "handler", name: "工单处理信息", standardFieldIds: ["656788ffdaf71"]}

confidence:                              # 各字段置信度，驱动 review
  request: high
  outputs: high
  requires: low                          # 默认需人工补
  rollback: medium
  module: low                            # extract 粗推，LLM 修正
```

## endpoint（调用模式不固化）

卡片落地时常带 `endpoint` 块，**只含 `contract_ref`，不写 `mode`**：

```yaml
endpoint:
  contract_ref: logic.cmdb.service|GET|/object_basic_all   # service|method|path，对齐后端契约的 operation_key
  # 注意：没有 mode 字段——注册期不固化调用模式
```

**mode 不固化（spec 5.1）**：`api-console register-cards extract` **不写** `endpoint.mode`，主干不决策平台特定调用模式（守平台中性铁律）。mode 留到**真调时**由 adapter `resolve_call_mode` 动态决定：

```
1. 卡片显式 endpoint.mode（存量旧卡可能有）→ 尊重之，不覆盖
2. manifest.call_policy.default_mode → 平台级默认兜底（如 easyops_internal）
3. 契约带 port → internal；否则 gateway
```

**为何不固化**：注册期一旦把 mode 写进卡片，运行时第 1 条就锁死——之后改 `manifest.default_mode`（如切环境、切鉴权方式），**旧卡片不跟着变**（已踩过：cmdb_model 注册时固化 gateway，后 manifest 改 internal 不生效）。不固化后，`manifest.default_mode` 改动立即对所有卡片生效，无滞后。

**存量卡片**：历史上注册期曾固化 mode（registry 中现存卡片仍带 `mode`），它们按第 1 条优先级继续用固化值，不受影响；若发现某卡 mode 滞后于当前 `default_mode`，手清该卡的 `endpoint.mode` 即可让它重新走运行时决策。

## path 多来源优先级

卡片 `path` 按可靠性取最高置信来源（`path_align.align_path`）：

| 优先级 | 来源 | path_source | path_confidence | 触发条件 |
|---|---|---|---|---|
| 1 | 后端契约 endpoint.uri（归一化） | backend_contract | high | contracts.yaml 能按 (service,method,uri) 匹配 |
| 2 | 前端 gateway_path 按 gateway-rules 剥离 | gateway_strip | medium | 后端未命中 + 剥离规则覆盖 |
| 3 | 前端 gateway_path 原样（归一化） | frontend_raw | low | 都未命中 |

> **已知限制**：前端 `{modelId}` vs 后端 `{instanceId}` 参数名差异，当前精确比对导致含参 path（GET/PUT/DELETE）降级到 gateway_strip。不阻塞真调（参数值运行时填），留后续优化（占位符通配）。

## path 归一化

后端契约 colon style（`:instanceId`）与前端 openapi brace style（`{modelId}`）都归一化为 **brace style `{param}`**。`path_align.normalize_path` 处理。

## module（功能域）

module 是"一组功能内聚卡片"的逻辑分组，粒度=**功能域**（domain_model/standard_field/process/form/cmdb_model），不等于 openapi 文件名或后端服务名。

- extract 阶段粗推（从 tag/文件名），标 `confidence.module=low`
- LLM 补语义阶段修正（依据后端功能划分 + openapi tags）
- 一个 openapi 文件可产出多个 module 的卡片

## 字段来源分工

| 字段 | 产出方 | 典型置信 |
|---|---|---|
| name/method/module | 确定性（operationId/method）+ LLM（module） | high / low(module) |
| service/path/path_source/path_confidence | 确定性（多来源优先级） | high/medium/low |
| gateway_path | 确定性（前端 openapi 原样） | high |
| request | 确定性（前端 openapi schema + 后端 contracts 互证） | high |
| outputs（锚点） | 确定性骨架（命中契约 `response.fields`：`type`含`[]`→list_full/list_ids、instanceId/total 等）+ LLM 精修 | high（命中契约）/ low（未命中） |
| tags/summary/description | LLM | high |
| requires | LLM（猜前置条件） | low |
| rollback | LLM（同模块找 delete） | medium（MVP-1 可空） |
| examples | 确定性（openapi example） | high |
| confidence | LLM 自评 | — |

## LLM 补语义要点

extract 产出 `_draft.yaml` 后，LLM 补语义时：

1. **module**：从后端功能划分 / openapi tags 推断功能域名（英文 snake_case）
2. **tags**：3-5 个关键词（中英混合 OK），覆盖业务概念 + 操作类型
3. **summary**：一句话用途（≤20 字）
4. **description**：详细说明（用途 + 典型场景 + 关键约束）
5. **outputs**：精修 extract 已生成的骨架（命中契约时 extract 已确定性填好）。规则：
   - 响应有 `data.instanceId` → 标 `instanceId: $.data.instanceId`
   - 响应有 `data.list` → 标 `list_full: $.data.list` + `list_ids: $.data.list`（list_ids 配合表达式投影 `${s1.list_full.instanceId}`）
   - 响应有 `data`（详情）→ 标 `detail: $.data`
   - jsonpath 子集：`$.xxx.yyy` / `$.xxx[0]` / `$.xxx`，**不支持 `[*]`**（引导用 list_full + 表达式投影）
   - extract 骨架合理性以契约 `response.fields` 为准；契约未命中（path_source=frontend_raw/gateway_strip 含参）的卡片，LLM 从 description/summary 推断，标 confidence.outputs=medium/low
6. **requires**：前置条件（如"删除前须解绑流程"），猜不出留空
7. **rollback**：同模块找 delete 操作，填 `api: <delete card name>` + `params`（参数映射列表）。单参数 path（如 `/{modelId}`）一条；多参数 path（如 `/form/{formId}/version/{versionId}`）按占位符逐个填。每条三字段：`param_key`=目标参数名（path 占位符名）、`from_output`=本步 output 锚点/bind 名、`from_field`=对象锚点取的字段名（标量锚点留空）。verify 会校验 param_key 集合 == 目标 path 占位符集合，填不全会被拦。
8. **confidence**：每个字段自评 high/medium/low

## validate 规则（Card.validate）

- `side_effect` ∈ {read, create, update, delete}
- `path_source` ∈ {backend_contract, gateway_strip, frontend_raw}
- `path_confidence` ∈ {high, medium, low}
- name/module/method/path 必填
- outputs 锚点 jsonpath 必须 `$.` 开头
- confidence 各值 ∈ {high, medium, low}
- rollback（若提供）：`api` 非空、`params` 非空、每条 `param_key`/`from_output` 非空
- rollback 参数完备性在 `verify_dag` 规则12 校验（需 cards 上下文）：`params.param_key` 集合须 == 目标卡片 path 占位符集合，每条 `from_output` 须 == 本步 output.bind 或锚点名
