#!/usr/bin/env python3
"""
platforms lint —— 校验 platforms/<deployment>/ 符合 asset-schema + 引用闭合。

通用、零系统耦合（不认识任何具体系统，只按 asset-schema.md 的结构约定校验）。
供 onboarding 步 7 自检 / 任意时刻核对 platforms 资料健康度。

用法:
  scripts/lint-platforms.py [deployment]      # 默认 demo
  scripts/lint-platforms.py demo
  scripts/lint-platforms.py demo --api-cli /path/to/api-cli   # 额外用 api-cli 解析校验 spec

退出码: 0=无 ERR（可有 WARN）；1=有 ERR。
"""
import sys, os, argparse, glob, re

def repo_root():
    # 相对本脚本定位仓库根（脚本在 skills/api-orchestrator/scripts/）
    here = os.path.dirname(os.path.abspath(__file__))
    # 往上找 .git
    d = here
    for _ in range(6):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return here  # fallback

def load_yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f), None
    except ImportError:
        return None, "PyYAML 未装（pip install pyyaml）"
    except Exception as e:
        return None, f"YAML 解析失败: {e}"

def resolve_base(deployment, override=None):
    """解析 platforms base 目录（与 run.sh 部署根解析同语义）。

    优先级（高→低）：
      1. override（--base 显式，自测用）
      2. $API_CLI_PLATFORMS_DIR/<deployment>
      3. $API_CLI_DEPLOYMENT_ROOT/platforms/<deployment>（目录存在才用）
      4. fallback <skill>/platforms/<deployment>
    """
    if override:
        return os.path.join(override, deployment)
    env_platforms = os.getenv("API_CLI_PLATFORMS_DIR")
    if env_platforms:
        return os.path.join(env_platforms, deployment)
    root = os.getenv("API_CLI_DEPLOYMENT_ROOT", os.path.join(os.getcwd(), ".api-orchestrator"))
    candidate = os.path.join(root, "platforms", deployment)
    if os.path.isdir(candidate):
        return candidate
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # skills/api-orchestrator/
    return os.path.join(skill_dir, "platforms", deployment)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deployment", nargs="?", default="demo")
    ap.add_argument("--api-cli", help="api-cli 二进制路径，提供则额外校验 spec 可被 api-cli 解析")
    ap.add_argument("--base", help="platforms 根目录覆盖（自测用；默认按解析链：API_CLI_PLATFORMS_DIR → 部署根 → skill 内置）")
    args = ap.parse_args()

    base = resolve_base(args.deployment, override=args.base)
    errs, warns, oks = [], [], []
    def ok(msg): oks.append(msg)
    def warn(msg): warns.append(msg)
    def err(msg): errs.append(msg)

    if not os.path.isdir(base):
        print(f"ERR: 部署目录不存在: platforms/{args.deployment}/")
        sys.exit(1)

    # ---- 1. 必需文件 ----
    for need in ["README.md", "systems.yaml"]:
        p = os.path.join(base, need)
        (ok if os.path.isfile(p) else err)(f"必需文件 {need} {'存在' if os.path.isfile(p) else '缺失'}")

    # ---- 2. systems.yaml 结构 ----
    sys_path = os.path.join(base, "systems.yaml")
    systems = {}
    if os.path.isfile(sys_path):
        d, e = load_yaml(sys_path)
        if e:
            err(f"systems.yaml: {e}")
        elif not isinstance(d, dict):
            err("systems.yaml: 顶层不是 mapping")
        else:
            if "deployment" not in d:
                warn("systems.yaml: 缺 deployment 字段")
            systems = d.get("systems") or {}
            if not systems:
                err("systems.yaml: 无 systems")
            for sname, s in systems.items():
                if not isinstance(s, dict):
                    err(f"systems.{sname}: 不是 mapping"); continue
                spec = s.get("spec")
                if not spec:
                    err(f"systems.{sname}: 缺 spec（api-cli 清单路径）"); continue
                spec_path = os.path.join(base, spec)
                if not os.path.isfile(spec_path):
                    err(f"systems.{sname}.spec → {spec} 文件不存在")
                else:
                    ok(f"systems.{sname}.spec → {spec} 存在")

    # ---- 3. 收集所有 spec 的 resource.verb（供 flows/entities 引用闭合）----
    spec_verbs = set()   # "resource.verb"
    spec_files = [os.path.join(base, s["spec"]) for s in systems.values()
                  if isinstance(s, dict) and s.get("spec") and os.path.isfile(os.path.join(base, s["spec"]))]
    for sp in spec_files:
        d, e = load_yaml(sp)
        if e or not isinstance(d, dict):
            continue
        for rname, r in (d.get("resources") or {}).items():
            if not isinstance(r, dict):
                continue
            for verb in (r.get("operations") or {}).keys():
                spec_verbs.add(f"{rname}.{verb}")

    # 可选：api-cli 解析校验
    if args.api_cli and spec_files:
        for sp in spec_files:
            import subprocess
            r = subprocess.run([args.api_cli, "--spec", sp, "--help"],
                               capture_output=True, text=True, timeout=20)
            (ok if r.returncode == 0 else err)(f"api-cli 解析 {os.path.basename(sp)}: {'OK' if r.returncode==0 else '失败 '+r.stderr[:80]}")

    # ---- 4. objects.yaml 结构 + ref 闭合 ----
    obj_path = os.path.join(base, "objects.yaml")
    if os.path.isfile(obj_path):
        d, e = load_yaml(obj_path)
        if e:
            err(f"objects.yaml: {e}")
        elif isinstance(d, dict):
            objs = d.get("objects") or {}
            if not objs:
                warn("objects.yaml: 无 objects")
            for oname, o in objs.items():
                if not isinstance(o, dict):
                    continue
                # api 引用 → spec 有该 resource
                api = o.get("api")
                if api and spec_verbs and not any(v.startswith(api + ".") for v in spec_verbs):
                    warn(f"objects.{oname}.api → {api} 不在任何 spec 的 resource 里")
                # 【证据门禁】有 api 的 object 必须有非空 source（防 onboarding 跳过源码确认）
                # 规则来源：onboarding.md 步 3「探源码补全」+ 证据纪律「字段值域必须有源码/样例证据」。
                # 没有 source = 字段值域（枚举/正则/副作用）未被查证，编排时 LLM 不知道能填什么 → ERR。
                if api:
                    src = o.get("source")
                    if not src or (isinstance(src, str) and not src.strip()):
                        err(f"objects.{oname}: 有 api={api} 但缺 source —— onboarding 步 3 未做（字段值域无源码/样例证据），补 source: <源码 file:line 或枚举接口或契约>")
                # fields.ref → objects 内有该 object
                for fname, f in (o.get("fields") or {}).items():
                    if isinstance(f, dict):
                        ref = f.get("ref")
                        iv = f.get("items")
                        if isinstance(iv, str) and iv in objs:
                            ref = ref or iv  # items 仅当指向 object 名才算 ref；基础类型(string/int)不算
                        if ref and ref not in objs:
                            err(f"objects.{oname}.fields.{fname}.ref → {ref} 不在 objects 里")
            ok("objects.yaml 引用闭合 + source 证据门禁校验完成")
    else:
        warn("无 objects.yaml（对象结构/副作用知识缺失，onboarding 不完整）")

    # ---- 5. entities.yaml 结构 ----
    ent_path = os.path.join(base, "entities.yaml")
    if os.path.isfile(ent_path):
        d, e = load_yaml(ent_path)
        if e:
            err(f"entities.yaml: {e}")
        elif isinstance(d, dict):
            for t in (d.get("transitions") or []):
                if not isinstance(t, dict):
                    continue
                frm = t.get("from")
                if frm and spec_verbs and frm not in spec_verbs:
                    warn(f"entities.transitions.from → {frm} 不在 spec verbs 里")
            ok("entities.yaml 校验完成")
    # entities 可选，不 warn

    # ---- 6. flows/*.yaml 结构 + op 引用闭合 ----
    flow_files = sorted(glob.glob(os.path.join(base, "flows", "*.yaml")))
    for fp in flow_files:
        d, e = load_yaml(fp)
        if e:
            err(f"flows/{os.path.basename(fp)}: {e}"); continue
        if not isinstance(d, dict):
            err(f"flows/{os.path.basename(fp)}: 非 mapping"); continue
        if not d.get("name"):
            err(f"flows/{os.path.basename(fp)}: 缺 name")
        for step in (d.get("steps") or []):
            if not isinstance(step, dict):
                continue
            op = step.get("op")
            if op and spec_verbs and op not in spec_verbs:
                err(f"flows/{os.path.basename(fp)} step {step.get('n')}: op {op} 不在 spec verbs 里")
        ok(f"flows/{os.path.basename(fp)} 校验完成")
    if not flow_files and os.path.isdir(os.path.join(base, "flows")):
        warn("flows/ 目录空（无流程模板）")

    # ---- 7. README 引用的 .yaml 文件存在（引用闭合）----
    rm = os.path.join(base, "README.md")
    if os.path.isfile(rm):
        txt = open(rm, encoding="utf-8").read()
        seen = set()
        for m in re.findall(r'`([A-Za-z0-9_./-]+\.yaml)`', txt):
            if m in seen or m.startswith("http") or ".." in m:
                continue
            seen.add(m)
            if not os.path.isfile(os.path.join(base, m)):
                warn(f"README 引用 {m} 但文件不存在（若引用外部/其他 deployment 可忽略）")
        ok("README .yaml 引用闭合校验完成")

    # ---- 8. 规则①：platforms 数据禁 ~/.api-cli/ 字面串（干净切换，防回潮）----
    import re as _re
    _STALE = "~/.api-cli/"
    for root, dirs, files in os.walk(base):
        # 跳过 __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if not (fn.endswith(".yaml") or fn.endswith(".yml") or fn.endswith(".md")):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            if _STALE in content:
                rel = os.path.relpath(fp, base)
                err(f"{rel}: 含「{_STALE}」字面串（已废弃旧位置）—— 改「原 home 目录位置已废弃」措辞，密钥/env 统一走部署根")

    # ---- 9. 规则②：systems.yaml 的 env: 段值禁非空 URL/IP（防 LLM 复用默认值）----
    _URL_OR_IP = _re.compile(r"(https?://|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    if os.path.isfile(sys_path):
        d2, e2 = load_yaml(sys_path)
        if d2 and isinstance(d2.get("systems"), dict):
            for sname, s in d2["systems"].items():
                if not isinstance(s, dict):
                    continue
                env = s.get("env")
                if isinstance(env, dict):
                    for k, v in env.items():
                        if isinstance(v, str) and v and _URL_OR_IP.search(v):
                            err(f"systems.{sname}.env.{k}: 值「{v}」含 URL/IP（环境配置只在部署根 env.d，systems.yaml 只留变量契约 key）")

    # ---- 10. 规则④：单一真相源（文件间）——flow 非指针字段禁复述 objects side_effect 规则 ----
    # 设计原则④：同一规则全文只在一个权威文件，其余指针回指。lint 兜底：把 objects.yaml
    # side_effects 里的显著规则子串（≥8 连续汉字/字母数字，去标点）抽出来，扫描 flows/*.yaml
    # 里 side_effects: 行之外的内容，命中即 WARN（提示：删全文换指针「见 objects.yaml#X.side_effects」）。
    # 阈值偏保守只 WARN 不 ERR——步骤值（API 请求体示例/字段名）是操作的一部分，不算复述。
    if os.path.isfile(obj_path):
        od, _ = load_yaml(obj_path)
        rules = []
        if od and isinstance(od.get("objects"), dict):
            for obj in od["objects"].values():
                if not isinstance(obj, dict):
                    continue
                se = obj.get("side_effects")
                if isinstance(se, list):
                    for item in se:
                        if isinstance(item, dict):
                            r = item.get("rule")
                            if isinstance(r, str):
                                rules.append(r)
                if isinstance(se, dict):
                    r = se.get("rule")
                    if isinstance(r, str):
                        rules.append(r)
        # 抽显著子串——两类强信号（避免「所有版本/关系字段」等 4 字术语误报）：
        # ① 报错原文 『...!』/『...』（规则最强特征，平台报错原话）
        # ② 长中文片段 ≥8 字（过滤短操作术语）
        _NOISE = {"不允许删除", "流程定义版本"}
        sig_tokens = set()
        for r in rules:
            # 报错原文：『...』
            for m in _re.findall(r"『[^』]{4,}』", r):
                sig_tokens.add(m)
            # 长中文片段 ≥8
            for m in _re.findall(r"[一-龥]{8,}", r):
                if m not in _NOISE:
                    sig_tokens.add(m)
        # 扫描 flows
        flows_dir = os.path.join(base, "flows")
        if os.path.isdir(flows_dir) and sig_tokens:
            for fn in sorted(os.listdir(flows_dir)):
                if not (fn.endswith(".yaml") or fn.endswith(".yml")):
                    continue
                fp = os.path.join(flows_dir, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        lines = f.readlines()
                except Exception:
                    continue
                for li, line in enumerate(lines, 1):
                    # 跳过 side_effects: 行（它本就该是指针）和指针引用行
                    s = line.lstrip()
                    if s.startswith("side_effects:") or "objects.yaml#" in line or "见 " in line or "详见 " in line:
                        continue
                    for tok in sig_tokens:
                        if tok in line:
                            warn(f"flows/{fn}:{li} 复述 objects.yaml side_effect 规则「{tok}…」—— 设计原则④：删全文换指针（见 objects.yaml#<object>.side_effects）。步骤值/字段名不算复述，可忽略。")
                            break  # 一行只报一次

    # ---- 报告 ----
    print(f"lint platforms/{args.deployment}/")
    for m in oks:
        print(f"  [OK]   {m}")
    for m in warns:
        print(f"  [WARN] {m}")
    for m in errs:
        print(f"  [ERR]  {m}")
    print(f"\n合计: {len(oks)} OK, {len(warns)} WARN, {len(errs)} ERR")
    sys.exit(1 if errs else 0)

if __name__ == "__main__":
    main()
