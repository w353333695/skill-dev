# browser-recorder

跨平台、**平台中性**的浏览器操作录制 / 回放 / 导出 CLI。

录制人类在浏览器里的真实操作（点击、输入、滚动、导航等），同时采集网络请求、截图、可选录屏；可对录制轨迹做**回放**，并导出**图文报告（HTML / Markdown）+ 结构化接口清单**。

- 录制：Playwright + 页面注入钩子捕获事件，CDP 采集网络，按时机策略自动截图。
- 回放：按轨迹逐条重放（选择器回退 + 坐标兜底 + 页面稳定判定 + 失败不中断）。
- 导出：Pillow 半透明画标（序号气泡 + 描边 + 碰撞避让），跨次聚合接口字段 schema。
- 平台中性：主干不耦合任何特定系统 / host / 鉴权细节，对接走外部登录态 profile。

---

## 环境配置

需要 **Python ≥ 3.10** 与 **uv**（包管理）。

```bash
# 1. 安装依赖（在仓库根目录执行）
uv sync

# 2. 安装 Playwright 浏览器（录制/回放/集成测试需要 Chromium）
uv run playwright install chromium
```

验证安装：

```bash
uv run browser-recorder version      # 输出 0.1.0
uv run browser-recorder --help       # 列出 record / replay / export / auth / version
```

> 录屏可选转 mp4：依赖随包的 `imageio-ffmpeg`，无需系统安装 ffmpeg。默认录屏格式为 webm（Playwright 原生）。

---

## 快速开始

下面以一个**中性示例站点** `<your-site>` 为例（请替换为你要录制的真实地址）。

```bash
# 1. 录制：弹出浏览器，你手动操作，关闭浏览器即结束
uv run browser-recorder record --url https://<your-site>/list --name demo --headed

# 2. 导出：生成 HTML/Markdown 报告 + 接口清单 + 画标截图
uv run browser-recorder export demo

# 3. 回放：按轨迹重放（可选录屏）
uv run browser-recorder replay demo --video
```

> **人工录制必须 `--headed`**：默认的 `--headless` 适用于脚本驱动场景；纯 headless 下无人操作会得到空轨迹（无截图、无动作）。录制时长由"关闭浏览器"控制；不带 `--headed` 的脚本化录制默认约 10s 后结束。

录制产物落在 `tmp/<session-id>/`（过程产物），导出产物落在 `.browser-recorder/exports/<name>/`（最终产物）。可用 `--out-dir` 改变根目录。

---

## 配套 skill：browser-manual（推荐的生产用法）

「录制 → 出操作手册」的端到端流水线，封装在 `skills/browser-manual/`：按系统复用登录态、
按主题过滤后台请求、自动生成统一格式操作手册。详见 `skills/browser-manual/SKILL.md`。

```bash
bash skills/browser-manual/scripts/record-export.sh \
  --system <系统> --url <起始页> --scenario <场景> --theme "<主题>"
# 脚本跑完步骤 1-3（登录态保障 + record + export），再由 skill 内 Claude 做
# 步骤 4（主题过滤 → requests.theme.json + 接口清单.md）+ 步骤 5（手册分章 → manual.md）。
# 产物落在 <root>/<system>/exports/<scenario>/，<root> 默认 ./.browser-recordories/（--root 可改）。
```

---

## 子命令用法

### `record` —— 录制

```bash
uv run browser-recorder record \
  --url https://<your-site>/dashboard \
  --name my-rec \              # 易读会话名（不传则用时间戳）
  --auth my-profile \          # 登录态 profile（不传则按 scope 自动匹配；都无则匿名录制）
  --headed \                   # 有头模式，便于人工操作（默认 --headless）
  --screenshot-policy pol.yaml # 自定义截图时机（不传用默认）
  --no-video                   # 不录屏（默认录 webm）
```

