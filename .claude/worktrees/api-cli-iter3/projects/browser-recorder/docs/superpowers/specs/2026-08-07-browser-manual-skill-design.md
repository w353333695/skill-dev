# browser-manual 配套 skill + recorder 两项优化 — 设计文档

| 项 | 值 |
|---|---|
| 日期 | 2026-08-07 |
| 状态 | 已确认，待实现 |
| 项目 | `projects/browser-recorder/`（CLI 改动）+ 新增 skill `/workspace/skills/browser-manual/` |
| 基线 | branch `api-cli-iter2`（与 browser-recorder 现状无关，独立工作） |
| 前序 | `2026-08-02-browser-record-replay-design.md`（recorder 主体设计） |

---

## 1. 目标

在既有 `browser-recorder` 之上做**两项默认值优化**，并开发一个配套 skill **`browser-manual`**，把「按系统录制 + 复用登录态 + 按主题过滤后台请求 + 生成统一格式操作手册」串成一条端到端流水线。最终产物服务于 `projects/api-cli` 的 schema 分析（后续迭代再接，本迭代只产精筛 `requests.theme.json`）。

沿用 api-console 范式：**脚本做确定性脏活，LLM 做语义**。

## 2. 范围

### 2.1 范围内

- **A1**：`export` 默认产物 Markdown（html 改为可选）。
- **A2**：录制**默认捕获所有动作**，框选范围保持「最小可点击元素」。
- **A3**：`export` 增结构化产物 `structure.json`（供手册分章的确定性输入）。
- **B（skill browser-manual）**：
  - 统一输出目录、按系统归类、system 同时作登录态 profile 名实现「按系统复用登录态」。
  - 首次录制自动剔除登录过程（recorder 已默认剔除，skill 负责登录态保障编排）。
  - 按客户主题**语义过滤**后台请求，产 `requests.theme.json` + 可读 `接口清单.md`。
  - 按客户主题对 md **自动分章节/步骤**、补层级标题与操作说明，产统一格式 `manual.md`。

### 2.2 范围外（明确不做，防 scope creep）

- ❌ 不生成 api-cli YAML spec（延后；只产精筛 `requests.theme.json`）。
- ❌ 不改 record/export 核心架构、不破坏现有测试。
- ❌ skill/CLI 不硬编码任何特定系统名/host/鉴权（守平台中性铁律）。
- ❌ 不引入对 Claude/LLM 的外部 API 调用脚本——语义判断由 skill 内的 Claude 自身完成。

## 3. 现状关键事实（设计依据）

- `export` 现同时写 `report.md` + `report.html`（`export/runner.py:136-139`）。
- 录制钩子 `record/injector.py`：默认 `pickInteractive`（从最深节点向上找首个「自身可交互 + 真实盒子」节点 = **最小可点击元素**，bbox 最准）；`--capture-all-clicks`（默认关）取 `composedPath()[0]`（最深原始节点，bbox 常是 svg/path 碎片）；点空白 `pickInteractive` 返回 null → 不记录。
- 登录态：profile 缺失/过期且 `--headed` 时，`record/runner.py` 已自动弹临时浏览器让用户登录、回车后抓 storage_state 存入 profile 再正式录制（登录动作默认剔除；`--keep-auth-events` 为 reserved 未实现）。
- `--auth` 未传时 `auth/store.find_matching` 按 scope（registrable domain + host）自动匹配最新未过期 profile。
- `out_dir` 同时承载 `auth/<profile>/` 与 `exports/<name>/`，故「按系统归类」可用 `--out-dir <root>/<system>` + `--auth <system>` + `--name <scenario>` 组合实现，CLI 无需感知「系统」概念。

## 4. 设计

### 4.1 A1 — export 默认 Markdown

`export` 增 `--format md|html|both`，默认 `md`：

- `md`（默认）：只写 `report.md`。
- `html`：只写 `report.html`。
- `both`：两者都写。

`run_export` 据格式条件写报告文件；其余产物（requests.json / structure.json / 截图）不受影响。

### 4.2 A2 — 默认捕获所有动作 + 框选保持「最小可点击元素」

**澄清**：新默认 ≠ 旧 `--capture-all-clicks`（后者取最深原始节点，不符合「最小可点击元素」）。

新 click 捕获逻辑（`record/injector.py` 的 click handler）：

