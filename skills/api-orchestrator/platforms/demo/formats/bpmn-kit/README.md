# bpmn-kit —— ITSM 流程图合规检测 + 自动布局

## check_compliance.py —— 流程设计合规检测器

bpmn-js-bpmnlint 27 条规则 + EasyOps 扩展的等价 Python 实现，零依赖（纯标准库），
离线检测 BPMN 2.0 XML（flowable/camunda 扩展兼容）。

- **权威源**（2026-08-16 对源重校准）：`data/sources/frontend/ITSM/itsc-form-management/process-detail.e0d5.e200490e.js`
  （2.9MB lazy chunk = bricks/itsc-process-manage 1.84.9 流程设计 lazy-bricks，用户归档）
  - 27 条规则实现体 `rD["bpmnlint/<name>"]` + 启用配置 `oD.rules`（error/warn/off 等级表）
  - 中文消息对照表（144 条 en→zh 映射，检测消息已按此中文化）
  - 表达式变量提取 `nD`（math.js AST SymbolNode——Python 侧用正则近似，保留字/函数名排除）
- 规则分级（源码 oD 原样）：error 15 条 / warn 5 条 / off 7 条（`--include-off` 可开）
- 与源码的已知差异（修正笔误）：源码多处写 `"bpmn:ParallelGatewa"`（漏 y），已修正为
  `bpmn:ParallelGateway`——使并行网关被正确检查
- EasyOps 侧补充（bpmnlint 之外）：
  - `branch-gateway-only`（error）：节点多出边必须上网关（2026-08-15 用户实测——能建成但流转报错）
  - `form-decision-vars-consistent`（error）：表单决定流转变量与网关表达式变量一致性
  - `form-expression-path-resolvable`（error，2026-08-16）：**运行时取值路径存在性**——
    formExpressionName 的 `var:userTaskId.containId[row].componentId[.valueField]`
    逐段对照真实表单校验。对齐后端求值链（step/manager.go:1109 静默跳过语义 +
    GetFormValueByComponentId 的 Component.Key 匹配）：段数<4（静默无值走默认分支，
    最隐蔽）/ 节点不存在 / 无绑定表单 / 容器不存在 / 控件不存在 五类全部设计期拦截。
    前端 bpmnlint **无此规则**（前端靠级联选择器结构性规避），直调 API 绕过前端时
    这里是唯一防线。用法：`--form-bindings <json|@file>`（精简形
    `{userTaskId: []Container}` 或 process_version.get 的 taskInfo 原始数组），
    不传时仅格式层校验
  - `diagram-required` / `diagram-element-missing`：DI 图形坐标存在性（设计器渲染依赖）
- 🔴form-flow 布尔语义（2026-08-16 node 对拍定案）：不报 **当且仅当** 条件含 `==`；
  空条件/纯标识符/含 `>` `>=` 等一律报——旧注释把范围符号场景写反过，以 `rule_form_flow`
  docstring 的实测矩阵为准
- 入口：CLI `python3 check_compliance.py <file|XML|-> [--json] [--include-off] [--no-exit-code]`
- 使用方：flows/build-process.yaml（建流程链 0 error 门禁）/ flows/migrate-legacy-process.yaml（迁移合规门）

## relayout.py —— BPMN 自动布局（ITSM 流程图 DI 重排，无交叉版）

relayout.py：读入 bpmnXML（含烂 DI 或纯语义无 DI），重算全部节点坐标+正交连线，流程语义零改动。
- 算法（v2 无交叉版，2026-08-16 替换 Dagre 风格旧版——旧版实测 34 节点图 18 处穿节点+4 交叉）：
  长边虚拟节点化（跨层边拆链，结构上消除穿节点）→ 排序以零逆序为收敛判据
  （median sweep + transpose 精化 + 固定 seed 重启）→ 坐标保序落位（主链锚主流道 /
  虚拟链整链同走廊 y / 其余按相邻列前驱均值对齐，能对齐的直线连接）→
  列间通道轨道 x 分配（同 gap 竖直段各占一轨）；出入口一律边沿中点。
  CLI 内置几何校验器：节点重叠/连线穿节点/边-边交叉 三主指标非零 → exit 1。
- 观感指标（34 节点实测）：主链纯水平直线、26/41 条边零弯折、其余基本一次直角转。
- 入口：CLI `python3 relayout.py <in> [-o out] [--svg out.svg] [--no-strict]`；
  库 `from relayout import relayout_xml`（XML 串进出，签名与旧版兼容）
- 领域适配点（为何在 platforms 不在 skill）：flowable: 扩展属性、EasyOps parser 的
  incoming/outgoing 回填、userTask 100x80/网关 50x50 尺寸约定、bpmn2:→bpmn: 前缀重写（URI 等价）
- 使用方：flows/build-process.yaml（设计时生成即布局）/ flows/relayout-process-diagram.yaml（存量补救）

## 前端包重拉配方（换版本时）

union bootstrap `sa-static/micro-apps/v3/itsc-union/<ver>/bootstrap-union.<hash>.json` 的
brickPackages 里取 `bricks/itsc-process-manage/<ver>/dist/index.<hash>.js`（带 PHPSESSID cookie，
路径前缀 `/next/sa-static/-/`）；设计器规则在 lazy chunk（process-detail/process-design.e0d5.*），
主包里搜 `rD["bpmnlint/` 定位规则注册表。