| 选项                          | 说明                                                |
| ----------------------------- | --------------------------------------------------- |
| `--url`                     | 目标 URL（必填）                                    |
| `--auth`                    | 登录态 profile 名；不传则自动扫描匹配未过期 profile |
| `--name`                    | 易读会话名，用作过程/最终产物目录名                 |
| `--headless` / `--headed` | 是否无头（人工录制建议`--headed`）                |
| `--screenshot-policy`       | 截图时机策略 yaml（见下）                           |
| `--no-video`                | 关闭录屏                                            |
| `--keep-raw-bodies`         | 所有响应原始体落盘（不受 1MB 阈值限制）             |
| `--out-dir`                 | 产物根目录（默认`./.browser-recorder`）           |

### `export` —— 导出报告 + 接口清单

```bash
uv run browser-recorder export my-rec \
  --format md \                 # md（默认）/ html / both
  --annotate-style verbose \   # 或 compact
  --annotate-opacity 60 \      # 0–100，半透明填充透明度
  --filter-requests filter.yaml
```

| 选项                   | 说明                                                                  |
| ---------------------- | --------------------------------------------------------------------- |
| `--format`           | `md`（默认，只产 report.md）/ `html` / `both`                       |
| `--annotate-style`   | `verbose`（半透明填充 + 描边 + 序号）/ `compact`（仅描边 + 序号） |
| `--annotate-opacity` | 0–100，半透明填充透明度                                              |
| `--filter-requests`  | 请求过滤规则 yaml（见下），用于排除第三方/静态/特定状态码             |
| `--keep-raw-bodies`  | 导出期保留所有响应原始体引用                                          |
| `--name`             | 导出目录名（默认同 session 名）                                       |

### `replay` —— 回放

```bash
uv run browser-recorder replay my-rec \
  --pace human \               # faithful | human | slow
  --delay click.before=200ms \ # 细粒度覆盖
  --video --video-format mp4 --video-width 1024
```

| 选项                             | 说明                                                                                |
| -------------------------------- | ----------------------------------------------------------------------------------- |
| `--pace`                       | `faithful`（按录制真实时间戳）/ `human`（默认，固定停顿）/ `slow`（停顿 ×2） |
| `--delay`                      | 形如`click.before=200ms` / `input.after=500ms` / `*.idle=600ms`               |
| `--policy`                     | 回放延迟策略 yaml（不指定用内置默认）                                            |
| `--video` / `--video-format` | 录屏 + 格式（`webm` 默认，可 `mp4`）                                            |
| `--video-width`                | mp4 导出宽度（默认 **1024**，高度按原比例自动；`0`=不缩放）                      |
| `--annotate-during-replay`     | 回放期实时截图（含内联标记）                                                      |

### 默认值速查（非必填参数都有默认，最小命令即可跑）

- 浏览器：**locale=zh-CN**（中文界面/Accept-Language）、viewport 1280×720、headless。
- 截图策略 / 请求过滤：不传 `--screenshot-policy` / `--filter-requests` 时用**内置最佳实践默认**（见「配置文件示例」）。
- 回放：pace=`human`、video-format=`webm`、video-width=`1024`。
- 导出：format=`md`、annotate-style=`verbose`、annotate-opacity=`60`。
- 产物根目录：`./.browser-recorder`；会话名/导出名缺省用时间戳。

### `auth` —— 登录态管理

登录态基于 Playwright `storage_state`（cookies + localStorage），按 **registrable domain + host 范围**匹配，端口/子域/路径变化可容。

```bash
# 交互式登录并保存 profile（弹出浏览器，登录后回车）
uv run browser-recorder auth refresh my-profile --url https://<your-site>/login --expires 7

# 列出 / 查看
uv run browser-recorder auth list
uv run browser-recorder auth show my-profile
```

录制/回放时若不传 `--auth`，会自动扫描所有 profile，按 scope 匹配目标 URL，取最新未过期者。

---

## 产物结构

