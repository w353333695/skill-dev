# browser-manual skill + recorder 两项优化 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 browser-recorder 加「导出默认 Markdown、默认捕获所有动作（框选=最小可点击元素）、导出增 structure.json」三项 CLI 优化，并开发配套 skill `browser-manual`（按系统复用登录态 + 主题过滤后台请求 + 生成统一格式操作手册）。

**Architecture:** CLI 继续做确定性脏活（A1/A2/A3），skill 做编排 + 语义（沿用 api-console「脚本脏活 / LLM 语义」范式）。统一输出根默认 `./.browser-recordories/`（相对 cwd，`--root` 可改）；system 同时作 auth profile 名实现「按系统复用登录态」。语义步骤（主题过滤、手册分章）由 skill 内 Claude 完成，不引外部 LLM API。

**Tech Stack:** Python 3.10+ / click / playwright / pillow / pyyaml（CLI）；skill = SKILL.md + bash scripts + references/*.md + evals.json。

## Global Constraints

- **平台中性铁律**：CLI 主干、skill、scripts、SKILL.md、references 不得出现任何特定系统名/host/路由/鉴权细节（system/scenario/theme/login-url 全由用户输入）。提交前自检：`grep -rinE "easyops|172\.|/next/api|toolId|aksk" browser_recorder/ skills/browser-manual/`。
- **Python ≥ 3.10**；包管理用 `uv`（`uv sync` / `uv run pytest`）。
- 现有测试不得回归；改默认行为的测试用例须同步更新断言。
- 遵循现有代码风格：`from __future__ import annotations`、dataclass、docstring 中文注释、文件头模块 docstring。
- 改完代码立即手动 commit（用户工作流：javis 会自动 chore(ai) 提交未提交改动，故主动用语义化 commit 信息）。

---

## File Structure

**CLI 改动（projects/browser-recorder/）：**
- `browser_recorder/cli.py` — `export` 加 `--format`；`record` 加 `--interactive-only`、`--capture-all-clicks` 降级为 no-op+警告。
- `browser_recorder/record/injector.py` — 新增 `pickDeepestWithBox`；click handler 新默认（先 `pickInteractive`，无果且非 `interactive_only` 时兜底）；去掉 `__br_capture_all`，加 `__br_interactive_only`。
- `browser_recorder/record/runner.py` — `_record_async`/`run_record` 的 `capture_all_clicks` 参数换为 `interactive_only`；注入脚本改 `__br_interactive_only`。
- `browser_recorder/export/structure.py` — **新建**，纯函数 `build_segments(actions, groups) -> dict`（按 navigation/URL path 切段）。
- `browser_recorder/export/runner.py` — `run_export` 加 `fmt="md"` 参数（条件写报告）+ 写 `structure.json`。
- `tests/test_export_format.py` — **新建**，A1 测试。
- `tests/test_export_structure.py` — **新建**，A3 测试。
- `tests/test_injector.py` — 改 A2 断言。
- `tests/test_injector_interactive.py` — 改 A2 行为断言。
- `tests/test_cli_smoke.py` — run_export 调用加 `fmt="both"`（保持两报告都测）。

**Skill（/workspace/skills/browser-manual/，新建整目录）：**
- `SKILL.md` — 工作流 + 语义步骤提示模板。
- `scripts/run.sh` — 步骤 1-3 确定性 CLI 编排（登录态保障 + record + export）。
- `references/manual-format.md` — manual.md 统一格式规范。
- `references/theme-filter.md` — 主题过滤判定准则。
- `evals/evals.json` — 手册/过滤结构断言。

**文档：** `projects/browser-recorder/README.md` 增 skill 用法 + A1/A2/A3 说明。

---

## Task 1: A1 — export 默认 Markdown（`--format md|html|both`）

**Files:**
- Modify: `browser_recorder/export/runner.py`（`run_export` 签名 + 条件写报告）
- Modify: `browser_recorder/cli.py`（`export` 加 `--format`）
- Modify: `tests/test_cli_smoke.py`（run_export 加 `fmt="both"`）
- Test: `tests/test_export_format.py`（新建）

**Interfaces:**
- Produces: `run_export(session, out_dir, name, filter_path, keep_raw_bodies, annotate_style, annotate_opacity, tmp_root=None, fmt="md") -> Path`。`fmt` 取值 `"md"`|`"html"`|`"both"`，决定写哪些报告文件（其余产物不变）。

- [ ] **Step 1: 写失败测试 `tests/test_export_format.py`**

```python
# tests/test_export_format.py
"""A1：export 默认产物 Markdown；--format html/both 控制是否额外产 html。"""
import json
from pathlib import Path
from browser_recorder.models import Action, Target, RequestRecord, ResponseInfo
from browser_recorder.export import runner as exp


def _seed_session(tmp_root: Path, name: str = "s1") -> Path:
    """在 tmp_root 下造一个最小 session（trace+requests+meta），返回 session_dir。"""
    from browser_recorder import paths
    paths.TMP_ROOT = tmp_root
    sd = paths.session_dir(name)
    sd.mkdir(parents=True, exist_ok=True)
    a = Action(seq=1, ts=0, type="click", url="https://x.com/p",
               target=Target(css="#go", bbox={"x": 1, "y": 1, "w": 10, "h": 10}))
    (sd / "trace.jsonl").write_text(json.dumps(a.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    (sd / "requests.jsonl").write_text("", encoding="utf-8")
    (sd / "meta.json").write_text(json.dumps({"url": "https://x.com/p"}), encoding="utf-8")
    return sd


def _export(tmp_path, fmt):
    sd = _seed_session(tmp_path / "tmp")
    return exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp", fmt=fmt)


def test_default_format_is_md_only(tmp_path: Path):
    edir = _export(tmp_path, fmt="md")
    assert (edir / "report.md").exists()
    assert not (edir / "report.html").exists(), "默认不应再产 html"


def test_format_html_only(tmp_path: Path):
    edir = _export(tmp_path, fmt="html")
    assert (edir / "report.html").exists()
    assert not (edir / "report.md").exists()


def test_format_both(tmp_path: Path):
    edir = _export(tmp_path, fmt="both")
    assert (edir / "report.md").exists()
    assert (edir / "report.html").exists()


def test_default_fmt_when_not_passed(tmp_path: Path):
    """不传 fmt → 默认 md（旧行为同时产两文件，须回归为只产 md）。"""
    sd = _seed_session(tmp_path / "tmp")
    edir = exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp")
    assert (edir / "report.md").exists()
    assert not (edir / "report.html").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_export_format.py -q`
Expected: FAIL（`run_export() got an unexpected keyword argument 'fmt'`，且 report.html 仍被默认生成）。

- [ ] **Step 3: 改 `run_export` 加 `fmt` 参数 + 条件写报告**

在 `browser_recorder/export/runner.py`，把签名与报告写入段改为：

```python
def run_export(session, out_dir, name, filter_path, keep_raw_bodies,
               annotate_style, annotate_opacity, tmp_root=None, fmt="md") -> Path:
    """导出入口：返回 export 目录。session 是 session_id 或 name。

    fmt: "md"（默认，只写 report.md）/ "html"（只写 report.html）/ "both"（都写）。
    """
    if fmt not in ("md", "html", "both"):
        raise ValueError(f"未知 format: {fmt}（应为 md|html|both）")
    out_dir = Path(out_dir) if not isinstance(out_dir, Path) else out_dir
```

把末尾两行无条件写报告：

```python
        (edir / "report.md").write_text(
            report_md.render(actions, groups, annotated_map, meta), encoding="utf-8")
        (edir / "report.html").write_text(
            report_html.render(actions, groups, annotated_map, meta), encoding="utf-8")
        return edir
```

改为条件写：

```python
        if fmt in ("md", "both"):
            (edir / "report.md").write_text(
                report_md.render(actions, groups, annotated_map, meta), encoding="utf-8")
        if fmt in ("html", "both"):
            (edir / "report.html").write_text(
                report_html.render(actions, groups, annotated_map, meta), encoding="utf-8")
        return edir
```

- [ ] **Step 4: 改 `tests/test_cli_smoke.py` 让端到端仍测两份报告**

把 `run_export(...)` 调用（约 42-47 行）加 `fmt="both"`：

```python
    out = exp_runner.run_export(
        session=str(session_dir.name), out_dir=tmp_path / ".browser-recorder",
        name="smoke", filter_path=None, keep_raw_bodies=False,
        annotate_style="verbose", annotate_opacity=60,
        tmp_root=tmp_path / "tmp", fmt="both",
    )
```

（否则默认 md 会让 `assert (out / "report.html").exists()` 失败。）

- [ ] **Step 5: 加 CLI `--format` 选项**

在 `browser_recorder/cli.py` 的 `export` 命令，`@click.argument("session")` 后的选项区追加：

```python
@click.option("--format", "fmt", type=click.Choice(["md", "html", "both"]), default="md",
              help="导出报告格式：md（默认）/ html / both")
```

`export(...)` 形参加 `fmt`，并在 `run_export(...)` 调用末尾传 `fmt=fmt`：

```python
def export(session, filter_path, keep_raw_bodies, annotate_style, annotate_opacity, out_dir, name, fmt):
    """导出图文报告 + 接口清单。"""
    from . import paths
    from .export import runner
    od = paths.resolve_out_dir(out_dir)
    ed = runner.run_export(session, od, name,
                           Path(filter_path) if filter_path else None,
                           keep_raw_bodies, annotate_style, annotate_opacity, fmt=fmt)
    click.echo(f"导出完成：{ed}")
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_export_format.py tests/test_report_md.py tests/test_report_html.py tests/test_cli_smoke.py::test_cli_export_help_lists_subcommands -q`
Expected: PASS（4 个 format 测试 + 既有 report 测试 + CLI help 均过）。

- [ ] **Step 7: Commit**

```bash
cd /workspace/projects/browser-recorder
git add browser_recorder/export/runner.py browser_recorder/cli.py tests/test_export_format.py tests/test_cli_smoke.py
git commit -m "$(cat <<'EOF'
feat(browser-recorder): export 默认产物 Markdown（--format md|html|both）

默认只写 report.md；html 改为 --format html/both 显式开启。
test_cli_smoke 显式 fmt=both 以保持两报告渲染路径都被测。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: A2 — 默认捕获所有动作 + 框选保持「最小可点击元素」

**Files:**
- Modify: `browser_recorder/record/injector.py`（click handler 重写 + `pickDeepestWithBox`）
- Modify: `browser_recorder/record/runner.py`（`interactive_only` 取代 `capture_all_clicks`）
- Modify: `browser_recorder/cli.py`（`--interactive-only` 新增；`--capture-all-clicks` 降级 no-op+警告）
- Test: `tests/test_injector.py`、`tests/test_injector_interactive.py`

**Interfaces:**
- Produces: `run_record(..., interactive_only: bool = False) -> Path`（取代旧 `capture_all_clicks`）。injector JS 读 `window.__br_interactive_only`（真 → 关闭空白兜底，恢复「点空白丢弃」旧行为）。

**关键澄清（spec §4.2）**：新默认 ≠ 旧 `--capture-all-clicks`。新默认 = 先 `pickInteractive`（最小可点击元素，bbox 最准），无果且非 interactive_only 时兜底记「composedPath 里最深的、有真实盒子的节点」。

- [ ] **Step 1: 改 `tests/test_injector.py` 断言（去掉 `__br_capture_all`，加 `__br_interactive_only`）**

把 `test_inject_script_custom_button_and_tabindex_signals` 改为：

```python
def test_inject_script_custom_button_and_tabindex_signals():
    """A+B：isInteractiveSelf 识别自定义按钮标签名(-button/-link 等)、tabindex；
    新默认全捕兜底（__br_interactive_only 关闭兜底）；composedPath 穿透 shadow。"""
    s = injector.INJECT_SCRIPT
    import re
    # A：标签名模式（平台中性，不硬编码厂商前缀）
    assert re.search(r"-\(button\|link\|tab\|menuitem\|option\|switch\)", s), \
        "INJECT_SCRIPT 未按标签名模式识别自定义按钮"
    # B：tabindex 作为交互信号
    assert "hasAttribute('tabindex')" in s
    # interactive_only 逃生开关（关闭空白兜底）
    assert "__br_interactive_only" in s, "INJECT_SCRIPT 未支持 __br_interactive_only"
    # shadow 穿透
    assert "composedPath" in s
    # 旧 __br_capture_all 已退役
    assert "__br_capture_all" not in s
```

- [ ] **Step 2: 改 `tests/test_injector_interactive.py` 行为断言（空白默认现在被记；interactive_only 关闭兜底）**

把 `_collect_clicks` 的 `capture_all` 参数换为 `interactive_only`，并更新用例：

```python
async def _collect_clicks(click_selectors, html=HTML, interactive_only=False):
    """注入钩子到 HTML（file:// goto，会触发 init script），点若干选择器，返回 click 列表。"""
    d = Path(tempfile.mkdtemp()) / "t.html"
    d.write_text(html, encoding="utf-8")
    async with async_playwright() as pw:
        b = await launch(pw, headless=True)
        ctx = await new_context(b)
        page = await ctx.new_page()
        captured = []
        await page.expose_function("__br_emit", lambda ev: captured.append(ev))
        await page.expose_function("__br_flush", lambda: None)
        await page.expose_function("__br_stop", lambda: None)
        await ctx.add_init_script(INJECT_SCRIPT)
        if interactive_only:
            await ctx.add_init_script("window.__br_interactive_only = true;")
        await page.goto(f"file://{d}", wait_until="domcontentloaded")
        await page.wait_for_timeout(150)
        for sel in click_selectors:
            await page.locator(sel).first.click(timeout=3000)
            await page.wait_for_timeout(80)
        await b.close()
        return [ev.get("target_node") or {} for ev in captured if ev.get("type") == "click"]
```

把模块 docstring 末段、`test_blank_div_not_captured_by_default`、`test_capture_all_records_blank` 三处替换为：

```python
@pytest.mark.asyncio
async def test_blank_div_captured_by_default():
    """新默认全捕：点纯 div 现在也记（目标=最深深实盒节点，即该 div）。"""
    clicks = await _collect_clicks(["#blank"])
    assert len(clicks) == 1
    assert clicks[0].get("tag") == "div"
    assert clicks[0].get("css", "").startswith("#blank")


@pytest.mark.asyncio
async def test_interactive_only_skips_blank():
    """--interactive-only：关闭空白兜底，点纯 div 不记（恢复旧行为）。"""
    clicks = await _collect_clicks(["#blank"], interactive_only=True)
    assert clicks == []
```

（`test_custom_button_tag_captured`、`test_tabindex_widget_captured`、`test_native_button_still_captured` 保留不变。）

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_injector.py tests/test_injector_interactive.py -q`
Expected: FAIL（`__br_interactive_only` 不存在于脚本；空白默认仍不记）。

- [ ] **Step 4: 改 `injector.py` —— 加 `pickDeepestWithBox` + 重写 click handler**

在 `browser_recorder/record/injector.py` 的 `INJECT_SCRIPT` 中，找到现有 click handler：

```js
  document.addEventListener('click', function(e){
    var target;
    if (window.__br_capture_all) {
      // 逃生开关（--capture-all-clicks）：关掉交互过滤，记录所有 click（含点空白）。
      // 取 composedPath 最深节点作为目标，最具体。默认关闭，仅在 A+B 仍漏时启用。
      target = (e.composedPath && e.composedPath()[0]) || e.target;
    } else {
      target = pickInteractive(e);
    }
    if (!target) return;  // 点空白处不记 click、不截图
    emit('click', target, null);
  }, true);
```

替换为（新增兜底函数 + 新默认逻辑）：

```js
  // 兜底：路径里无「自身可交互」节点时（点了纯空白/容器），取 composedPath 里最深的、
  // 有真实盒子的节点（用户实际点中的东西），让无效点击也留痕供后期清理。
  // composedPath 从深到浅，故首个有真实盒子的即最深者。
  function pickDeepestWithBox(e){
    var path = (e.composedPath && e.composedPath()) || [e.target];
    for (var i = 0; i < path.length && i < 12; i++){
      var n = path[i];
      if (!n || n.nodeType !== 1) continue;
      try {
        var r = n.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) return n;
      } catch(_) {}
    }
    return null;
  }
  document.addEventListener('click', function(e){
    // 优先：最小可点击元素（向上找首个自身可交互 + 真实盒子节点，bbox 最准）
    var target = pickInteractive(e);
    if (!target && !window.__br_interactive_only){
      // 默认全捕：无可交互节点时兜底记「最深有盒节点」；
      // --interactive-only（window.__br_interactive_only）关闭此兜底，恢复「点空白丢弃」。
      target = pickDeepestWithBox(e);
    }
    if (!target) return;
    emit('click', target, null);
  }, true);
```

- [ ] **Step 5: 改 `runner.py` —— `capture_all_clicks` → `interactive_only`**

在 `browser_recorder/record/runner.py`：

`_record_async` 签名末参 `capture_all_clicks: bool = False` 改为 `interactive_only: bool = False`。

把注入段（约 257-259 行）：

```python
        # 逃生开关：--capture-all-clicks 时关掉交互过滤，记录所有 click（默认关）
        if capture_all_clicks:
            await ctx.add_init_script("window.__br_capture_all = true;")
```

改为：

```python
        # --interactive-only：关闭空白点击兜底，恢复「点纯空白丢弃」的旧行为。
        # 新默认（不传）= 全捕：先取最小可点击元素，无果时兜底记最深有盒节点。
        if interactive_only:
            await ctx.add_init_script("window.__br_interactive_only = true;")
```

`run_record` 签名末参 `capture_all_clicks: bool = False` 改为 `interactive_only: bool = False`；其内 `asyncio.run(_record_async(... capture_all_clicks=capture_all_clicks))` 改为 `... interactive_only=interactive_only)`。

- [ ] **Step 6: 改 `cli.py` —— 加 `--interactive-only`、降级 `--capture-all-clicks`**

`browser_recorder/cli.py` 的 `record` 命令选项区，把现有：

```python
@click.option("--capture-all-clicks", "capture_all_clicks", is_flag=True,
              help="逃生开关：关掉交互过滤、记录所有 click（含点空白，噪音大）。"
                   "默认关；仅当 A+B（自定义按钮/tabindex 识别）仍漏动作时启用")
def record(url, profile, keep_auth_events, screenshot_policy, no_video, out_dir, name,
           headless, keep_raw_bodies, ignore_https_errors, record_timeout_s,
           capture_all_clicks):
```

改为（保留旧 flag 名作 no-op、新增 interactive-only）：

```python
@click.option("--capture-all-clicks", "capture_all_clicks", is_flag=True,
              help="(已废弃，现为 no-op) 新默认即捕获所有点击；保留参数仅为不破坏旧脚本")
@click.option("--interactive-only", "interactive_only", is_flag=True,
              help="关闭空白点击兜底：点纯空白/容器不记（恢复旧默认）。"
                   "默认关（全捕，由用户后期清理无效点击）")
def record(url, profile, keep_auth_events, screenshot_policy, no_video, out_dir, name,
           headless, keep_raw_bodies, ignore_https_errors, record_timeout_s,
           capture_all_clicks, interactive_only):
    """录制浏览器操作。"""
    if capture_all_clicks:
        click.echo("[record] 提示：--capture-all-clicks 已废弃（新默认即捕获所有点击），本次忽略该参数。")
    if keep_auth_events:
```

`run_record(...)` 调用（约 58-64 行）去掉 `capture_all_clicks=capture_all_clicks`、加 `interactive_only=interactive_only`：

```python
    sd = runner.run_record(url, od, profile, keep_auth_events,
                           Path(screenshot_policy) if screenshot_policy else None,
                           video=not no_video, name=name, headless=headless,
                           keep_raw_bodies=keep_raw_bodies,
                           ignore_https_errors=ignore_https_errors,
                           record_timeout_s=record_timeout_s,
                           interactive_only=interactive_only)
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_injector.py tests/test_injector_interactive.py tests/test_capture.py -q`
Expected: PASS（空白默认被记、interactive_only 关闭兜底、click+submit 合并不回归）。

- [ ] **Step 8: Commit**

```bash
cd /workspace/projects/browser-recorder
git add browser_recorder/record/injector.py browser_recorder/record/runner.py browser_recorder/cli.py tests/test_injector.py tests/test_injector_interactive.py
git commit -m "$(cat <<'EOF'
feat(browser-recorder): 默认捕获所有动作，框选保持最小可点击元素

- click 先取 pickInteractive（最小可点击元素，bbox 最准），无果时兜底记
  composedPath 里最深的、有真实盒子的节点（让无效点击留痕供后期清理）。
- 新增 --interactive-only 关闭空白兜底（恢复旧默认）。
- --capture-all-clicks 降级为 no-op+警告（新默认已全捕）。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: A3 — export 增 `structure.json`（确定性分章输入）

**Files:**
- Create: `browser_recorder/export/structure.py`（纯函数 `build_segments`）
- Modify: `browser_recorder/export/runner.py`（写 structure.json）
- Test: `tests/test_export_structure.py`（新建）

**Interfaces:**
- Produces: `build_segments(actions: list[Action], groups: list[dict]) -> dict`。返回 `{"url","segments":[{index,page_url,entry_action_seq,action_seqs,linked_endpoints}],"actions_total","endpoints_total"}`。分段规则：首个动作起段；遇 `navigation` 动作或 URL path 变化开新段。`linked_endpoints` 元素 `{method,url_template,observations}`（段内去重）。

- [ ] **Step 1: 写失败测试 `tests/test_export_structure.py`**

```python
# tests/test_export_structure.py
"""A3：build_segments 按 navigation/URL path 切段；run_export 写 structure.json。"""
import json
from pathlib import Path
from browser_recorder.models import Action, Target
from browser_recorder.export.structure import build_segments


def _act(seq, atype, url):
    return Action(seq=seq, ts=0, type=atype, url=url,
                  target=Target(css="#x", bbox={"x": 0, "y": 0, "w": 1, "h": 1}))


def test_single_page_single_segment():
    actions = [_act(1, "click", "https://x.com/a"), _act(2, "input", "https://x.com/a")]
    s = build_segments(actions, [])
    assert s["actions_total"] == 2
    assert len(s["segments"]) == 1
    assert s["segments"][0]["action_seqs"] == [1, 2]
    assert s["segments"][0]["page_url"] == "https://x.com/a"
    assert s["segments"][0]["entry_action_seq"] == 1


def test_navigation_starts_new_segment():
    actions = [
        _act(1, "click", "https://x.com/a"),
        _act(2, "navigation", "https://x.com/b"),
        _act(3, "click", "https://x.com/b"),
    ]
    s = build_segments(actions, [])
    assert len(s["segments"]) == 2
    assert s["segments"][0]["action_seqs"] == [1]
    assert s["segments"][1]["action_seqs"] == [2, 3]
    assert s["segments"][1]["entry_action_seq"] == 2


def test_url_path_change_starts_new_segment():
    # query 变化不算新页（path 相同），仅 path 变化才切。
    actions = [
        _act(1, "click", "https://x.com/list?q=1"),
        _act(2, "click", "https://x.com/list?q=2"),    # 同 path，同段
        _act(3, "click", "https://x.com/detail/1"),    # path 变，新段
    ]
    s = build_segments(actions, [])
    assert len(s["segments"]) == 2
    assert s["segments"][0]["action_seqs"] == [1, 2]
    assert s["segments"][1]["action_seqs"] == [3]


def test_linked_endpoints_dedup_per_segment():
    actions = [_act(1, "click", "https://x.com/a")]
    groups = [{"endpoint": {"method": "GET", "url_template": "/api/x", "param_path": []},
               "observations": 3, "linked_seq": [1]}]
    s = build_segments(actions, groups)
    assert s["endpoints_total"] == 1
    assert s["segments"][0]["linked_endpoints"] == [
        {"method": "GET", "url_template": "/api/x", "observations": 3}]


def test_empty_actions():
    s = build_segments([], [])
    assert s["segments"] == []
    assert s["actions_total"] == 0


def test_run_export_writes_structure_json(tmp_path: Path):
    from browser_recorder import paths
    from browser_recorder.export import runner as exp
    paths.TMP_ROOT = tmp_path / "tmp"
    sd = paths.session_dir("s1")
    sd.mkdir(parents=True, exist_ok=True)
    a = _act(1, "click", "https://x.com/a")
    (sd / "trace.jsonl").write_text(json.dumps(a.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
    (sd / "requests.jsonl").write_text("", encoding="utf-8")
    (sd / "meta.json").write_text(json.dumps({"url": "https://x.com/a"}), encoding="utf-8")
    edir = exp.run_export(session="s1", out_dir=tmp_path / "out", name="s1",
                          filter_path=None, keep_raw_bodies=False,
                          annotate_style="verbose", annotate_opacity=60,
                          tmp_root=tmp_path / "tmp", fmt="md")
    data = json.loads((edir / "structure.json").read_text(encoding="utf-8"))
    assert data["actions_total"] == 1
    assert len(data["segments"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_export_structure.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'browser_recorder.export.structure'`）。

- [ ] **Step 3: 新建 `browser_recorder/export/structure.py`**

```python
# browser_recorder/export/structure.py
"""结构化分章输入：按 navigation 动作 / URL path 变化把 actions 切成页面段。

确定性「脏活」：export 产 structure.json，供 skill 里的 Claude 据段做语义分章、
起层级标题。规则可解释、可单测，无语义判断。
"""
from __future__ import annotations
from urllib.parse import urlparse
from ..models import Action


def _path_of(url: str) -> str:
    return urlparse(url or "").path


def build_segments(actions: list[Action], groups: list[dict]) -> dict:
    """返回 {url, segments, actions_total, endpoints_total}。

    分段：首个动作起一段；遇 type=="navigation" 或 URL path 变化开新段。
    每段 linked_endpoints = 该段动作命中的接口组（按 method+url_template 去重）。
    groups 元素需含 endpoint.{method,url_template}、observations、linked_seq（见 request_aggregator + runner）。
    """
    # (method, tmpl) -> observations；seq -> 命中的接口 key 列表
    ep_obs: dict[tuple[str, str], int] = {}
    seq_to_eps: dict[int, list[tuple[str, str]]] = {}
    ep_keys: set[tuple[str, str]] = set()
    for g in groups:
        ep = g["endpoint"]
        key = (ep["method"], ep["url_template"])
        ep_keys.add(key)
        ep_obs[key] = g.get("observations", 0)
        for s in g.get("linked_seq", []):
            seq_to_eps.setdefault(s, []).append(key)

    segments: list[dict] = []
    cur: dict | None = None
    for a in actions:
        start_new = (cur is None or a.type == "navigation"
                     or _path_of(a.url) != _path_of(cur["page_url"]))
        if start_new:
            cur = {"index": len(segments), "page_url": a.url,
                   "entry_action_seq": a.seq, "action_seqs": [], "_eps": []}
            segments.append(cur)
        cur["action_seqs"].append(a.seq)
        for key in seq_to_eps.get(a.seq, []):
            if key not in cur["_eps"]:
                cur["_eps"].append(key)

    out_segs = [{
        "index": s["index"],
        "page_url": s["page_url"],
        "entry_action_seq": s["entry_action_seq"],
        "action_seqs": s["action_seqs"],
        "linked_endpoints": [
            {"method": k[0], "url_template": k[1], "observations": ep_obs.get(k, 0)}
            for k in s["_eps"]],
    } for s in segments]

    return {
        "url": actions[0].url if actions else "",
        "segments": out_segs,
        "actions_total": len(actions),
        "endpoints_total": len(ep_keys),
    }
```

- [ ] **Step 4: 在 `run_export` 写 structure.json**

`browser_recorder/export/runner.py` 顶部导入区加：

```python
from .structure import build_segments
```

在写 `requests.json` 之后、写报告之前，插入（约 133 行后）：

```python
        (edir / "structure.json").write_text(
            json.dumps(build_segments(actions, groups), ensure_ascii=False, indent=2),
            encoding="utf-8")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd /workspace/projects/browser-recorder && uv run pytest tests/test_export_structure.py tests/test_export_format.py -q`
Expected: PASS。

- [ ] **Step 6: 跑全量回归**

Run: `cd /workspace/projects/browser-recorder && uv run pytest -q`
Expected: PASS（确认 A1/A2/A3 未破坏既有测试；含 demo_site 集成与浏览器烟测）。

- [ ] **Step 7: Commit**

```bash
cd /workspace/projects/browser-recorder
git add browser_recorder/export/structure.py browser_recorder/export/runner.py tests/test_export_structure.py
git commit -m "$(cat <<'EOF'
feat(browser-recorder): export 增 structure.json（确定性分章输入）

按 navigation 动作 / URL path 变化把 actions 切成页面段，每段挂动作 seq 与
命中的接口组。供 browser-manual skill 里的 Claude 据段做语义分章。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 配套 skill `browser-manual` 骨架

**Files:**
- Create: `/workspace/skills/browser-manual/SKILL.md`
- Create: `/workspace/skills/browser-manual/scripts/run.sh`
- Create: `/workspace/skills/browser-manual/references/manual-format.md`
- Create: `/workspace/skills/browser-manual/references/theme-filter.md`
- Create: `/workspace/skills/browser-manual/evals/evals.json`

**Interfaces:**
- Consumes: `browser-recorder` CLI（`auth refresh` / `record` / `export`），A1（md 默认）/A2（全捕默认）/A3（structure.json）已就绪。
- Produces: `<root>/<system>/exports/<scenario>/{report.md, requests.json, structure.json, requests.theme.json, 接口清单.md, manual.md}`。root 默认 `./.browser-recordories/`，可 `--root` 或 `$BROWSER_RECORDINGS_ROOT` 覆盖。

**约定**：脚本只做确定性步骤 1-3（登录态保障 + record + export）；步骤 4（主题过滤）与 5（手册分章）由 SKILL.md 指引 Claude 用语义完成。

- [ ] **Step 1: 建 `scripts/run.sh`（步骤 1-3 编排）**

```bash
#!/usr/bin/env bash
# browser-manual：步骤 1-3 确定性 CLI 编排。
# 用法：scripts/run.sh --system <sys> --url <url> --scenario <scn> [--login-url <u>]
#                       [--root <dir>] [--reauth] [--headed|--headless]
# 产出：<root>/<system>/exports/<scenario>/{report.md,requests.json,structure.json,...}
# 步骤 4（主题过滤 requests.theme.json + 接口清单.md）与 5（manual.md）由 skill 内 Claude 语义完成。
set -euo pipefail

SYSTEM="" URL="" SCENARIO="" LOGIN_URL="" ROOT="${BROWSER_RECORDINGS_ROOT:-./.browser-recordories}"
REAUTH=0 HEADLESS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) SYSTEM="$2"; shift 2;;
    --url) URL="$2"; shift 2;;
    --scenario) SCENARIO="$2"; shift 2;;
    --login-url) LOGIN_URL="$2"; shift 2;;
    --root) ROOT="$2"; shift 2;;
    --reauth) REAUTH=1; shift;;
    --headless) HEADLESS=1; shift;;
    --headed) HEADLESS=0; shift;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done
[[ -n "$SYSTEM" && -n "$URL" && -n "$SCENARIO" ]] || { echo "用法: $0 --system <sys> --url <url> --scenario <scn> [--login-url <u>] [--root <dir>] [--reauth] [--headless]"; exit 2; }
LOGIN_URL="${LOGIN_URL:-$URL}"
OUT="$ROOT/$SYSTEM"
HEADED_FLAG="--headed"; [[ "$HEADLESS" == "1" ]] && HEADED_FLAG="--headless"

# 在 browser-recorder 项目目录里跑其 CLI（定位仓库）
BR_DIR="$(git rev-parse --show-toplevel 2>/dev/null)/projects/browser-recorder"
[[ -d "$BR_DIR" ]] || { echo "找不到 projects/browser-recorder（$BR_DIR）" >&2; exit 1; }
BR="uv run --project $BR_DIR browser-recorder"

# 步骤 1：登录态保障（首次/过期/--reauth 时弹窗人工登录一次；profile 名=system 名）
NEED_AUTH=1
if [[ "$REAUTH" == "0" ]] && "$BR" auth show "$SYSTEM" --out-dir "$OUT" >/dev/null 2>&1; then
  # profile 存在；再看过期（meta 里 expired=是 → 重登）
  if "$BR" auth show "$SYSTEM" --out-dir "$OUT" 2>&1 | grep -q "expired.*否"; then NEED_AUTH=0; fi
fi
if [[ "$NEED_AUTH" == "1" ]]; then
  echo "[browser-manual] 首次/过期：请在弹出浏览器完成 $SYSTEM 登录，登录后回终端按回车。"
  "$BR" auth refresh "$SYSTEM" --url "$LOGIN_URL" --out-dir "$OUT" --headed
fi

# 步骤 2：录制（A2 全捕默认、不传 --interactive-only；headed 便于人工操作）
echo "[browser-manual] 录制中：操作完成后按 Ctrl/Cmd+Shift+X 或关浏览器结束。"
"$BR" record --url "$URL" --auth "$SYSTEM" --name "$SCENARIO" --out-dir "$OUT" $HEADED_FLAG

# 步骤 3：导出（A1 md 默认；A3 自动产 structure.json）
"$BR" export "$SCENARIO" --out-dir "$OUT" --format md

echo "[browser-manual] 步骤 1-3 完成。产物在：$OUT/exports/$SCENARIO/"
echo "[browser-manual] 接下来由 Claude 做步骤 4（主题过滤）+ 5（手册分章）。"
```

赋可执行权限：`chmod +x /workspace/skills/browser-manual/scripts/run.sh`

- [ ] **Step 2: 建 `references/theme-filter.md`（主题过滤判定准则）**

```markdown
# 主题过滤判定准则（步骤 4）

读 `<out>/requests.json`（聚合接口组，每组 `{endpoint, observations, merged_schema, sample_statuses, linked_seq}`）+ 用户 `--theme`，逐组判与主题相关性，写：

- `requests.theme.json`：仅相关组（结构同 requests.json 子集，每组加 `relevance_note` 一句话理由）。
- `接口清单.md`：可读清单（method/url_template/字段 schema/与主题关系）。

## 判定准则

1. **强相关（保留）**：url_template 或 merged_schema 字段语义直接服务于主题。
   - 例：theme=「资产导入」→ 保留 `POST /import`、`POST /upload`、`GET /import/tasks`、含 `assetId/uploadStatus/batch` 字段者。
2. **强无关（丢弃）**：用户菜单/通知/权限/审计/通用分页元接口与主题无关。
   - 例：theme=「资产导入」→ 丢 `GET /user/menu`、`GET /notifications`、`GET /permissions`。
3. **边界（保留并标「待确认」）**：无法仅凭 schema 判断（如通用 `GET /list`、`POST /save`）。
   - 在 `relevance_note` 标注「待确认」，不擅自丢弃——宁多勿少，避免漏掉主题接口。
4. **去第三方/静态**：export 期内置 filter 已排除；此处不重复处理。

## 输出格式

`requests.theme.json` 是数组；元素沿用 requests.json 的组结构，追加：
```json
{"endpoint": {...}, "observations": 3, "merged_schema": {...}, "relevance_note": "导入任务查询，强相关"}
```

`接口清单.md` 用表格：`| 方法 | 接口 | 字段(节选) | 与主题关系 |`。
```

- [ ] **Step 3: 建 `references/manual-format.md`（manual.md 统一格式规范）**

```markdown
# manual.md 统一格式规范（步骤 5）

读 `<out>/structure.json`（确定性页面段）+ `report.md`（每步描述+截图）+ `requests.theme.json`（主题相关接口）+ 用户 `--theme`，产出 `<out>/manual.md`。

## 结构（严格遵循）

```markdown
# <System> · <Scenario> 操作手册

> 主题：<theme> ｜ 系统：<system> ｜ 场景：<scenario> ｜ 生成：YYYY-MM-DD

## 一、<语义章节标题>

### 步骤 1：<一句话说清这步在干嘛>
- 操作：<点击「新建」按钮 / 在搜索框输入 `工单号` / ...>
- 触发接口：`GET /api/x`（主题相关；无则省略此行）
![步骤1](screenshots_annotated/step-0001-after.png)

## 二、<语义章节标题>
...

## 附：主题相关接口清单
- `GET /api/x` — <一句话用途>
- `POST /api/y` — <一句话用途>
```

## 规则

- **章节**：以 structure.json 的 segments 为候选；据动作语义**合并**（同流程的连续段合成一章）或**切分**（一段内多流程拆多章）。章节标题用语义短语（如「二、查询与筛选」「三、提交导入任务」），不用「页面 A」「步骤 1-5」这类机械名。
- **步骤标题**：一句话概括动作意图（「在搜索框输入工单号并查询」），不照抄 type/css。
- **操作说明**：用「点击/输入/选择 + 元素描述」自然语言；输入值用反引号。
- **触发接口**：仅列 requests.theme.json 里的（主题相关）；该步无主题接口则省。
- **截图**：引用 screenshots_annotated/ 下对应文件（沿用 report.md 的文件名）。
- **生成日期**：用今天日期（YYYY-MM-DD）。
- 无效点击（A2 全捕留下的噪音）：据上下文语义**剔除**，不写进手册。
```

- [ ] **Step 4: 建 `SKILL.md`（工作流 + 语义提示模板）**

```markdown
---
name: browser-manual
description: 浏览器操作录制配套 skill——按系统复用登录态录制真实操作，按客户主题过滤后台请求并生成统一格式操作手册。覆盖「录某系统操作流程出操作手册」「按主题精筛接口清单供后续 api-cli schema 分析」「首次登录后复用登录态多次录制」。当用户提到录制系统操作/出操作手册/操作文档/按主题过滤接口/录制某系统流程，或要在 projects/api-cli 之外先采接口 schema 时，使用本 skill。
version: 0.1.0
---
# browser-manual

browser-recorder 的配套编排 skill。把「按系统录制 + 复用登录态 + 按主题过滤后台请求 + 生成统一格式操作手册」串成一条流水线。沿用 api-console 范式：**脚本（scripts/run.sh）做确定性脏活，Claude 做语义**。

## 何时用

- 「录一下 XX 系统的 YY 操作流程，出一份操作手册」
- 「按主题过滤这次录到的接口，给我一份干净的接口清单」
- 「我要录某系统的操作，复用上次登录态」

## 工作流（5 步）

输入：`--system`（必填，同时作登录态 profile 名）、`--url`（起始页）、`--scenario`（场景名）、`--theme`（自然语言主题，如「资产导入流程」）、可选 `--login-url`（缺省=`--url`）、`--reauth`（强制重登）、`--root`（缺省 `./.browser-recordories/` 或 `$BROWSER_RECORDINGS_ROOT`）、`--headed/--headless`（缺省 headed）。

### 步骤 1-3：确定性（跑 scripts/run.sh）

```
bash skills/browser-manual/scripts/run.sh \
  --system <sys> --url <url> --scenario <scn> --theme <theme> [--login-url <u>] [--root <dir>]
```

脚本自动：①保障登录态（首次/过期弹窗登录一次，profile 名=system 名，存 `<root>/<system>/auth/<system>/`）；②`record`（默认全捕、headed）；③`export --format md`（产 report.md / requests.json / structure.json / 画标截图）。

> 录制过程：浏览器弹出后正常操作；完成按 **Ctrl/Cmd+Shift+X** 或关浏览器结束。登录动作默认已剔除（recorder 行为）。

### 步骤 4：主题过滤（Claude 语义）

读 `<root>/<system>/exports/<scenario>/requests.json` + 用户 theme，按 `references/theme-filter.md` 准则逐组判相关性，写：
- `requests.theme.json`（仅相关组 + `relevance_note`）
- `接口清单.md`（可读表格清单）

### 步骤 5：手册分章（Claude 语义）

读 `structure.json`（确定性页面段）+ `report.md`（每步描述+截图）+ `requests.theme.json`（主题接口）+ theme，按 `references/manual-format.md` 规范产出 `manual.md`（统一格式：语义章节 / 步骤标题 / 操作说明 / 触发接口 / 截图）。剔除 A2 全捕留下的无效点击噪音。

## 产物落点

`<root>/<system>/exports/<scenario>/`：`report.md`、`requests.json`、`structure.json`、`screenshots_annotated/`、`requests.theme.json`、`接口清单.md`、`manual.md`。

`requests.theme.json` 是后续接 projects/api-cli schema 分析的干净输入（本迭代不直接生成 api-cli YAML）。

## 铁律

- 平台中性：system/scenario/theme/login-url 全由用户给，skill 不内置任何系统名/host/鉴权。
- 语义步骤必须**先读真实文件**再判断；判不准的接口标「待确认」，不擅自丢弃。
```

- [ ] **Step 5: 建 `evals/evals.json`（手册/过滤结构断言）**

```json
{
  "version": "0.1.0",
  "evals": [
    {
      "id": "theme-filter-keeps-relevant-drops-unrelated",
      "prompt": "theme=资产导入流程。requests.json 含：POST /api/assets/import、GET /api/import/tasks、GET /api/user/menu、GET /api/notifications。按 references/theme-filter.md 产出 requests.theme.json 与接口清单.md。",
      "expect": {
        "theme_json_keeps": ["POST /api/assets/import", "GET /api/import/tasks"],
        "theme_json_drops": ["GET /api/user/menu", "GET /api/notifications"],
        "清单_md_has_table": true
      }
    },
    {
      "id": "manual-chaptered-and-uniform",
      "prompt": "theme=工单查询。structure.json 有 2 段（搜索页 / 详情页），report.md 有 4 步含截图。按 references/manual-format.md 产出 manual.md。",
      "expect": {
        "has_h1_title": "# 工单系统 · 工单查询 操作手册",
        "chapter_headings_are_semantic_not_mechanical": true,
        "step_headlines_are_intent_phrases": true,
        "references_theme_endpoints_only": true,
        "embeds_screenshots": true
      }
    },
    {
      "id": "manual-drops-noise-clicks",
      "prompt": "trace 含一次点空白（A2 全捕留下）+ 正常 3 步。产出 manual.md。",
      "expect": {
        "noise_click_not_in_manual": true,
        "step_count": 3
      }
    }
  ]
}
```

- [ ] **Step 6: 校验脚本语法 + 平台中性自检**

Run:
```bash
bash -n /workspace/skills/browser-manual/scripts/run.sh && echo "syntax OK"
grep -rinE "easyops|172\.|/next/api|toolId|aksk" /workspace/skills/browser-manual/ || echo "中性自检 clean"
```
Expected: `syntax OK`、`中性自检 clean`（无命中）。

- [ ] **Step 7: Commit**

```bash
cd /workspace
git add skills/browser-manual
git commit -m "$(cat <<'EOF'
feat(skill): 新增 browser-manual 配套 skill

按系统复用登录态录制 + 按主题过滤后台请求（requests.theme.json + 接口清单.md）
+ 生成统一格式操作手册（manual.md）。scripts/run.sh 做确定性步骤 1-3，
Claude 做步骤 4/5 语义。根目录默认 ./.browser-recordories/，--root 可改。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: README 更新

**Files:**
- Modify: `projects/browser-recorder/README.md`

- [ ] **Step 1: README 增 A1/A2/A3 + skill 用法**

在 `projects/browser-recorder/README.md`：

(a) 「快速开始」后、「子命令用法」前，插入 skill 引导段：

```markdown
---

## 配套 skill：browser-manual（推荐的生产用法）

录制 → 出操作手册 的端到端流水线，封装在 `skills/browser-manual/`：按系统复用登录态、
按主题过滤后台请求、自动生成统一格式操作手册。详见 `skills/browser-manual/SKILL.md`。

```bash
bash skills/browser-manual/scripts/run.sh \
  --system <系统> --url <起始页> --scenario <场景> --theme "<主题>"
# 脚本跑完步骤 1-3（登录态保障 + record + export），再由 skill 内 Claude 做主题过滤 + 手册分章。
```
```

(b) 「录制细节默认」段，把 `--capture-all-clicks` 条目改为反映新默认：

```markdown
- **默认捕获所有点击**：点交互元素 → 记「最小可点击元素」（向上找首个自身可交互+真实盒子节点，bbox 最准）；
  点纯空白/容器 → 兜底记「最深的、有真实盒子的节点」，让无效点击留痕供后期清理。
  `--interactive-only` 关闭空白兜底（恢复「点空白丢弃」）。旧 `--capture-all-clicks` 已废弃（新默认即全捕），保留为 no-op。
```

(c) 「导出」段表格加 `--format` 行；并说明默认只产 md：

```markdown
| `--format` | `md`（默认，只产 report.md）/ `html` / `both` |
```

(d) 「产物结构」段，`exports/<name>/` 下补 `structure.json`（确定性分章输入，供 browser-manual skill）。

- [ ] **Step 2: 中性自检 + Commit**

Run: `cd /workspace/projects/browser-recorder && grep -rinE "easyops|172\.|/next/api|toolId|aksk" browser_recorder/ README.md || echo clean`

```bash
cd /workspace
git add projects/browser-recorder/README.md
git commit -m "$(cat <<'EOF'
docs(browser-recorder): README 补 browser-manual skill 用法 + A1/A2/A3 默认变更

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 结论

**Spec 覆盖**：A1（Task 1）/ A2（Task 2）/ A3（Task 3）/ skill 全部能力（Task 4）/ 文档（Task 5）均映射到任务。范围外项（api-cli YAML 生成）明确不做。

**占位符**：无 TBD/TODO；每步含真实代码或真实命令。

**类型一致**：`run_export(... fmt="md")`、`run_record(... interactive_only=False)`、`build_segments(actions, groups) -> dict`、`requests.theme.json` 组结构在各 Task 间一致。
