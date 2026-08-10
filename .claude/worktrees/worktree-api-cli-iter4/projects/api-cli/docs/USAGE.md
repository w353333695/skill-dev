# api-cli 使用指南

> 面向**使用者**的操作指南：怎么装、怎么调第一个接口、怎么对接一个新系统。
> 开发/架构/迭代设计见仓库根 `README.md` 与 `docs/2026-08-0*-api-cli-*.md`。

api-cli 是一个声明式 CLI：你交一份 YAML 接口清单，它就生成分层命令树，让你像调本地命令一样调远端 API；同时自动导出 MCP tools，让 LLM（Claude 等）直接调用。

```bash
api-cli --spec my-system.yaml inst read i-1          # 像本地命令一样调 API
api-cli --spec my-system.yaml --mcp                   # 或变成 MCP server 给 LLM
```

---

## 1. 安装

### 方式 A：预编译二进制（推荐）
从发布包取对应平台的二进制（`darwin-arm64` = Apple Silicon Mac）：

```bash
unzip api-cli-binaries-<ver>.zip
chmod +x api-cli-<ver>-darwin-arm64
mv api-cli-<ver>-darwin-arm64 ~/.local/bin/api-cli
echo $PATH | grep -q ~/.local/bin || echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.zshrc
api-cli --help
```

macOS 首次运行若被 Gatekeeper 拦：`xattr -d com.apple.quarantine $(which api-cli)`。

### 方式 B：源码
```bash
git clone <repo> && cd <repo>/projects/api-cli
make build                    # 产物 bin/api-cli
./bin/api-cli --help
```

---

## 2. 五分钟上手

**目标**：调通一个 `read` 接口。三步。

**① 写最小清单** `myspec.yaml`（`auth: none` 跳过鉴权，先跑通）：
```yaml
spec: api-cli/v1
service:
  name: demo
  default_endpoint: be
  endpoints:
    be: { base_url: http://localhost:9000, auth: none, path_prefix: /api/v1 }
resources:
  widget:
    description: 部件
    path: /widgets
    operations:
      read: { method: GET, path: "/{id}", description: 读取单个部件, params: { id: { in: path, required: true, description: 部件 ID } } }
      list: { method: GET, path: "", description: 列出全部部件 }
```

**② 看生成的命令**（验证清单被正确解析）：
```bash
api-cli --spec myspec.yaml --help           # 顶层 help：看到 widget 子命令
api-cli --spec myspec.yaml widget --help    # widget 下的 verb：read / list
```

**③ 调第一个接口**（`read` 的 `id` 是 path 参数，按位置传）：
```bash
api-cli --spec myspec.yaml widget read w-1
# → GET http://localhost:9000/api/v1/widgets/w-1
```

跑通后，把 `auth: none` 换成真实鉴权（见 §5），就能对接生产系统了。

---

## 3. 命令怎么用

### 命令树
api-cli 按**清单结构**自动生成命令树：

```
api-cli                          # service 根
└── <resource>                   # 每个顶层 resource 一个子命令
    ├── create / read / update / delete / <自定义 verb>   # 每个 operation 一个 verb 子命令
    └── <child resource>         # 嵌套 resource（children）再下一层
```

verb（create/read/update/delete）有**默认 method**（POST/GET/PATCH/DELETE），清单里不写 `method` 也能用；自定义 verb（如 `search`）需声明 `method`。

### 参数怎么传
| 参数位置 | 怎么传 | 例子 |
|---|---|---|
| `path`（URL 里的 `{id}`） | **按位置**跟在 verb 后 | `widget read w-1` → `id=w-1` |
| `query` / `header` / `body` | **按 flag**（参数名即 flag 名） | `widget list --fields name,size` |
| 嵌套/复杂 body | `--body-file body.json` 或 MCP `_body` | `widget create --body-file ./new.json` |