```
.browse-recorder/
├── auth/                              # 登录态
│   └── <profile>/
│       ├── meta.json                  # scope / 创建时间 / 有效期
│       └── storage_state.json
└── exports/
    └── <name>/                        # 最终产物（export 输出）
        ├── report.md                  # 图文报告（默认产物；--format html/both 才额外产 report.html）
        ├── report.html                # 仅 --format html/both 时产出
        ├── requests.json              # 聚合后的接口清单（按 method+url_template 分组）
        ├── structure.json             # 确定性页面分段（供 browser-manual skill 分章）
        ├── screenshots_annotated/     # 画标截图（半透明标注 + 序号）
        └── video.mp4 / video.webm     # 可选录屏

tmp/<session-id>/                      # 过程产物（record/replay 输出）
├── meta.json
├── trace.jsonl                        # 动作轨迹（每行一条 Action）
├── requests.jsonl                     # 网络请求（每行一条 RequestRecord）
├── screenshots/                       # 截图原图（step-NNNN-before/after.png）
├── responses/                         # 超 1MB 的响应原始体（C 方案落盘）
└── *.webm                             # 可选录屏
```

---

## 配置文件示例

> **内置默认**：截图策略与请求过滤都带**最佳实践默认**（`browser_recorder/defaults/*.yaml`）。
> 不传 `--screenshot-policy` / `--filter-requests` 时自动加载它们——截图策略与下表示例一致；
> 请求过滤默认排除静态资源/埋点/长连接/心跳/OPTIONS/304/204 等无业务语义请求，只保留有意义接口。
> 需要定制时拷贝默认 yaml、改完用对应参数指定即可。

### 截图时机策略（`--screenshot-policy`）

```yaml
# 动作类型 -> 截图点：before / after / [before,after] / []（不截）
points:
  click: [after]            # 事件在 capture 阶段触发，before 实为事件瞬间（spec §5.2）
  submit: [before, after]
  input: [after]
  select: [after]
  scroll: []
  navigation: [after]
  hover: [before]
dedup_window_ms: 500            # 同指纹同类型在此窗口内去重
input_aggregate_timeout_ms: 1500
```

### 请求过滤规则（`--filter-requests`）

```yaml
# 不传时用内置默认（同此示例）：排除无业务语义请求
exclude_url_patterns:           # 正则，匹配则排除
  - "\\.(js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|webp|map)(\\?|$)"
  - "/(sentry|beacon|track|log|report)"   # 埋点/日志上报
  - "^wss?://"                            # websocket 长连接
  - "/(healthz|ping|version)$"            # 心跳
exclude_methods: [OPTIONS]
exclude_status: [304, 204]      # 走缓存/无内容
exclude_resource_types: [ping, beacon]
```

### 回放延迟策略（`--policy`）

```yaml
delays:
  after_action:                 # 各类型动作后的「页面稳定」超时上限（ms）
    default: 5000
    submit: 15000
    navigation: 10000
  before_action:                # 动作前固定停顿（ms），受 --pace 缩放
    default: 500
    click: 300
  idle_for_visibility: 600
settle_debounce_ms: 300
```

---

## 视频内联标记

录屏（`record`/`replay` 带 `--video`）时，会在页面上注入「序号气泡 + 描边框」浮层并
随页面录进 webm→mp4，使**视频也能像画标截图一样标注每个动作位置**：

- **replay**：每个动作**前**在目标位置闪现标记（真正的 lead，「先标后点」），截图前清掉保持干净。
- **record**：事件在 capture 阶段才到，无法真正 lead；改为截图后近瞬时闪现，常驻到下一步。

颜色按动作类型区分（click/submit 红、input 蓝、select 紫…），与画标截图配色一致。仅录视频时启用，
不影响截图（截图在标记清掉后拍）。对应实现见 `browser_recorder/marker.py`。

## 录制细节默认

