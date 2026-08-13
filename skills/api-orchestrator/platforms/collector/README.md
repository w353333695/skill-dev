# platforms/collector/ —— EasyOps 采集套件服务接入资料

> deployment=collector（172.30.0.90 / org 8888，独立 EasyOps 实例）。
> 唯一真相来源——换环境/换 LLM 从此读，勿依赖记忆。

## 资料地图

| 文件 | 职责 | 何时读 |
|---|---|---|
| `systems.yaml` | 接入面/鉴权/端口/org/user/激活机制/拓扑/计数坑 | **编排入口**，每次先读 capabilities 粗筛可达性 |
| `objects.yaml` | 套件结构/字段/关系/副作用/接口行为 | 命中 resource.verb 后按需读对应对象段（grep 定位）|
| `entities.yaml` | 字段锚(plugin_instance_id 等)+跨 service 接力 | e2e dataflow 接线时读 transitions |
| `easyops-collector-plugin.yaml` | api-cli 清单（collector_plugin_service:8151，23端点）| 执行套件 CRUD/导入导出/指标导入 |
| `easyops-collector-service.yaml` | api-cli 清单（collector_service kit:12000，2端点）| 执行套件激活/列表 |
| `flows/*.yaml` | e2e 流程模板 | 需求匹配某 flow trigger 时读 |
| `formats/collector-kit/`（在 demo deployment）| 套件包格式/plugin.yaml schema/py2规范/$.attr（跨部署复用）| 开发套件/打包时读 |

## 两个系统

- **collector_plugin_service:8151** —— 采集套件管理（CRUD/导入导出/指标导入）。spec: `easyops-collector-plugin.yaml`
- **collector_service kit:12000** —— 套件激活/列表（⚠️8125 是旧版无 kit 模块，kit 端点在 12000，需 giraffe-contract-name header）。spec: `easyops-collector-service.yaml`

## 关键认知（编排必看）

1. **无启用/禁用端点** —— collector_plugin_service 无 enable/disable/activate。激活在 collector_service.kit.activate（:12000）。
2. **激活机制** —— activate 不直接建任务，触发 AssignJobs（CMDB事件驱动+600s兜底）。成功判定 totalStatus!=fail。
3. **multipart 走 SDK** —— plugin_package.export/import/import_update 是 multipart/binary，api-cli 仅 --print-curl，真调走 Python SDK。
4. **list 计数坑** —— plugin.list 的 total 在 data.total（body内），非 stderr _meta.total。
5. **采集脚本 py2.7** —— print 语句/requests/subprocess 无 timeout（详见 formats/collector-kit/sampler-types.yaml）。
6. **两种 samplerType** —— metric_sampler 输出 [{dims,vals}]（监控）/ process_sampler 输出 GATHERING DATA 标记（CMDB采集）。
7. **$.attr 取参** —— `$.` 开头配 paramType=cmdb，取值对象=采集目标实例（详见 formats/collector-kit/param-mechanism.yaml）。

## 真调验证状态（2026-08-13，org 8888）

**collector_plugin_service:8151 —— 完整验证通过**：
- ✅ plugin list / detail / metricbeat_list（读路径）
- ✅ plugin_package.import（curl -F 上传，两套件均成功；ZIP_STORED+UTF8 flag 确认可用）
- ✅ plugin_package.export（GET zip 流，含 HOST.json/metric/dashboard 完整结构）
- ✅ plugin_package.import_update（version 必填 + 版本唯一约束 code:100007）
- ✅ plugin.delete（前置检查 + 物理删）

**collector_service kit:12000 —— 部分（contract gap）**：
- ⚠️ kit.activate / list：端点在 12000（giraffe-contract-name 路由确认），但 contract 实际版本/名未确定（kits.go 的 @1.0.19 实测 not found，1.0.0~1.0.20 全 not found）。需前端实际激活操作抓包拿真实 `giraffe-contract-name` header 回流 systems.yaml。

**e2e 测试套件**：
- 套件A『主机端口可达性监控套件』(simple-script/metric_sampler，instanceId=658e73a176ad1) — 已导入保留，用于后续激活验证
- 套件B『主机信息采集套件』(simple-script/process_sampler) — 已验证导入后删除

**待解 gap**：
1. kit.activate contract 版本号（需前端抓包）
2. 采集脚本 py2 实际执行（.90 HOST _agentStatus=未安装，无 agent 接收——套件导入/激活链路可验，采集执行依赖 agent 另一层）
3. process_sampler GATHERING DATA 协议解析（在 collector_proxy_server/agent 端，源码不在本地）
