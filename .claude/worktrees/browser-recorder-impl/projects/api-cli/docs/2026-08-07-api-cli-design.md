# api-cli 设计文档（MVP）

| 项 | 值 |
|---|---|
| 日期 | 2026-08-07 |
| 状态 | Draft（待实现，下一步 writing-plans） |
| 项目位置 | `projects/api-cli/`（golang，`projects/` 目录的破例 project） |
| 语言 | Go |
| 运行/验证环境 | 当前沙箱（需先安装 go 工具链，走国内镜像） |

---

## 1. 背景与目标

### 1.1 问题

对接一个系统（如 CMDB）的 API，传统方式是写一次性脚本或长篇 SDK。每接一个系统重复一遍，且产物既不便于人交互式探索，也不便于 LLM 直接调用。

### 1.2 目标

做一个 **声明式驱动的通用 CLI**：三方按规范提交一份"接口清单"，CLI 自动生成一棵分层命令树，覆盖该系统的全部 API。同一份主干代码对接任意系统，差异只落在清单和可插拔的 adapter 上。

核心命题：**verb（动词）是身份，HTTP method 是配置**；**主干通用、按 adapter 接入**。

### 1.3 非目标

- 不做 API 网关、不做请求编排/DAG（那是上层 skill 的职责）。
- 不做 GUI。
- MVP 不做 OpenAPI 自动导入、批量写、长任务轮询（见 §2.2）。

---

## 2. MVP 范围

### 2.1 做（完整功能核心闭环）

| # | 能力 | 说明 |
|---|---|---|
| 1 | 清单 YAML schema | `spec: api-cli/v1`，含 service/endpoints/resources/operations/pagination/schemas |
| 2 | OperationTree 内部模型 | 纯数据，零依赖；所有下游消费它 |
| 3 | cobra 动态命令树 | CRUD 标准动词（默认 method 映射）+ 自定义 action；N 层 `children` 嵌套 |
| 4 | endpoint 多接入面 | base_url + auth + path_prefix；`--endpoint` 切换；前后端均全功能 |
| 5 | 入参 schema 自适应 | 详细→强校验(type/required/enum/pattern)，简略→透传 |
| 6 | 内置鉴权 adapter | bearer / oauth2-client-credentials / hmac-sign |
| 7 | go-plugin 外部鉴权 adapter | 三方自研，HashiCorp go-plugin gRPC 协议（解耦卖点核心） |
| 8 | 分页引擎 | cursor + offset + 隐式终止；流式 NDJSON；死循环上限 + `--limit` + 主键去重 |
| 9 | 错误契约归一化 | exit code 语义化 + stderr 结构化 JSON |
| 10 | 写操作安全 | delete/update 默认 `--confirm`（`--yes` 跳过）；全操作 `--dry-run` / `--print-curl` |
| 11 | LLM 友好输出 | `--help-format=json`、`--format json\|table\|yaml` |
| 12 | MCP tool 导出 | OperationTree → MCP tools（stdio server），CLI 即 LLM toolset |

### 2.2 不做（后续增量）

| 能力 | 为什么先不做 |
|---|---|
| OpenAPI/Swagger importer | 独立子系统；MVP 先手写 YAML 验证模型 |
| `allow_operations` 前端只读限制 | schema 预留字段，不启用逻辑 |
| 批量 create（`--batch-file` 流式） | 独立非平凡操作，与分页对称但坑不同 |
| 长任务轮询（create 后轮询 status） | 独立子系统 |
| 并发分页 / link-header 分页 | 优化项；cursor+offset+隐式 已覆盖主流 |
| 静态代码生成快照（`generate` 子命令） | 动态命令树已够用 |
| 通用打包脚本 `pack-dist.sh` 集成 | whl 体系不适用 go；MVP 用 `go build` 单二进制 |
| 非 Go 语言的 adapter SDK | 协议是 gRPC，后续按需补 |

---

## 3. 整体架构

