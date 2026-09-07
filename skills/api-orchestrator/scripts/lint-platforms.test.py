#!/usr/bin/env python3
"""
lint-platforms.py 自测 —— 造故意的 good/bad fixtures，验证 lint 放行对的、抓出错的。
跑: python3 scripts/lint-platforms.test.py
"""
import os, sys, subprocess, tempfile, textwrap, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, "lint-platforms.py")

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(textwrap.dedent(content).lstrip())

def run(base, dep):
    r = subprocess.run([sys.executable, LINT, dep, "--base", base],
                       capture_output=True, text=True)
    return r.returncode, r.stdout

def main():
    tmp = tempfile.mkdtemp(prefix="lint-test-")
    base = os.path.join(tmp, "platforms")
    fails = []
    try:
        # ============ good fixtures（正确最小，应 exit 0 无 ERR）============
        g = os.path.join(base, "test-good")
        write(os.path.join(g, "README.md"), """
            # good
            资料见 systems.yaml 与 sys.yaml。
        """)
        write(os.path.join(g, "systems.yaml"), """
            deployment: test-good
            systems:
              sys:
                description: ok
                spec: sys.yaml
        """)
        write(os.path.join(g, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(g, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        rc, out = run(base, "test-good")
        if rc != 0:
            fails.append(f"[good] 期望 exit 0，实际 {rc}\n{out}")
        elif "[ERR]" in out:
            fails.append(f"[good] 期望无 ERR，实际有\n{out}")

        # ============ bad fixtures（多处故意错，应 exit 1 含对应 ERR）============
        b = os.path.join(base, "test-bad")
        # 故意不写 README → 必需文件 ERR
        write(os.path.join(b, "systems.yaml"), """
            deployment: test-bad
            systems:
              sys:
                spec: sys.yaml
        """)
        write(os.path.join(b, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(b, "objects.yaml"), """
            objects:
              o:
                api: nope               # 不在 spec resource → WARN
                fields:
                  f: { ref: ghost }      # ghost 不在 objects → ERR
        """)
        write(os.path.join(b, "flows", "bad.yaml"), """
            name: bad
            steps:
              - n: 1
                op: widget.delete        # spec 只有 widget.read → ERR
        """)
        rc, out = run(base, "test-bad")
        if rc == 0:
            fails.append(f"[bad] 期望 exit 1，实际 {rc}\n{out}")
        else:
            for kw in ["README", "ref → ghost", "widget.delete"]:
                if kw not in out:
                    fails.append(f"[bad] 期望输出含「{kw}」\n{out}")

        # ============ 规则①②：禁 ~/.api-cli 字面串 + env 段值禁非空 URL/IP ============
        s1 = os.path.join(base, "test-stale-path")
        write(os.path.join(s1, "README.md"), "# x\n")
        write(os.path.join(s1, "systems.yaml"), """
            deployment: test-stale-path
            systems:
              sys:
                description: ok
                spec: sys.yaml
                auth: easyops-cookie     # 原 ~/.api-cli/auth.d/ 位置（应禁字面串）
        """)
        write(os.path.join(s1, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(s1, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        rc, out = run(base, "test-stale-path")
        if rc == 0:
            fails.append(f"[stale-path] 期望 exit 1（含 ~/.api-cli 字面串），实际 {rc}\n{out}")
        elif "~/.api-cli" not in out:
            fails.append(f"[stale-path] 期望输出含「~/.api-cli」ERR\n{out}")

        s2 = os.path.join(base, "test-env-value")
        write(os.path.join(s2, "README.md"), "# x\n")
        write(os.path.join(s2, "systems.yaml"), """
            deployment: test-env-value
            systems:
              sys:
                description: ok
                spec: sys.yaml
                env:
                  EASYOPS_X_BACKEND_URL: "http://172.30.0.232:8079"   # 非空 URL（应禁）
        """)
        write(os.path.join(s2, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(s2, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        rc, out = run(base, "test-env-value")
        if rc == 0:
            fails.append(f"[env-value] 期望 exit 1（env 段含非空 URL），实际 {rc}\n{out}")
        elif "EASYOPS_X_BACKEND_URL" not in out:
            fails.append(f"[env-value] 期望输出含「EASYOPS_X_BACKEND_URL」ERR\n{out}")

        # ============ hub 校验 case（INDEX 一致性）============
        # 最小 good：hub + INDEX 齐全自洽 → exit 0
        hg = os.path.join(base, "test-hub-good")
        write(os.path.join(hg, "README.md"), "# x\n")
        write(os.path.join(hg, "systems.yaml"), """
            deployment: test-hub-good
            systems:
              sys:
                description: ok
                spec: sys.yaml
        """)
        write(os.path.join(hg, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                description: w
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(hg, "objects.yaml"), """
            objects:
              widget:
                api: widget
                source: sys.yaml:1
                fields:
                  id: { type: string }
        """)
        write(os.path.join(hg, "hub", "kits", "acme-kit_v1.0.1.zip"), "fake")
        write(os.path.join(hg, "hub", "INDEX.yaml"), """
            items:
              - id: acme-kit
                name: ACME套件
                category: kits
                files: [acme-kit_v1.0.1.zip]
                version: 1.0.1
                history:
                  - {ver: 1.0.1, date: 2026-09-07, change: 初版入库}
                scenario: ACME 设备监控接入
                notes: ""
                added: 2026-09-07
        """)
        rc, out = run(base, "test-hub-good")
        if rc != 0 or "[ERR]" in out:
            fails.append(f"[hub-good] 期望 exit 0 无 ERR，实际 rc={rc}\n{out}")

        # bad-1：hub 存在但无 INDEX → WARN（不 ERR）
        hb1 = os.path.join(base, "test-hub-noindex")
        write(os.path.join(hb1, "README.md"), "# x\n")
        write(os.path.join(hb1, "systems.yaml"), "deployment: test-hub-noindex\nsystems:\n  sys:\n    spec: sys.yaml\n")
        write(os.path.join(hb1, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(hb1, "hub", "kits", "a.zip"), "fake")
        rc, out = run(base, "test-hub-noindex")
        if rc != 0:
            fails.append(f"[hub-noindex] 缺 INDEX 应只 WARN 不 ERR，实际 rc={rc}\n{out}")
        elif "INDEX.yaml" not in out:
            fails.append(f"[hub-noindex] 期望 WARN 提及 INDEX.yaml\n{out}")

        # bad-2：七宗错集齐（category 悬空/文件不存在/未登记/id 重复/多版本/history 不一致/based_on 悬空）→ exit 1 全抓
        hb2 = os.path.join(base, "test-hub-bad")
        write(os.path.join(hb2, "README.md"), "# x\n")
        write(os.path.join(hb2, "systems.yaml"), "deployment: test-hub-bad\nsystems:\n  sys:\n    spec: sys.yaml\n")
        write(os.path.join(hb2, "sys.yaml"), """
            spec: api-cli/v1
            service: { name: sys, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
            resources:
              widget:
                operations:
                  read: { method: GET, path: "/{id}" }
        """)
        write(os.path.join(hb2, "hub", "kits", "x-kit_v1.0.1.zip"), "fake")   # 未登记
        write(os.path.join(hb2, "hub", "kits", "y-kit_v1.0.1.zip"), "fake")   # 多版本成员1
        write(os.path.join(hb2, "hub", "kits", "y-kit_v1.0.2.zip"), "fake")   # 多版本成员2
        write(os.path.join(hb2, "hub", "INDEX.yaml"), """
            items:
              - id: x-kit
                name: X套件
                category: ghost-dir            # 悬空类目
                files: [x-kit_v1.0.1.zip, missing.zip]   # missing 不存在
                version: 1.0.1
                history:
                  - {ver: 1.0.0, date: 2026-09-07, change: 初版}   # 末条 1.0.0 ≠ version 1.0.1
                scenario: X 设备
                added: 2026-09-07
              - id: x-kit                      # 重复 id
                name: X套件2
                category: kits
                files: [y-kit_v1.0.1.zip, y-kit_v1.0.2.zip]   # 两版本并存
                version: 1.0.2
                history:
                  - {ver: 1.0.2, date: 2026-09-07, change: v2}
                based_on: ghost-base           # 悬空谱系
                scenario: Y 设备
                added: 2026-09-07
        """)
        rc, out = run(base, "test-hub-bad")
        if rc == 0:
            fails.append(f"[hub-bad] 期望 exit 1，实际 {rc}\n{out}")
        else:
            for kw in ["ghost-dir", "missing.zip", "未登记", "id 重复", "多版本并存", "不一致", "ghost-base"]:
                if kw not in out:
                    fails.append(f"[hub-bad] 期望输出含「{kw}」\n{out}")

        # ============ resolve_base 解析链 case（env 变量 / 部署根派生）============
        import importlib.util
        spec = importlib.util.spec_from_file_location("lint_mod", LINT)
        lint_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint_mod)

        # Case A: API_CLI_PLATFORMS_DIR 设了 → base = <dir>/<dep>
        os.environ["API_CLI_PLATFORMS_DIR"] = os.path.join(tmp, "ext-platforms")
        os.environ.pop("API_CLI_DEPLOYMENT_ROOT", None)
        write(os.path.join(tmp, "ext-platforms", "envdep", "systems.yaml"), "deployment: envdep\n")
        write(os.path.join(tmp, "ext-platforms", "envdep", "README.md"), "# x\n")
        got = lint_mod.resolve_base("envdep")
        if got != os.path.join(tmp, "ext-platforms", "envdep"):
            fails.append(f"[resolve A] PLATFORMS_DIR: got {got}")

        # Case B: 无 PLATFORMS_DIR，有 DEPLOYMENT_ROOT 且目录存在 → 派生
        del os.environ["API_CLI_PLATFORMS_DIR"]
        os.environ["API_CLI_DEPLOYMENT_ROOT"] = os.path.join(tmp, "myroot")
        write(os.path.join(tmp, "myroot", "platforms", "rdep", "systems.yaml"), "deployment: rdep\n")
        got = lint_mod.resolve_base("rdep")
        if got != os.path.join(tmp, "myroot", "platforms", "rdep"):
            fails.append(f"[resolve B] ROOT派生: got {got}")

        # Case C: 都没设，目录不存在 → fallback skill 内置（含 <skill>/platforms/<dep>）
        del os.environ["API_CLI_DEPLOYMENT_ROOT"]
        got = lint_mod.resolve_base("nonexist_dep_xyz")
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(LINT)))
        expected = os.path.join(skill_dir, "platforms", "nonexist_dep_xyz")
        if got != expected:
            fails.append(f"[resolve C] fallback: got {got}, expected {expected}")

        # ============ 报告 ============
        if fails:
            print("❌ lint 自测失败:")
            for f in fails:
                print("  -", f.replace("\n", " | "))
            sys.exit(1)
        print("✓ lint 自测通过：good 放行（exit 0 无 ERR）/ bad 抓错（exit 1，含 README缺失 + ref未闭合 + flow op未注册）+ hub 校验（good 放行 / noindex WARN / bad 七宗错全抓）")
    finally:
        # 清理环境变量（异常安全——resolve_base 用例设过则必清，避免污染父进程）
        os.environ.pop("API_CLI_PLATFORMS_DIR", None)
        os.environ.pop("API_CLI_DEPLOYMENT_ROOT", None)
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
