---
flow: ITSM-运行管理-SLA协议管理
system: EasyOps ITSM
system_slug: itsm
host: http://172.30.0.90
module:
  - itsc-advanced-settings
  - itsc-operation-management
  - itsc-workbench
entry: /next/itsc-workbench/workbench
intent: [SLA, SLA协议, 服务级别协议, 服务协议, SLA管理, 响应时效, 处理时效, 完成时效, 响应预警, 响应超时, 完成预警, 完成超时, 服务时段, 工作日历, 优先级算法, SLA规则, 新建SLA, 编辑SLA, 删除SLA, 服务质量设置, 任务节点SLA, 运行管理]
api_tags: [SLA协议管理, 服务质量设置, 优先级与服务时段, 通知策略]
related: [ITSM-工单发起, ITSM-定时工单管理, ITSM-系统管理-流程管理]
---

# ITSM 运行管理 - SLA 协议管理 - 操作指引

> 适用场景：在 ITSM「运行管理 / 高级设置」中管理 **SLA 协议（服务级别协议）**——定义工单在不同优先级/任务节点下的**响应时效、完成时效**，以及达到**预警/超时**时的通知策略和适用的服务时段。本流程覆盖「进入 SLA 列表 → 高级搜索 → 新建 SLA 协议（基本信息/时效/通知/服务时段）→ 保存 → 编辑 → 删除 → 服务质量设置中关联 SLA」全链路。
> 配套接口：见同目录 [`ITSM-运行管理-SLA协议管理-openapi.yaml`](./ITSM-运行管理-SLA协议管理-openapi.yaml)。
>
> 与 [`ITSM-定时工单管理`](../ITSM-定时工单管理/ITSM-定时工单管理-操作指引.md) 的区别：定时工单管「何时自动发起」；SLA 协议管「发起后多久内必须响应/完成，否则预警超时通知」。
>
> 名词约定：**响应(answer)**=工单从发起到被认领/处理的时效；**完成(done)**=从发起到彻底解决的时效。每个时效各配「预警(warning)」和「超时(timeout)」两套通知，共 4 种通知策略。
>
> 截图标注图例：🔴红框=点击 / 🔵蓝虚线框=输入 / 🟠橙框+▾=下拉 / 🟣紫圈=单复选 / 🟢绿粗框=提交。

## 目录
- [一、进入 SLA 协议管理](#一进入-sla-协议管理)
- [二、列表搜索与高级筛选](#二列表搜索与高级筛选)
- [三、新建 SLA 协议](#三新建-sla-协议)
- [四、编辑 SLA 协议](#四编辑-sla-协议)
- [五、删除 SLA 协议](#五删除-sla-协议)
- [六、服务质量设置中关联 SLA](#六服务质量设置中关联-sla)
- [附：本流程接口速查](#附本流程接口速查)

<!-- deep-links: 本流程关键页面直达（SPA 路径，去掉 host 前缀，参数化）
  工作台:          itsc-workbench/workbench
  SLA协议列表:      itsc-advanced-settings/service-agreement-list
  新建SLA协议:      itsc-advanced-settings/service-agreement-list/service-agreement-create
  SLA协议详情/编辑: itsc-advanced-settings/service-agreement-list/service-agreement-detail/{id}
  服务管理设置:     itsc-service-management/setting-list/{serviceInstanceId}
-->

## 一、进入 SLA 协议管理

从工作台导航到「SLA 协议管理」列表页（`service-agreement-list`，属高级设置/运行管理模块）。

### 步骤 1：在工作台点击「系统管理」
<!-- url: itsc-workbench/workbench | step_id: 1 -->
在工作台点击「系统管理」入口。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-01.png)

### 步骤 2：进入 SLA 协议管理菜单
<!-- url: itsc-advanced-settings/service-agreement-list | step_id: 2-3 -->
在系统管理菜单点击「SLA 协议管理」（运行管理下），进入列表页。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-02.png)

跳转到 SLA 协议列表页，自动拉取协议列表。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-03.png)
> 🔗 本步调用：`POST /next/api/gateway/logic.flowable_service/api/flowable_service/v1/sla/rule/_search`（详见 openapi.yaml 的「SLA协议管理」），同时做权限校验 `POST .../permission/validate`（校验 `itsc:sla_rule_create/delete/access`）。

## 二、列表搜索与高级筛选

在列表页按关键词、协议负责人、可见性等条件搜索。

### 步骤 1：关键词搜索
<!-- url: ...service-agreement-list?page=1&q=soc | step_id: 4-5 -->
在搜索框输入关键词（如 `soc`），列表按协议名称模糊匹配。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-10.png)

### 步骤 2：展开高级搜索
<!-- step_id: 6 -->
点击「高级搜索」展开高级筛选面板。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-12.png)

### 步骤 3：填写高级搜索条件（协议负责人）
<!-- step_id: 7-13 -->
在高级搜索中填写条件，如协议负责人输入 `easyops`（step-18），点击「搜索」按钮触发查询。
协议负责人输入框：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-18.png)

点击「搜索」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-19.png)