1. 先 `pickInteractive(e)`——拿「最小可点击元素」（向上找首个自身可交互 + 真实盒子节点，**不变**）。
2. 命中 → 记录该节点（bbox 最准）。
3. 未命中（点了纯空白/容器，路径内无可交互节点）→ **仍记录**，目标取 `composedPath` 里「最深的、有真实盒子（w>0 && h>0）」的节点（用户实际点中的东西），让无效点击留痕供后期清理。
4. 全路径无可交互且无任何有盒子节点 → 不记录（极端兜底，与现状一致）。

Flag 调整：

- 新增 `--interactive-only`：恢复「点空白丢弃」的旧行为（`pickInteractive` 返回 null 即不记）。
- 旧 `--capture-all-clicks`：降级为 **no-op + deprecation 警告**（其旧行为=最深原始节点，已被新默认取代；保留参数仅为不破坏旧调用，打印一行警告后走新默认）。

净效果：默认全捕、不漏；点按钮=按钮 bbox，点空白=点中节点 bbox；想要净化用 `--interactive-only`。

### 4.3 A3 — export 增 `structure.json`

`export` 额外写 `structure.json`：按 **navigation 动作** 与 **URL path 变化** 把 actions 切成「页面段」，每段挂其 action seq 列表 + 该段触发的接口组。

```json
{
  "url": "<起始 URL>",
  "segments": [
    {
      "index": 0,
      "page_url": "<该段代表性 URL>",
      "entry_action_seq": 1,
      "action_seqs": [1, 2, 3],
      "linked_endpoints": [
        {"method": "GET", "url_template": "/api/x", "observations": 2}
      ]
    }
  ],
  "actions_total": 12,
  "endpoints_total": 4
}
```

分段规则（确定性）：

- 遇 `navigation` 动作或 URL path（去掉 query）变化 → 开新段。
- 第一段从首个动作开始。
- 每段的 `linked_endpoints` = 该段 action_seqs 对应的聚合接口组（去重）。

这是 CLI 给 Claude 的「脏活」输入；Claude 据此合并/切分、起语义标题（§4.5）。

### 4.4 B — 目录布局（skill 组合 CLI 既有参数）

**统一输出根**：默认 `./.browser-recordories/`（相对 cwd），用户可经 skill `--root`（或环境变量 `BROWSER_RECORDINGS_ROOT`）自定义。

```
<root>/                              # 默认 ./.browser-recordories/
└── <system>/                        # --out-dir <root>/<system>
    ├── auth/<system>/               # --auth <system>；登录态按系统独立、复用
    │   ├── meta.json
    │   └── storage_state.json
    └── exports/<scenario>/          # --name <scenario>
        ├── report.md                # A1 默认
        ├── requests.json            # 聚合接口清单（全量，含 schema）
        ├── structure.json           # A3 确定性分章输入
        ├── screenshots_annotated/
        ├── requests.theme.json      # skill 主题精筛产物（§4.6）
        ├── 接口清单.md               # skill 主题相关可读清单
        └── manual.md                # skill 统一格式手册（§4.7）
```

**system 同时是 auth profile 名** → 首次录制某系统弹窗登录一次、存 `<root>/<system>/auth/<system>/`，之后该系统所有录制自动复用（profile 缺失/过期且 headed 时 recorder 已自动弹登录）。skill 只需保证 `--auth <system>` + `--out-dir <root>/<system>`。

### 4.5 B — skill 工作流

输入：`--system`（必填）、`--url`（起始页）、`--scenario`（场景名）、`--theme`（自然语言主题，如「资产导入流程」）、可选 `--login-url`（缺省=`--url`）、`--reauth`（强制重登）、`--root`（缺省=`./.browser-recordories/`）、`--headed/--headless`（缺省 headed）。

| 步骤 | 动作 | 执行者 |
|---|---|---|
| 1 登录态保障 | 查 `<root>/<system>/auth/<system>/`；缺失/过期/`--reauth` → `auth refresh <system> --url <login-url> --out-dir <root>/<system>`（弹窗人工登录一次） | `scripts/run.sh` |
| 2 录制 | `record --url <url> --auth <system> --name <scenario> --out-dir <root>/<system> --headed`（A2 全捕、A1 md 默认已内置） | `scripts/run.sh` |
| 3 导出 | `export <scenario> --out-dir <root>/<system> --format md` → report.md / requests.json / structure.json / 截图 | `scripts/run.sh` |
| 4 主题精筛 | 读 requests.json + theme；对每个接口组判主题相关性 → 写 `requests.theme.json`（仅相关 + schema）+ `接口清单.md` | **Claude 语义** |
| 5 手册分章 | 读 structure.json + report.md + 截图 + theme → 合并/切分章节、起层级标题、写操作说明 → `manual.md` | **Claude 语义** |

