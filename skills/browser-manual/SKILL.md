---
name: browser-manual
description: 浏览器操作录制配套 skill——按系统复用登录态录制真实操作，按客户主题过滤后台请求并生成统一格式操作手册。覆盖「录某系统操作流程出操作手册」「按主题精筛接口清单供后续 api-cli schema 分析」「首次登录后复用登录态多次录制」。当用户提到录制系统操作/出操作手册/操作文档/按主题过滤接口/录制某系统流程，或要在 projects/api-cli 之外先采接口 schema 时，使用本 skill。
version: 0.1.0
---
# browser-manual

`browser-recorder` 的配套编排 skill。把「按系统录制 + 复用登录态 + 按主题过滤后台请求 + 生成统一格式操作手册」串成一条流水线。范式：**脚本（`scripts/record-export.sh`）做确定性脏活，Claude 做语义**。

## 何时用

- 「录一下 XX 系统的 YY 操作流程，出一份操作手册」
- 「按主题过滤这次录到的接口，给我一份干净的接口清单」
- 「我要录某系统的操作，复用上次登录态」

## 工作流（5 步）

输入：`--system`（必填，同时作登录态 profile 名）、`--url`（起始页）、`--scenario`（场景名）、`--theme`（自然语言主题，如「资产导入流程」）、可选 `--login-url`（缺省=`--url`）、`--reauth`（强制重登）、`--root`（缺省 `./.browser-recordories/` 或 `$BROWSER_RECORDINGS_ROOT`）、`--headed/--headless`（缺省 headed）。

### 步骤 1-3：确定性（跑 scripts/record-export.sh）

```bash
bash skills/browser-manual/scripts/record-export.sh \
  --system <sys> --url <url> --scenario <scn> [--login-url <u>] [--root <dir>] [--reauth]
```

脚本自动：

1. **登录态保障**——`--reauth` 时先弹窗重登；否则 `record` 在 headed 下检测到 profile 缺失/过期会自动弹登录窗、抓 storage_state 存入 profile（profile 名=system 名，落 `<root>/<system>/auth/<system>/`）再正式录制。首次登录动作默认已剔除。
2. **录制**——默认全捕（点交互元素=最小可点击元素；点空白=兜底记最深有盒节点），headed 便于人工操作。
3. **导出**——`export --format md` 产 `report.md` / `requests.json` / `structure.json` / 画标截图。

> 录制过程：浏览器弹出后正常操作；完成按 **Ctrl/Cmd+Shift+X** 或关浏览器结束。

### 步骤 4：主题过滤（Claude 语义）

读 `<root>/<system>/exports/<scenario>/requests.json` + 用户 theme，按 `references/theme-filter.md` 准则逐组判相关性，写：

- `requests.theme.json`（仅相关组 + 每组一句 `relevance_note`）
- `接口清单.md`（可读表格清单）

### 步骤 5：手册分章（Claude 语义）

读 `structure.json`（确定性页面段）+ `report.md`（每步描述+截图）+ `requests.theme.json`（主题接口）+ theme，按 `references/manual-format.md` 规范产出 `manual.md`（统一格式：语义章节 / 步骤标题 / 操作说明 / 触发接口 / 截图）。**剔除** A2 全捕留下的无效点击噪音。

## 产物落点

`<root>/<system>/exports/<scenario>/`：

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `report.md` | export（步骤 3） | 平铺步骤报告（原始结构化） |
| `requests.json` | export | 全量聚合接口清单（含 schema） |
| `structure.json` | export | 确定性页面分段（供分章） |
| `screenshots_annotated/` | export | 画标截图 |
| `requests.theme.json` | 步骤 4（Claude） | 主题相关接口子集 + 相关性说明 |
| `接口清单.md` | 步骤 4（Claude） | 主题相关可读清单 |
| `manual.md` | 步骤 5（Claude） | 统一格式操作手册（最终交付） |

`requests.theme.json` 是后续接 `projects/api-cli` schema 分析的干净输入（本迭代不直接生成 api-cli YAML）。

## 铁律

- **平台中性**：system/scenario/theme/login-url 全由用户给，skill 不内置任何系统名/host/鉴权细节。
- **语义步骤必须先读真实文件再判断**；判不准的接口标「待确认」，不擅自丢弃。
- `--headless` 模式无法人工登录，要求 profile 已存在且未过期（或先用 `--reauth --headed` 建立登录态）。