> 💡 高级搜索面板的协议名称/负责人等输入框交互（step-20~25 为面板内元素焦点变化）。
> 🔗 本步调用：`POST .../sla/rule/_search`（带 name/ownerName/serviceName 等条件）。

### 步骤 4：切换可见性筛选（全部/我相关）
<!-- step_id: 14-15 -->
点击可见性切换（全部 / 我相关），列表按可见范围过滤。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-26.png)
> 🔗 本步调用：`POST .../sla/rule/_search`（带可见性参数）。

## 三、新建 SLA 协议

点击「新建」打开 SLA 协议配置表单，依次配置基本信息、响应/完成时效、预警/超时通知、服务时段后保存。

### 步骤 1：输入协议名称
<!-- url: .../service-agreement-create | step_id: 16 -->
进入新建页，在「协议名称」输入框填写名称（如 `test`）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-32.png)

### 步骤 2：设置协议状态与负责人
<!-- step_id: 17-18 -->
协议状态选择「启用」（step-33），协议负责人选择用户（如 `easyops`，step-34）。
选择「启用」状态：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-33.png)

选择负责人 easyops：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-34.png)

### 步骤 3：选择适用范围与流程
<!-- step_id: 19-21 | step_id: 19 -->
选择适用范围（「适用于服务」step-35 / 「适用于任务节点」step-36），再选择关联的流程分类（如「变更管理」step-37）。
选择「适用于服务」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-35.png)

选择「适用于任务节点」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-36.png)

选择流程分类「变更管理」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-37.png)
> 🔗 本步调用：`GET .../service_priority`（优先级列表）、`GET .../sla/calendar`（服务时段/工作日历）。

### 步骤 4：选择服务时段（工作日历）
<!-- step_id: 22 -->
在服务时段下拉选择工作日历（如「全年无休」）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-38.png)
> 🔗 服务时段来自 `GET .../sla/calendar`。

### 步骤 5：配置响应时效（answer）与完成时效（done）
<!-- step_id: 23-31 -->
在时效配置区，为当前优先级等级配置响应时效（如 `2` 小时）与完成时效（如 `4` 小时）。
输入响应时效 `2`：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-45.png)

选择单位「小时」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-46.png)

输入完成时效 `4`：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-53.png)

选择单位「小时」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-54.png)
> 💡 时效最终落在 `slaConfig[].levelConfig`：`{agreementType: "answer", duration: "2h"}` 与 `{agreementType: "done", duration: "4h"}`，并绑定 `workingCalendarId`（服务时段）。

### 步骤 6：配置响应预警通知（answer_warning）
<!-- step_id: 32-38 -->
展开「【任务】响应预警-通知信息」，配置响应预警通知（次数 `1`、间隔 `1h`、通知策略）。
配置次数 `1`：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-59.png)

间隔 `1h`、单位「小时」、步进调整：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-64.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-65.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-66.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-67.png)

### 步骤 7：配置响应超时通知（answer_timeout）
<!-- step_id: 39-42 -->
展开「【任务】响应超时-通知信息」，配置响应超时通知（次数 `1`、间隔 `1h`）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-68.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-69.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-75.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-76.png)

