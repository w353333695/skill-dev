# 同步CCPC值班表 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 开发 EasyOps autoops 定时工具 `sync_ccpc_duty.py`，把 CCPC 值班表同步到 EasyOps ITSM 值班组日历配置（upsert 幂等、班次动态分析、班次变更自动更新）。

**Architecture:** 单文件自包含脚本（py2/3 兼容，stdlib http 直连 easyops 8134 + urllib 拉 CCPC）。前置 onboarding 任务把 duty_group_config 三端点契约沉淀进 platforms（easyops-itsm.yaml + objects.yaml），成品回流 hub。测试：fixture 模式（CCPC 不可达）+ .26 真环境端到端。

**Tech Stack:** Python（py2.7 兼容写法 + py3 测试）、api-orchestrator lint-platforms.py、EasyOps autoops tool API（8181）、flowable_service（8134）

**Spec:** `projects/ccpc-duty/docs/sync-ccpc-duty-design.md`

## Global Constraints

- py2/3 兼容：`IS_PY2 = sys.version_info[0] == 2`、不用 f-string、`u''` 字面量、logging 不直接 print、except 不带 from（platforms systems.yaml platform_conventions.code）
- 脚本自包含：不 import 项目内其他 .py、不用第三方包（agent py2 无 pip）
- easyops 直连鉴权：org/user/Host(admin.easyops.local) 三件 header，免 cookie（systems.yaml platform_conventions.auth）
- 角色映射（固定）：CCPC `dutys`→`users`；`maintainer`+`leader` → `leader`（顺序：先 maintainer 后 leader）
- 班次动态分析：不写死白/夜班，从 CCPC 数据归纳 `{shiftName → "startTime~endTime"}`，同名不同时段以数据中最后出现的为准
- dutyCycle 未来一百年：`"{今年}-01~{今年+100}-12"`
- upsert 幂等：已有配置人员一致→skip；不一致→PUT `/v1/duty_group_config/{configId}`；无→POST
- CCPC 某日无数据→跳过该日（不删已有配置）；单日失败不中断整轮
- 工作目录 `tmp/ccpc-duty/`（gitignore 内）；平台资料改动后 lint 必须 0 ERR（当前基线 45 OK/6 WARN/0 ERR）
- 改完代码立即手动 commit（javis 会自动 chore(ai) 抢提交）

---

### Task 1: onboarding —— duty_group_config 契约沉淀进 platforms

**Files:**
- Modify: `/workspace/skills/api-orchestrator/platforms/easyops/easyops-itsm.yaml`（duty_group 资源块内，约 1177-1296 行，新增 duty_group_config 资源）
- Modify: `/workspace/skills/api-orchestrator/platforms/easyops/objects.yaml`（978-1005 行 itsm_duty_group 对象后新增 itsm_duty_group_config 对象）
- 同步镜像：`/workspace/.api-orchestrator/platforms/easyops/`（部署根同名文件，diff 确认当前 SAME，改完 cp 同步）

**Interfaces:**
- Produces: platforms 知识（供 Task 3 工具实现背书 + lint 引用闭合：itsm.yaml 新资源 `duty_group_config` 的 api 键、objects.yaml 新对象 `itsm_duty_group_config` 的 `api: duty_group_config` 引用）

**数据源**（本轮已挖出的源码事实，直接用）：
- 路由 `duty_group/route.go`：POST `/api/flowable_service/v1/duty_group_config`（create）、PUT `/v1/duty_group_config/:configId`（update）、POST `/v1|v2/duty_group_config/search`
- validator `request_validate_trees.go`：create 必填 `groupId/date/status(int)`；update 必填 `configId/date/status(int)/dutyShiftConf(object[])`；search v1/v2 必填 `date`
- service `duty_group_service.go:861-907`：create 后端自动 `SyncDutyDays`（同步值班数据+法定假日判断）；config 名=`groupId_date`
- service `duty_group_service.go:929-903`：update 若原配置 date≠请求 date → 后端自动转 create
- service `duty_group_service.go:985-1042`：search 先按 `{$or:[{name:groupName},{instanceId:groupId}]}` 查组，**total≠1 即 500 "查询值班日历信息失败"**；dutyCycle 结束月<查询月→空 list；date 粒度 YYYY/YYYY-MM/YYYY-MM-DD（日→查到当月底）
- `converter.go:1360-1368`：dutyShiftConf item = `{name, users[], leader[]}`
- v2 search 响应 List：`{instanceId, name, date, dateStatus, dutyMode, dutyShiftConf[{name, leader[{name,nickname,userTel}], users[...], dutyTime}]}`（v2 会 user 服务补 nickname/tel）
- create 响应：`{code, data: {instanceId}}`
- ⚠️ 实测坑（.26 复现）：无值班组时 v2 search 直接 500（不是空列表）

- [ ] **Step 1: easyops-itsm.yaml 新增 duty_group_config 资源**

在 duty_group 资源块末尾（delete operation 之后、下一个资源之前）插入：

```yaml

  # ---------------------------------------------------------------------------
  # 资源：duty_group_config —— 值班组日历配置（某天谁值班）。
  # 8134 flowable_service。create 名=groupId_date；创建后自动 SyncDutyDays
  # 同步值班数据。update 若 date 变化后端自动转 create。search 按
  # groupName/groupId 精确命中组（≠1 个→500），date 支持 YYYY/YYYY-MM/YYYY-MM-DD
  # 三粒度（日→查到当月底）。v2 search 额外经 user 服务补 nickname/userTel。
  # 数据源：后端源码 duty_group/{route.go, duty_group_service.go:861-1180,
  # validators/request_validate_trees.go} + .26 实测（无组时 500 复现）。
  # 2026-09-15 随「同步CCPC值班表」工具 onboarding 纳入。
  # ---------------------------------------------------------------------------
  duty_group_config:
    description: ITSM 值班组日历配置——定义某日期各班次的值班人(users)/值班领导(leader)。config 名=groupId_date。被 SyncDutyDays 展开成值班数据供排班/通知引用。
    path: ""

    operations:
      search_v2:
        description: 按组+日期查日历配置（v2，user 信息增强）。⚠️组必须按 groupName/groupId 恰好命中 1 个（total≠1 报 500 "查询值班日历信息失败"）；dutyCycle 结束月<查询月返回空 list。date 三粒度：YYYY/YYYY-MM/YYYY-MM-DD（日→查到当月底闭区间）。
        method: POST
        path: /api/flowable_service/v2/duty_group_config/search
        body:
          type: object
          required: [date]
          properties:
            groupName: { type: string, description: "值班组名（与 groupId 二选一）" }
            groupId:   { type: string, description: "值班组 id 13hex（与 groupName 二选一）" }
            date:      { type: string, description: "日期，YYYY / YYYY-MM / YYYY-MM-DD" }
            isMine:    { type: boolean, description: "只看我的（按 header user 过滤 users/leader）" }
        response:
          type: object
          description: "{ code, data: { list[] } }——list item 见 get 响应（v2 的 users/leader 是 {name,nickname,userTel} 对象数组，dutyShiftConf 多 dutyTime）"

      create:
        description: 新建某日配置。后端自动 SyncDutyDays（值班数据+法定假日）；config 名=groupId_date；同组同日重复 create 会产生重复 config（幂等靠先 search）。update 时 date 变化后端自动转此接口。
        method: POST
        path: /api/flowable_service/v1/duty_group_config
        body:
          type: object
          required: [groupId, date, status]
          properties:
            groupId:    { type: string, description: "值班组 id 13hex" }
            date:       { type: string, description: "日期 YYYY-MM-DD" }
            status:     { type: integer, description: "日历状态（int；工具 sync_ccpc_duty 实测语义待校准，默认 0）" }
            dutyShiftConf:
              type: array
              description: "班次配置列表"
              items:
                type: object
                properties:
                  name:   { type: string, description: "班次名（须与值班组 dutyShift.name 一致）" }
                  users:  { type: array, items: { type: string }, description: "值班人 username 列表" }
                  leader: { type: array, items: { type: string }, description: "值班领导 username 列表" }
            dutyMode:         { type: string, description: "重复模式（空=无重复）" }
            handOverNotifyId: { type: string, description: "交班通知模版 id" }
            takeOverNotifyId: { type: string, description: "接班通知模版 id" }
        response:
          type: object
          description: "{ code, data: { instanceId } }"

      update:
        description: 更新某日配置（全量）。⚠️若原配置 date≠请求 date，后端自动转新建（不删旧的）。configId 从 search_v2 结果取。
        method: PUT
        path: /api/flowable_service/v1/duty_group_config/{configId}
        params:
          configId: { in: path, type: string, required: true, description: "配置 id 13hex" }
        body:
          type: object
          required: [configId, date, status, dutyShiftConf]
          properties:
            configId:    { type: string, description: "配置 id 13hex" }
            date:        { type: string, description: "日期 YYYY-MM-DD" }
            status:      { type: integer, description: "同 create" }
            dutyShiftConf:
              type: array
              description: "班次配置列表（结构同 create）"
              items:
                type: object
                properties:
                  name:   { type: string }
                  users:  { type: array, items: { type: string } }
                  leader: { type: array, items: { type: string } }
```