### 3.1 三层 + 可插拔 adapter

```
┌─ 输入层 ─────────────────────────────────────────────┐
│  examples/cmdb.yaml  (手写清单)                       │
└────────────────────┬─────────────────────────────────┘
                     │ parse
                     ▼
┌─ 内部模型层（纯数据，零依赖）─────────────────────────┐
│  OperationTree                                       │
│    ├─ endpoints[]   接入面(base_url+auth+path_prefix)│
│    └─ resources[]   operations[] / children[](N层)   │
└────────────────────┬─────────────────────────────────┘
                     │ consume
        ┌────────────┴───────────┐
        ▼                        ▼
   cobra 命令树               MCP tools
   (人用)                     (LLM 用)
        │                        │
        └───────────┬────────────┘
                    ▼
┌─ 执行引擎 engine ────────────────────────────────────┐
│ param校验 → 拼 path → auth.Apply → http.Do           │
│          → 分页引擎 → 错误归一化 → 输出               │
└──────┬───────────────────────────────────┬───────────┘
       ▲ 可插拔                              ▲ 可插拔
┌──────┴──────────┐                ┌────────┴─────────┐
│ auth adapters    │                │ paging 引擎       │
│ 内置3种 + go-plugin│              │ cursor/offset     │
└──────────────────┘                │ + go-plugin 外部  │
                                    └──────────────────┘
```

主干（清单→tree→执行）一套通用代码；**鉴权和分页是仅有的两个可插拔点**，都走 go-plugin。

### 3.2 数据流（一次 `cmdb inst read i-123` 的完整路径）

```
cmdb inst read i-123 --fields name
   │
   1. cobra 解析 flag → 匹配 Operation(inst.read)
   2. Param 校验：id=i-123 (path)、fields=name (query)、必填项检查
   3. 选 endpoint（--endpoint 或默认）→ 物化 path：
      endpoint.path_prefix + resource.path + operation.path
      = /api/v1 + /instances + /{id}  →  /api/v1/instances/i-123?fields=name
   4. AuthProvider.Apply(req) → 注入 Authorization / 签名 header
   5. http.Do ──▶ 响应
   6. 分页？是 → 按 pagination 声明自动翻页聚合（流式吐）
   7. 错误归一化 → exit code + 结构化 stderr
   8. 输出：--format json|table|yaml
```

### 3.3 设计原则

1. **verb 是身份，method 是配置**：operation map 的 key 是动词名（唯一），method 是属性（会重复）。同一资源 N 个 verb 共用一个 method 完全正常。
2. **主干通用，按 adapter 接入**：通用逻辑由 OperationTree 驱动，唯一可插拔点是鉴权与分页。
3. **endpoint 与 resources 正交**：资源模型只写一份，接入面差异（base_url/auth/path_prefix）打包成 endpoint。
4. **契约固定，实现自由**：adapter 必须实现固定 gRPC 接口，内部逻辑/语言自由。
5. **internal 私有、pkg 公开**：主干实现私有，扩展契约（adapter 接口）公开。

---

## 4. 目录结构

```
projects/api-cli/
├── go.mod / go.sum / Makefile        # module api-cli；build/test/run 便捷入口
├── README.md                         # golang 例外说明 + 打包/调用方式
├── cmd/api-cli/main.go               # 入口：加载清单 → 构树 → Execute
├── internal/                         # 私有实现
│   ├── spec/         schema.go(parse YAML→Tree) · parse_test.go
│   ├── tree/         tree.go · resolve.go(按 endpoint 物化完整 path/URL)
│   ├── cobracli/     build.go(递归构树) · flags.go(param→flag+校验) · help.go(--help-format=json)
│   ├── engine/       request.go · execute.go(auth→http→流式) · safety.go(--confirm/--dry-run/--print-curl)
│   ├── auth/         adapter.go(接口) · bearer.go/oauth2.go/hmac.go · plugin.go(go-plugin host)
│   ├── paging/       engine.go · cursor.go/offset.go · plugin.go
│   ├── endpoint/     select.go(--endpoint 解析+默认值)
│   ├── output/       format.go(json/table/yaml) · errors.go(归一化+exit code)
│   └── mcp/          server.go(Tree→MCP tools, stdio)
├── pkg/                              # 对外公开：三方写 adapter 要 import
│   └── adapter/      AuthProvider/PaginationProvider 接口 · auth.proto/paging.proto · types.go
├── examples/
│   ├── cmdb.yaml                     # 示例清单：前后端双 endpoint
│   └── auth.d/                       # 鉴权配置模板(环境变量占位，无真实密钥)
├── tests/integration/                # mockserver.go + cmdb_test.go 端到端
└── docs/                             # 项目设计文档（与代码同仓隔离）
    └── 2026-08-07-api-cli-design.md  # 本设计文档
```

