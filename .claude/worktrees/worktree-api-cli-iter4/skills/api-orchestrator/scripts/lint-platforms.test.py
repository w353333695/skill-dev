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

        # ============ 报告 ============
        if fails:
            print("❌ lint 自测失败:")
            for f in fails:
                print("  -", f.replace("\n", " | "))
            sys.exit(1)
        print("✓ lint 自测通过：good 放行（exit 0 无 ERR）/ bad 抓错（exit 1，含 README缺失 + ref未闭合 + flow op未注册）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
