---
flow: ITSM-系统管理-通知触发器管理与配置
system: EasyOps ITSM
system_slug: itsm
host: http://172.30.0.90
module:
  - itsc-advanced-settings
  - itsc-service-management
  - itsc-process-manage
  - itsc-workbench
entry: /next/itsc-workbench/workbench
intent: [通知, 通知管理, 通知配置, 通知策略, notify_policy, 触发器, 触发器管理, trigger, 触发条件, 触发动作, 发送通知, 任务状态变化, 通知范围, 通知模式, 工单信号, 触发信号, 条件配置, 引用触发器, 节点触发器, 新建通知, 新建触发器, 编辑触发器, 删除触发器]
api_tags: [通知配置管理, 触发器管理, 触发器引用]
related: [ITSM-运行管理-SLA协议管理, ITSM-定时工单管理, ITSM-系统管理-流程管理]
---

# ITSM 系统管理 - 通知/触发器管理与配置 - 操作指引

> 适用场景：在 ITSM「系统管理 → 高级设置」中管理**通知配置（notify_policy）**与**触发器（trigger）**——通知配置定义「工单在什么信号下、用什么方式、通知哪些人、通知内容」；触发器定义「当工单/任务发生某事件且满足某条件时，执行什么动作（如发通知）」。本流程覆盖三大块：
>
> 1. **通知配置**：列表 → 新建（名称/通知类型/工单信号/触发信号/通知模式/通知范围/内容模板）→ 编辑 → 删除 → 搜索/高级搜索
> 2. **触发器**：列表 → 搜索 → 新建（名称/引用范围/触发事件/动作-发送通知/条件-工单名称包含·任务状态变化/保存）→ 删除
> 3. **在服务管理/流程中引用触发器**：服务设置里引用触发器；流程版本里为节点配置触发器
>
> 配套接口：见同目录 [`ITSM-系统管理-通知触发器管理与配置-openapi.yaml`](./ITSM-系统管理-通知触发器管理与配置-openapi.yaml)。
>
> 与其他流程的关系：通知配置被 SLA 协议（4 种预警/超时通知）、定时工单、触发器引用；触发器被服务管理/流程节点引用。
>
> 截图标注图例：🔴红框=点击 / 🔵蓝虚线框=输入 / 🟠橙框+▾=下拉 / 🟣紫圈=单复选 / 🟢绿粗框=提交。

## 目录
- [一、进入通知配置管理](#一进入通知配置管理)
- [二、新建通知配置](#二新建通知配置)
- [三、编辑 / 删除通知配置](#三编辑--删除通知配置)
- [四、通知列表搜索与高级筛选](#四通知列表搜索与高级筛选)
- [五、触发器管理 - 新建触发器](#五触发器管理---新建触发器)
- [六、在服务/流程中引用触发器](#六在服务流程中引用触发器)
- [七、删除触发器](#七删除触发器)
- [附：本流程接口速查](#附本流程接口速查)

<!-- deep-links: 本流程关键页面直达（SPA 路径，去掉 host 前缀，参数化）
  工作台:         itsc-workbench/workbench
  通知配置列表:    itsc-advanced-settings/notify-config
  新建通知配置:    itsc-advanced-settings/notify-config/create
  编辑通知配置:    itsc-advanced-settings/notify-config/create?instanceId={notifyPolicyId}
  触发器列表:      itsc-advanced-settings/trigger-manage
  新建触发器:      itsc-advanced-settings/trigger-manage/create
  服务管理设置:    itsc-service-management/setting-list/{serviceInstanceId}
  流程版本配置:    itsc-process-manage/{processDefinitionId}/versionCreate-v2/{processVersionId}
-->

## 一、进入通知配置管理

从工作台导航到「通知配置」列表页（`notify-config`，高级设置下）。

### 步骤 1：在工作台点击「系统管理」
<!-- url: itsc-workbench/workbench | step_id: 1 -->
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-01.png)

### 步骤 2：进入通知配置管理
<!-- url: itsc-advanced-settings/notify-config | step_id: 2-4 -->
在系统管理 → 高级设置中点击「通知配置」入口。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-02.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-03.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-04.png)
> 🔗 本步调用：`GET .../itsc_trigger/v1/notify_policy`（列表）、`GET .../itsc_trigger/v1/enums?name=notify_mode`（通知模式枚举）、`GET .../itsc_trigger/v2/notify_type`（通知类型）。

## 二、新建通知配置

点击「新建」打开通知配置表单，依次配置名称、工单/触发信号、通知模式、通知范围、内容模板后保存。

### 步骤 1：输入通知名称
<!-- url: .../notify-config/create | step_id: 5-6 -->
> ⚠️ 名称输入过程不截图（step-5 逐字符录入，最终值 `【**项目】测试通知`）。
通知名称输入完成：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-11.png)

### 步骤 2：选择工单信号与触发信号
<!-- step_id: 7-9 -->
点击「工单信号」选择工单类型（step-12），选择具体工单（step-13），点击「提交」确认。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-12.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-13.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-14.png)
> 💡 通知类型默认 `process_instance`（工单）、触发信号 `start`（发起时触发），最终落在 body 的 `notifyType` / `triggerSignal` 字段。

### 步骤 3：选择通知模式
<!-- step_id: 10-11 -->
点击「通知模式」下拉，选择通知方式（如「语音通知测试」，对应 `notifyMode: [test_voice]`）。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-15.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-16.png)

### 步骤 4：选择通知范围
<!-- step_id: 12-14 -->
在通知范围勾选要通知的对象（如「工单创建人」「待办人」，对应 `notifyRange: [creator, todo_user]`）。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-17.png)

勾选「工单创建人」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-18.png)

勾选「待办人」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-19.png)

