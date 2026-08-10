---
flow: ITSM-运行管理-营业时间管理
system: EasyOps ITSM
system_slug: itsm
host: http://172.30.0.90
module:
  - work-calendar
  - itsc-operation-management
  - itsc-workbench
entry: /next/itsc-workbench/workbench
intent: [营业时间, 营业时间管理, 工作日历, 工作时段, 工作时间, 服务时段, 日历管理, 假期, 节假日, 加班日, 特殊日期, 业务时间, business hours, working calendar, 新建日历, 编辑日历, 删除日历, 运行管理]
api_tags: [营业时间(工作日历)管理]
related: [ITSM-运行管理-SLA协议管理, ITSM-定时工单管理]
---

# ITSM 运行管理 - 营业时间管理 - 操作指引

> 适用场景：在 ITSM「运行管理 / 营业时间管理（工作日历 work-calendar）」中维护**服务时段日历**——定义每周工作日的工作时段、特殊加班日期的时段、节假假期。该日历是 SLA 协议时效计算、定时任务调度等的**时间基准**。本流程覆盖「进入日历列表 → 搜索 → 新建日历（工作日时段/加班日/假期）→ 保存 → 编辑 → 删除」全链路。
> 配套接口：见同目录 [`ITSM-运行管理-营业时间管理-openapi.yaml`](./ITSM-运行管理-营业时间管理-openapi.yaml)。
>
> 与 [`ITSM-运行管理-SLA协议管理`](../ITSM-运行管理-SLA协议管理/ITSM-运行管理-SLA协议管理-操作指引.md) 的关系：SLA 协议在「服务时段」字段引用本流程创建的工作日历（`workingCalendarId`），SLA 时效按所选日历的营业时间累计。
>
> 名词约定：**工作日(workDayList)**=每周固定上班日及其时段；**加班日(extraDayList)**=非工作日但需计时的特殊日期时段；**假期(holidayList)**=不计时间的休息日。
>
> 截图标注图例：🔴红框=点击 / 🔵蓝虚线框=输入 / 🟠橙框+▾=下拉 / 🟣紫圈=单复选 / 🟢绿粗框=提交。

## 目录
- [一、进入营业时间管理](#一进入营业时间管理)
- [二、列表搜索](#二列表搜索)
- [三、新建工作日历](#三新建工作日历)
- [四、编辑工作日历](#四编辑工作日历)
- [五、删除工作日历](#五删除工作日历)
- [附：本流程接口速查](#附本流程接口速查)

<!-- deep-links: 本流程关键页面直达（SPA 路径，去掉 host 前缀，参数化）
  工作台:       itsc-workbench/workbench
  日历列表:      work-calendar/list
  新建日历:      work-calendar/create-calendar
  日历详情:      work-calendar/detail/{calendarId}
  编辑日历:      work-calendar/edit/{calendarId}?editingDate={year}
-->

## 一、进入营业时间管理

从工作台导航到「营业时间管理（工作日历）」列表页（`work-calendar/list`）。

### 步骤 1：在工作台点击「系统管理」
<!-- url: itsc-workbench/workbench | step_id: 1 -->
在工作台点击「系统管理」入口。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-01.png)

### 步骤 2：进入营业时间管理菜单
<!-- url: work-calendar/list | step_id: 2-3 -->
在系统管理菜单点击「营业时间管理」（运行管理下），进入工作日历列表页。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-02.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-03.png)
> 🔗 本步调用：`GET /next/api/gateway/logic.sys_setting/api/sys_setting/v1/query/work/calendar`（详见 openapi.yaml），同时加载 work-calendar 微应用。

## 二、列表搜索

按日历名称或创建人模糊搜索。

### 步骤 1：搜索日历
<!-- url: work-calendar/list?page=1&q=假日 | step_id: 4-5 -->
在搜索框输入关键词（如 `假日`），列表按日历名称模糊匹配。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-14.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-15.png)
> 🔗 本步调用：`GET .../query/work/calendar?Q=假日`。

## 三、新建工作日历

点击「新建」打开日历配置页，依次配置工作日时段、加班日、假期后保存。

### 步骤 1：点击「新建」
<!-- url: work-calendar/create-calendar | step_id: 6 -->
在列表页点击「新建」按钮，进入新建日历页。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-16.png)

### 步骤 2：输入日历名称
<!-- step_id: 7 -->
在日历名称输入框填写名称（如 `test`）。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-26.png)

### 步骤 3：配置工作日时段（workDayList）
<!-- step_id: 8-18 -->
选择工作日（如「周三」），为其添加工作时段：上午 09:00~12:00、下午 14:00~17:00（通过时间选择器点选小时后「确定」）。

选择工作日「周三」：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-27.png)

设置上午开始 09:00：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-28.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-29.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-30.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-31.png)

设置上午结束 12:00：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-32.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-33.png)

设置下午开始 14:00：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-34.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-35.png)

