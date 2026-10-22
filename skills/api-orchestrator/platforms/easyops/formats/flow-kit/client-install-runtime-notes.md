# 原生客户端安装流程知识归档

记录日期：2026-10-22。范围：24 环境原生 AutoOps Flow + EasyFlow + CMDB。

## 编排默认规范（后续需求优先遵循）

- 不涉及外部接口时，原生流程默认使用工具节点或已有子流程。内部 API 请求、解析、轮询是工具/子流程内部细节，不应为了实现而把业务步骤拆成大量 HTTP 节点。
- 三节点简版按「文件分发 → 安装 → 验证」组织，全部为工具节点；旧九节点流程保留作为实现细节参考，不再作为默认画布设计。
- CMDB 实例选择类型输入的显示字段要简洁、可读，通常只留 1–2 个业务字段。文件包版本使用「描述 description、版本名称 versionName」；工具使用 name；主机使用 ip、hostname。不要默认展示业务 ID、instanceId、长哈希和重复字段。
- displayFields 只影响显示，仍用 instanceId 查询版本、toolId 执行工具，不得把 description/versionName 当执行 ID。
- 使用上述简洁显示字段时显式配置 cmdbSelector=simple-select；候选过滤按工具输入契约设置 selector=cmdb.range.instance.query、cmdbQuery={defaultInstanceId: [], query: "序列化查询 JSON"}，不要把原始查询对象直接塞到 cmdbQuery 顶层。
- 分发和动态安装封装工具使用平台注入的 EASYOPS_CMDB_HOST、EASYOPS_EASYFLOW_HOST、EASYOPS_TOOLS_HOST 及租户用户上下文，不硬编码部署 IP。
- 工具输出可通过 PutStr 返回空白分隔的主机 IP，供后续验证工具的 @agents 使用；该格式由工具执行目标解析器 parseRawAgent 原生支持。不要把未解析的 JSON 字符串直接当 @agents。
- 24 环境名字服务 EASYOPS_CMDB_HOST 返回单值关联时，_ARTIFACT 可能是对象；直连 CMDB 8079 的同名接口返回数组。工具需把单对象归一成单元素数组后再解析，不要把协议差异当成无关联。
- Python2 工具中，中文格式串与 JSON 返回的 unicode 字符串拼接时，中文格式串应写为 u"中文 %s"，否则可能在任务已提交后因日志格式化触发 UnicodeDecodeError。不要通过修改全局默认编码规避。
- 失败诊断：失败工具的结构化 outputs 可能只保留已写入的任务 ID，流程层 error 也可能只显示通用的 tool exec error。需要把失败任务 URL 和日志最后 20 行同时写入工具的输出参数，并拼入抛出的 RuntimeError；平台执行详情的 `msg` 会保留这些参数标记和可读失败上下文。
- 分发失败 URL 格式固定为 `https://{frontend}/next/file-distrubute/task/{taskId}?type=fileDelivery&event=deploy`；安装失败 URL 格式固定为 `https://{frontend}/next/tool/task/{execId}`。本次 24 环境前端基址为 `https://192.168.110.24`。
- 部署日志从 `/deployTask/{taskId}` 的各 target `msg` 汇总后取最后 20 行；工具日志从 `/tools/execution/logs/{execId}` 读取后取最后 20 行。取日志失败时仍输出任务 URL 和失败原因，不能覆盖原始任务失败。

## 模型与接口

- `_ARTIFACT_VERSION.name` 是版本业务 ID；关联 `_ARTIFACT[0].name` 是文件包业务 ID，不可用 instanceId 直接代替。
- 工具模型是 `_TOOL_CONFIG@EASYOPS`，属性 `toolId` 才是执行工具 ID；不存在本次误猜的 `_TOOL` 模型。
- 主机 CMDB instanceId 与 `_uuid` 不同；EasyFlow targetId 用 `_uuid`，工具目标使用带 ip/instanceId 的主机对象。
- 本次通过 POST `/object/{objectId}/instance/_search` 读取关联属性；Host/org/user 是本部署直连接口上下文。
- `/tools/execution` 传 `vId=$latest_production` 在实际执行时解析生产版本；状态响应检查 `data.totalStatus`，完成后读 `/tools/execution/result/{execId}`。

## 原生输入、CEL 与输出