### 步骤 8：配置完成预警（done_warning）与完成超时（done_timeout）通知
<!-- step_id: 43-50 -->
依次展开「【任务】完成预警-通知信息」「【任务】完成超时-通知信息」，分别配置（次数 `1`、间隔 `1h`）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-77.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-78.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-84.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-90.png)

调整通知间隔单位「小时」：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-102.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-103.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-104.png)
> 💡 4 种通知最终落在 `slaConfig[].notifyPolicy`：`answer_warning` / `answer_timeout` / `done_warning` / `done_timeout`，每条含 `notifyPolicyId`（来自通知策略）、`count`、`interval`。

### 步骤 9：保存 SLA 协议
<!-- step_id: 51-57 | api: POST .../sla/rule (CreateSLARule) | tag: SLA协议管理 -->
点击「保存」按钮提交，创建 SLA 协议。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-105.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-106.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-107.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-108.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-109.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-110.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-111.png)
> 🔗 本步调用：`POST /next/api/gateway/flowable_service.sla.CreateSLARule/api/flowable_service/v1/sla/rule`（详见 openapi.yaml 的「SLA协议管理」），body 含 `basicInfo`（name/status/ownerId/type/priorityId）+ `slaConfig`（levelConfig 时效 + notifyPolicy 通知）。创建成功后返回 ruleId，并 `GET .../sla/rule/{id}` 回显详情。

## 四、编辑 SLA 协议

从列表进入某条 SLA 的编辑页，修改配置后保存。

### 步骤 1：点击列表中的协议进入编辑
<!-- url: .../service-agreement-detail/{id} | api: GET .../sla/rule/{id} | tag: SLA协议管理 | step_id: 58-59 -->
在列表点击目标协议（如 `test`），进入详情/编辑页，表单回填原配置。
点击协议 `test`：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-112.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-113.png)
> 🔗 本步调用：`GET .../sla/rule/{ruleId}`（回填详情）。

### 步骤 2：修改协议描述
<!-- step_id: 60-76 -->
> ⚠️ 未截图（纯文本输入过程不截图，逐字符录入）。在「协议描述」输入框修改说明，最终值为 `更改测试`。失焦后即 step-120 截图。
确认描述内容（`更改测试`）：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-120.png)

### 步骤 3：修改协议负责人
<!-- step_id: 77-78 | api: PUT .../sla/rule/{id} (UpdateSLARule) | tag: SLA协议管理 -->
重新选择协议负责人（如从 `easyops` 改为 `barryhu`）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-114.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-121.png)

### 步骤 4：保存修改
<!-- step_id: 79-85 | api: PUT .../sla/rule/{id} | tag: SLA协议管理 -->
点击「保存」提交编辑。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-122.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-123.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-124.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-125.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-126.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-127.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-128.png)
> 🔗 本步调用：`PUT /next/api/gateway/flowable_service.sla.UpdateSLARule/api/flowable_service/v1/sla/rule/{ruleId}`，body 结构同 create（basicInfo + slaConfig）。

## 五、删除 SLA 协议

在列表删除某条 SLA 协议。

### 步骤 1：搜索定位并删除
<!-- step_id: 86-88 | api: DELETE .../sla/rule/{id} | tag: SLA协议管理 -->
在搜索框输入「删除」定位操作（或打开行的删除入口），点击「删除」。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-129.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-130.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-131.png)
> 🔗 本步调用：`DELETE /next/api/gateway/logic.flowable_service/api/flowable_service/v1/sla/rule/{ruleId}`（路径参数为 ruleId）。

## 六、服务质量设置中关联 SLA

在「服务管理」的「更多设置 → 服务质量设置」中，为流程的任务节点关联 SLA 协议（决定该节点按哪条 SLA 计时效）。

### 步骤 1：进入服务管理 → 事件管理
<!-- url: itsc-service-management/setting-list/{id} | step_id: 89-92 -->
从系统管理进入「服务管理」，选择「事件管理」流程分类。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-132.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-133.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-134.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-135.png)

### 步骤 2：更多设置 → 服务质量设置
<!-- step_id: 93-96 | api: GET .../service_instance/{id}/sla_config | tag: 服务质量设置 -->
点击「更多设置」→「服务质量设置」，进入 SLA 关联配置页（回显当前各任务节点已关联的 SLA）。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-136.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-137.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-138.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-139.png)
> 🔗 本步调用：`GET .../service_instance/{serviceInstanceId}/sla_config`（GetServiceSLAConfig，回显关联）+ `POST .../sla/rule/_search`（可选 SLA 列表）。

