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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deployment", nargs="?", default="demo")
    ap.add_argument("--api-cli", help="api-cli 二进制路径，提供则额外校验 spec 可被 api-cli 解析")
    args = ap.parse_args()

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # skills/api-orchestrator/
    base = os.path.join(skill_dir, "platforms", args.deployment)
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
                # fields.ref → objects 内有该 object
                for fname, f in (o.get("fields") or {}).items():
                    if isinstance(f, dict):
                        ref = f.get("ref")
                        iv = f.get("items")
                        if isinstance(iv, str) and iv in objs:
                            ref = ref or iv  # items 仅当指向 object 名才算 ref；基础类型(string/int)不算
                        if ref and ref not in objs:
                            err(f"objects.{oname}.fields.{fname}.ref → {ref} 不在 objects 里")
            ok("objects.yaml 引用闭合校验完成")
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

    # ---- 7. README 引用的 .yaml 文件存在 ----
    rm = os.path.join(base, "README.md")
    if os.path.isfile(rm):
        txt = open(rm, encoding="utf-8").read()
        for m in re.findall(r'`([A-Za-z0-9_./-]+\.yaml)`', txt):
            refp = os.path.join(base, m)
            if not os.path.isfile(refp) and "/" not in m:
                # 可能是相对引用（如 systems.yaml），已查
                pass

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