- flowInputs 由节点输入契约推导。HTTP showInputDefs 的结构没有 CMDB 模型元数据；要提供真正 CMDB 选择器，可使用有完整工具输入定义的起始工具节点。
- cmdbInstance+cmdbAttrId=instanceId 保留所选实例 ID；使用其他属性时平台根据选中实例 ID 查询对应属性。多选 HOST 的 instanceId 数组可用于后续 CMDB 查询。
- HTTP requestBody.json 必须首先是合法 JSON。将 `<% ... %>` 表达式作为 JSON 字符串值写入，运行时可以得到原生 map/list。
- 实测 CEL：`$.install_tool_inputs.merge({"@agents": step["step_3"].output.response.data.list, "install_path": $.install_path})`；目标列表可用 `list.map(host, {"targetId": host._uuid})`。
- HTTP 节点不会自动输出 body：必须 showOutputDefs 显式映射 `<% $.$get_result.body %>`，后续读取 `step["step_N"].output.response.data...`。
- HTTP 来源的 stepOutput 映射 key 可以为 `response.data.list`：后端直接按点路径拼 CEL，已用于最终验证工具目标传参并成功运行。
- 工具节点需 `outputs: {}` 或具体输出映射；outputs=null 会转换为空字符串并导致流程结果接口 protobuf 解码失败。若要显示输出列，配置 outputs 的 aliasId/asFlowOutputColumns。
- HTTP POST 除 HTTP 状态外还要检查业务 code；轮询终止检查 `$.$polling`，最终 successConditions 检查 `$.$get_result`。轮询完成后还会额外取一次结果。

## 更新、脚本和导出

- PUT `/flows/{flowId}` 可更新节点并创建新版本；其响应 version=0 不可信，应 list/get 回读真实时间戳再执行。
- `/api/tool_service/v2/flows/{flowId}` 的元信息更新不能等价替换完整节点更新。
- 工具 Python 正文前平台会注入较长 header，因此不能包含 from __future__ import（不在文件开头，实际 SyntaxError）。本次使用 Python2/3 通用语法。
- 工具更新时重复 vName 会返回 409；可省略 vName 由平台生成，再 get `$latest_development` 获得新 vId。
- V2 Flow 导出实际忽略本次传入的 versionId，源代码读取最新流程；同时读取依赖工具默认版本导致仅开发版工具的本次导出失败。
- 替代方案：POST `/api/tool_service/v1/batch/export`，显式 exportList 的 toolId/versionId，得到真实批量工具包；与回读流程、准确 tools/flows 元数据组装 V2 根目录，再 `/flows/import/check` 预检。不要为打包擅自生产发布。
- 同目录重复分发存在安装路径冲突语义；试跑用全新专用目录，不通过强制覆盖/删除用户目录消除冲突。

## 前端验收 URL 模板

- 流程：`https://{frontend}/next/flow/management/{flowId}/detail?version={version}`
- 文件包版本：`https://{frontend}/next/file-distrubute/file-pkg/{packageId}/version/{versionId}/file-tree?path=%2F`
- 分发任务：`https://{frontend}/next/file-distrubute/task/{taskId}?type=fileDelivery&event=deploy`

## 源码依据

- tool_service/internal/types/flow/flow_version.go：HTTP 输入定义、FlowStep。
- tool_service/internal/types/flow/convert.go：HTTP stepOutput 点路径和工具输出转换。
- tool_service/internal/types/flow/workflow.go：JSON 请求体、轮询与最终结果。
- tool_service/internal/flow_convert/flow_convert.go：从工具契约推导 Flow 输入。
- tool_service/internal/flow_execution/flow_execution.go：CMDB 参数实例解析。
- tool_service/static/objects/objects.json：工具配置模型 ID。
- tool_service/flow_basic/flow_basic_service.go：V2 导出、默认工具版本查询及导入包结构。
- tool_service/import_export/route.go、custom_controller.go：指定工具版本批量导出。
- 中文错误与日志可能以字面量 `\\uXXXX` 返回，工具在截取日志和组装异常前应先解码；Python 2 不要直接 `raise RuntimeError(unicode_text)`，应将最终异常消息编码为 UTF-8 bytes，避免平台 `str()` 失败后再次展示成 Unicode 转义。