### 步骤 3：为任务节点选择 SLA 并保存
<!-- step_id: 97-102 | api: PUT .../service_instance/{id}/sla_config | tag: 服务质量设置 -->
为各任务节点（如「适用于任务节点」）选择 SLA 协议（如 `SLA-1小时`），点击「新增」继续配置，最后保存。

选择适用范围与 SLA：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-140.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-141.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-142.png)

新增并选择通知策略（如 `SOC-安全事件-未处理提醒`）：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-143.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-144.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-145.png)

保存：
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-146.png)
> 🔗 本步调用：`PUT /next/api/gateway/flowable_service.service_catalog.SetServiceSLAConfig/api/flowable_service/v1/service_instance/{serviceInstanceId}/sla_config`，body 含 `scope`（step=任务节点）+ `slaConfig[]`（每个 `{userTaskId, slaId}` 把流程节点绑定到具体 SLA）。

### 步骤 4：返回并查看配置生效
<!-- step_id: 104-108 -->
回到服务质量设置列表，配置已生效。
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-147.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-148.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-149.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-150.png)
![](./_assets/ITSM-运行管理-SLA协议管理-操作指引/step-151.png)

## 附：本流程接口速查

| 操作 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| SLA 协议列表 | POST | `/next/api/gateway/logic.flowable_service/api/flowable_service/v1/sla/rule/_search` | body 含 Q/name/ownerName/serviceName/page/pageSize |
| SLA 协议列表(另一入口) | POST | `/next/api/gateway/flowable_service.sla.SearchSLARule/api/flowable_service/v1/sla/rule/_search` | 同上，服务质量设置里选 SLA 用 |
| SLA 协议详情 | GET | `/next/api/gateway/flowable_service.sla.GetSLARule/api/flowable_service/v1/sla/rule/{ruleId}` | 编辑表单回填 |
| 新建 SLA 协议 | POST | `/next/api/gateway/flowable_service.sla.CreateSLARule/api/flowable_service/v1/sla/rule` | body: basicInfo + slaConfig(levelConfig 时效 + notifyPolicy 通知) |
| 编辑 SLA 协议 | PUT | `/next/api/gateway/flowable_service.sla.UpdateSLARule/api/flowable_service/v1/sla/rule/{ruleId}` | 同 create body |
| 删除 SLA 协议 | DELETE | `/next/api/gateway/logic.flowable_service/api/flowable_service/v1/sla/rule/{ruleId}` | 路径参数为 ruleId |
| 服务时段/工作日历 | GET | `/next/api/gateway/flowable_service.sla.ListWorkingCalendar/api/flowable_service/v1/sla/calendar` | 选服务时段用 |
| 优先级列表 | GET | `/next/api/gateway/flowable_service.service_priority.ListServiceCatlogPriority/api/flowable_service/v1/service_priority` | 选优先级算法 |
| 优先级算法详情 | GET | `/next/api/gateway/flowable_service.service_priority.GetPriorityAlgorithm/api/flowable_service/v2/service_priority/{priorityId}` | 取算法配置 |
| 通知策略列表 | GET | `/next/api/gateway/flowable_service.notify_policy.ListNotifyPolicy/api/itsc_trigger/v1/notify_policy` | 4 种通知选用 |
| 服务质量设置-查询关联 | GET | `/next/api/gateway/flowable_service.service_catalog.GetServiceSLAConfig/api/flowable_service/v1/service_instance/{serviceInstanceId}/sla_config` | 回显节点已关联 SLA |
| 服务质量设置-保存关联 | PUT | `/next/api/gateway/flowable_service.service_catalog.SetServiceSLAConfig/api/flowable_service/v1/service_instance/{serviceInstanceId}/sla_config` | body: scope + slaConfig[]({userTaskId,slaId}) |
| 权限校验 | POST | `/next/api/gateway/logic.micro_app_service/api/micro_app/v1/permission/validate` | 校验 itsc:sla_rule_create/delete/access |