### 步骤 5：配置通知内容模板（插入变量）
<!-- step_id: 15-19 -->
在内容模板里通过变量插入工单信息，如插入「工单ID」（`${process_instance_id}`）、「工单名称」、「工单当前状态」等。
点击插入「工单ID」变量：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-20.png)

点击插入「工单名称」变量：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-22.png)

点击插入「工单当前状态」变量：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-24.png)

### 步骤 6：编辑通知正文
<!-- step_id: 20-116 -->
> ⚠️ 通知正文为大量逐字符文本输入（step 20-115 不截图，在模板里书写 `工单ID: ${process_instance_id}...` 等内容）。最终正文见 step-31。
正文编辑完成：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-31.png)

### 步骤 7：保存通知配置
<!-- step_id: 117 | api: POST .../notify_policy (CreateNotifyPolicy) | tag: 通知配置管理 -->
点击「保存」按钮，创建通知配置。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-32.png)
> 🔗 本步调用：`POST /next/api/gateway/flowable_service.notify_policy.CreateNotifyPolicy/api/itsc_trigger/v1/notify_policy`，body: name/notifyType=process_instance/triggerSignal=start/notifyMode=[test_voice]/notifyRange=[creator,todo_user] + 内容模板字段。

## 三、编辑 / 删除通知配置

### 步骤 1：点击通知进入编辑，修改通知模式
<!-- url: .../create?instanceId={id} | api: PUT .../notify_policy/{id} | tag: 通知配置管理 | step_id: 118-122 -->
在列表点击通知（如「【**项目】测试通知」），进入编辑页。将通知模式改为「短信（模板）」（对应追加 `dx`），保存。
点击进入编辑：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-33.png)

修改通知模式为「短信（模板）」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-34.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-35.png)

编辑正文：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-42.png)

保存：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-43.png)
> 🔗 本步调用：`PUT /next/api/gateway/flowable_service.notify_policy.UpdateNotifyPolicy/api/itsc_trigger/v1/notify_policy/{id}`，body 结构同 create（notifyMode 更新为 `[test_voice, dx]`）。

### 步骤 2：删除通知配置
<!-- step_id: 123-127 | api: DELETE .../notify_policy | tag: 通知配置管理 -->
点击「删除」，输入校验值（如 `1`）确认删除。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-44.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-45.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-46.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-48.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-49.png)
> 🔗 本步调用：`DELETE /next/api/gateway/logic.flowable_service/api/itsc_trigger/v1/notify_policy?instanceIds={id}`（批量删除，instanceIds 逗号分隔）。

## 四、通知列表搜索与高级筛选