**`internal/` vs `pkg/` 分界**：`internal/` 私有实现；`pkg/adapter/` 是对外契约——三方写 go-plugin adapter 时 import 这里的接口和 proto。

---

## 5. 清单 Schema 设计

### 5.1 完整示例（前后端双 endpoint）

```yaml
spec: api-cli/v1
service:
  name: cmdb
  version: "1.0"
  default_endpoint: backend
  endpoints:
    backend:
      base_url: ${CMDB_BACKEND_URL}
      auth: backend-sign              # 引用 ~/.api-cli/auth.d/backend-sign.yaml
      path_prefix: /api/v1
    frontend:
      base_url: ${CMDB_FRONTEND_URL}
      auth: frontend-token            # 引用 ~/.api-cli/auth.d/frontend-token.yaml
      path_prefix: /web/api/v1

resources:
  inst:                                # 资源名 = 命令名 → cmdb inst ...
    path: /instances
    singular: instance
    operations:
      create: { method: POST,  path: "", body: { $ref: "#/schemas/Instance" } }
      read:   { method: GET,   path: "/{id}",
                params: { id: { type: string, required: true, description: 实例 ID } } }
      update: { method: PATCH, path: "/{id}", body: { $ref: "#/schemas/InstancePatch" } }
      delete: { method: DELETE, path: "/{id}" }
      search:                         # 非 CRUD 自定义 action
        method: POST
        path: "/search"
        body: { $ref: "#/schemas/SearchQuery" }
        pagination:
          type: cursor
          items_path: data.list
          next: { from: data.next, request_in: query, request_as: page_token }
          has_more: data.next
    children:                          # 嵌套子资源 → cmdb inst <id> relation create
      relation:
        path: "/{instance_id}/relations"
        parent_key: instance_id
        operations:
          create: { method: POST, path: "" }
          read:   { method: GET,  path: "/{id}" }

schemas:
  Instance:
    type: object
    required: [name, class_id]
    properties:
      name:     { type: string, description: 实例名称 }
      class_id: { type: string, description: 模型 ID }
      labels:   { type: array, items: { type: string } }
  InstancePatch:
    type: object
    properties:
      name:   { type: string }
      labels: { type: array, items: { type: string } }
  SearchQuery:
    type: object
    properties:
      q:        { type: string }
      class_id: { type: string }
```

### 5.2 字段语义

| 字段 | 语义 |
|---|---|
| `spec` | 清单格式版本，演进用 |
| `service.base_url` | 不在此处；base_url 属于 endpoint |
| `service.default_endpoint` | 不指定 `--endpoint` 时使用 |
| `endpoint.base_url` | 支持 `${ENV}` 占位 |
| `endpoint.auth` | 引用 `~/.api-cli/auth.d/<name>.yaml`，不内联密钥 |
| `endpoint.path_prefix` | URL 前缀，参与路径拼装 |
| `endpoint.allow_operations` | 预留字段，MVP 不启用 |
| `resource.path` | 相对 endpoint.path_prefix |
| `resource.singular` | 给 `--help` 和 `<id>` 参数说明用 |
| `resource.parent_key` | 父 ID 注入到子命令 path 模板的键名 |
| `operation.method` | 标准 verb 可省略（走默认映射）；自定义 verb 必填 |
| `operation.path` | 相对 resource.path，含 `{param}` 模板 |
| `param.in` | path / query / header / body |
| `param.type` | 省略 = 透传（接受任意值） |
| `pagination.type` | cursor / offset / implicit |
| `pagination.items_path` | GJSON path，定位数据数组 |
| `pagination.has_more` | 省略 → 引擎用 "本轮条数 < size 或空" 隐式判断 |

