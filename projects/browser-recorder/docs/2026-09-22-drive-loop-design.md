# browser-recorder drive 闭环设计（方向 2：录制 → 重放）

> 日期：2026-09-22 ｜ 状态：已与用户逐节确认
> 背景讨论脉络：browser-manual skill 能力域扩展的三方向论证（NL 探索 / 录制重放 / 参数化条件流转）。
> 本设计覆盖第一个子项目：**drive 闭环**。方向 3（flow 变量/分支引擎）、方向 1（probe 探索）不在本文范围。

## 0. 目标与边界

**目标**：`browser-recorder drive` 子命令——读动作链 JSON（flow.json）驱动浏览器复现操作流，默认跑即录；含 replay 转换器（session.jsonl → flow.json）；捆绑录制增强（descriptor 新属性 + ws_frame 事件）。

**已确认的决策**（brainstorming 澄清结果）：

| 决策点 | 结论 |
|---|---|
| 子项目边界 | drive 闭环（方向 2），不含变量/分支引擎与 probe |
| 验收场景 | EasyOps 21 步（登录→创建套件→删除）真机全流程 |
| drive 输入 | flow.json（含 replay 转换器，拿到「录一次→自动重放」完整链路） |
| 跑即录 | drive 默认同步录制 session，`--no-record` 才关 |
| 录制增强 | descriptor 新属性 + ws_frame 捆绑进本子项目 |
| 失败处置 | 重试 N 次 + 证据包落盘 + 终止（exit 3）；不做交互式接管、不做步级容错声明 |
| 事件派发 | CDP Input 信任事件为主，复检不通过降级 JS 直调，派发方式落盘可审计 |
| 重构深度 | 先拆 SessionHarness（record 行为零变化，测试全绿为门槛），再长 drive |

**总架构定位**：browser-recorder 从录制器演化为「浏览器会话引擎」——record / drive / probe（未来）三种主循环共用一个 harness，session.jsonl 升格为所有模态共用的中枢资产（录制即留档、自动化即取证）。

## 1. 模块布局与 harness 拆分（M1+M2）

### 拆分后模块图

```
src/browser_recorder/
├── cdp.py          # 不动（接口已稳）
├── writer.py       # M1 加 ws_frame 脱敏分支（~+15 行）
├── inject.js       # M1 descriptor 增录 3 类属性（~+15 行）
├── harness.py      # M2 新增：SessionHarness（从 recorder.py 抽出）
├── recorder.py     # M2 瘦身：record() = harness + 录制主循环（~360→150 行）
├── driver.py       # M3 新增：locate / act / wait_for / 证据包
├── flow.py         # M4 新增：flow.json schema + 执行引擎
├── replay.py       # M5 新增：session → flow 转换器
└── cli.py          # M4 加 drive / M5 加 replay 子命令
```

### SessionHarness 边界（M2 核心）

从 record() 抽出所有模态共用的会话壳，`async with` 语义：

```python
class SessionHarness:
    """一次浏览器会话的共用壳：生命周期 + 挂域 + 注入 + settle + 落盘。
    record/drive/probe 三种主循环共用，保证 session 产物行为一致。"""
```

**职责**（从 record() 平移，逻辑不变）：

- chrome 启动参数组装 / Popen / 收尸（Browser.close 优雅退出链，session cookie 落盘语义保持）
- autoAttach + attach_tab（runIfWaitingForDebugger 先于挂域的时序）
- 三域挂载 + inject 注入 + 主 frame 导航后重注入
- StableState + wait_stable（网络空闲 ∧ DOM 静默 500ms；ws/SSE 长连接排除在 inflight 外）
- writer 落盘 + writer.fatal 升级停止
- profile / incognito 管理
- 事件注册回调的注册表（request/response/nav/binding 挂到 harness 上）

**对主循环暴露的接口**：

| 接口 | 说明 |
|---|---|
| `harness.client` | CDPClient |
| `harness.tabs` | `{sid: _TabSession}`，含 `tid_of()` |
| `harness.state` / `harness.writer` | StableState / SessionWriter |
| `harness.wait_stable(timeout)` | → "stable" \| "timeout" |
| `harness.navigate(url, tid)` | 首导航（挂域完成同步点内建） |
| `harness.flush_inputs()` | `__brFlush` 冲刷 |
| `harness.emit_action(payload)` | 动作落盘 + before 截图即拍 |
| `harness.schedule_after_shot(seq, ...)` | after 异步补拍 |
| `harness.stop_event` / `harness.shutdown_reason` | 停止协调（hotkey/browser_closed/terminal_q） |