### 步骤 1：关键词搜索
<!-- url: .../notify-config?page=1&q=发起 | step_id: 128-129 -->
搜索框输入关键词（如 `发起`）。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-56.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-57.png)

### 步骤 2：高级搜索
<!-- step_id: 130-141 -->
点击「高级搜索」展开面板，按通知类型/工单信号/触发信号等条件筛选后点「搜索」。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-58.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-59.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-60.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-61.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-62.png)

高级搜索面板：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-64.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-65.png)

点击「搜索」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-63.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-70.png)
> 🔗 本步调用：`GET .../notify_policy`（带筛选条件）。

## 五、触发器管理 - 新建触发器

导航到「触发器管理」（`trigger-manage`），新建触发器并配置触发事件、动作、条件。

### 步骤 1：进入触发器管理并搜索
<!-- url: itsc-advanced-settings/trigger-manage | step_id: 143-145 -->
在搜索框输入关键词（如 `test`）查询触发器。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-80.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-81.png)
> 🔗 本步调用：`GET .../flowable_service/v1/trigger`（列表）。

### 步骤 2：输入触发器名称
<!-- url: .../trigger-manage/create | step_id: 146-147 -->
点击「新建」，输入触发器名称（如 `【**项目】测试触发器`）。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-87.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-93.png)

### 步骤 3：选择引用范围（scope）
<!-- step_id: 148-153 -->
在「引用范围」依次选择维度：服务实例（step-94/95）→ 工单实例（step-96/97）→ 任务节点（step-98），决定触发器作用的层级。
选择「服务实例」+ 确定：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-94.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-95.png)

选择「工单实例」+ 确定：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-96.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-97.png)

选择「任务节点」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-98.png)
> 💡 最终 `scope=process_task`（任务节点级触发器），触发事件 `process_task.todo,process_task.jump`（任务待办/跳转）。

### 步骤 4：配置动作 - 发送通知消息
<!-- step_id: 154-161 -->
点击「发送通知消息」（step-103），展开「【任务】通知信息」，选择通知策略、通知次数（如 `1`）、间隔（如 `1h`），点「设置」确认。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-99.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-100.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-101.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-102.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-103.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-104.png)

通知次数 `1`、点「设置」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-116.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-117.png)
> 💡 动作落在 `config.actionList[0]`：`{name: "send_message", args: {notifyPolicyId, notifyTimes: 1, notifyInterval: "1h"}}`。

### 步骤 5：配置触发条件（工单名称包含 / 任务状态变化）
<!-- step_id: 162-171 -->
点击「添加条件」配置触发条件。可配多组条件，组内「或」关系：
- 条件1：工单名称「包含」`网络不`
- 条件2：任务状态变化为「退回」（rejected）

添加条件、选择「包含」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-118.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-119.png)

输入条件值 `网络不`：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-120.png)

添加第二个条件「工单名称」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-121.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-122.png)

选择「任务状态变化」：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-123.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-124.png)

选择「是」、退回、确定：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-125.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-126.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-127.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-128.png)
> 💡 条件落在 `config.actionList[0].condition`：`{logical: "or", conditionList: [{ruleList:[{variable:"process_instance_name",operator:"=~",value:"网络不"}]}, {ruleList:[{variable:"process_task_status_change",operator:"==",value:"rejected"}]}]}`。

### 步骤 6：保存触发器
<!-- step_id: 172-179 | api: POST .../trigger (CreateTrigger) | tag: 触发器管理 -->
点击「保存」按钮，创建触发器。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-129.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-130.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-131.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-132.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-133.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-134.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-135.png)
> 🔗 本步调用：`POST /next/api/gateway/flowable_service.trigger.CreateTrigger/api/flowable_service/v1/trigger`，body: name/event/status=enabled/scope=process_task/config.actionList（动作+条件）。

## 六、在服务/流程中引用触发器

新建的触发器需在服务管理或流程节点中「引用」才会生效。

### 步骤 1：服务管理设置 - 引用触发器
<!-- url: itsc-service-management/setting-list/{id} | api: PUT (引用触发器) | tag: 触发器引用 | step_id: 180-192 -->
系统管理 → 事件管理 → 触发器 → 更多设置 → 编辑，在「引用触发器」选择触发器（如 `service_trigger_test`），确认保存。
进入服务管理-事件管理：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-136.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-137.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-138.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-139.png)