- **浏览器语言**：默认 `locale=zh-CN`（中文界面 + `Accept-Language`），便于中文系统录制；
  需要其它语言可在 `new_context(locale=...)` 覆盖。
- **可交互元素识别**（人工录制能捕到哪些点击）：钩子判定一个元素是否「可点」的信号依次是——
  原生交互标签(button/a/input/select/textarea/...)、`role`、内联 `onclick`、`contentEditable`、
  `cursor:pointer/cell`、**`tabindex`(B)**、**自定义元素标签名以 `-button/-link/-tab/-menuitem/-option/-switch` 结尾(A)**；
  并用 `composedPath` **穿透 shadow DOM** 找路径里第一个有真实盒子的可交互节点（跳过 `<slot>` 等 0 尺寸节点）。
  → 即使是 `eo-button` 这类「零信号自定义按钮」(shadow 内部常包了原生 button)，也能被记。
- **click+submit 合并**：点提交按钮会依次触发 `click`(button) + `submit`(form)，capture 层自动把
  窗口内的两者合并为一条、保留 click（bbox 是按钮更精准），不再产生重复动作/标注。通用 DOM 行为。
- **mp4 分辨率**：`--video-format mp4` 时 `--video-width`（默认 **1024**）控制宽度，高度按原比例
  自动计算；`0` 表示不缩放、保持原分辨率。
- **默认捕获所有点击**：点交互元素 → 记「最小可点击元素」（向上找首个自身可交互+真实盒子节点，bbox 最准）；
  点纯空白/容器 → 兜底记「最深的、有真实盒子的节点」，让无效点击留痕供后期清理。
  `--interactive-only` 关闭空白兜底（恢复「点空白丢弃」旧行为）。
  旧 `--capture-all-clicks` 已废弃（新默认即全捕），保留为 no-op+提示。

---

## 架构与平台中性

```
browser_recorder/
├── models.py            # 单一数据源：Action / Target / RequestRecord / ResponseInfo
├── paths.py config.py   # 路径解析 / 策略加载 / 内置最佳实践默认 conf
├── selectors.py         # 多维度选择器（role→css→xpath→坐标）+ 回退定位
├── settle.py            # 三信号页面稳定判定（网络/DOM/CPU + debounce）
├── marker.py            # 视频内联标记（序号气泡+描边框，随页面录进 mp4）
├── response_schema.py   # 响应体按 MIME 解析为字段骨架（结构不丢）
├── request_aggregator.py# 跨次聚合接口字段 schema（出现统计 / 数值采样）
├── defaults/            # 内置最佳实践默认：screenshot_policy.yaml / filter_requests.yaml
├── auth/                # 登录态 scope 匹配 + storage_state 存储
├── record/              # 注入钩子 / 事件捕获 / 截图时机（导航前短等）/ runner
├── replay/              # 延迟解析 / 执行器（视频 lead 标记）/ runner
└── export/              # Pillow 画标 / HTML+MD 报告 / 转码 / runner
```

**职责边界**：`record` / `replay` / `export` 三个子包互不 import 对方，只通过 `trace.jsonl` / `requests.jsonl` + `models` 通信，保证各自可独立测试。

**平台中性铁律**：主干代码、注释、变量名、测试 fixture 不得出现任何特定系统名 / host / IP / 端口 / 路由 / 鉴权细节。对接的系统通过 `auth` profile（外部 storage_state）接入，主干不知情。提交前自检：

```bash
grep -rinE "easyops|172\.|/next/api|toolId|aksk" browser_recorder/ || echo clean
```

---

## 测试

```bash
uv run pytest -q                          # 全量（含 demo_site 集成测试 + 浏览器烟测）
uv run pytest tests/test_cli_smoke.py -q  # 端到端：record → export → 画标截图
```

测试用 `tests/fixtures/demo_site/` 下的中性静态站点（登录 / 列表 / 搜索 XHR）驱动，不依赖任何真实系统。
