---
name: instance-id
kind: concept
module: ''
tags:
- instanceId
- ID生成
- 跨模块
- modelId别名
- GenInstanceId
- 微秒时间戳
completeness: full
gaps: []
scope:
- 所有涉及实例 ID 的编排（path 参数/跨模块引用/foreach）
- 理解 modelId vs instanceId 别名
related:
- value-types（instanceId 的类型）
last_verified: '2026-07-22'
---

# instanceId 概念（全局，跨所有模块）

> 全局共享领域概念。EasyOps 所有模块的实例 ID 都遵循同一规则。
>
> **当前状态：已确认（后端 `GenInstanceId()` 源码机制，2026-07-22 核对）**。

## 定义

`instanceId` 是 EasyOps 实例的全局唯一标识。所有资源（领域模型、标准字段、CMDB 实例、流程实例...）创建时由后端自动生成一个 instanceId，**不可由用户指定或修改**，作为后续引用的句柄。

## 生成机制（已证实）

后端 `GenInstanceId()` 函数生成，核心逻辑：

1. 取当前时间的**微秒级时间戳**（`UnixNano() / 1000`）
2. 若同一微秒内生成多个 ID，在上一值基础上**自增 1**，确保唯一性
3. 格式化为 **13 位小写十六进制字符串**

```yaml
格式:
  pattern: 13 位小写十六进制字符串
  example: "5d38fa40c9a19"
  example2: "60ba62a4abdad"
  regex: '^[0-9a-z]{13}$'   # 已证实；注意早期样本疑为 12 位，以 13 位为准

唯一性: 全局唯一，跨模型/模块不重复（同微秒自增保证）
生命周期: 创建时后端生成，不可指定/修改，永不复用（删除后该 id 废弃，不会分给新实例）
```

> **历史订正**：此前从少量数据观察误判为「12 位 hex / MongoDB ObjectId 去时间戳前缀」，均不正确——
> 实际为 13 位、基于微秒时间戳 + 同微秒自增（见 `GenInstanceId()`）。旧样本 `656788ffdaf71`/
> `656789ae45cb9` 计 12 位，与权威机制不符，疑为誊写误差或非 CMDB 模块的另一套 id，待复核。

## 使用场景（跨模块）

| 场景 | 用法 |
|---|---|
| path 参数 | `/domain_model/{instanceId}`、`/standard_field/{instanceId}` |
| 卡片 outputs 锚点 | `instanceId: $.data.instanceId`（create 返回新建 id） |
| 跨模块引用 | domain_model 的 `standardFieldIds` 数组里每个值 = standard_field 的 instanceId |
| foreach 展开 | DAG 里 `${s1.models.instanceId}` 投影出 id 数组，喂给下游 foreach |

## 重要陷阱：前端后端参数名不一致

同一个 instanceId 值，前端 openapi 和后端契约用**不同的占位符名**：

| 来源 | 占位符名 | 实际值 |
|---|---|---|
| 前端 openapi path | `{modelId}` | 656789ae45cb9 |
| 后端契约 endpoint.uri | `:instanceId` / `{instanceId}` | 656789ae45cb9（同一个值） |

**含义**：path 参数名只是占位符，实际值运行时填充。`{modelId}` 和 `{instanceId}` 指向同一个实例 ID。这是 path_align 已知限制（精确比对导致降级 gateway_strip）的根因。

## 相关概念

- [value-types](./value-types.yaml)：instanceId 的类型是 `instance_id`（string 子类型）
- [cmdb-model](./cmdb-model.yaml)：CMDB 实例也用 instanceId，但 objectId + instanceId 双键

## 消费场景

LLM 编排涉及 instanceId 时读此文件：
- 理解 `${s1.models.instanceId}` 投影出的是 13 位 hex 数组
- 理解跨模块引用（standardFieldIds 用 standard_field 的 instanceId）
- 理解 modelId=instanceId（前端后端别名）
