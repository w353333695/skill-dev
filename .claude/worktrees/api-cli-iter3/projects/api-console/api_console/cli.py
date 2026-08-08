# api_console/cli.py
"""api-console 统一 CLI：click group 转发到各能力模块的 main()。

设计：
- 不重写各模块已有的 argparse，只透传剩余参数给对应模块的 ``main(list(args))``；
- 保留原 ``run.sh`` 的行为契约：产物根 = 调用方 cwd（``API_CONSOLE_WORKDIR``），
  使 ``platforms/``、``tmp/orchestrate/`` 落点与迁移前一致；
- 单一 entry point ``api-console = api_console.cli:main``（见 pyproject.toml）。
"""
from __future__ import annotations
import os
import click


@click.group()
def main() -> None:
    """api-console：API 资产建设 + 调用编排 CLI（平台中性，adapter 可拔插）。

    子命令透传剩余参数给对应能力模块。产物根 = 调用方 cwd。
    """
    # 保留 run.sh 行为：钉死调用方 cwd 为产物根（platforms/、tmp/orchestrate/ 落此）
    os.environ.setdefault("API_CONSOLE_WORKDIR", os.getcwd())


def _forward(module_path: str, func: str = "main"):
    """生成透传子命令：把剩余 args 交给 ``module_path.func(list(args))``。"""
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def _cmd(args):
        import importlib
        mod = importlib.import_module(module_path)
        rc = getattr(mod, func)(list(args))
        raise SystemExit(rc if rc is not None else 0)
    return _cmd


# 7 个子命令：parse-backend / register-cards / call-card / extract-auth /
# knowledge-gaps / verify-dag / execute-dag。register-cards 与 knowledge-gaps
# 自带的子子命令（extract/commit、report/register/...）由透传的 args 进各自 main 处理。
for _name, _mod in [
    ("parse-backend", "api_console.parse_backend"),
    ("register-cards", "api_console.register_cards"),
    ("call-card", "api_console.call_card"),
    ("extract-auth", "api_console.extract_auth"),
    ("knowledge-gaps", "api_console.knowledge_gaps"),
    ("verify-dag", "api_console.verify_dag"),
    ("execute-dag", "api_console.execute_dag"),
]:
    main.command(_name, context_settings={"ignore_unknown_options": True},
                 add_help_option=False)(_forward(_mod))


if __name__ == "__main__":
    main()