- [ ] **Step 2: objects.yaml 新增 itsm_duty_group_config 对象**

在 `itsm_duty_group` 对象的 `side_effects` 列表之后（约 1005 行）、下一个对象 `sys_setting_work_calendar` 之前插入：

```yaml

  # ---------- ITSM 值班组日历配置（duty_group_config）----------
  itsm_duty_group_config:
    description: ITSM 值班组日历配置——某日期各班次 {name, users[], leader[]}。config 名=groupId_date；create 后自动 SyncDutyDays 展开值班数据。sync 类工具的幂等锚点（先 search 再 create/update）。
    source: data/sources/backend/ITSM/flowable_service/duty_group/{duty_group_service.go:861-1180, validators/request_validate_trees.go, internal/duty_group/models.go} + .26 实测（2026-09-15）
    api: duty_group_config
    fields:
      instanceId:    { type: string, anchor: true, desc: "配置 id（13hex）" }
      name:          { type: string, desc: "配置名，= groupId_date（后端拼）" }
      date:          { type: string, required: true, desc: "日期 YYYY-MM-DD" }
      status:        { type: integer, required: true, desc: "日历状态 int（语义未完全确认，工具默认 0）" }
      dutyShiftConf: { type: array, items: object, desc: "班次配置 [{name, users[](值班人 username), leader[](值班领导 username)}]。name 须与值班组 dutyShift.name 一致" }
      dutyMode:      { type: string, desc: "重复模式（空=无重复，非空时 search 会按 date<=查询日 展开）" }
      fbFormInstanceId: { type: string, desc: "表单构建器表单实例 id（useFormBuilder=true 时）" }
    relations:
      - { to: itsm_duty_group, type: association, cardinality: "N:1", desc: "属某值班组（groupId）；组删除级联失效" }
    api_behavior:
      search_total_must_be_1: "search v1/v2 先按 groupName/groupId 查组，total≠1（0 个或多个同名）直接 500『查询值班日历信息失败』——排查时先 GET /v1/duty_group?name= 确认组唯一（.26 无组时复现）"
      update_date_shift: "update 时原配置 date≠请求 date → 后端自动转 create 新配置（旧的不删），并非改期"
      sync_duty_days: "create/update 成功后自动 SyncDutyDays（按法定假日日历展开值班数据），无需手动触发"
    side_effects:
      - op: duty_group_config.create
        rule: "POST /v1/duty_group_config。groupId/date/status 必填。同组同日重复 create 产生重复 config——同步工具必须先 search 判重"
```

- [ ] **Step 3: 同步部署根镜像 + lint 验证**

```bash
cp /workspace/skills/api-orchestrator/platforms/easyops/easyops-itsm.yaml /workspace/.api-orchestrator/platforms/easyops/easyops-itsm.yaml
cp /workspace/skills/api-orchestrator/platforms/easyops/objects.yaml /workspace/.api-orchestrator/platforms/easyops/objects.yaml
python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py easyops 2>&1 | tail -1
```

Expected: `合计: 46 OK, 6 WARN, 0 ERR`（OK +1，WARN 不增，ERR=0）

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add skills/api-orchestrator/platforms/easyops/easyops-itsm.yaml skills/api-orchestrator/platforms/easyops/objects.yaml && git commit -m "feat(api-orchestrator): onboarding duty_group_config 契约（v2 search/create/update）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

（.api-orchestrator/ 在 gitignore，只提交 skill 侧）

---

### Task 2: 工具核心逻辑 + fixture 单测（纯函数层）

**Files:**
- Create: `/workspace/tmp/ccpc-duty/sync_ccpc_duty.py`（开发态在 tmp，Task 4 终态回流 hub）
- Create: `/workspace/tmp/ccpc-duty/test_sync_ccpc_duty.py`（py3 unittest，import 同目录模块）
- Read（测试输入）: `/workspace/tmp/ccpc-dutys.txt`（CCPC 响应样例，第 2 行 response: 后的 JSON）

**Interfaces:**
- Produces（Task 3/4 依赖，函数名精确）:
  - `analyze_shifts(days) -> list[{name, dutyTime}]`：days=CCPC 响应数组；按 shiftName 归纳，同名不同时段取最后出现；返回 easyops duty_group.dutyShift 结构
  - `build_shift_conf(day) -> list[dict]`：单日 CCPC 数据 → dutyShiftConf；`{name: shiftName, users: dutys.uids, leader: maintainer.uids + leader.uids}`（members 按 field 匹配；缺角色=空数组）
  - `date_range(n) -> list[str]`：今天起 n 天 `YYYY-MM-DD` 列表
  - `duty_cycle_100y() -> str`：`"{今年}-01~{今年+100}-12"`
  - `conf_equal(a, b) -> bool`：dutyShiftConf 深比较（顺序敏感）
  - `fetch_ccpc(ip, group_id, start, end) -> list`：http 层（Task 3 mock 它）；fixture 模式读文件
  - `parse_args(argv) -> dict`：四入参 ccpc_ip/ccpc_group_id/duty_group_name/sync_days（globals 注入>env>argv>默认，同 alert2ticket 模式）
  - `http_json(method, path, body) -> (status, parsed)`：easyops 8134 直连（Task 3 mock 它）

- [ ] **Step 1: 写失败测试（fixture 解析 + 班次归纳 + 映射）**