更多设置 → 编辑：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-140.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-141.png)

引用触发器 → 选择 `service_trigger_test` → 确认：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-142.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-143.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-144.png)
> 🔗 本步调用：`PUT` 引用触发器接口（绑定触发器到服务实例）。

编辑、移除(close)、再次确认（更换为 `工单完成触发器测试` + `test`）：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-145.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-146.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-147.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-148.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-149.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-150.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-151.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-152.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-153.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-154.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-155.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-156.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-157.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-158.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-159.png)

### 步骤 2：流程版本配置 - 为节点配置触发器
<!-- url: itsc-process-manage/{id}/versionCreate-v2/{ver} | step_id: 193-219 -->
进入流程管理 → 打开流程版本配置，在节点（如「测试触发器导入」「变更管理流程_节点触发_生成子工单」）上配置触发器，保存并确定。

进入流程管理、打开流程版本：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-160.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-161.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-162.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-163.png)

保存、确定：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-164.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-165.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-166.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-167.png)

第二个版本同样配置：
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-168.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-169.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-170.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-171.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-172.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-173.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-174.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-175.png)

## 七、删除触发器

### 步骤 1：删除并确认
<!-- step_id: 220-223 | api: DELETE .../trigger/{id} | tag: 触发器管理 -->
回到触发器列表，删除目标触发器，输入校验值（如 `1`）确认。
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-176.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-177.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-179.png)
![](./_assets/ITSM-系统管理-通知触发器管理与配置-操作指引/step-180.png)
> 🔗 本步调用：`DELETE /next/api/gateway/logic.flowable_service/api/flowable_service/v1/trigger/{triggerId}`（路径参数为 triggerId）。

## 附：本流程接口速查

| 操作 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 通知配置列表 | GET | `/next/api/gateway/logic.flowable_service/api/itsc_trigger/v1/notify_policy` | 支持 Q/notifyType/notifyMode/triggerSignal/creator/pageSize |
| 通知配置详情 | GET | `/next/api/gateway/flowable_service.notify_policy.GetNotifyPolicyDetail/api/itsc_trigger/v1/notify_policy/{id}` | 编辑回填 |
| 新建通知配置 | POST | `/next/api/gateway/flowable_service.notify_policy.CreateNotifyPolicy/api/itsc_trigger/v1/notify_policy` | body: name/notifyType/triggerSignal/notifyMode/notifyRange/内容模板 |
| 编辑通知配置 | PUT | `/next/api/gateway/flowable_service.notify_policy.UpdateNotifyPolicy/api/itsc_trigger/v1/notify_policy/{id}` | 同 create body |
| 删除通知配置 | DELETE | `/next/api/gateway/logic.flowable_service/api/itsc_trigger/v1/notify_policy` | query: instanceIds（逗号分隔批量） |
| 通知模式枚举 | GET | `/next/api/gateway/flowable_service.notify_policy.ListEnums/api/itsc_trigger/v1/enums` | query: name=notify_mode |
| 通知类型 | GET | `/next/api/gateway/flowable_service.notify_policy.ListAllNotifyTypeV2/api/itsc_trigger/v2/notify_type` | 通知类型下拉用 |
| 触发器列表 | GET | `/next/api/gateway/logic.flowable_service/api/flowable_service/v1/trigger` | 支持 Q/scope/page |
| 触发器枚举 | GET | `/next/api/gateway/flowable_service.trigger.GetTriggerEnums/api/flowable_service/v1/enums/trigger_enum` | 事件/动作/条件枚举 |
| 新建触发器 | POST | `/next/api/gateway/flowable_service.trigger.CreateTrigger/api/flowable_service/v1/trigger` | body: name/event/status/scope/config.actionList(动作+条件) |
| 删除触发器 | DELETE | `/next/api/gateway/logic.flowable_service/api/flowable_service/v1/trigger/{triggerId}` | 路径参数为 triggerId |
| 引用触发器(服务/流程) | PUT | 服务管理/流程版本设置接口 | 将触发器绑定到服务实例或流程节点 |