### 5.3 路径拼装规则

完整 URL = `endpoint.base_url` + `endpoint.path_prefix` + `resource.path` + `operation.path`

- 斜杠归一化：相邻片段间多余的 `/` 合并，避免 `//`。
- 模板参数 `{id}` 解析为位置参数（`cmdb inst read <id>`）或 flag；`{parent_key}` 从父命令自动注入，无需用户传入。

示例：frontend endpoint + inst.read：
`https://cmdb.example.com` + `/web/api/v1` + `/instances` + `/{id}` → `https://cmdb.example.com/web/api/v1/instances/i-123`

### 5.4 标准动词默认 method 映射

| verb | 默认 method |
|---|---|
| create | POST |
| read | GET |
| update | PATCH |
| delete | DELETE |

清单里省略 `method` 时按此填充（importer 阶段填入 OperationTree，内部模型 method 永远必填）。自定义 verb（search/import/freeze）必须显式声明 method。

---

## 6. OperationTree 内部模型

纯数据、零依赖（不 import cobra / net/http）。importer（YAML/OpenAPI）生产它，exporter（cobra/MCP/文档）消费它。

```go
type OperationTree struct {
    Service   Service
    Resources map[string]*Resource
}

type Service struct {
    Name, Version    string
    DefaultEndpoint  string
    Endpoints        map[string]*Endpoint
}

type Endpoint struct {
    Name             string
    BaseURL          string
    Auth             string   // 引用 auth adapter 配置名
    PathPrefix       string
    AllowOperations  []string // 预留，MVP 不启用
}

type Resource struct {
    Name       string
    Path       string
    Singular   string
    ParentKey  string
    Operations map[string]*Operation  // key: create/read/.../custom
    Children   map[string]*Resource    // 递归 → N 层
}

type Operation struct {
    Verb       string
    Method     string
    Path       string
    Params     []Param
    Body       *Schema        // nil = 无 body
    Pagination *Pagination    // nil = 无分页
}

type Param struct {
    Name                                  string
    In                                    string // path|query|header|body
    Type                                  string // 空 = any（透传）
    Required                              bool
    Enum                                  []string
    Pattern, Description string
    Example                               any
}

type Pagination struct {
    Type                      string // cursor|offset|implicit
    ItemsPath                 string
    NextTokenPath             string // cursor
    PageParam, SizeParam      string // offset
    HasMorePath               string // 空 → 隐式兜底
}
```

---

## 7. Endpoint 多接入面

同一系统的前后端 API，**资源模型同一份**，差异只在接入面。endpoint 把差异打包：

| 差异维度 | 后端面 | 前端面 |
|---|---|---|
| base_url | 内网/直连 | 走网关 |
| 鉴权 | appkey + HMAC 签名 | 用户 token (Bearer) |
| URI 前缀 | `/api/v1` | `/web/api/v1` |
| 能力 | 全功能 | 全功能（MVP 不做限制） |

**MVP 决策**：前后端均全功能，`allow_operations` 字段预留不启用。endpoint 与鉴权 adapter 正交——endpoint 只声明"用哪个 auth adapter"，签名/token 实现仍在各自 adapter 内。

调用：
- `cmdb inst read i-123` → 默认 backend
- `cmdb inst read i-123 --endpoint frontend` → 走前端面

---

## 8. 鉴权 Adapter

### 8.1 接口契约（`pkg/adapter/`，对外公开）