skill 产物结构（照 api-console 风格）：

```
skills/browser-manual/
├── SKILL.md            # 工作流 + 步骤 4/5 语义提示模板 + 统一格式规范
├── scripts/
│   └── run.sh          # 步骤 1-3 的确定性 CLI 编排（含登录态保障）
└── references/
    ├── manual-format.md    # manual.md 统一格式规范（章节/步骤/标题/操作说明写法）
    └── theme-filter.md     # 主题过滤判定准则（相关性判据、边界接口如何处置）
```

### 4.6 B — 主题精筛（步骤 4，Claude 语义）

**输入**：`requests.json`（聚合接口组，每组 `{endpoint, observations, merged_schema, ...}`）+ 用户 `theme`。
**确定性前置**：export 已用内置默认 filter（排除静态/埋点/长连接/OPTIONS/304/第三方）。
**语义判定**（Claude）：对每个接口组，据 `url_template` + `merged_schema` 字段语义判与 theme 的相关性 → 保留 / 丢弃。判据见 `references/theme-filter.md`（如「theme=资产导入」保留 import/upload 相关、丢弃用户菜单/通知/权限等无关；边界接口默认保留并标注「待确认」）。
**输出**：
- `requests.theme.json`：仅相关接口组的数组（结构同 requests.json 子集，附 `relevance_note`）。
- `接口清单.md`：可读清单（method/url/字段 schema/与主题关系）。

### 4.7 B — 操作手册（步骤 5，Claude 语义）

**输入**：`structure.json`（确定性分段）+ `report.md`（每步描述 + 截图）+ `requests.theme.json`（主题相关接口）+ `theme`。
**Claude 做的语义活**：以 `structure.json` 的 segments 为章候选 → 据动作语义合并/切分 → 起「## 一、<语义章节标题>」→ 每步起「### 步骤 N：<一句话说清在干嘛>」+ 操作说明 + 关联主题接口 + 截图。
**输出** `manual.md`，严格遵循 `references/manual-format.md` 的统一格式：

```markdown
# <System> · <Scenario> 操作手册
> 主题：<theme> ｜ 系统：<system> ｜ 场景：<scenario> ｜ 生成：YYYY-MM-DD

## 一、<章节标题>
### 步骤 1：<语义化动作说明，如「在搜索框输入工单号」>
- 操作：点击「新建」按钮 / 输入 `工单号`
- 触发接口：`GET /api/x`（主题相关）
![步骤1](screenshots_annotated/step-0001-after.png)

## 二、<章节标题>
...

## 附：主题相关接口清单
- `GET /api/x` — <一句话用途>
```

## 5. 测试

- **A1** `tests/test_export_format.py`（或扩 `test_report_md/html`）：`--format md` 只产 report.md（无 html）；`html` 只产 report.html；`both` 都产；缺省=md。
- **A2** 集成用例（`tests/fixtures/demo_site/`）：点空白现在被记录（目标=最深深实盒节点）；`--interactive-only` 恢复丢弃；旧 `--capture-all-clicks` = 新默认并打 deprecation 警告。
- **A3** `tests/test_export_structure.py`：structure.json 按 navigation/URL path 切段；段内 action_seqs 与 linked_endpoints 正确。
- **skill** `skills/browser-manual/evals/evals.json`：给示例 trace+theme，断言手册章节结构与精筛 requests.theme.json 的相关性（照 api-console evals 风格）。

## 6. 平台中性约束（铁律）

- CLI 主干、skill、SKILL.md、scripts 不得出现任何特定系统名/host/路由/鉴权细节。
- system / scenario / theme / login-url 全由用户输入；skill 不内置任何系统。
- 提交前自检沿用 `grep -rinE "easyops|172\.|/next/api|toolId|aksk" browser_recorder/ skills/browser-manual/`。

## 7. 实现顺序（writing-plans 据此细化）

1. A1 export `--format`（TDD：先测试）。
2. A2 injector 新默认 + `--interactive-only` + 旧 flag 降级（TDD）。
3. A3 export `structure.json`（TDD）。
4. skill 骨架：scripts/run.sh + SKILL.md + references/* + evals。
5. README 增 skill 用法 + A1/A2/A3 说明。
