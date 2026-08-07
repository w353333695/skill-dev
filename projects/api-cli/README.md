# api-cli

声明式 golang CLI：三方提交 YAML 接口清单，自动生成分层命令树。

**状态**：MVP 开发中。设计见 `docs/2026-08-07-api-cli-design.md`，实现计划见 `docs/2026-08-07-api-cli-plan.md`。

## 开发

```bash
make run        # go run ./cmd/api-cli
make test       # go test ./...
make build      # 产物 bin/api-cli
```

> 本 project 为 `projects/` 目录的 golang 破例（见工作空间 CLAUDE.md）。