```python
# -*- coding: utf-8 -*-
"""sync_ccpc_duty 纯函数层单测（py3）。fixture 来自 tmp/ccpc-dutys.txt 真实响应样例。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_ccpc_duty as m

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(os.path.dirname(HERE), 'ccpc-dutys.txt')


def load_fixture():
    with open(FIXTURE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('response: '):
                return json.loads(line[len('response: '):].strip())
    raise AssertionError('fixture response line not found')


class TestAnalyzeShifts(unittest.TestCase):
    def setUp(self):
        self.days = load_fixture()

    def test_two_shifts_day_night(self):
        shifts = m.analyze_shifts(self.days)
        self.assertEqual(
            [{'name': u'白班', 'dutyTime': '08:00~19:00'},
             {'name': u'夜班', 'dutyTime': '19:00~08:00'}],
            shifts)

    def test_shift_change_takes_last(self):
        days = [
            {'date': '2026-09-01', 'shifts': [
                {'shiftName': '白班', 'startTime': '08:00', 'endTime': '19:00', 'members': []}]},
            {'date': '2026-09-02', 'shifts': [
                {'shiftName': '白班', 'startTime': '09:00', 'endTime': '18:00', 'members': []}]},
        ]
        self.assertEqual([{'name': u'白班', 'dutyTime': '09:00~18:00'}], m.analyze_shifts(days))

    def test_empty(self):
        self.assertEqual([], m.analyze_shifts([]))


class TestBuildShiftConf(unittest.TestCase):
    def setUp(self):
        self.days = load_fixture()

    def test_role_mapping(self):
        conf = m.build_shift_conf(self.days[0])
        self.assertEqual(2, len(conf))
        self.assertEqual({u'name': u'白班', 'users': [u'tianyaqiong'],
                          'leader': [u'liuzhenlin', u'luchao']}, conf[0])
        self.assertEqual({u'name': u'夜班', 'users': [u'chenchen'],
                          'leader': [u'liuzhenlin', u'luchao']}, conf[1])

    def test_missing_role_empty(self):
        day = {'date': '2026-09-01', 'shifts': [
            {'shiftName': '白班', 'startTime': '08:00', 'endTime': '19:00',
             'members': [{'field': 'dutys', 'name': '值班人员', 'uids': ['a']}]}]}
        self.assertEqual([{u'name': u'白班', 'users': ['a'], 'leader': []}],
                         m.build_shift_conf(day))

    def test_no_day_data(self):
        self.assertIsNone(m.build_shift_conf(None))


class TestMisc(unittest.TestCase):
    def test_date_range(self):
        dates = m.date_range(3)
        import datetime
        today = datetime.date.today()
        self.assertEqual(3, len(dates))
        self.assertEqual(today.strftime('%Y-%m-%d'), dates[0])
        self.assertEqual((today + datetime.timedelta(days=2)).strftime('%Y-%m-%d'), dates[2])

    def test_duty_cycle_100y(self):
        import datetime
        y = datetime.date.today().year
        self.assertEqual('%d-01~%d-12' % (y, y + 100), m.duty_cycle_100y())

    def test_conf_equal(self):
        a = [{'name': u'白班', 'users': ['x'], 'leader': ['y']}]
        self.assertTrue(m.conf_equal(a, [{'name': u'白班', 'users': ['x'], 'leader': ['y']}]))
        self.assertFalse(m.conf_equal(a, [{'name': u'白班', 'users': ['z'], 'leader': ['y']}]))
        self.assertFalse(m.conf_equal(a, []))


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        cfg = m.parse_args([])
        self.assertEqual({'ccpc_ip': '127.0.0.1',
                          'ccpc_group_id': '8882eec490c54bacb382c5e859f20f05',
                          'duty_group_name': u'告警值班组',
                          'sync_days': 30}, cfg)

    def test_argv(self):
        cfg = m.parse_args(['ccpc_ip=1.2.3.4', 'sync_days=7'])
        self.assertEqual('1.2.3.4', cfg['ccpc_ip'])
        self.assertEqual(7, cfg['sync_days'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /workspace/tmp/ccpc-duty && python3 test_sync_ccpc_duty.py
```

Expected: `ImportError: cannot import name 'sync_ccpc_duty'`（模块不存在）

- [ ] **Step 3: 写纯函数实现（http 层先放占位真实现）**

创建 `sync_ccpc_duty.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EasyOps 工具：同步CCPC值班表（CCPC 值班表 → ITSM 值班组日历配置）

入参：
    ccpc_ip          CCPC 地址，字符串，默认 127.0.0.1（端口固定 8880）
    ccpc_group_id    CCPC 值班组 id，字符串，默认 8882eec490c54bacb382c5e859f20f05
    duty_group_name  EasyOps 值班组名称，字符串，默认 告警值班组
    sync_days        同步今天起 N 天，整数，默认 30

逻辑：
    1) 拉 CCPC 今天起 N 天值班表（/api/dutys/schedule/public）
    2) 动态归纳班次（shiftName → startTime~endTime，不写死白/夜班）
    3) ensure 值班组：无则建（dutyCycle 未来一百年）；班次定义变更则 PUT 更新
    4) 逐日 upsert 日历配置：dutys→users；maintainer+leader→leader
       （已有且人员一致 skip；不一致 PUT；无 POST）

运行环境：EasyOps agent（py2，stdlib only）或编排侧 py3。
鉴权：org/user header 直连后端（免 cookie）。
输出：PutStr 回吐进度与统计（agent 工具模式下可见）。
"""
import datetime
import json
import logging
import os
import sys

if sys.version_info[0] == 2:
    import httplib as _http_client
    import urllib2 as _urllib_request
else:
    import http.client as _http_client
    import urllib.request as _urllib_request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('sync_ccpc_duty')

IS_PY2 = sys.version_info[0] == 2

CCPC_PORT = 8880
FLOWABLE_PORT = 8134               # logic.flowable_service

HOST = ''
ORG = ''
USER = ''


def _resolve_conn():
    """运行时解析连接参数（平台 globals 注入 > env；同 alert2ticket 模式）。"""
    global HOST, ORG, USER
    g = globals()
    for var in ('EASYOPS_ITSM_BACKEND_URL', 'EASYOPS_CMDB_BACKEND_URL',
                'EASYOPS_CMDB_SERVICE_HOST', 'EASYOPS_HOST'):
        v = g.get(var) or os.environ.get(var, '')
        if v:
            HOST = v.replace('http://', '').replace('https://', '').split(':')[0].strip()
            break
    ORG = str(g.get('EASYOPS_ORG') or os.environ.get('EASYOPS_ORG') or '1888')
    USER = str(g.get('EASYOPS_USER') or os.environ.get('EASYOPS_USER') or 'easyops')


def http_json(method, path, body=None, timeout=30):
    """直连 flowable_service:8134（stdlib，py2/3 兼容）。返回 (status, parsed_json_or_text)。"""
    conn = _http_client.HTTPConnection(HOST, FLOWABLE_PORT, timeout=timeout)
    data = json.dumps(body) if body is not None else None
    headers = {'org': ORG, 'user': USER, 'Host': 'admin.easyops.local',
               'Content-Type': 'application/json'}
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
    finally:
        conn.close()
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def put_str(message):
    logger.info(message)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 纯函数层
# ---------------------------------------------------------------------------
def date_range(n):
    """今天起 n 天 YYYY-MM-DD 列表。"""
    today = datetime.date.today()
    return [(today + datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n)]


def duty_cycle_100y():
    """值班周期：今年 1 月 ~ 今年+100 年 12 月。"""
    y = datetime.date.today().year
    return '%d-01~%d-12' % (y, y + 100)


def analyze_shifts(days):
    """CCPC 响应 → easyops dutyShift 定义列表。

    按 shiftName 归纳 {name → startTime~endTime}；同名不同时段以最后出现为准。
    """
    seen = {}
    order = []
    for day in days or []:
        for shift in day.get('shifts') or []:
            name = shift.get('shiftName') or ''
            if not name:
                continue
            if name not in seen:
                order.append(name)
            seen[name] = '%s~%s' % (shift.get('startTime') or '', shift.get('endTime') or '')
    return [{'name': name, 'dutyTime': seen[name]} for name in order]


def build_shift_conf(day):
    """单日 CCPC 数据 → dutyShiftConf。

    角色映射：dutys→users；maintainer+leader→leader（顺序固定）。
    返回 None 表示该日无数据（跳过）。
    """
    if not day or not day.get('shifts'):
        return None
    conf = []
    for shift in day.get('shifts') or []:
        users, leader = [], []
        for mem in shift.get('members') or []:
            field = mem.get('field')
            uids = [u for u in (mem.get('uids') or []) if u]
            if field == 'dutys':
                users.extend(uids)
            elif field == 'maintainer':
                leader.extend(uids)
            elif field == 'leader':
                leader.extend(uids)
        conf.append({'name': shift.get('shiftName') or '', 'users': users, 'leader': leader})
    return conf


def conf_equal(a, b):
    """dutyShiftConf 深比较（顺序敏感——班次顺序也是配置的一部分）。"""
    return a == b
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /workspace/tmp/ccpc-duty && python3 test_sync_ccpc_duty.py -v
```