设置下午结束 17:00：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-36.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-37.png)
> 💡 工作日时段最终落在 `config.workDayList`：`{weekday: 3, hours: "09:00~12:00,14:00~17:00"}`（weekday 1=周一…7=周日）。

### 步骤 4：配置加班日时段（extraDayList）
<!-- step_id: 19-27 -->
点击「添加」增加加班日，选择日期区间（如 8 月 1 日至 31 日），设置加班时段（如 18:00~22:00）。

点击「添加」加班日：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-38.png)

选择起止日期（1 日 ~ 31 日）：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-39.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-40.png)

点击 plus-circle 添加时段：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-41.png)

设置加班时段 18:00~22:00：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-42.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-43.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-44.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-45.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-46.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-47.png)
> 💡 加班日最终落在 `config.extraDayList`：`{from: "2026-08-01", to: "2026-08-31", hours: "18:00~22:00"}`。

### 步骤 5：配置假期（holidayList）
<!-- step_id: 28-34 -->
点击「添加」增加假期，输入假期名称（如 `国庆`），选择假期日期区间（如 10 月 1 日至 7 日）。假期无需时段（休息日）。

> ⚠️ 假期名称输入过程不截图（step-29 逐字符录入，最终值 `国庆`）。
假期名称输入完成：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-57.png)

选择假期日期区间（10-01 ~ 10-07）：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-58.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-59.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-60.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-61.png)
> 💡 假期最终落在 `config.holidayList`：`{memo: "国庆", from: "2026-10-01", to: "2026-10-07", hours: ""}`。

### 步骤 6：保存日历
<!-- step_id: 35 | api: POST .../work/calendar | tag: 营业时间(工作日历)管理 -->
点击「保存」按钮，创建工作日历。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-62.png)
> 🔗 本步调用：`POST /next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar`（详见 openapi.yaml），body 为 `{config: {workDayList, extraDayList, holidayList, mode: "simple"}}`。创建成功后返回 `calendarId`，并拉取详情 `GET .../work/calendar/{id}`、月视图 `GET .../work/calendar_month/{id}`、年视图 `GET .../work/calendar_year/{id}`。

## 四、编辑工作日历

从列表进入某日历的编辑页，修改配置后保存。

### 步骤 1：点击日历进入详情
<!-- url: work-calendar/detail/{id} | api: GET .../work/calendar/{id} | tag: 营业时间(工作日历)管理 | step_id: 36 -->
在列表点击目标日历（如 `test`），进入详情页。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-63.png)
> 🔗 本步调用：`GET .../work/calendar/{calendarId}`（回填详情）。

### 步骤 2：进入编辑，添加新假期
<!-- url: work-calendar/edit/{id}?editingDate=2026 | step_id: 37-40 -->
点击「编辑」，进入编辑页。点击「添加」增加新假期，输入假期名称（如 `51`）。

点击「编辑」：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-64.png)

点击「添加」假期：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-65.png)

> ⚠️ 假期名称 `51` 输入过程不截图（step-39 逐字符录入）。
假期名称输入完成：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-75.png)

### 步骤 3：选择假期日期并保存
<!-- step_id: 41-51 | api: PUT .../work/calendar/{id} | tag: 营业时间(工作日历)管理 -->
选择新假期的日期区间（如 5 月 1 日至 7 日），点击「保存」提交编辑。

选择假期日期：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-76.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-77.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-78.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-79.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-80.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-81.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-82.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-83.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-85.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-86.png)

点击「保存」：
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-87.png)
> 🔗 本步调用：`PUT /next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar/{calendarId}`，body 结构同 create。

## 五、删除工作日历

在列表删除某条日历。

### 步骤 1：删除并确认
<!-- step_id: 52-54 | api: DELETE .../work/calendar/{id} | tag: 营业时间(工作日历)管理 -->
点击「删除」，在确认操作中输入校验值（如 `1`）后点击「删除」确认。
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-88.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-89.png)
![](./_assets/ITSM-运行管理-营业时间管理-操作指引/step-90.png)
> 🔗 本步调用：`DELETE /next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar/{calendarId}`（路径参数为 calendarId）。

## 附：本流程接口速查

| 操作 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 日历列表 | GET | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/query/work/calendar` | 支持 Q 关键词、page/pageSize |
| 日历详情 | GET | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar/{calendarId}` | 编辑表单回填 |
| 月视图 | GET | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar_month/{calendarId}` | query: month、year，按月展示特殊日期 |
| 年视图 | GET | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar_year/{calendarId}` | query: year，按年展示 |
| 新建日历 | POST | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar` | body: `{config: {workDayList, extraDayList, holidayList, mode}}` |
| 编辑日历 | PUT | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar/{calendarId}` | 同 create body |
| 删除日历 | DELETE | `/next/api/gateway/logic.sys_setting/api/sys_setting/v1/work/calendar/{calendarId}` | 路径参数为 calendarId |