```go
type AuthProvider interface {
    Configure(config map[string]any) error
    Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error)
}

type AuthRequest struct {
    Method  string
    URL     string
    Body    []byte               // 用 []byte 不用 io.Reader —— 跨进程要能序列化
    Headers map[string]string
}

type AuthResponse struct {
    Headers map[string]string    // 主程序合并进真实 request
    Query   map[string]string
}
```

`Apply` 不直接接 `*http.Request`——因为 `http.Request.Body` 是 `io.Reader`，跨进程无法传。给纯数据 `AuthRequest`，adapter 算完返回 headers/query，主程序合并到真实请求。

### 8.2 内置 vs 外部部署分档

| | 内置 3 种 (bearer/oauth2/hmac) | 外部 go-plugin |
|---|---|---|
| 部署 | 编译进主二进制，同进程调用 | 独立子进程，gRPC |
| 适用 | 高频、可信、稳定 | 三方自研、可能崩溃、不可信代码 |
| 接口 | 都实现 `AuthProvider` | 都实现 `AuthProvider` |

对 engine 完全透明——engine 只认 `AuthProvider` 接口，不关心背后是同进程函数还是子进程 gRPC。同进程零开销，子进程有隔离（崩溃不波及主程序、信任边界清晰）。

### 8.3 go-plugin 机制

采用 HashiCorp go-plugin（gRPC 模式），**不用 Go native plugin**（`.so` 要求主程序与插件 Go 版本/依赖完全一致，分发即地狱）。adapter 是独立可执行二进制，主程序子进程启动 + gRPC 握手。

### 8.4 Go adapter 骨架（三方示例）

```go
// 独立 main 包，编译成 auth-backend-sign 二进制
func main() {
    plugin.Serve(&plugin.ServeConfig{
        HandshakeConfig: adapter.Handshake,
        Plugins: map[string]plugin.Plugin{
            "auth": &adapter.AuthPluginGRPC{Impl: &BackendSignAuth{}},
        },
    })
}

type BackendSignAuth struct{ appkey, secret string }

func (b *BackendSignAuth) Configure(c map[string]any) error {
    b.appkey = c["appkey"].(string); b.secret = c["secret"].(string); return nil
}
func (b *BackendSignAuth) Apply(ctx context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
    sign := hmacSHA256(b.secret, r.Method+r.URL+string(r.Body))
    return &adapter.AuthResponse{Headers: map[string]string{
        "X-App-Key": b.appkey, "X-Sign": sign,
    }}, nil
}
```

分页 adapter 同构（`PaginationProvider.Next`）。鉴权和分页同一套机制、同一套 SDK，三方学一次写两种。

### 8.5 发现与配置

```yaml
# ~/.api-cli/auth.d/backend-sign.yaml
provider: backend-sign         # 二进制名（PATH 或 ~/.api-cli/bin/ 查找）
config:
  appkey: ${CMDB_APPKEY}
  secret: ${CMDB_SECRET}
```

主程序：读 manifest → 找二进制 → 子进程启动 → `Configure(config)` → 握手 → 后续每请求调 `Apply`。

内置 adapter 同样通过 `~/.api-cli/auth.d/<name>.yaml` 配置，`provider` 为 `bearer`/`oauth2`/`hmac` 时走同进程实现。

---

## 9. 分页引擎

### 9.1 三种形态（声明式配置覆盖）

**① cursor 型**（token 在响应里）：
```yaml
pagination:
  type: cursor
  items_path: data.list
  next: { from: data.next, request_in: query, request_as: page_token }
  has_more: data.next
```

**② offset 型**（自己算页码）：
```yaml
pagination:
  type: offset
  items_path: result.records
  page_param: page
  size_param: per_page
  size: 50
  # 不配 has_more → 引式兜底
```

**③ 隐式终止型**（API 不给结束信号）：
```yaml
pagination:
  type: implicit
  items_path: data
  # 引擎默认用 "本轮条数 < size 或 items 为空" 判断结束
```