### 必看：`--help` 与 `--explain`
- `api-cli <resource> <verb> --help`：人读的命令帮助。
- `api-cli <resource> <verb> --help-format=json`：结构化 JSON（resource/verb/method/path/params/body），给脚本/LLM 消费。
- `api-cli explain <resource> <verb>`：输出该 operation 的**完整 input + output schema**（含嵌套 body、响应字段、required），调接口前先看这个最清楚。
- `--help-format=json` 单独给（不带 `--help`）也触发 help（iter3 修复）。

### 全局 flag（可放子命令前或后）
| flag | 作用 |
|---|---|
| `--spec <path>` | 指定清单（也可用 `API_CLI_SPEC` 环境变量） |
| `--endpoint <name>` | 选接入面（默认 `service.default_endpoint`） |
| `--format json\|yaml\|table` | 输出格式（默认 json；json 分页时流式 NDJSON，table/yaml 缓冲） |
| `--help-format text\|json` | `--help` 输出格式 |
| `--dry-run` | 不真发，打印将发的请求 |
| `--print-curl` | 不真发，打印等价 curl |
| `--yes` | 跳过写操作（POST/PUT/PATCH/DELETE）的确认 |
| `--limit N` / `--all` | 分页：拉够 N 条停 / 拉到尽头 |
| `--body-file <path>` | 请求 body（JSON 文件，支持嵌套/复杂结构） |
| `--insecure` | 跳过 TLS 证书校验（自签证书） |
| `--timeout 30s` | HTTP 超时 |

---

## 4. 常用场景

### CRUD
```bash
api-cli --spec s.yaml widget create --body-file new.json   # POST   /widgets
api-cli --spec s.yaml widget read w-1                      # GET    /widgets/w-1
api-cli --spec s.yaml widget update w-1 --body-file up.json# PATCH  /widgets/w-1
api-cli --spec s.yaml widget delete w-1                    # DELETE /widgets/w-1
```

### 搜索 + 翻页
```bash
api-cli --spec s.yaml widget search --all                  # 拉全部分页（流式 NDJSON）
api-cli --spec s.yaml widget search --limit 100            # 拉够 100 条停
api-cli --spec s.yaml widget search --all --format table   # table 表格（中文表头取响应字段 description）
```
分页规则在清单的 `pagination` 里声明（cursor / offset，page 在 query 或 body）——见 §6。

### 发请求前先预览（写操作尤其有用）
```bash
api-cli --spec s.yaml widget delete w-1 --dry-run          # 打印将发的请求，不删
api-cli --spec s.yaml widget delete w-1 --print-curl       # 打印等价 curl，方便手动复现
```
`--dry-run` 不受写确认闸门拦截（安全预览）。

### 切换接入面（同一资源，前后端不同入口）
清单里声明多个 `endpoints`，用 `--endpoint` 切：
```bash
api-cli --spec s.yaml widget read w-1 --endpoint frontend  # 走前端网关
api-cli --spec s.yaml widget read w-1 --endpoint backend   # 直连后端
```

### 嵌套 resource（resource 下挂子 resource）
```bash
api-cli --spec s.yaml inst read i-1                        # 顶层 resource
```
> ⚠️ **已知限制**：cobra CLI 端的**嵌套位置参数**尚未完全支持——`inst i-1 relation read r-1` 会把 `i-1` 当未知子命令。当前嵌套 resource 建议走 MCP 通道（见 §7），或在清单层用平级 resource 拆开。顶层 resource 不受影响。

---

## 5. 鉴权配置

清单里 `auth: <name>` 引用 `~/.api-cli/auth.d/<name>.yaml`（默认搜索路径，可用 `API_CLI_AUTH_D` 覆盖）。

### 内置 provider
```yaml
# bearer：静态 token
provider: bearer
config:
  token: ${MY_TOKEN}

# oauth2：client_credentials
provider: oauth2
config:
  token_url: https://xxx/oauth2/token
  client_id: ${CLIENT_ID}
  client_secret: ${CLIENT_SECRET}

# hmac：AK/SK 签名（如 EasyOps）
provider: hmac
config:
  appkey: ${APPKEY}
  secret: ${SECRET}
```