**拆分原则**：纯搬运。recorder.py 里真机踩坑换来的时序（放行先于挂域、导航后重注入、before 即拍）一行逻辑不改，只换归属。record() 退化为「harness + 三层停止等待 + stop_reason/abnormal 判定」。

**跑即录的实现基础**：drive 主循环同样 `async with SessionHarness(...)`，用 `emit_action()` 落盘驱动动作——机器动作与人录动作走同一条落盘路径，session 产物无差别；动作事件加 `source: "drive"` 字段区分（writer 透传）。

### 录制增强（M1）

1. **inject.js `describe()` 增录**：
   - `name`：input/select 的 name 属性
   - `aria_label`：aria-label 属性
   - `data_attrs`：测试锚点白名单（data-testid / data-test / data-qa / data-cy），不录业务 data-* 避免膨胀
   - descriptor 向后兼容（新字段可缺省）
2. **recorder 挂 `Network.webSocketFrameSent/Received`** → writer 落 `ws_frame` 事件：
   - 字段：`{request_id, direction: sent|received, payload, target_id}`
   - payload 文本截 8KB；二进制标 base64
   - writer 对 payload 沿用敏感键打码逻辑（token 类 JSON 键打码）

## 2. driver 库（M3）

纯执行原语层：不读 flow、不知道步序，只提供「找到元素 / 施加动作 / 等待 / 留证据」。

### locate(spec, tab) -> LocatedElement

定位规格为字符串，前缀区分策略（沿用 easyops_mvp 已验证语法）：

```
css:#name                    # CSS，deepQuery 穿透 open shadow root
xpath://*[@id='name']        # XPath（lowercase 兜底）
text:^monitor                # 文本匹配（^=词首锚定）
dom:div#app>span.btn         # 录制 descriptor.dom_path 直译
```

实现：easyops_mvp 的 `FIND_JS`（deepAll shadow 穿透 + 文本锚定匹配）沉到 driver.py，经 `Runtime.evaluate` 执行。

**降级链**：调用方传候选数组 `locate(["css:#name", "text:套件名称"])` 按序试到第一个命中。单 spec 内部无魔法降级，多候选是显式降级。

**歧义处理**：命中多个取视口内最靠近中心的第一个（可预测），返回值带 `match_count`——>1 时 drive 层记 warning 落盘。

### act(action, target, tab)

| 动作 | 默认路径（信任事件） | 降级路径（JS 直调） |
|---|---|---|
| click | 滚动入视 → rect 中心 → Input.dispatchMouseEvent（moved→pressed→released） | element.click() |
| input | 聚焦 → 先退清现值（全选+Delete）→ 逐键 Input.dispatchKeyEvent | 原生 setter 赋值 + input/change 事件 |
| submit | 定位 form 提交按钮走 click；无按钮则 JS form.requestSubmit() | 同左（submit 本身走 JS） |
| hover | Input.dispatchMouseEvent moved | mouseenter/mouseleave 合成 |

**降级触发判定**（可观测）：信任派发后 `wait_stable` + 复检目标状态（input value 是否变预期、click 后 dom_mutations 是否有脉冲）——复检不通过才降级；降级作为 `drive_step` 的 `dispatch: "trusted" → "js-fallback"` 字段落盘。

**输入特殊处理**：`type=password` 的值在 flow.json 里写 `${env.XXX}`（v1 只做 env 变量替换，变量池留给方向 3）；实际值不落盘（writer 脱敏双保险）。

### wait_for(kind, arg, timeout)

- `wait_for("element", spec)`：轮询 locate（200ms 间隔）直到命中或超时
- `wait_for("settle")`：即 harness.wait_stable()
- `wait_for("nav", url_contains)`：等主 frame URL 含关键字（harness 事件注册表订阅）

### 失败协议：重试 + 证据终止

```
单步执行失败 → 重试 N 次（默认 3，flow 可覆盖）：每次先 settle 再重新 locate
仍败 → 证据包落盘 + drive_fail 事件 → 终止（exit 3）
```

**证据包**（`<out_dir>/evidence/fail-step<N>/`）：

| 文件 | 内容 |
|---|---|
| screenshot.png | 失败瞬间全页截图（annotator 画目标位置红框；locate 失败无框附 spec 文字） |
| dom.json | 失败时根节点 innerHTML 截断 dump（512KB 上限） |
| context.json | 步号/spec/已试候选/重试次数/当时 URL/派发方式/前后 action seq |

### driver 可测性

全部方法「CDPClient 打桩 → 断言发出的 CDP 命令序列」单测（test_cdp 的 fake ws 基建复用）；真机验证留给 M4 验收。

## 3. flow.json 格式与执行引擎（M4）

### flow.json schema（v1）