Expected: 全部 PASS（11 个测试）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tmp/ccpc-duty/ 2>/dev/null; git commit -m "feat(ccpc-duty): 班次归纳/角色映射/日期序列纯函数+单测

Co-Authored-By: Claude <noreply@anthropic.com>" --allow-empty
```

注意：tmp/ 在 gitignore，commit 可能空——用 `--allow-empty` 留痕，或跳过本步 commit（tmp 产物不入库，最终以 Task 4 hub 回流为准）。

---

### Task 3: CCPC 拉取 + easyops ensure/upsert 编排层

**Files:**
- Modify: `/workspace/tmp/ccpc-duty/sync_ccpc_duty.py`（追加编排层）
- Modify: `/workspace/tmp/ccpc-duty/test_sync_ccpc_duty.py`（追加 mock http 单测）

**Interfaces:**
- Consumes: Task 2 的 `http_json/fetch_ccpc/parse_args/analyze_shifts/build_shift_conf/date_range/duty_cycle_100y/conf_equal`
- Produces:
  - `fetch_ccpc(ip, group_id, start, end, fixture=None) -> list`：fixture 非 None 时读文件（`response: ` 行解析），否则 urllib GET；非 200/非 list 抛 RuntimeError
  - `ensure_duty_group(name, shifts) -> (group_id, created_or_updated_desc)`：查/建/更新值班组
  - `upsert_day(group_id, group_name, date, want_conf) -> str`：返回 'created'/'updated'/'skipped'/'failed:<msg>'
  - `main(argv) -> int`

- [ ] **Step 1: 写失败测试（mock http 层）**

test_sync_ccpc_duty.py 追加：

```python
class FakeResp(object):
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def read(self):
        return json.dumps(self.payload).encode('utf-8')


class TestFetchCcpcFixture(unittest.TestCase):
    def test_fixture_mode(self):
        days = m.fetch_ccpc('x', 'g', '2026-09-01', '2026-09-30',
                            fixture=FIXTURE)
        self.assertTrue(days)
        self.assertEqual('2026-09-01', days[0]['date'])

    def test_fixture_file_missing(self):
        with self.assertRaises(RuntimeError):
            m.fetch_ccpc('x', 'g', 'a', 'b', fixture='/nonexistent.json')