不同 API 的结构差异（`data.list` / `result.records` / 根数组）通过 `items_path`（GJSON path）声明，引擎代码同一份。

### 9.2 引擎循环（伪代码）

```go
func (e *Engine) ListAll(ctx, op, baseReq) (<-chan json.RawMessage, error) {
    out := make(chan json.RawMessage, 100)
    go func() {
        defer close(out)
        req := baseReq
        for page := 0; page < e.maxPages; page++ {
            resp := e.do(req)
            items := gjsonGet(resp.Body, op.Pagination.ItemsPath).Array()
            for _, it := range items {
                emit(out, it)                       // 流式吐
                if reached(limit) { return }
            }
            if !hasMore(resp, op.Pagination, len(items)) { return }
            req = applyNext(req, resp, op.Pagination)  // cursor 抽 / offset += size
        }
    }()
    return out, nil
}
```

`hasMore` 与 `applyNext` 是仅有的两处分支，其余通用。

### 9.3 工程硬要求

1. **流式输出**：边取边吐 NDJSON，不全部累积。
2. **死循环硬上限**：默认最大页数 1000 + 最大条数 10000；`--all` 也受约束；`--limit` 可调高但警告。
3. **去重**：能拿到主键 id 时默认按 id 去重；`--no-dedupe` 关闭。
4. **`--limit N` 语义**：拉够 N 条就停（条数，不是页数）。
5. **进度到 stderr**：`fetched 1200, page 24` 走 stderr，不污染 stdout 数据流。

### 9.4 逃生舱（声明式吃不掉的）

响应非 JSON、next token 要从 header+body 拼分、翻页参数带签名等神仙结构，走自定义 `PaginationProvider`（go-plugin）：

```go
type PaginationProvider interface {
    Next(resp []byte, headers map[string]string, state map[string]any) (items []any, next any, err error)
}
```

清单声明：
```yaml
pagination:
  provider: mycompany-weird-pager
```

---

## 10. MCP 导出

OperationTree 的第二个消费者（与 cobra 命令树并列）。每个 Operation 映射为一个 MCP tool：

- tool name = `service + resource + verb`（如 `cmdb_inst_read`）
- input schema = params + body schema
- 调用走同一 engine（鉴权/分页/错误归一化复用）

MVP 提供 stdio server。这意味着加一个 MCP tool = 在清单里加一个 operation，不用动 mcp 包本身。CLI 因此同时是一份可被 Claude/Cursor 直接调用的 LLM toolset。

---

## 11. CLI 契约（对人 + 对 LLM）

### 11.1 全局 flag

| flag | 作用 |
|---|---|
| `--spec <path>` | 指定清单文件（默认搜索 `./.api-cli/` 与 `~/.api-cli/specs/`） |
| `--endpoint <name>` | 选接入面（默认 service.default_endpoint） |
| `--format json\|table\|yaml` | 输出格式（默认 json） |
| `--help-format text\|json` | `--help` 输出格式（json 给 LLM） |
| `--dry-run` | 不真调，打印将发的请求 |
| `--print-curl` | 打印等价 curl 命令 |
| `--yes` | 跳过写操作确认 |
| `--limit N` | 分页拉取上限（条数） |
| `--all` | 拉全部分页（受硬上限约束） |

### 11.2 exit code

| code | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 参数校验失败 |
| 2 | 鉴权失败 |
| 3 | API 业务错误 |
| 4 | 分页超限 |
| 5 | 网络超时 |

### 11.3 输出

- stdout：纯数据（json/yaml/table），可管道。
- stderr：进度、警告、结构化错误 JSON。
- `--help-format=json`：输出命令树片段的机器可读 schema（含参数约束、示例），供 LLM 发现可用命令。

---

## 12. 错误处理与写操作安全

**错误归一化**：清单可选声明 error schema（错误码/消息字段路径）；未声明则原样透传。归一化后统一以 exit code + stderr JSON 呈现。

