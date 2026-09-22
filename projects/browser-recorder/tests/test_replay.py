"""replay 转换器单测：候选链推导（构造 action 事件 → 断言 loc 顺序）+ CLI + 回路。"""
import json
import pathlib
import subprocess
import sys

from browser_recorder.replay import _stable_classes, is_stable_id, session_to_flow

_PROJ_ROOT2 = pathlib.Path(__file__).parent.parent


def _action(seq, t, type_, desc_extra=None, **kw):
    base = {"t_mono": t, "kind": "action", "seq": seq, "type": type_,
            "element": {"rect": {}, "descriptor": {}}, "value": None,
            "target_id": "t0"}
    base.update(kw)
    if desc_extra:
        base["element"]["descriptor"].update(desc_extra)
    return base


def test_is_stable_id():
    assert is_stable_id("name") is True          # 语义 id 稳定
    assert is_stable_id("rc_select_20") is False  # 纯数字后缀自动生成
    assert is_stable_id("dynamicForm_0_name") is False


def test_stable_classes_filters_hash_classes():
    """锁定：框架前缀（sc- 词边界）与哈希形态剔除，语义 class 保留。

    desc-header/disc-list/misc-info 含 "sc-" 子串但非 sc- 开头——
    子串匹配会误杀，必须按词边界前缀判。button2 纯字母数字 ≥6 含数字
    → 按含数字即可能哈希，剔除。
    """
    got = _stable_classes(["sc-item", "desc-header", "disc-list", "misc-info",
                           "btn-primary", "submit", "css-1q2w3e", "button2"])
    assert got == ["desc-header", "disc-list", "misc-info",
                   "btn-primary", "submit"]


def test_candidate_order_by_stability():
    lines = [
        {"t_mono": 1, "kind": "session_start", "seq": 1},
        _action(2, 100, "click", desc_extra={
            "id": "btn-ok", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "button", "text": "确认", "classes": ["btn", "btn-primary-hash1"],
            "dom_path": "html>body>button#btn-ok"}),
        _action(3, 200, "input", desc_extra={
            "id": None, "name": "username", "aria_label": "用户名", "data_attrs": {},
            "tag": "input", "text": "", "classes": [],
            "dom_path": "html>body>input"}, value="alice", html_type="text"),
        _action(4, 300, "input", desc_extra={
            "id": None, "name": None, "aria_label": None,
            "data_attrs": {"data-testid": "pw"}, "tag": "input", "text": "",
            "classes": [], "dom_path": "html>body>input"},
            value="***", html_type="password"),
    ]
    flow, removed = session_to_flow(lines)
    steps = flow["steps"]
    # 步1：id 稳定 → css:#btn-ok 首发；文本候选次之
    assert steps[0]["loc"][0] == "css:#btn-ok"
    assert "text:确认" in steps[0]["loc"]
    # 步2：无 id 有 name → css:[name=username]
    assert steps[1]["loc"][0] == "css:[name=username]"
    assert steps[1]["value"] == "alice"
    # 步3：password → needs_credential + env 占位
    assert steps[2].get("needs_credential") is True
    assert steps[2]["value"] == "${env.BR_PW_3}"
    assert removed == []


def test_dom_path_only_step_removed_by_default():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": None, "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "", "classes": [], "dom_path": "html>body>div"}),
    ]
    flow, removed = session_to_flow(lines)
    assert len(removed) == 1 and removed[0]["reason"] == "dom-path-only"
    assert len(flow["steps"]) == 0


def test_unstable_id_falls_to_next_candidate():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": "rc_select_20", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "选择OS", "classes": [], "dom_path": "a>b"}),
    ]
    flow, removed = session_to_flow(lines)
    assert flow["steps"][0]["loc"][0] != "css:#rc_select_20"
    assert "text:选择OS" in flow["steps"][0]["loc"]