### 外部 adapter（go-plugin，net/rpc 模式）
内置 provider 不够用时，写一个 adapter 二进制，`provider` 填二进制名：
```yaml
provider: easyops-cookie   # 对应 ~/.api-cli/auth.d/easyops-cookie 二进制（或 adapter 注册名）
config: { ... }
```

---

## 6. 对接一个新系统（清单语法）

清单是一份 YAML，描述**接入面 + 资源树 + 每个操作**。完整骨架：

```yaml
spec: api-cli/v1
service:
  name: my-system
  version: "1.0"
  default_endpoint: backend
  endpoints:
    backend:
      base_url: ${API_BASE}            # 支持 ${ENV} 占位
      auth: my-auth                    # 引用 ~/.api-cli/auth.d/my-auth.yaml
      path_prefix: /api/v1             # 所有 path 前的前缀
      # host: admin.x.local            # 可选：自定义 Host header（IP 直连 + 改 host 场景）
    frontend:
      base_url: ${API_FRONT}
      auth: my-auth-front
      path_prefix: /web/api/v1

resources:
  inst:                                # resource 名 = 子命令名
    description: 实例                  # ← 写好！MCP tool description 与 cobra Short 用它
    path: /instances                   # resource 的 URL 段
    singular: instance                 # 可选：单数名（operation 描述回退用）
    operations:
      read:
        description: 读取单个实例      # ← 写好！MCP description 含它
        method: GET
        path: "/{id}"                  # operation 的 URL 段，含 {param} 模板
        params:
          id: { in: path, required: true, type: string, description: 实例 ID }
          fields: { in: query, description: 返回字段 }
      search:
        description: 按条件搜索
        method: POST
        path: /search
        body:                          # 请求 body schema（MCP inputSchema 展开 _body）
          type: object
          required: [page, page_size]
          description: 搜索请求
          properties:
            query: { type: object, description: MongoDB 风格条件, additional_properties: true }
            page: { type: integer }
        response:                      # 响应 schema（MCP outputSchema + table 中文表头）
          type: object
          properties:
            data: { type: object, properties: { list: { type: array, items: { type: object } }, total: { type: integer } } }
        pagination:                    # 分页声明
          type: offset                 # cursor | offset | implicit
          page_in: body                # page 在 body（默认 query）
          items_path: data.list        # 用 GJSON path 从响应抽 items
          page_param: page
          size_param: page_size
          size: 20
```

### 清单编写要点
- **`description` 是关键**：resource 和 operation 的 `description` 会进 MCP tool description（`祖先链 · 用途 · [写操作][可分页]`）和 cobra Short。写清楚用途，LLM 抉择才准；不写则回退到名字。
- **嵌套 resource 用 `children`**：父 resource 声明 `parent_key`，子 resource 的 `path` 用 `{parent_key}` 占位。**`parent_key` 写在父 resource 上**（不是子）。
  ```yaml
  inst:
    path: /instances
    parent_key: instance_id        # ← 在父上：声明子的 path 会用 {instance_id}
    children:
      relation:
        path: "/{instance_id}/relations"   # 子 path 用占位，不含父级 /instances（祖先链自动拼）
        operations: { ... }
  ```
  启动时若 `parent_key` 声明了但子 path 里没有对应占位，会**告警**（URL 可能缺父 ID）。
