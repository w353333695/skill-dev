# api-console

平台中性的 **API 资产建设 + 调用编排** CLI（对接系统可拔插，按 adapter 接入）。从 `skills/api-console` 抽取的**能力层**；编排指令与文档仍在 skill 侧（`skills/api-console/SKILL.md` + `references/`）。

## 两大主线

- **建库**：后端契约 / swagger + 前端 openapi → 标准化「API 卡片」库
- **编排**：自然语言需求 → 调用 DAG（读聚合 / 写 + 确认闸 + 回滚）→ 真调执行

## 安装（开发）

```bash
cd projects/api-console
uv venv --python 3.9
uv sync
```

## CLI

```bash
uv run api-console --help
uv run api-console parse-backend   --platform <p> --in <raw> --out <contracts.yaml>
uv run api-console register-cards  extract  --platform <p> --openapi <o> --backend-contracts <c> --out <_draft.yaml>
uv run api-console register-cards  commit   --platform <p> --in <_draft.yaml>
uv run api-console extract-auth    --platform <p> [--env <env>]
uv run api-console call-card       --platform <p> --card <n> [--param k=v]... [--allow-write]
uv run api-console knowledge-gaps  report   --platform <p>
uv run api-console verify-dag      --platform <p> --dag <dag.yaml>
uv run api-console execute-dag     --platform <p> --dag <dag.yaml> [--yes]
```

> 产物根 = 调用方 cwd（保留 `API_CONSOLE_WORKDIR` 约定）：`platforms/`、`tmp/orchestrate/` 落此。

## 测试

```bash
uv run pytest                  # 非 integration 测试（默认）
uv run pytest -m integration   # 含真实平台 integration（默认 skip）
```

## 与 skill 的关系

本 project 是**能力层**（确定性脏活：解析 / 注册 / 校验 / 执行）。`skills/api-console` 是**编排层**（SKILL.md + references + evals），通过本 CLI 调用，不 import 代码（CLI 边界）。