def test_open_step_synthesized_from_pre_action_nav():
    """drive 的 open 步只落 nav 事件——转换须合成 open，否则重放缺起点导航。"""
    lines = [
        {"t_mono": 1, "kind": "session_start", "seq": 1},
        {"t_mono": 50, "kind": "nav", "seq": 2, "url": "http://x/blank",
         "target_id": "t0"},
        {"t_mono": 80, "kind": "nav", "seq": 3, "url": "http://x/form.html",
         "target_id": "t0"},
        _action(4, 100, "input", desc_extra={
            "id": None, "name": "title", "aria_label": None, "data_attrs": {},
            "tag": "input", "text": "", "classes": [], "dom_path": "a>b"},
            value="hi"),
    ]
    flow, removed = session_to_flow(lines)
    assert removed == []
    assert flow["steps"][0]["act"] == "open"
    assert flow["steps"][0]["value"] == "http://x/form.html"   # 取最后一次 nav
    assert flow["steps"][0]["tabs"] == "main"
    assert flow["steps"][1]["act"] == "input"


def test_keep_fragile_retains_dom_path_step():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": None, "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "", "classes": [], "dom_path": "html>body>div"}),
    ]
    flow, removed = session_to_flow(lines, keep_fragile=True)
    assert len(flow["steps"]) == 1
    assert flow["steps"][0]["loc"] == ["dom:html>body>div"]
    assert flow["steps"][0]["fragile"] is True
    # 报告仍列出
    assert len(removed) == 1 and removed[0]["reason"] == "dom-path-only"


def test_masked_password_value_gets_env_placeholder():
    """录制侧已脱敏（值 ***，无 html_type）同样走 env 占位。"""
    lines = [
        _action(1, 100, "input", desc_extra={
            "id": None, "name": "pw", "aria_label": None, "data_attrs": {},
            "tag": "input", "text": "", "classes": [], "dom_path": "a>b"},
            value="***"),
    ]
    flow, removed = session_to_flow(lines)
    assert flow["steps"][0]["needs_credential"] is True
    assert flow["steps"][0]["value"].startswith("${env.BR_PW_")


def test_wait_nav_derived_from_nav_between_actions():
    """本动作与下一动作之间有同 tab 的 nav → 本步 wait:nav。"""
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": "go", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "a", "text": "跳转", "classes": [], "dom_path": "a>b"}),
        {"t_mono": 150, "kind": "nav", "seq": 2, "url": "http://x/page2",
         "target_id": "t0"},
        _action(3, 200, "click", desc_extra={
            "id": "next", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "button", "text": "下一步", "classes": [], "dom_path": "a>b"}),
    ]
    flow, removed = session_to_flow(lines)
    assert flow["steps"][0].get("wait") == "nav"
    assert "wait" not in flow["steps"][1]


def test_new_tab_action_gets_tabs_and_prev_step_on_new_tab():
    lines = [
        _action(1, 100, "click", desc_extra={
            "id": "open-tab", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "a", "text": "开新页", "classes": [], "dom_path": "a>b"}),
        _action(2, 200, "click", desc_extra={
            "id": "in-new-tab", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "button", "text": "新页按钮", "classes": [], "dom_path": "a>b"},
            target_id="t1"),
    ]
    flow, removed = session_to_flow(lines)
    assert flow["steps"][0]["on_new_tab"] == "switch"
    assert flow["steps"][1]["tabs"] == "t1"


# ---- CLI（无浏览器，subprocess 走真入口）----


def test_cli_replay_writes_flow_and_report(tmp_path):
    sd = tmp_path / "sess"
    sd.mkdir()
    (sd / "session.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"t_mono": 1, "kind": "session_start", "seq": 1},
        _action(2, 100, "click", desc_extra={
            "id": "btn-ok", "name": None, "aria_label": None, "data_attrs": {},
            "tag": "button", "text": "确认", "classes": [], "dom_path": "a>b"}),
        {"t_mono": 300, "kind": "session_end", "seq": 3},
    ]) + "\n", encoding="utf-8")
    out = tmp_path / "f.json"
    r = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "replay", str(sd),
         "--out", str(out), "--name", "cli"],
        capture_output=True, text=True, timeout=60, cwd=_PROJ_ROOT2)
    assert r.returncode == 0, r.stderr
    flow = json.loads(out.read_text(encoding="utf-8"))
    assert flow["name"] == "cli"
    assert flow["steps"][0]["loc"][0] == "css:#btn-ok"
    assert flow["meta"]["generated_by"] == "replay"
    rep = (tmp_path / "f.report.md").read_text(encoding="utf-8")
    assert "剔除步数：0" in rep and "replay 报告 · cli" in rep