class TestUpsertDay(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_http(method, path, body=None, timeout=30):
            self.calls.append((method, path, body))
            if path.startswith('/api/flowable_service/v2/duty_group_config/search'):
                if body.get('date') == '2026-09-15':
                    return 200, {'code': 0, 'data': {'list': [
                        {'instanceId': 'cfg0000000001', 'date': '2026-09-15',
                         'dutyShiftConf': [{'name': u'白班', 'users': [u'x'],
                                            'leader': [u'y']}]}]}}
                return 200, {'code': 0, 'data': {'list': []}}
            if path.startswith('/api/flowable_service/v1/duty_group_config/'):
                return 200, {'code': 0, 'data': {}}
            return 200, {'code': 0, 'data': {}}

        self.orig_http = m.http_json
        m.http_json = fake_http

    def tearDown(self):
        m.http_json = self.orig_http

    def test_skip_when_equal(self):
        conf = [{'name': u'白班', 'users': [u'x'], 'leader': [u'y']}]
        self.assertEqual('skipped', m.upsert_day('g1', u'组', '2026-09-15', conf))
        self.assertEqual(1, len(self.calls))          # 只 search，没写

    def test_update_when_diff(self):
        conf = [{'name': u'白班', 'users': [u'z'], 'leader': [u'y']}]
        self.assertEqual('updated', m.upsert_day('g1', u'组', '2026-09-15', conf))
        self.assertEqual('PUT', self.calls[-1][0])

    def test_create_when_absent(self):
        conf = [{'name': u'白班', 'users': [u'x'], 'leader': []}]
        self.assertEqual('created', m.upsert_day('g1', u'组', '2026-09-16', conf))
        self.assertTrue(any(c[0] == 'POST' and c[1].endswith('/v1/duty_group_config')
                            for c in self.calls))


class TestEnsureDutyGroup(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.resp_queue = []

        def fake_http(method, path, body=None, timeout=30):
            self.calls.append((method, path, body))
            if self.resp_queue:
                return self.resp_queue.pop(0)
            return 200, {'code': 0, 'data': {}}

        self.orig_http = m.http_json
        m.http_json = fake_http

    def tearDown(self):
        m.http_json = self.orig_http

    def test_create_when_absent(self):
        self.resp_queue = [
            (200, {'code': 0, 'data': {'list': [], 'total': 0}}),
            (200, {'code': 0, 'data': {'instanceId': 'newgroup00001'}}),
        ]
        shifts = [{'name': u'白班', 'dutyTime': '08:00~19:00'}]
        gid, desc = m.ensure_duty_group(u'告警值班组', shifts)
        self.assertEqual('newgroup00001', gid)
        create_call = [c for c in self.calls if c[1].endswith('/v1/duty_group') and c[0] == 'POST']
        self.assertEqual(1, len(create_call))
        self.assertEqual(duty_cycle_expect(), create_call[0][2]['dutyCycle'])

    def test_no_change_when_shifts_equal(self):
        self.resp_queue = [
            (200, {'code': 0, 'data': {'list': [
                {'instanceId': 'existgroup001', 'name': u'告警值班组',
                 'dutyShift': [{'name': u'白班', 'dutyTime': '08:00~19:00'}]}], 'total': 1}}),
        ]
        gid, desc = m.ensure_duty_group(u'告警值班组',
                                        [{'name': u'白班', 'dutyTime': '08:00~19:00'}])
        self.assertEqual('existgroup001', gid)
        self.assertFalse(any(c[0] == 'PUT' for c in self.calls))

    def test_update_when_shifts_diff(self):
        self.resp_queue = [
            (200, {'code': 0, 'data': {'list': [
                {'instanceId': 'existgroup001', 'name': u'告警值班组',
                 'dutyShift': [{'name': u'白班', 'dutyTime': '08:00~12:00'}]}], 'total': 1}}),
        ]
        gid, desc = m.ensure_duty_group(u'告警值班组',
                                        [{'name': u'白班', 'dutyTime': '08:00~19:00'}])
        self.assertEqual('existgroup001', gid)
        put_calls = [c for c in self.calls if c[0] == 'PUT']
        self.assertEqual(1, len(put_calls))


def duty_cycle_expect():
    import datetime as _d
    y = _d.date.today().year
    return '%d-01~%d-12' % (y, y + 100)
```

- [ ] **Step 2: 跑测试确认新用例失败**

```bash
cd /workspace/tmp/ccpc-duty && python3 test_sync_ccpc_duty.py -v 2>&1 | tail -5
```

Expected: FAIL/ERROR——`fetch_ccpc`/`ensure_duty_group`/`upsert_day` 不存在（AttributeError）

- [ ] **Step 3: 实现编排层**

sync_ccpc_duty.py 追加（在 conf_equal 之后）：

```python
# ---------------------------------------------------------------------------
# 入参解析（EasyOps 工具入参经 argv：key=value；或模块级调用）
# ---------------------------------------------------------------------------
def parse_args(argv):
    """入参优先级：globals 注入 > env 同名 > argv k=v > 默认值（同 alert2ticket 模式）。"""
    cfg = {'ccpc_ip': '127.0.0.1',
           'ccpc_group_id': '8882eec490c54bacb382c5e859f20f05',
           'duty_group_name': u'告警值班组',
           'sync_days': 30}

    def _coerce(key, val):
        if val in (None, ''):
            return
        if key == 'sync_days':
            try:
                cfg[key] = int(val)
            except (TypeError, ValueError):
                pass
        else:
            cfg[key] = _to_unicode(val).strip() if hasattr(val, 'strip') else str(val)

    g = globals()
    for k in cfg:
        if k in g and g[k] not in (None, ''):
            _coerce(k, g[k])
    for k in cfg:
        _coerce(k, os.environ.get(k) or os.environ.get(k.upper()))
    ti = os.environ.get('EASYOPS_TOOL_INPUT') or (g.get('EASYOPS_TOOL_INPUT') if isinstance(g.get('EASYOPS_TOOL_INPUT'), str) else '')
    if ti:
        try:
            for k, v in (json.loads(ti) or {}).items():
                if k in cfg:
                    _coerce(k, v)
        except ValueError:
            pass
    for a in argv or []:
        if '=' not in a:
            continue
        k, v = a.split('=', 1)
        k = k.lstrip('-').strip()
        if k in cfg:
            _coerce(k, v)
    return cfg


def _to_unicode(v):
    if IS_PY2 and isinstance(v, str):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            return v
    return v


# ---------------------------------------------------------------------------
# CCPC 拉取
# ---------------------------------------------------------------------------
def fetch_ccpc(ip, group_id, start, end, fixture=None):
    """拉 CCPC 值班表。fixture 非 None 读样例文件（`response: ` 行），否则 GET。

    返回天数组；非 200 / 非 list 抛 RuntimeError。
    """
    if fixture:
        if not os.path.isfile(fixture):
            raise RuntimeError(u'fixture 文件不存在: %s' % fixture)
        with open(fixture, 'r') as f:
            for line in f:
                if line.startswith('response: '):
                    data = json.loads(line[len('response: '):].strip())
                    return [d for d in data
                            if start <= (d.get('date') or '') <= end]
        raise RuntimeError(u'fixture 无 response 行: %s' % fixture)
    url = 'http://%s:%d/api/dutys/schedule/public?groupId=%s&startDate=%s&endDate=%s' % (
        ip, CCPC_PORT, group_id, start, end)
    if IS_PY2:
        try:
            resp = _urllib_request.urlopen(url, timeout=30)
            raw = resp.read()
            status = resp.getcode()
        except _urllib_request.URLError as e:
            raise RuntimeError(u'CCPC 请求失败 %s: %s' % (url, e))
    else:
        try:
            with _urllib_request.urlopen(url, timeout=30) as resp:
                raw = resp.read()
                status = resp.getcode()
        except _urllib_request.URLError as e:
            raise RuntimeError(u'CCPC 请求失败 %s: %s' % (url, e))
    if status != 200:
        raise RuntimeError(u'CCPC HTTP %s: %s' % (status, url))
    data = json.loads(raw.decode('utf-8', 'replace'))
    if not isinstance(data, list):
        raise RuntimeError(u'CCPC 响应非数组: %r' % type(data))
    return data


# ---------------------------------------------------------------------------
# ensure 值班组
# ---------------------------------------------------------------------------
def ensure_duty_group(name, shifts):
    """查/建/更新值班组。返回 (groupId, 变更描述)。

    无 → 建（dutyCycle 未来一百年，dutyShift=归纳班次）；
    有且 dutyShift（名称+时段集合）不一致 → PUT 更新 dutyShift（保留 name/dutyCycle）。
    """
    status, resp = http_json('GET', '/api/flowable_service/v1/duty_group?name=%s' % _url_quote(name))
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        raise RuntimeError(u'查询值班组失败: HTTP %s %s' % (status, _resp_text(resp)))
    lst = (resp.get('data') or {}).get('list') or []
    if not lst:
        body = {'name': name, 'dutyCycle': duty_cycle_100y(), 'status': 'enabled',
                'dutyShift': shifts, 'memo': u'sync_ccpc_duty 自动创建'}
        status, resp = http_json('POST', '/api/flowable_service/v1/duty_group', body)
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            raise RuntimeError(u'创建值班组失败: HTTP %s %s' % (status, _resp_text(resp)))
        gid = (resp.get('data') or {}).get('instanceId') or ''
        if not gid:
            raise RuntimeError(u'创建值班组未返回 instanceId: %s' % _resp_text(resp))
        put_str(u'值班组已创建: %s (%s) 班次=%s' % (name, gid, json.dumps(shifts, ensure_ascii=False)))
        return gid, 'created'
    group = lst[0]
    gid = group.get('instanceId') or ''
    if sorted_shifts(group.get('dutyShift') or []) != sorted_shifts(shifts):
        body = {'name': group.get('name') or name,
                'dutyCycle': group.get('dutyCycle') or duty_cycle_100y(),
                'status': group.get('status') or 'enabled',
                'dutyShift': shifts}
        status, resp = http_json('PUT', '/api/flowable_service/v1/duty_group/%s' % gid, body)
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            raise RuntimeError(u'更新值班组班次失败: HTTP %s %s' % (status, _resp_text(resp)))
        put_str(u'值班组班次已更新: %s -> %s' % (name, json.dumps(shifts, ensure_ascii=False)))
        return gid, 'shifts_updated'
    return gid, 'unchanged'


def sorted_shifts(shifts):
    """班次集合比较键（名称+时段，排序后比较——组定义顺序非关键）。"""
    return sorted(({'name': s.get('name') or '', 'dutyTime': s.get('dutyTime') or ''}
                   for s in shifts or []),
                  key=lambda x: (x['name'], x['dutyTime']))


def _url_quote(s):
    if IS_PY2:
        import urllib as _u
        return _u.quote(s.encode('utf-8'))
    import urllib.parse as _up
    return _up.quote(str(s))


def _resp_text(resp):
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False)[:300]
    return str(resp)[:300]


# ---------------------------------------------------------------------------
# 逐日 upsert
# ---------------------------------------------------------------------------
def upsert_day(group_id, group_name, date, want_conf):
    """单日配置 upsert。返回 created/updated/skipped/failed:<msg>。"""
    status, resp = http_json('POST', '/api/flowable_service/v2/duty_group_config/search',
                             {'groupName': group_name, 'date': date})
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        return 'failed:search HTTP %s %s' % (status, _resp_text(resp))
    existing = None
    for item in (resp.get('data') or {}).get('list') or []:
        if item.get('date') == date:
            existing = item
            break
    if existing is not None:
        have_conf = norm_conf(existing.get('dutyShiftConf') or [])
        if conf_equal(want_conf, have_conf):
            return 'skipped'
        status, resp = http_json('PUT', '/api/flowable_service/v1/duty_group_config/%s'
                                 % existing.get('instanceId'),
                                 {'configId': existing.get('instanceId'), 'date': date,
                                  'status': 0, 'dutyShiftConf': want_conf})
        if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
            return 'failed:update HTTP %s %s' % (status, _resp_text(resp))
        return 'updated'
    status, resp = http_json('POST', '/api/flowable_service/v1/duty_group_config',
                             {'groupId': group_id, 'date': date, 'status': 0,
                              'dutyShiftConf': want_conf})
    if status != 200 or not isinstance(resp, dict) or resp.get('code') != 0:
        return 'failed:create HTTP %s %s' % (status, _resp_text(resp))
    return 'created'


def norm_conf(conf):
    """v2 search 返回的 dutyShiftConf 归一化（users/leader 可能是对象数组→取 name）。"""
    out = []
    for s in conf or []:
        users = []
        for u in s.get('users') or []:
            users.append(u.get('name') if isinstance(u, dict) else u)
        leader = []
        for l in s.get('leader') or []:
            leader.append(l.get('name') if isinstance(l, dict) else l)
        out.append({'name': s.get('name') or '', 'users': users, 'leader': leader})
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv=None):
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    _resolve_conn()
    put_str(u'配置: %s' % json.dumps(cfg, ensure_ascii=False))

    dates = date_range(cfg['sync_days'])
    start, end = dates[0], dates[-1]

    fixture = os.environ.get('CCPC_FIXTURE') or None
    days = fetch_ccpc(cfg['ccpc_ip'], cfg['ccpc_group_id'], start, end, fixture=fixture)
    put_str(u'CCPC 返回 %d 天 (%s~%s)' % (len(days), start, end))
    by_date = dict((d.get('date'), d) for d in days)

    shifts = analyze_shifts(days)
    if not shifts:
        raise RuntimeError(u'CCPC 数据未归纳出任何班次')
    gid, group_desc = ensure_duty_group(cfg['duty_group_name'], shifts)

    stat = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0}
    for date in dates:
        day = by_date.get(date)
        want_conf = build_shift_conf(day)
        if want_conf is None:
            put_str(u'%s 无CCPC数据，跳过' % date)
            stat['skipped'] += 1
            continue
        result = upsert_day(gid, cfg['duty_group_name'], date, want_conf)
        if result.startswith('failed'):
            stat['failed'] += 1
            put_str(u'%s %s' % (date, result))
        else:
            stat[result] += 1
            if result != 'skipped':
                put_str(u'%s %s' % (date, result))
    put_str(u'同步完成 组=%s(%s) 建=%d 改=%d 跳=%d 败=%d' % (
        cfg['duty_group_name'], group_desc,
        stat['created'], stat['updated'], stat['skipped'], stat['failed']))
    return 0 if stat['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
```

注意：`parse_args` 里引用了 `_to_unicode`，把它从 Task 2 的实现中挪到模块顶部（`conf_equal` 之前任一位置），或直接放在 `parse_args` 上方——本步实现已按"放 parse_args 上方"编排，与 Task 2 Step 3 的文件不冲突（追加位置在文件末尾 main 区域之前）。

- [ ] **Step 4: 跑全量测试确认通过**

```bash
cd /workspace/tmp/ccpc-duty && python3 test_sync_ccpc_duty.py -v 2>&1 | tail -3
```

Expected: 全部 PASS（20 个测试），OK

- [ ] **Step 5: py2 语法兼容自检**

```bash
python3 -c "import ast; ast.parse(open('/workspace/tmp/ccpc-duty/sync_ccpc_duty.py').read())" && echo SYNTAX_OK
grep -n "f'" /workspace/tmp/ccpc-duty/sync_ccpc_duty.py; grep -cn "f\"" /workspace/tmp/ccpc-duty/sync_ccpc_duty.py
```

Expected: SYNTAX_OK；f-string grep 无输出（exit 1 / 计数 0）

- [ ] **Step 6: Commit（tmp 不入库，留空提交痕）**

```bash
cd /workspace && git commit --allow-empty -m "feat(ccpc-duty): CCPC拉取+ensure/upsert 编排层（mock单测20绿）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: .26 真环境端到端 + status 语义校准

**Files:**
- 临时操作：真环境建/改/查/清理（无文件改动；.26 环境数据）
- Modify: `/workspace/tmp/ccpc-duty/sync_ccpc_duty.py`（若 status 语义需校准）

**Interfaces:**
- Consumes: Task 3 完整 main 流程
- Produces: 端到端验证结论；`status` 实测语义（记入 platforms objects.yaml itsm_duty_group_config.fields.status desc——若与默认 0 不符）

- [ ] **Step 1: fixture 模式真跑 .26（建组+同步 30 天）**

```bash
cd /workspace/tmp/ccpc-duty && \
EASYOPS_ITSM_BACKEND_URL=http://192.168.110.26:8134 EASYOPS_ORG=1888 EASYOPS_USER=easyops \
CCPC_FIXTURE=/workspace/tmp/ccpc-dutys.txt \
python3 sync_ccpc_duty.py duty_group_name=告警值班组TEST sync_days=16
```

Expected: fixture 日期是 2026-09-01~30，今天 09-15 起 16 天 → 09-15~09-30 有数据（16 天 upsert）；输出 `同步完成 组=告警值班组TEST(created) 建=16 改=0 跳=0 败=0`，exit 0

- [ ] **Step 2: 验证 easyops 侧结果（v2 search 直查）**

```bash
curl -s -m 8 http://192.168.110.26:8134/api/flowable_service/v2/duty_group_config/search \
  -H "org: 1888" -H "user: easyops" -H "Host: admin.easyops.local" -H "Content-Type: application/json" \
  -d '{"groupName":"告警值班组TEST","date":"2026-09-15"}' | python3 -m json.tool | head -60
```

Expected: code=0，list 含 2026-09-15，dutyShiftConf 白班 users=[tianyaqiong…等 fixture 人员]、leader=[liuzhenlin, luchao]、夜班 chenchen（与 fixture 09-15 数据一致）；v2 的 users/leader 应已带 nickname（校准点：确认 v2 响应结构是否对象数组，校验 norm_conf 正确性）

- [ ] **Step 3: 幂等验证（再跑一遍）**

重复 Step 1 命令。

Expected: `组=告警值班组TEST(unchanged) 建=0 改=0 跳=16 败=0`，exit 0

- [ ] **Step 4: upsert 变更验证（改 fixture 数据再同步）**

```bash
cd /workspace/tmp/ccpc-duty && python3 - <<'EOF'
# 把 fixture 2026-09-16 白班 dutys 换人：tianyaqiong → chenchen
import io
src = open('/workspace/tmp/ccpc-dutys.txt', encoding='utf-8').read()
# 针对性替换 09-16 白班成员（fixture 中 09-16 白班 dutys 是 tianyaqiong）
old = '"date":"2026-09-16","groupId":"8882eec490c54bacb382c5e859f20f05","groupName":"CCPC监控值守组","shifts":[{"endTime":"19:00","members":[{"field":"dutys","name":"值班人员","uids":["tianyaqiong"]}'
new = old.replace('uids":["tianyaqiong"]', 'uids":["wanglina"]')
assert old in src, 'fixture anchor not found'
open('/workspace/tmp/ccpc-duty/fixture-mutated.txt', 'w', encoding='utf-8').write(src.replace(old, new))
print('mutated fixture written')
EOF
EASYOPS_ITSM_BACKEND_URL=http://192.168.110.26:8134 EASYOPS_ORG=1888 EASYOPS_USER=easyops \
CCPC_FIXTURE=/workspace/tmp/ccpc-duty/fixture-mutated.txt \
python3 sync_ccpc_duty.py duty_group_name=告警值班组TEST sync_days=16
```

Expected: `建=0 改=1 跳=15 败=0`（只有 09-16 updated）；v2 search 09-16 白班 users=[wanglina]

- [ ] **Step 5: 班次定义变更验证（换成三班）**

```bash
cd /workspace/tmp/ccpc-duty && python3 - <<'EOF'
# 09-17 起白班拆成 早班+中班（新班次名），触发 dutyShift 自动更新
src = open('/workspace/tmp/ccpc-duty/fixture-mutated.txt', encoding='utf-8').read()
old = '"date":"2026-09-17","groupId":"8882eec490c54bacb382c5e859f20f05","groupName":"CCPC监控值守组","shifts":[{"endTime":"19:00","members":[{"field":"dutys","name":"值班人员","uids":["shenwenjuan"]}'
new = '"date":"2026-09-17","groupId":"8882eec490c54bacb382c5e859f20f05","groupName":"CCPC监控值守组","shifts":[{"endTime":"14:00","members":[{"field":"dutys","name":"值班人员","uids":["shenwenjuan"]}'
assert old in src
open('/workspace/tmp/ccpc-duty/fixture-3shift.txt', 'w', encoding='utf-8').write(src.replace(old, new).replace(
    '"shiftName":"白班","startTime":"08:00"' if False else '"shiftId":"c7f4d5865690417facb9721cac438925","shiftName":"白班","startTime":"08:00"',
    '"shiftId":"c7f4d5865690417facb9721cac438925","shiftName":"早班","startTime":"08:00"').replace(
    '"endTime":"14:00","members":[{"field":"dutys","name":"值班人员","uids":["shenwenjuan"]},{"field":"maintainer","name":"技术值班","uids":["liuzhenlin"]},{"field":"leader","name":"带班主任","uids":["luchao"]}],"shiftId":"c7f4d5865690417facb9721cac438925"',
    '"endTime":"14:00","members":[{"field":"dutys","name":"值班人员","uids":["shenwenjuan"]},{"field":"maintainer","name":"技术值班","uids":["liuzhenlin"]},{"field":"leader","name":"带班主任","uids":["luchao"]}],"shiftId":"c7f4d5865690417facb9721cac438925"'))
print('3shift fixture written')
EOF
```

（⚠️ 实现者注意：上面 fixture 变异脚本若锚点串对不上，直接手工编辑 fixture-3shift.txt——目标是让 09-17 起出现新班次名“早班 08:00~14:00”且数据自洽）

```bash
EASYOPS_ITSM_BACKEND_URL=http://192.168.110.26:8134 EASYOPS_ORG=1888 EASYOPS_USER=easyops \
CCPC_FIXTURE=/workspace/tmp/ccpc-duty/fixture-3shift.txt \
python3 sync_ccpc_duty.py duty_group_name=告警值班组TEST sync_days=16
```

Expected: 输出含 `值班组班次已更新`；后续日期按新班次名 upsert。前端校验：`http://192.168.110.26/next/itsc-operation-management/duty-configuration`（systems.yaml acceptance_urls.duty_group_list）

- [ ] **Step 6: 清理测试数据**

```bash
curl -s -m 8 "http://192.168.110.26:8134/api/flowable_service/v1/duty_group?name=告警值班组TEST" \
  -H "org: 1888" -H "user: easyops" -H "Host: admin.easyops.local" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for g in (d.get('data') or {}).get('list') or []:
    print(g['instanceId'])"
# 用返回的 groupId 删除：
curl -s -m 8 -X DELETE "http://192.168.110.26:8134/api/flowable_service/v1/duty_group/<groupId>" \
  -H "org: 1888" -H "user: easyops" -H "Host: admin.easyops.local"
```

Expected: code=0；再查 name=告警值班组TEST 为空

- [ ] **Step 7: status 语义结论回写 platforms（若需）+ Commit**

若端到端发现 status≠0 才是正常工作日配置（例如前端建的 config status=1），同步修改：
1. `sync_ccpc_duty.py` upsert_day/main 中两处 `status: 0` → 实测值
2. objects.yaml `itsm_duty_group_config.fields.status` desc 更新实测语义
3. 重跑 fixture 单测确认绿

```bash
cd /workspace && git add skills/api-orchestrator/platforms/easyops/objects.yaml && git commit -m "docs(api-orchestrator): duty_group_config status 实测语义回写

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 注册 autoops 工具 + 导出 + hub 回流

**Files:**
- Create: `/workspace/tmp/ccpc-duty/tool-create.json`
- Create: `/workspace/skills/api-orchestrator/platforms/easyops/hub/scripts/tools/sync_ccpc_duty.py`（终态副本）
- Create: `/workspace/skills/api-orchestrator/platforms/easyops/hub/scripts/tools/同步CCPC值班表.tool.tar.gz`
- Modify: `/workspace/skills/api-orchestrator/platforms/easyops/hub/INDEX.yaml`（scripts 类目加条目）

**Interfaces:**
- Consumes: Task 3/4 完成的 `sync_ccpc_duty.py`；autoops tool API（8181 POST /tools，objects.yaml autoops_tool）；SDK `export_tool`（platforms/easyops/sdk/easyops_client.py:308）

- [ ] **Step 1: 组装 tool-create.json 并注册**

```bash
cd /workspace/tmp/ccpc-duty && python3 - <<'EOF'
import json
content = open('sync_ccpc_duty.py', encoding='utf-8').read()
tool = {
    "name": "同步CCPC值班表",
    "category": "ITSM",
    "memo": "拉CCPC值班表同步到EasyOps ITSM值班组日历配置（班次动态归纳/未来一百年周期/upsert幂等/班次变更自动更新）",
    "type": "python",
    "vName": "v1",
    "vDesc": "初版：CCPC拉取+班次归纳+值班组ensure+逐日upsert",
    "content": content,
    "timeout": 300,
    "inputs": [
        {"name": "ccpc_ip", "label": "CCPC地址", "type": "string", "required": True,
         "default": "127.0.0.1", "description": "CCPC IP（端口固定8880）"},
        {"name": "ccpc_group_id", "label": "CCPC值班组id", "type": "string", "required": True,
         "default": "8882eec490c54bacb382c5e859f20f05", "description": "CCPC 值班组 groupId"},
        {"name": "duty_group_name", "label": "EasyOps值班组名称", "type": "string", "required": True,
         "default": "告警值班组", "description": "EasyOps 侧值班组名（不存在自动创建）"},
        {"name": "sync_days", "label": "同步时间范围(天)", "type": "int", "required": False,
         "default": 30, "description": "同步今天起 N 天"},
    ],
    "outputDefs": [
        {"id": "created", "name": "新建配置数"},
        {"id": "updated", "name": "更新配置数"},
        {"id": "skipped", "name": "跳过数"},
        {"id": "failed", "name": "失败数"},
    ],
}
json.dump(tool, open('tool-create.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('tool-create.json written, content len=%d' % len(content))
EOF
curl -s -m 15 http://192.168.110.26:8181/tools -X POST \
  -H "org: 1888" -H "user: easyops" -H "Host: admin.easyops.local" -H "Content-Type: application/json" \
  --data-binary @tool-create.json | python3 -m json.tool
```

Expected: code=0，data 含 toolId + vId（记下 toolId）

- [ ] **Step 2: 平台执行验证（run 工具，fixture 环境变量带不进去——用真 CCPC 参数语法跑通为限）**

```bash
curl -s -m 60 http://192.168.110.26:8181/tools/<toolId>/versions/<vId>/execute -X POST \
  -H "org: 1888" -H "user: easyops" -H "Host: admin.easyops.local" -H "Content-Type: application/json" \
  -d '{"inputs":{"ccpc_ip":"127.0.0.1","ccpc_group_id":"8882eec490c54bacb382c5e859f20f05","duty_group_name":"告警值班组TEST2","sync_days":1}}'
```

Expected: execId 返回（CCPC 127.0.0.1 不可达→执行失败是预期，验证的是"工具脚本被平台拉起、入参注入、报错清晰"）；get_exec_result 看 stderr 应含 `CCPC 请求失败`。清理：删 告警值班组TEST2（若建出）。

- [ ] **Step 3: 导出 tool.tar.gz**

```bash
cd /workspace/tmp/ccpc-duty && python3 - <<'EOF'
import sys
sys.path.insert(0, '/workspace/skills/api-orchestrator/platforms/easyops/sdk')
from easyops_client import EasyOpsClient
c = EasyOpsClient(base_url='http://192.168.110.26:8181', org='1888', user='easyops')
# toolId/vId 从 Step 1/2 结果填入
r = c.export_tool(toolId='<toolId>', versionId='<vId>',
                  save_to='/workspace/tmp/ccpc-duty/同步CCPC值班表.tool.tar.gz')
print(r)
EOF
```

Expected: tar.gz 落盘；`tar -tzf` 列出包内容（含工具 json + 脚本）

- [ ] **Step 4: hub 回流（文件 + INDEX）**

```bash
cp /workspace/tmp/ccpc-duty/sync_ccpc_duty.py /workspace/skills/api-orchestrator/platforms/easyops/hub/scripts/tools/sync_ccpc_duty.py
cp /workspace/tmp/ccpc-duty/同步CCPC值班表.tool.tar.gz /workspace/skills/api-orchestrator/platforms/easyops/hub/scripts/tools/
```

INDEX.yaml `items:` 的 scripts 类目区（alert2ticket 条目后）追加：

```yaml
  - id: sync-ccpc-duty
    name: 同步CCPC值班表
    category: scripts
    files: [tools/sync_ccpc_duty.py, tools/同步CCPC值班表.tool.tar.gz]
    history:
      - {date: "2026-09-15", change: 初版入库（.26 fixture 端到端通过：建组/幂等/upsert/班次变更自动更新）}
    scenario: 拉 CCPC 值班表同步 EasyOps ITSM 值班组日历配置（py2/3 兼容，可配 EasyOps agent 定时工具；班次动态归纳不写死、dutyCycle 未来一百年、upsert 幂等）
    notes: "入参 ccpc_ip/ccpc_group_id/duty_group_name/sync_days；dutys→users、maintainer+leader→leader；CCPC_FIXTURE 环境变量可切样例文件测试；端口 8134 flowable"
    added: "2026-09-15"
```

- [ ] **Step 5: 部署根镜像同步 + lint**

```bash
cp /workspace/skills/api-orchestrator/platforms/easyops/objects.yaml /workspace/.api-orchestrator/platforms/easyops/objects.yaml 2>/dev/null
rsync -a /workspace/skills/api-orchestrator/platforms/easyops/hub/ /workspace/.api-orchestrator/platforms/easyops/hub/ 2>/dev/null || cp -r /workspace/skills/api-orchestrator/platforms/easyops/hub/* /workspace/.api-orchestrator/platforms/easyops/hub/
python3 /workspace/skills/api-orchestrator/scripts/lint-platforms.py easyops 2>&1 | tail -1
```

Expected: 0 ERR

- [ ] **Step 6: Commit**

```bash
cd /workspace && git add skills/api-orchestrator/platforms/easyops/hub/ && git commit -m "feat(api-orchestrator): hub 回流同步CCPC值班表工具 sync_ccpc_duty v1

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 结论

1. **Spec 覆盖**：入参四项（Task 2/3/5）、动态班次（Task 2）、ensure 组+dutyCycle 100 年（Task 3）、班次变更自动更新（Task 3/4 Step 5）、逐日 upsert（Task 3/4）、角色映射（Task 2）、错误处理-单日失败不中断+无数据跳过（Task 3 main）、fixture 测试（Task 2/3/4）、端到端（Task 4）、platforms 沉淀（Task 1）、注册+导出+回流（Task 5）——全覆盖
2. **占位符**：Task 4 Step 5 fixture 变异脚本给了 fallback（手工编辑）；Task 5 toolId/vId 是运行时值，用 `<>` 标注从上一步结果填入——非设计占位
3. **类型一致性**：`analyze_shifts` 返回 `[{name, dutyTime}]` 与 `ensure_duty_group(name, shifts)` 消费一致；`build_shift_conf` 返回 `[{name, users, leader}]` 与 `upsert_day(..., want_conf)` / `conf_equal` 一致；测试 import 路径 `sys.path.insert` 同目录
4. **已修**：Task 2 测试里 `TestParseArgs.test_defaults` 断言 dict 相等会被 py2/3 dict 顺序影响——py3.7+ dict 保序且值全等，直接 assertEqual dict 可行；`_to_unicode` 定义位置已在 Task 3 Step 3 注明挪到 parse_args 上方
