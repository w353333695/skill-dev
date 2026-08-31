# api-cli

声明式 golang CLI：三方提交一份 YAML 接口清单，自动生成分层命令树，覆盖系统全部 API（CRUD + 自定义 action + 分页），鉴权与分页可插拔，并导出 MCP tools 供 LLM 直接调用。

经 iter2/iter3 演进，MCP tool 已是 **schema 驱动 + 用途富化**的 LLM 接口：inputSchema 展开嵌套 body（`_body`）、outputSchema 解释响应、tool description 含祖先链用途 + 行为标签（写操作/可分页），LLM 一次 `tools/list` 即可精准抉择；嵌套 resource 的 N 层相对 path 也已正确拼接。

📖 面向使用者的详细指南（安装、首次调用、对接新系统、MCP、排错）：[`docs/USAGE.md`](docs/USAGE.md)。

> **本 project 是 `projects/` 目录的 golang project**（与 Python project 平行支持，见工作空间 `AGENTS.md` §2）。打包走 `scripts/pack-go.sh` 多平台二进制大礼包，不走 whl。

## 核心命题
- **verb 是身份，method 是配置**：`operations` 是 map，key 是动词；method 是属性。
- **主干通用，按 adapter 接入**：清单→OperationTree→{cobra, MCP}；鉴权与分页是仅有的可插拔点（go-plugin）。
- **endpoint 多接入面**：同一资源模型挂前后端不同接入面（base_url + auth + path_prefix）。

## 迭代能力

- **MVP（iter1）**：声明式清单 → cobra 命令树 + MCP tools；CRUD + 自定义 action + 分页（cursor/offset/implicit）+ 鉴权可插拔（bearer/oauth2/hmac + go-plugin 外部 adapter）+ endpoint 多接入面。
- **iter2（schema 驱动 LLM + 真实翻页 + 体验打磨）**：inputSchema 展开嵌套 body（`_body` 完整 JSON Schema）+ outputSchema 解释响应 + `--explain` 子命令 + table 中文表头；分页 page-in-body（EasyOps/ES 风格）+ `--format`（json 流式 NDJSON / table-yaml 缓冲）；`--timeout`；MCP inputSchema.required 聚合；dry-run 移写闸门前。
- **iter3（LLM 抉择富化 + N 层 path）**：MCP tool description 富化（祖先链用途 · operation 用途 · 行为标签 `[写操作]`/`[可分页]`），cobra Short 用 resource/operation `description`；N 层相对 path（`ResolveURL` 沿祖先链拼接 + parent_key 占位填充 + 缺占位 lint）；修 `--help-format=json` 隐含 `--help`、全局 flag 放子命令前生效。

## 快速开始
```bash
make build                              # 产物 bin/api-cli
export CMDB_BACKEND_URL=http://localhost:9000
./bin/api-cli --spec examples/cmdb.yaml inst read i-1
./bin/api-cli --spec examples/cmdb.yaml inst search --all --format json
./bin/api-cli --spec examples/cmdb.yaml inst read i-1 --endpoint frontend
./bin/api-cli --spec examples/cmdb.yaml inst delete i-1 --dry-run
```

## 鉴权配置
清单里 `auth: <name>` 引用 `~/.api-cli/auth.d/<name>.yaml`：
```yaml
provider: hmac          # bearer|oauth2|hmac 或外部 adapter 二进制名
config:
  appkey: ${CMDB_APPKEY}
  secret: ${CMDB_SECRET}
```

内置 provider：`bearer`（静态 token）、`oauth2`（client_credentials）、`hmac`（AK/SK 签名）。外部 adapter 走 go-plugin（net/rpc 模式），provider 字段填 adapter 二进制名。模板见 `examples/auth.d/`。

## 作为 MCP server（供 LLM 调用）
```bash
./bin/api-cli --spec examples/cmdb.yaml --mcp
```
stdin/stdout JSON-RPC：`initialize` / `tools/list` / `tools/call`。每个 operation 自动成一个 tool。