def test_cli_replay_keep_fragile(tmp_path):
    sd = tmp_path / "sess"
    sd.mkdir()
    (sd / "session.jsonl").write_text(json.dumps(_action(
        1, 100, "click", desc_extra={
            "id": None, "name": None, "aria_label": None, "data_attrs": {},
            "tag": "div", "text": "", "classes": [],
            "dom_path": "html>body>div"})) + "\n", encoding="utf-8")
    out = tmp_path / "k.json"
    r = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "replay", str(sd),
         "--out", str(out), "--keep-fragile"],
        capture_output=True, text=True, timeout=60, cwd=_PROJ_ROOT2)
    assert r.returncode == 0, r.stderr
    flow = json.loads(out.read_text(encoding="utf-8"))
    assert flow["steps"][0]["fragile"] is True
    assert flow["steps"][0]["loc"] == ["dom:html>body>div"]
    rep = (tmp_path / "k.report.md").read_text(encoding="utf-8")
    assert "dom-path-only" in rep and "已保留" in rep


# ---- 回路：drive 跑即录 → replay → dry-run 全命中（真 chrome）----


def test_replay_then_dry_run_on_fixture(local_site, chrome_path, tmp_path):
    """回路：drive 跑 smoke flow 生成 session（跑即录）→ replay 这个
    session → dry-run 重放。断言 removed 为空 + 产物过 load_flow +
    dry-run exit 0。

    session 里 drive_step 事件 replay 只读 kind=="action"；drive 产生的
    action 带 source:"drive"，与人工录制同等转换（不区分 source）。
    """
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps({"name": "s", "steps": [
        {"n": 1, "desc": "打开", "act": "open", "value": f"{local_site}/form.html"},
        {"n": 2, "desc": "标题", "act": "input", "loc": ["css:[name=title]"],
         "value": "回路测试"},
        {"n": 3, "desc": "提交", "act": "click",
         "loc": ["css:[data-testid=submit-btn]"]},
    ]}, ensure_ascii=False))
    out_root = tmp_path / "sessions"
    r = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "drive", str(smoke),
         "--out", str(out_root), "--headless", "--no-sandbox"],
        capture_output=True, text=True, timeout=180, cwd=_PROJ_ROOT2)
    assert r.returncode == 0, r.stderr
    sd = sorted(out_root.glob("*/session.jsonl"))[-1]
    lines = [json.loads(l) for l in sd.read_text().splitlines() if l.strip()]
    flow, removed = session_to_flow(lines, name="roundtrip")
    assert removed == [], f"被剔除: {removed}"
    # open 步已合成（drive 的 open 只落 nav 事件，不落 action）
    assert flow["steps"][0]["act"] == "open"
    assert flow["steps"][0]["value"] == f"{local_site}/form.html"
    # 产物能过 load_flow（schema 合规是本转换器的硬约束）
    from browser_recorder.flow import load_flow
    fp = tmp_path / "roundtrip.json"
    fp.write_text(json.dumps(flow, ensure_ascii=False), encoding="utf-8")
    assert load_flow(fp)["name"] == "roundtrip"
    # 2) dry-run 重放
    r2 = subprocess.run(
        [sys.executable, "-m", "browser_recorder.cli", "drive", str(fp),
         "--out", str(tmp_path / "dry"), "--headless", "--dry-run", "--no-sandbox"],
        capture_output=True, text=True, timeout=180, cwd=_PROJ_ROOT2)
    assert r2.returncode == 0, r2.stderr