```json
{
  "name": "easyops-create-kit",
  "meta": {"recorded_from": "sessions/20260901-xxxx", "created": "2026-09-01"},
  "steps": [
    {"n": 1, "desc": "点击菜单(launchpad)", "act": "click",
     "loc": ["css:eo-launchpad-button-v2 a"], "tabs": "new", "wait": "settle",
     "on_new_tab": "switch"},
    {"n": 8, "desc": "套件名称", "act": "input", "loc": ["css:#name"],
     "value": "e2e自动录制测试套件", "clear": true},
    {"n": 17, "desc": "提交保存", "act": "click",
     "loc": ["css:forms.general-buttons button:nth-of-type(1)"],
     "expect": {"response_contains": {"url": "/api/gateway/", "status": 200}},
     "on_expect_fail": "retry"}
  ]
}
```

字段全集（v1 无预留字段，方向 3 再扩）：

| 字段 | 必填 | 说明 |
|---|---|---|
| n | ✓ | 步号（证据包/日志引用锚点） |
| desc | ✓ | 人读描述（生成手册的步骤名原料） |
| act | ✓ | click / input / submit / hover / open |
| loc | ✓（除 open） | 候选数组，按序降级 |
| value | input 必填 | 值；`${env.XXX}` 唯一支持的变量形式 |
| clear | — | input 前清空（默认 true） |
| tabs | — | main（默认）/ new / tid |
| wait | — | settle（默认）/ none / nav |
| on_new_tab | — | switch / ignore |
| expect | — | response_contains（网络通道）/ dom_contains（DOM 通道） |
| on_expect_fail | — | retry / abort（默认） |

显式设计决策：

1. tabs/on_new_tab 进格式（easyops 第 7 步「确认(新tab)」是真实痛点，多 tab 必须显式建模）
2. expect 是断言不是条件（branch 留给方向 3；response_contains 走网络事件流，是方向 3 双通道条件的退化雏形）

### 执行引擎（flow.py）

```
run_flow(harness, flow, vars):
  for step:
    1. 解析 ${env.XXX}
    2. 选 tab
    3. wait_for 前置（默认 settle）
    4. locate 候选链（miss → 步级重试预算）
    5. act 信任派发 → 复检 → 不通过 JS 降级
    6. wait_for 后置
    7. expect 校验（网络：动作 t_mono 起 settle 窗口内找匹配 response；
       DOM：settle 后 evaluate contains）
    8. 落 drive_step 事件
    失败 → 证据包 + drive_fail → 终止（exit 3）
```

**expect 网络通道实现**：harness 事件注册表已收 Network.responseReceived——flow 引擎加带时间窗的响应捕获器（动作前 arm，settle 后检查），不改动 recorder 落盘路径，保证「跑即录」session 的归组关系与真人录制一致（browser-manual 的 t_mono 归组规则直接适用）。

### drive_step 事件（session.jsonl 新 kind）

```json
{"kind": "drive_step", "seq": 42, "t_mono": 12345,
 "n": 8, "desc": "套件名称", "act": "input", "dispatch": "trusted",
 "match_count": 1, "retry_used": 0, "expect_result": null, "target_id": "t1"}
```

drive 每步**同时落** drive_step（机器视角）和 action（统一动作视角，source: "drive"）——文档生成端只认 action + 截图，无感知兼容。

### CLI 形态

```bash
browser-recorder drive <flow.json> \
  [--out sessions/] [--profile easyops] [--headless] [--no-record] \
  [--var key=value ...] [--step-from 8] [--dry-run]
```

`--dry-run`：只 locate 不 act，drive_step 标 dispatch: "dry"——选择器腐化时低成本定位断点。

## 4. replay 转换器（M5）

纯转换器（无浏览器交互），核心难题：从录制现场数据推导下次还能命中的选择器。

### 转换算法（session → flow）

对每个 action：

1. **归组**：动作间隔 > 2s 或中间夹 nav → 切新阶段
2. **定位候选链推导**（按稳定性排序，转换器的灵魂）：
   - a. descriptor.id → `css:#<id>`
   - b. 测试锚点（M1 新增）→ `css:[data-testid=...]`
   - c. name / aria-label → `css:[name=x]` / `css:[aria-label=x]`（表单控件优先）
   - d. 显著文本（按钮/链接）→ `text:<锚定文本>`
   - e. tag + classes 稳定子集 → `css:button.btn-primary`（剔哈希后缀/样式类）
   - f. dom_path 直译 → `dom:<path>`（兜底，标 fragile: true）