**写操作安全**：
- `delete` / `update` 默认要求 `--confirm`（交互式确认），`--yes` 跳过。
- 所有操作支持 `--dry-run`（打印请求不发）与 `--print-curl`（打印等价 curl）。
- 这两项尤其重要于 LLM 场景——避免模型一句话误删生产数据。

---

## 13. 测试策略

| 层 | 范围 | 工具 |
|---|---|---|
| **单测** | spec 解析（YAML 边界用例）/ tree resolve（endpoint 物化 path）/ flag 注册校验 / 分页引擎（cursor·offset·隐式 各类响应）/ 3 种内置 auth / 错误归一化 | go test |
| **集成** | `httptest` mock server，端到端跑 `examples/cmdb.yaml` 前后端双 endpoint：CRUD + 分页流式 + 错误 + `--dry-run` | `tests/integration/` |
| **契约** | `pkg/adapter` 提供 test helper，三方 adapter 作者用它自验证符合 gRPC 契约 | go-plugin test harness |

mock server 关键职责：模拟 cursor/offset/隐式三种分页响应、各类错误格式、`has_more` 缺失场景——覆盖 engine 归一化逻辑。

---

## 14. go 工具链与依赖

### 14.1 安装（沙箱，中国网络）

- go 二进制：从 `golang.google.cn` 或国内镜像拉。
- `GOPROXY=https://goproxy.cn,direct`（七牛国内代理）。
- `GOSUMDB=sum.golang.google.cn`。
- 验证：`go version` + `go env` + `go build ./...` 能拉到全部依赖。

### 14.2 依赖清单（版本锁定，writing-plans 时钉死）

| 依赖 | 用途 |
|---|---|
| `github.com/spf13/cobra` | 命令树 |
| `github.com/tidwall/gjson` | 分页抽 items（JSON path） |
| `github.com/hashicorp/go-plugin` | 外部 adapter |
| `google.golang.org/grpc` | go-plugin 底层 |
| `gopkg.in/yaml.v3` | 清单解析 |

---

## 15. CLAUDE.md 例外说明

本工作空间 `projects/` 默认为 Python 能力包（uv + whl）。`projects/api-cli/` 为 **golang 破例 project**，实施时需在 `CLAUDE.md` §2 或 §3 增补一条：

> `projects/` 默认 Python；`api-cli` 为 golang 例外。打包走 `go build` 单二进制，不走 whl；通用打包脚本 `pack-dist.sh` 暂不覆盖。skill 编排层（如有）调用方式为 `go run ./cmd/api-cli`（开发态）或裸二进制（分发态），不走 `uv run`。

本 spec 仅记录该决策，CLAUDE.md 的实际修改属于实现阶段动作。

**文档位置**：本 spec 及后续 api-cli 设计文档放 `projects/api-cli/docs/`，遵循项目自包含原则（各 project 文档隔离，不占全局 `docs/`）。

---

## 16. 后续增量（V2+）

按优先级：

1. OpenAPI/Swagger importer（从 swagger 半自动生成清单）
2. `allow_operations` 前端只读限制启用
3. 批量 create（`--batch-file` 流式提交）
4. 长任务轮询（create 后轮询 status 直到 ready）
5. 并发分页 / link-header 分页
6. 静态代码生成快照（`generate` 子命令，类型安全 + IDE 友好）
7. 通用打包脚本 `pack-dist.sh` 多语言支持（go binary）
8. 非 Go 语言（Python/Rust）adapter SDK

---

## 17. 实施前置（writing-plans 第一步）

1. 沙箱安装 go + 配 `GOPROXY=https://goproxy.cn,direct`，`go build` 验证依赖可达。
2. `CLAUDE.md` 增补 golang 例外说明。
3. 建立 `projects/api-cli/` 目录骨架（`go mod init api-cli`）。
4. 按 §4 目录结构创建 internal/pkg/examples/tests 骨架文件。