每个 tool 的 `description` 是 **祖先链用途 · operation 用途 · 行为标签**（如 `CMDB 实例 · 按条件搜索实例 [写操作] [可分页]`），`inputSchema` 展开嵌套 body（`_body`）+ 聚合 required，`outputSchema` 解释响应——LLM 一次 `tools/list` 即可精准抉择，不必反复探查。`--explain <resource> <verb>` 给人/LLM 一份该 operation 的完整 input/output schema。

## 开发
```bash
make test       # go test ./...
make run        # go run ./cmd/api-cli
make build      # go build -o bin/api-cli ./cmd/api-cli
```

集成测试（mock server 端到端，前后端 CRUD + cursor 分页 + dry-run）：`cd projects/api-cli && go test ./tests/integration/...`。

## 分发打包

交叉编译全平台二进制（CGO=0 纯静态）+ zip 大礼包，独立于 `pack-dist.sh`（python whl 那套）：

```bash
# 工作空间根执行；-o 指定输出根目录（默认 tmp/）
scripts/pack-go.sh api-cli -o tmp/
# 自定义平台 / 版本 / 入口
scripts/pack-go.sh api-cli -o dist/ --targets linux/amd64,darwin/arm64 --version 0.1.0
```

产物：

```
<dir>/api-cli-binaries-<ver>/
  api-cli-<ver>-linux-amd64
  api-cli-<ver>-linux-arm64
  api-cli-<ver>-darwin-amd64
  api-cli-<ver>-darwin-arm64
  api-cli-<ver>-windows-amd64.exe
  checksums.txt                       # sha256 校验
<dir>/api-cli-binaries-<ver>.zip      # 全平台大礼包
```

**安装到 PATH**（手动三步）：

1. 解压 zip，挑对应平台二进制（**arm64 = aarch64 = Apple Silicon**）；
2. Mac/Linux：`chmod +x api-cli-<ver>-<os>-<arch>`；
3. 拷到 `~/.local/bin/api-cli`，确认 `~/.local/bin` 在 `PATH` 里。

**已知坑**：

- 解压后 `Permission denied` → 漏了 `chmod +x`（脚本已对非 windows 产物置位，但部分解压工具会丢权限）。
- macOS 首次运行被 Gatekeeper 拦：`xattr -d com.apple.quarantine /path/to/api-cli`。
- CGO=0 用纯 Go 的 DNS / TLS：少数公司 split-DNS、或老旧 `ca-certificates` 的 Linux 镜像可能解析失败 / 证书校验失败。遇此重编：`CGO_ENABLED=1` + 对应平台 C 工具链（失去交叉编译便利，按需取舍）。

## 文档
- **使用指南**（面向使用者）：`docs/USAGE.md` —— 安装、首次调用、命令用法、常见场景、对接新系统、MCP、排错
- MVP 设计：`docs/2026-08-07-api-cli-design.md` / 计划：`docs/2026-08-07-api-cli-plan.md`
- iter2 设计：`docs/2026-08-07-api-cli-iter2-design.md`（schema 驱动 LLM + 真实翻页 + 体验打磨）
- iter3 设计：`docs/2026-08-08-api-cli-iter3-design.md` / 计划：`docs/2026-08-08-api-cli-iter3-plan.md`（2 bug + LLM 抉择富化 + N 层 path）

## MVP 边界（不做）
OpenAPI importer、批量 create、长任务轮询、并发分页、静态代码生成、非 Go adapter SDK——见设计文档 §2.2 / §16。

**iter3 已知限制**（后续 iter 候选）：cobra 命令树不容忍嵌套位置 ID——`api-cli inst INST1 relation read REL1` 会把 `INST1` 当未知子命令。ResolveURL/engine/MCP 通道已正确（祖先链 + parent_key 填充），cobra CLI 端嵌套位置参数解析待修；当前嵌套 resource 走 MCP 或在清单层用平级 resource。