3. **act 映射**：type 直译；value 直拷（password 恒 *** → 标 needs_credential，值写 `${env.BR_PW_<step>}` 占位）
4. **tab 归属**：target_id → tabs；新 tid 首现于某 nav → 前一步标 on_new_tab: switch
5. **wait 推导**：动作后区间内有 nav → "nav"；否则默认 "settle"
6. **expect 推导**：v1 不自动推导（宁缺毋滥），只对 submit/末步落 dom_contains 占位注释，人工补

**通用性约束**：候选链过滤规则不硬编码 EasyOps 特例——通用规则如「纯数字后缀的自动生成 id（antd rc_select_20 类）降级为不稳定」，EasyOps 只是规则的测试场（easyops_mvp 手写 STEPS 的命中经验用于校准规则）。

### 转换质量自验证回路

```
录制 session A ──replay──> flow.json ──drive(dry-run)──> 逐步命中报告
```

dry-run 对同一系统跑一遍报告命中/未命中/多命中——转换器的验收 = 对源 session 的重放命中率。目标：EasyOps 21 步转换后 dry-run 命中率 100%（多命中 warning 可接受）。

### CLI 形态

```bash
browser-recorder replay <session_dir> \
  [--out flows/easyops.json] [--name easyops-create-kit] [--keep-fragile]
```

默认**剔除只有 dom_path 兜底的步并报告**（步列表+原因落 `flows/<name>.report.md`），旗子打开则保留并标 fragile——宁可显式失败，不可静默降级（与失败协议同哲学）。

### replay 边界（明确不做）

- 不自动推导 expect 断言
- 不合并/删减动作（忠实转译，优化是人的事）
- 不处理 iframe 内动作坐标换算（继承录制限制，报告标注）

## 5. 测试策略与里程碑验收

### 测试分层

| 层 | 测什么 | 形态 |
|---|---|---|
| 单测 | writer ws_frame 脱敏 / inject 新属性 / driver CDP 命令序列（打桩）/ flow 状态机（正常+重试+降级+终止）/ replay 候选链（构造事件） | 扩展 tests/（新增 test_driver / test_flow / test_replay，19→45+） |
| 回路自测 | harness 行为一致性 / dry-run 命中率 / replay 正确性 | 本地 fixture 页（tests/fixtures/ 静态 HTML：表单/shadow DOM/多 tab 链接）+ 本地 HTTP 服务 |
| 真机验收 | 21 步全流程 + 产物完整 | M4/M5 各一次，人工核对 |

fixture 页是关键新测试资产：shadow DOM 自定义元素 + 表单 + 新 tab 链接的静态页，harness/driver/flow 回路测试不依赖内网；easyops_mvp 迁移先当靶场，内网 21 步是终验。

### 里程碑验收门

| 里程碑 | 验收门 |
|---|---|
| M1 录制增强 | 单测绿 + 真机录 EasyOps：descriptor 含 name/aria-label/data-testid、ws 请求有 ws_frame、旧字段无回归 |
| M2 harness 拆分 | **现有 19 测试全绿（零修改通过）** + fixture 页金录像 diff 一致（kind/顺序/截图状态）。fixture 页（tests/fixtures/）在本里程碑创建——金录像依赖它 |
| M3 driver 库 | fixture 页单测：locate 四策略命中/歧义/miss、信任派发命令序列、降级触发、证据包落盘 |
| M4 drive 闭环 | easyops.json（21 步手写迁移）真机跑通创建→删除 + session 产物完整（action/drive_step/截图配对）+ browser-manual 消费无报错 |
| M5 replay 转换器 | M1 格式录的 21 步 session → replay → dry-run：转换器原始输出直接命中，或未命中步经人工补候选后命中（两种情况都要在 report.md 明示：原始命中率 + 人工补了哪些步）。未命中且未补 = 不过 |

### 风险与对策

| 风险 | 对策 |
|---|---|
| M2 拆分动 record() 收敛路径（三层停止+异常收尾时序敏感） | 拆分前固化「金录像」：fixture 页录制一次，拆分后同场景重录逐事件 diff，行为一致性机器判据 |
| 信任派发在 EasyOps 未验证（MVP 走 JS 直调） | M3 在 fixture 页先验信任派发对受控输入有效性；真机个别步不奏效由降级路径接住，最坏标 js-fallback 仍走通 |
| replay 候选链命中盲区（antd 自动生成 id 稳定性存疑） | 转换规则含「自动生成 id 降级」通用规则；M5 允许人工补候选后过关（报告明示） |

### 交付物清单

- docs/ 本设计文档 + 实施计划（writing-plans 产出）
- README 更新：drive/replay 用法 + flow.json schema 说明
- flows/easyops.json：21 步验收 flow（格式使用示例）
- session 产物向后兼容声明：新 kind（ws_frame/drive_step/drive_fail）对旧消费者（browser-manual）无感知