- **body 嵌套结构**：`body` 用 JSON Schema 风格递归声明，LLM/人都能看懂；动态结构（任意 key）用 `additional_properties: true` + `description` 说规则。
- **`${ENV}` 占位**：`base_url` / auth config / `endpoint.headers` 值里的 `${VAR}` 会被环境变量替换。
- **`endpoint.headers`（固定头，每个请求都带）**：租户号、API 版本、追踪 id 等"所有请求都要带"的头，写在 endpoint 上一次声明、所有 operation 自动注入。多租户系统（如 EasyOps 要 `org`+`user` header）尤其有用，避免逐 operation 重复。
  ```yaml
  endpoints:
    backend:
      base_url: ${API_BASE}
      auth: my-auth
      headers:
        org: ${ORG}        # 值支持 ${ENV}
        user: ${USER}
  ```
  优先级：`endpoint.headers`（基底）→ operation 的 `header` 参数（可覆盖同名）→ auth provider 回传 header（最终权威）。
- **无 `$ref`，schema 必须内联**：`body`/`response` 的 JSON Schema 全部内联展开；不解析 `$ref`，顶层 `schemas` 也不注入 operation。多个 operation 共用同一结构只能重复内联。
- **`required` 双义（别混）**：`params` 里 `required: true` 是 **bool**（path/query 参数）；`body`/`response`（schema 对象）里 `required` 是 **[]string**（父对象列出哪些子字段必填，如 `required: [id, name]`）。在 schema **属性**上写 `required: true` 会解析报错 `cannot unmarshal !!bool into []string`。

> 嵌套 resource 的 `children` 仅用于 **URL 真嵌套**（子真实 URL = 父 URL + 子段）。非嵌套结构用平级 resource。

---

## 7. 作为 MCP server 接 LLM

```bash
api-cli --spec my-system.yaml --mcp
```
stdin/stdout JSON-RPC（`initialize` / `tools/list` / `tools/call`）。每个 operation 自动成一个 tool：
- **name**：`<service>_<resource链>_<verb>`（如 `cmdb_inst_search`）
- **description**：`祖先链用途 · operation 用途 · [写操作][可分页]`（行为标签自动从 method/pagination 推断）
- **inputSchema**：path 参数扁平在外层，嵌套 body 在 `_body`，`required` 聚合必填
- **outputSchema**：响应字段结构

LLM 一次 `tools/list` 就能看全用途并精准抉择。复杂 body 通过 `_body` 传（JSON 对象，绕开单层 flag 限制）。

Claude Desktop / Cursor 等配置示例（stdio）：
```json
{ "mcpServers": { "api-cli": { "command": "api-cli", "args": ["--spec", "/abs/path/myspec.yaml", "--mcp"] } } }
```

---

## 8. 错误排查

| 现象 | 原因 / 解法 |
|---|---|
| `找不到清单` | 用 `--spec` 或设 `API_CLI_SPEC`，或放到 `.api-cli/spec.yaml` |
| `缺少 path 参数 X` | path 参数没按位置传（如 `widget read` 漏了 id） |
| `endpoint "x" 不存在` | `--endpoint` 名字与清单 `endpoints` 的 key 对不上 |
| 写操作被拦要确认 | 加 `--yes` 跳过，或这是设计（写操作默认需确认） |
| TLS 证书报错（自签） | 加 `--insecure` |
| 请求超时 | 加 `--timeout 30s` |
| `--help-format=json` 没出 JSON | iter3 已修复（单独给即触发 help）；确认二进制是新版 |
| 全局 flag 放子命令前不生效 | iter3 已修复（`--spec x --endpoint y inst read` 现在可用）；旧版需把全局 flag 放子命令后 |
| MCP tool 看不出用途 | 在清单给 resource/operation 写 `description` |
| 嵌套 resource 调用 URL 缺父级段 | 确认 `parent_key` 写在**父** resource 上；子 path 含 `{parent_key}` 占位 |

---

## 9. 已知限制

- **cobra CLI 嵌套位置参数**：`api-cli inst <id> relation read <rid>` 形式尚未支持（位置 id 被当未知子命令）。嵌套 resource 当前走 MCP，或清单层拆平级。
- **MVP 不做**：OpenAPI importer、批量 create、长任务轮询、并发分页、静态代码生成、非 Go adapter SDK。

完整能力演进与设计见仓库根 `README.md` 与 `docs/` 下的 design/plan。
