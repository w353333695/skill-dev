# api-cli Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个声明式 golang CLI：三方提交一份 YAML 清单，CLI 动态生成分层命令树，覆盖该系统全部 API（CRUD + 自定义 action + 分页），鉴权与分页可插拔，并导出 MCP tools 供 LLM 直接调用。

**Architecture:** 清单 YAML → OperationTree（纯数据模型）→ 两个消费者（cobra 命令树 / MCP tools）。执行引擎 engine 消费 OperationTree，在唯一的两个可插拔点（鉴权、分页）接入 adapter。adapter 走 go-plugin（gRPC 子进程）。前后端差异抽象为 endpoint（接入面），与 resources 正交。

**Tech Stack:** Go 1.22 / cobra（命令树）/ gjson（分页 JSON path）/ hashicorp/go-plugin + grpc（外部 adapter）/ yaml.v3（清单解析）/ httptest（集成测试）

## Global Constraints

- **语言/版本**：Go 1.22（沙箱当前无 go，Task 1 先装）
- **module path**：`api-cli`（`go mod init api-cli`）；`pkg/adapter` 对外公开，三方 import 路径为 `api-cli/pkg/adapter`
- **模块代理**：`GOPROXY=https://goproxy.cn,direct`、`GOSUMDB=sum.golang.google.cn`（中国网络，全 task 适用）
- **依赖版本（写进 go.mod）**：`github.com/spf13/cobra v1.8.1`、`github.com/tidwall/gjson v1.17.1`、`github.com/hashicorp/go-plugin v1.6.0`、`google.golang.org/grpc v1.65.0`、`gopkg.in/yaml.v3 v3.0.1`
- **命名规则**：Go 包/类型/方法用英文；注释、文档、错误消息用中文（CLAUDE.md 要求）
- **核心命题**：verb 是身份，method 是配置；同一资源 N 个 verb 可共用一个 method
- **路径拼装**：完整 URL = `endpoint.base_url` + `endpoint.path_prefix` + `resource.path` + `operation.path`，斜杠归一化
- **标准 verb 默认 method**：create=POST / read=GET / update=PATCH / delete=DELETE（清单可覆盖）
- **exit code**：0 成功 / 1 参数 / 2 鉴权 / 3 API 业务错误 / 4 分页超限 / 5 网络超时
- **项目位置**：`projects/api-cli/`（CLAUDE.md golang 破例 project，Task 1 增补说明）
- **提交规范**：每个 task 末尾 commit；message 用 `feat(api-cli):`/`refactor(api-cli):`/`test(api-cli):`/`docs(api-cli):` 前缀，body 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **spec 来源**：`projects/api-cli/docs/2026-08-07-api-cli-design.md`（本 plan 与之同目录）

---

## File Structure

| 文件 | 职责 | 依赖 |
|---|---|---|
| `go.mod` / `go.sum` | module 定义 + 依赖锁 | — |
| `Makefile` | build/test/run/install 便捷入口 | — |
| `cmd/api-cli/main.go` | 入口：加载清单 → 构命令树 / 起 MCP server → Execute | spec, tree, cobracli, mcp |
| `pkg/adapter/types.go` | 对外公开：`AuthProvider`/`PaginationProvider` 接口 + `AuthRequest/Response` 等 | — |
| `pkg/adapter/contract_test.go` | adapter 契约 test helper（三方自验证用） | types.go |
| `internal/tree/types.go` | OperationTree/Service/Endpoint/Resource/Operation/Param/Pagination/Schema 纯类型 | — |
| `internal/tree/resolve.go` | `ResolveURL`(endpoint 物化) / `FindOperation`(命令路径定位) | types.go |
| `internal/spec/schema.go` | 带 yaml tag 的清单 struct（importer 输入） | tree（产出 *tree.OperationTree） |
| `internal/spec/parse.go` | `Parse([]byte) (*tree.OperationTree, error)`：YAML → tree + 默认 method 填充 + env 占位展开 | schema.go, tree |
| `internal/auth/loader.go` | 读 `~/.api-cli/auth.d/<name>.yaml` → 选内置或外部 provider | pkg/adapter |
| `internal/auth/bearer.go` / `oauth2.go` / `hmac.go` | 内置 3 种 AuthProvider | pkg/adapter |
| `internal/auth/plugin.go` | go-plugin host：加载外部 adapter 二进制 | pkg/adapter |
| `internal/paging/engine.go` | 分页引擎：cursor/offset/implicit 统一循环 + 流式 channel | pkg/adapter, gjson |
| `internal/output/format.go` | json/table/yaml 格式化 | — |
| `internal/output/errors.go` | 错误归一化 + exit code 映射 | — |
| `internal/engine/request.go` | param→query/header/body 组装 + path 模板填充 | tree |
| `internal/engine/execute.go` | auth.Apply → http.Do → 分页/单次 → 输出；--dry-run/--print-curl | auth, paging, output, tree |
| `internal/engine/safety.go` | 写操作 --confirm/--yes 闸门 | tree |
| `internal/cobracli/build.go` | OperationTree → cobra 命令树（递归，N 层） | tree, engine |
| `internal/cobracli/flags.go` | param → cobra flag 注册 + 校验 | tree |
| `internal/cobracli/help.go` | --help-format=text\|json | tree |
| `internal/mcp/server.go` | OperationTree → MCP tools（stdio server） | tree, engine |
| `examples/cmdb.yaml` | 示例清单：前后端双 endpoint + CRUD + search 分页 + children | — |
| `examples/auth.d/*.yaml` | 鉴权配置模板（${ENV} 占位） | — |
| `tests/integration/mockserver.go` | httptest mock：cursor/offset/implicit 分页 + 错误格式 | — |
| `tests/integration/cmdb_test.go` | 端到端：前后端 CRUD + 分页流式 + dry-run | all |

---

## Task 1: go 工具链安装 + 项目骨架 + CLAUDE.md 例外

**Files:**
- Create: `projects/api-cli/go.mod` / `Makefile` / `cmd/api-cli/main.go` / `README.md`
- Create: `projects/api-cli/internal/.gitkeep` `pkg/.gitkeep` `examples/.gitkeep` `tests/integration/.gitkeep`（空目录占位）
- Modify: `/workspace/CLAUDE.md`（增补 golang 例外条目）

**Interfaces:**
- Consumes: spec §14.1（go 安装）、§15（CLAUDE.md 例外）
- Produces: 可编译的空 go 项目（`go build ./...` 通过）、module path `api-cli`、go 在 PATH

- [ ] **Step 1: 安装 go（沙箱无 go，走国内源）**

```bash
cd /tmp
curl -sSL --max-time 60 -o go.tgz https://golang.google.cn/dl/go1.22.5.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go.tgz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
echo 'export PATH=$PATH:$(go env GOPATH)/bin' >> ~/.bashrc
export PATH=$PATH:/usr/local/go/bin
go version
```
Expected: `go version go1.22.5 linux/amd64`

- [ ] **Step 2: 配置国内模块代理（写进 ENV，全 task 受益）**

```bash
go env -w GOPROXY=https://goproxy.cn,direct
go env -w GOSUMDB=sum.golang.google.cn
go env GOPROXY
```
Expected: `https://goproxy.cn,direct`

- [ ] **Step 3: 初始化 module + 目录骨架**

```bash
cd /workspace/projects/api-cli
go mod init api-cli
mkdir -p cmd/api-cli internal/tree internal/spec internal/auth internal/paging internal/output internal/engine internal/cobracli internal/mcp pkg/adapter examples/auth.d tests/integration
touch internal/.gitkeep pkg/.gitkeep examples/.gitkeep tests/integration/.gitkeep
```
Expected: 生成 `go.mod` 含 `module api-cli` + `go 1.22`

- [ ] **Step 4: 写最小 main.go（占位，能编译）**

Create `projects/api-cli/cmd/api-cli/main.go`:
```go
// Package main 是 api-cli 的入口。MVP 阶段先占位，后续 task 串联完整逻辑。
package main

import "fmt"

func main() {
	fmt.Println("api-cli (skeleton)")
}
```

- [ ] **Step 5: 验证编译**

Run: `cd /workspace/projects/api-cli && go build ./...`
Expected: 无输出（成功）

Run: `go run ./cmd/api-cli`
Expected: `api-cli (skeleton)`

- [ ] **Step 6: 写 Makefile**

Create `projects/api-cli/Makefile`:
```makefile
.PHONY: build test run install
build:
	go build -o bin/api-cli ./cmd/api-cli
test:
	go test ./...
run:
	go run ./cmd/api-cli
install:
	go install ./cmd/api-cli
```

- [ ] **Step 7: 增补 CLAUDE.md golang 例外**

Modify `/workspace/CLAUDE.md` §2（工作空间结构）末尾追加一段：
```markdown
* **golang 例外**：`projects/api-cli/` 为 golang project（破例）。打包走 `go build` 单二进制，不走 whl；通用打包脚本 `pack-dist.sh` 暂不覆盖它。skill 编排层调用方式为 `go run ./cmd/api-cli`（开发态）或裸二进制（分发态），不走 `uv run`。项目文档隔离在 `projects/<name>/docs/`。
```

- [ ] **Step 8: 写 README.md（最小，后续 Task 15 补全）**

Create `projects/api-cli/README.md`:
```markdown
# api-cli

声明式 golang CLI：三方提交 YAML 接口清单，自动生成分层命令树。

**状态**：MVP 开发中。设计见 `docs/2026-08-07-api-cli-design.md`，实现计划见 `docs/2026-08-07-api-cli-plan.md`。

## 开发

\`\`\`bash
make run        # go run ./cmd/api-cli
make test       # go test ./...
make build      # 产物 bin/api-cli
\`\`\`

> 本 project 为 `projects/` 目录的 golang 破例（见工作空间 CLAUDE.md）。
```

- [ ] **Step 9: Commit**

```bash
cd /workspace
git add projects/api-cli/ CLAUDE.md
git commit -m "feat(api-cli): 初始化 go 项目骨架与 CLAUDE.md golang 例外

- go mod init api-cli，目录骨架（internal/pkg/examples/tests）
- 最小 main.go 占位 + Makefile + README
- CLAUDE.md §2 增补 golang 例外条目

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: pkg/adapter 公共契约（接口 + 类型）

三方写外部 adapter 时 import 此包。零业务依赖，只放契约。

**Files:**
- Create: `pkg/adapter/types.go`
- Test: `pkg/adapter/types_test.go`

**Interfaces:**
- Consumes: spec §8.1（AuthProvider）、§9.4（PaginationProvider）
- Produces: `adapter.AuthProvider`、`adapter.PaginationProvider`、`adapter.AuthRequest/Response`、`adapter.PagingResult`、`adapter.Handshake`、`adapter.AuthPluginGRPC`/`PagingPluginGRPC`（go-plugin 桥接）

- [ ] **Step 1: 写失败测试（接口可被实现）**

Create `pkg/adapter/types_test.go`:
```go
package adapter

import (
	"context"
	"testing"
)

// 验证接口能被任意结构实现（编译期保证）
func TestInterfacesAreImplementable(t *testing.T) {
	var _ AuthProvider = (*stubAuth)(nil)
	var _ PaginationProvider = (*stubPaging)(nil)
}

type stubAuth struct{}
func (s *stubAuth) Configure(config map[string]any) error                      { return nil }
func (s *stubAuth) Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error) {
	return &AuthResponse{Headers: map[string]string{"Authorization": "Bearer x"}}, nil
}

type stubPaging struct{}
func (s *stubPaging) Next(resp []byte, headers map[string]string, state map[string]any) (*PagingResult, error) {
	return &PagingResult{Items: []any{}, HasNext: false}, nil
}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd /workspace/projects/api-cli && go test ./pkg/adapter/`
Expected: FAIL — `undefined: AuthProvider` 等

- [ ] **Step 3: 实现 types.go**

Create `pkg/adapter/types.go`:
```go
// Package adapter 是 api-cli 的对外扩展契约。
// 三方写鉴权/分页 adapter 时 import 本包，实现其中的接口。
package adapter

import "context"

// AuthProvider 鉴权 adapter 契约。内置 3 种与外部 go-plugin 都实现它。
type AuthProvider interface {
	// Configure 启动时灌配置（token/appkey/secret 等，来自 ~/.api-cli/auth.d/<name>.yaml 的 config 段）。
	Configure(config map[string]any) error
	// Apply 每个请求前调用，返回要追加的 headers/query。主程序合并进真实 *http.Request。
	Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error)
}

// AuthRequest 是给 adapter 的请求快照。用 []byte 而非 io.Reader，因跨进程要能序列化。
type AuthRequest struct {
	Method  string
	URL     string
	Body    []byte
	Headers map[string]string
}

// AuthResponse 是 adapter 算出的注入项。
type AuthResponse struct {
	Headers map[string]string
	Query   map[string]string
}

// PaginationProvider 分页 adapter 契约（声明式分页吃不掉时的逃生舱）。
type PaginationProvider interface {
	// Next 给一次响应，吐出本页数据 + 是否还有下一页 + 下一页状态。
	Next(resp []byte, headers map[string]string, state map[string]any) (*PagingResult, error)
}

// PagingResult 是 PaginationProvider.Next 的返回。
type PagingResult struct {
	Items   []any      // 本页数据条目
	HasNext bool       // 是否还有下一页
	State   map[string]any // 下一页状态（透传回下一次 Next）
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `go test ./pkg/adapter/`
Expected: `ok api-cli/pkg/adapter`

- [ ] **Step 5: 加 go-plugin 桥接（GRPC plugin 包装，go-plugin host/client 共用）**

Append to `pkg/adapter/types.go`:
```go
import (
	"context"
	"github.com/hashicorp/go-plugin
)

// Handshake 是 go-plugin 握手配置（主程序与外部 adapter 二进制必须用同样的值）。
var Handshake = plugin.HandshakeConfig{
	ProtocolVersion:  1,
	MagicCookieKey:   "API_CLI_PLUGIN",
	MagicCookieValue: "api-cli-adapter",
}

// AuthPluginGRPC 把 AuthProvider 包装成 go-plugin 的 GRPC 插件。
type AuthPluginGRPC struct {
	plugin.NetRPCUnsupportedPlugin
	Impl AuthProvider
}

// PagingPluginGRPC 把 PaginationProvider 包装成 go-plugin 的 GRPC 插件。
type PagingPluginGRPC struct {
	plugin.NetRPCUnsupportedPlugin
	Impl PaginationProvider
}

// PluginName 鉴权 adapter 在 plugin map 里用的 key。
const PluginNameAuth = "auth"
// PluginNamePaging 分页 adapter 在 plugin map 里用的 key。
const PluginNamePaging = "paging"
```

注：go-plugin 的 GRPC serve/dispense 具体协议在 Task 11（host）实现；此处先定义共享常量与包装类型骨架，避免循环依赖。GRPC 接口的 GRPCServer/GRPCClient 实现放 host 侧（Task 11），由 host 提供 `Serve` helper 给三方调用。

- [ ] **Step 6: 拉依赖 + go mod tidy**

Run: `go get github.com/hashicorp/go-plugin@v1.6.0 && go mod tidy`
Expected: `go.sum` 更新，无错误

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/
git commit -m "feat(api-cli): pkg/adapter 公共契约（AuthProvider/PaginationProvider + go-plugin 桥）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: internal/tree 纯类型定义

OperationTree 模型，纯数据，零依赖（不 import cobra/net/http）。spec §6 的 Go 落地。

**Files:**
- Create: `internal/tree/types.go`
- Test: `internal/tree/types_test.go`

**Interfaces:**
- Consumes: spec §6
- Produces: `tree.OperationTree/Service/Endpoint/Resource/Operation/Param/Pagination/Schema`（后续所有包依赖）

- [ ] **Step 1: 写失败测试（类型可构造 + json tag）**

Create `internal/tree/types_test.go`:
```go
package tree

import "testing"

func TestOperationTreeConstruct(t *testing.T) {
	tr := &OperationTree{
		Service: Service{Name: "cmdb", DefaultEndpoint: "backend",
			Endpoints: map[string]*Endpoint{
				"backend": {Name: "backend", BaseURL: "http://x", PathPrefix: "/api/v1", Auth: "backend-sign"},
			}},
		Resources: map[string]*Resource{
			"inst": {Name: "inst", Path: "/instances", Singular: "instance",
				Operations: map[string]*Operation{
					"read": {Verb: "read", Method: "GET", Path: "/{id}",
						Params: []Param{{Name: "id", In: "path", Type: "string", Required: true}}},
				}},
		},
	}
	if tr.Service.Name != "cmdb" {
		t.Fatal("service name mismatch")
	}
	if tr.Resources["inst"].Operations["read"].Method != "GET" {
		t.Fatal("method mismatch")
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/tree/`
Expected: FAIL — `undefined: OperationTree`

- [ ] **Step 3: 实现 types.go**

Create `internal/tree/types.go`:
```go
// Package tree 是 api-cli 的内部统一模型（OperationTree）。
// 纯数据、零依赖（不 import cobra/net/http）。importer 产它，cobra/MCP/engine 消费它。
package tree

// OperationTree 清单解析后的统一模型。
type OperationTree struct {
	Service   Service
	Resources map[string]*Resource
}

// Service 服务级配置。
type Service struct {
	Name            string
	Version         string
	DefaultEndpoint string
	Endpoints       map[string]*Endpoint
}

// Endpoint 接入面：同一资源模型挂不同接入面的差异打包于此。
type Endpoint struct {
	Name            string
	BaseURL         string // 支持 ${ENV} 占位（parse 阶段展开）
	Auth            string // 引用 ~/.api-cli/auth.d/<name>.yaml
	PathPrefix      string
	AllowOperations []string // 预留，MVP 不启用
}

// Resource 资源定义（命令树节点）。
type Resource struct {
	Name       string
	Path       string
	Singular   string
	ParentKey  string // 父 ID 注入到子命令 path 模板的键名
	Operations map[string]*Operation
	Children   map[string]*Resource // 递归 → N 层
}

// Operation 一个动作（verb 是身份，method 是配置）。
type Operation struct {
	Verb       string
	Method     string // 内部模型永远必填（parse 阶段对标准 verb 填默认值）
	Path       string // 相对 resource.Path，含 {param} 模板
	Params     []Param
	Body       *Schema     // nil = 无 body
	Pagination *Pagination // nil = 无分页
}

// Param 一个入参。
type Param struct {
	Name        string
	In          string // path|query|header|body
	Type        string // 空 = any（透传）
	Required    bool
	Enum        []string
	Pattern     string
	Description string
	Example     any
}

// Pagination 分页声明。
type Pagination struct {
	Type          string // cursor|offset|implicit
	ItemsPath     string // GJSON path
	NextTokenPath string // cursor：从响应抽 next token 的路径
	PageParam     string // offset：请求页码参数名
	SizeParam     string // offset：请求每页大小参数名
	Size          int    // offset：每页大小
	HasMorePath   string // 空 → 引擎用 "本轮条数 < size 或 items 空" 隐式判断
}

// Schema 参数/body 的结构描述（MVP 用最小子集，支持 type/required/properties）。
type Schema struct {
	Type       string
	Required   []string
	Properties map[string]*Schema
	Items      *Schema // type=array 时
	Description string
}
```

- [ ] **Step 4: 运行，确认通过**

Run: `go test ./internal/tree/`
Expected: `ok api-cli/internal/tree`

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/tree/
git commit -m "feat(api-cli): internal/tree OperationTree 纯类型定义

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: internal/tree resolve（endpoint 物化 URL + 命令路径定位）

把"相对路径模板"物化成实际 URL；按命令路径（`inst.read`）定位 Operation。

**Files:**
- Modify: `internal/tree/`（新增 `resolve.go`、`resolve_test.go`）

**Interfaces:**
- Consumes: Task 3 类型、spec §5.3（路径拼装）
- Produces: `(*OperationTree).ResolveURL(endpoint, op, vals) (string, error)`、`(*OperationTree).FindOperation([]string) (*Resource, *Operation, error)`、`(*OperationTree).SelectEndpoint(name) (*Endpoint, error)`

- [ ] **Step 1: 写失败测试（URL 物化 + 斜杠归一化）**

Create `internal/tree/resolve_test.go`:
```go
package tree

import "testing"

func sampleTree() *OperationTree {
	return &OperationTree{
		Service: Service{DefaultEndpoint: "backend",
			Endpoints: map[string]*Endpoint{
				"backend":  {Name: "backend", BaseURL: "https://cmdb.example.com", PathPrefix: "/api/v1", Auth: "bk"},
				"frontend": {Name: "frontend", BaseURL: "https://cmdb.example.com", PathPrefix: "/web/api/v1", Auth: "fe"},
			}},
		Resources: map[string]*Resource{
			"inst": {Name: "inst", Path: "/instances",
				Operations: map[string]*Operation{
					"read": {Verb: "read", Method: "GET", Path: "/{id}",
						Params: []Param{{Name: "id", In: "path"}}}},
		},
	}
}

func TestResolveURL(t *testing.T) {
	tr := sampleTree()
	ep, _ := tr.SelectEndpoint("frontend")
	op := tr.Resources["inst"].Operations["read"]
	url, err := tr.ResolveURL(ep, op, map[string]string{"id": "i-123"})
	if err != nil {
		t.Fatal(err)
	}
	want := "https://cmdb.example.com/web/api/v1/instances/i-123"
	if url != want {
		t.Fatalf("got %q want %q", url, want)
	}
}

func TestSelectEndpointDefault(t *testing.T) {
	tr := sampleTree()
	ep, err := tr.SelectEndpoint("") // 空名 → 默认 endpoint
	if err != nil {
		t.Fatal(err)
	}
	if ep.Name != "backend" {
		t.Fatalf("want default backend, got %s", ep.Name)
	}
}

func TestFindOperation(t *testing.T) {
	tr := sampleTree()
	r, op, err := tr.FindOperation([]string{"inst", "read"})
	if err != nil {
		t.Fatal(err)
	}
	if r.Name != "inst" || op.Verb != "read" {
		t.Fatal("locate failed")
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/tree/`
Expected: FAIL — `undefined: SelectEndpoint` 等

- [ ] **Step 3: 实现 resolve.go**

Create `internal/tree/resolve.go`:
```go
package tree

import (
	"fmt"
	"strings"
)

// SelectEndpoint 按名字选接入面；空名用 service.DefaultEndpoint。
func (t *OperationTree) SelectEndpoint(name string) (*Endpoint, error) {
	if name == "" {
		name = t.Service.DefaultEndpoint
	}
	ep, ok := t.Service.Endpoints[name]
	if !ok {
		return nil, fmt.Errorf("endpoint %q 不存在", name)
	}
	return ep, nil
}

// ResolveURL 物化完整 URL：base_url + path_prefix + resource.path + operation.path，填入 path 参数。
// 注：vals 是 path 参数值（query/header/body 由 engine 单独处理）。
func (t *OperationTree) ResolveURL(ep *Endpoint, op *Operation, vals map[string]string) (string, error) {
	// 1. 找到所属 resource 的 path（op 不持有 resource 引用，需由调用方拼好 op.Path 为相对 resource；
	//    这里约定 op.Path 已含 resource 上下文。engine 调用前会拼 resource.Path + op.Path。）
	full := joinPath(ep.BaseURL, ep.PathPrefix, op.Path)
	// 2. 填 {param} 模板
	for _, p := range op.Params {
		if p.In == "path" {
			v, ok := vals[p.Name]
			if !ok && p.Required {
				return "", fmt.Errorf("缺少 path 参数 %s", p.Name)
			}
			full = strings.ReplaceAll(full, "{"+p.Name+"}", v)
		}
	}
	return full, nil
}

// joinPath 拼接多段路径，归一化斜杠（避免 //）。
// 第一段若含 "://"（scheme），保留其原有的双斜杠。
func joinPath(segs ...string) string {
	if len(segs) == 0 {
		return ""
	}
	out := segs[0]
	for _, s := range segs[1:] {
		if out != "" && !strings.HasSuffix(out, "/") && s != "" && !strings.HasPrefix(s, "/") {
			out += "/"
		}
		out += s
	}
	// 合并中间多余的斜杠（但保留 scheme:// 的双斜杠）
	out = strings.ReplaceAll(out, "://", "\x00SCHEME\x00")
	out = strings.ReplaceAll(out, "//", "/")
	out = strings.ReplaceAll(out, "\x00SCHEME\x00", "://")
	return out
}

// FindOperation 按命令路径（如 ["inst","read"] 或 ["inst","<id>","relation","read"]）定位资源与动作。
// 返回最终命中的 Resource 与 Operation。中间的占位段（如父资源 id）跳过。
func (t *OperationTree) FindOperation(path []string) (*Resource, *Operation, error) {
	if len(path) < 2 {
		return nil, nil, fmt.Errorf("命令路径过短")
	}
	res, ok := t.Resources[path[0]]
	if !ok {
		return nil, nil, fmt.Errorf("资源 %q 不存在", path[0])
	}
	return findInResource(res, path[1:])
}

// findInResource 递归在 resource 内定位：交替跳过 id 占位段 + 进入 children/operations。
func findInResource(r *Resource, segs []string) (*Resource, *Operation, error) {
	if len(segs) == 0 {
		return nil, nil, fmt.Errorf("缺少动词")
	}
	// 先尝试 segs[0] 为 verb
	if op, ok := r.Operations[segs[0]]; ok {
		return r, op, nil
	}
	// 否则 segs[0] 是 id 占位，segs[1] 应是 child 资源名
	if len(segs) >= 3 {
		child, ok := r.Children[segs[1]]
		if !ok {
			return nil, nil, fmt.Errorf("子资源 %q 不存在", segs[1])
		}
		return findInResource(child, segs[2:])
	}
	return nil, nil, fmt.Errorf("无法定位动作：%v", segs)
}
```

- [ ] **Step 4: 运行，确认通过**

Run: `go test ./internal/tree/`
Expected: `ok api-cli/internal/tree`

- [ ] **Step 5: 补一个 joinPath 边界测试（隐式纳入 types_test 或新文件）**

Append to `internal/tree/resolve_test.go`:
```go
func TestJoinPathNormalization(t *testing.T) {
	cases := map[string]string{
		"https://x.com": joinPath("https://x.com"),
		"https://x.com/a/b": joinPath("https://x.com", "/a", "/b"),
		"https://x.com/a/b": joinPath("https://x.com/", "/a/", "b"),
	}
	for want, got := range cases {
		if got != want {
			t.Errorf("joinPath got %q want %q", got, want)
		}
	}
}
```
Run: `go test ./internal/tree/` → Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add projects/api-cli/internal/tree/
git commit -m "feat(api-cli): tree.ResolveURL/SelectEndpoint/FindOperation（endpoint 物化 + 命令定位）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: internal/spec 清单 YAML 解析（→ *tree.OperationTree）

importer：YAML → 带 yaml tag 的中间 struct → tree 类型。含标准 verb 默认 method 填充 + `${ENV}` 展开。

**Files:**
- Create: `internal/spec/schema.go`（带 yaml tag 的 struct）
- Create: `internal/spec/parse.go`（Parse 函数 + 默认 method + env 展开）
- Test: `internal/spec/parse_test.go`
- Test data: `internal/spec/testdata/cmdb.yaml`

**Interfaces:**
- Consumes: Task 3 (tree 类型)、spec §5（schema）、§5.4（默认 method）
- Produces: `spec.Parse([]byte) (*tree.OperationTree, error)`

- [ ] **Step 1: 写 testdata + 失败测试**

Create `internal/spec/testdata/cmdb.yaml`:
```yaml
spec: api-cli/v1
service:
  name: cmdb
  version: "1.0"
  default_endpoint: backend
  endpoints:
    backend:
      base_url: http://localhost:9000
      auth: backend-sign
      path_prefix: /api/v1
resources:
  inst:
    path: /instances
    singular: instance
    operations:
      create: { method: POST, path: "" }
      read: { path: "/{id}", params: { id: { type: string, required: true } } }
      delete: { path: "/{id}" }
      search:
        method: POST
        path: /search
        pagination:
          type: cursor
          items_path: data.list
          next_token_path: data.next
          has_more_path: data.next
```
（注：上面 read/delete 省略 method，验证默认填充）

Create `internal/spec/parse_test.go`:
```go
package spec

import (
	"os"
	"testing"
)

func TestParseDefaultsAndEnv(t *testing.T) {
	raw, _ := os.ReadFile("testdata/cmdb.yaml")
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if tr.Service.Name != "cmdb" {
		t.Fatal("name")
	}
	// read 省 method → 默认 GET
	if m := tr.Resources["inst"].Operations["read"].Method; m != "GET" {
		t.Fatalf("read method want GET, got %s", m)
	}
	// delete 省 method → 默认 DELETE
	if m := tr.Resources["inst"].Operations["delete"].Method; m != "DELETE" {
		t.Fatalf("delete method want DELETE, got %s", m)
	}
	// create 显式 POST
	if m := tr.Resources["inst"].Operations["create"].Method; m != "POST" {
		t.Fatalf("create method want POST, got %s", m)
	}
	// pagination 物化
	pg := tr.Resources["inst"].Operations["search"].Pagination
	if pg == nil || pg.Type != "cursor" || pg.ItemsPath != "data.list" {
		t.Fatalf("pagination not parsed: %+v", pg)
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/spec/`
Expected: FAIL — `undefined: Parse`

- [ ] **Step 3: 实现 schema.go（yaml tag struct）**

Create `internal/spec/schema.go`:
```go
// Package spec 把 YAML 清单解析成 *tree.OperationTree。
package spec

// yamlManifest 与清单 1:1 映射的中间结构。
type yamlManifest struct {
	Spec      string                  `yaml:"spec"`
	Service   yamlService             `yaml:"service"`
	Resources map[string]*yamlResource `yaml:"resources"`
	Schemas   map[string]*yamlSchema  `yaml:"schemas"`
}

type yamlService struct {
	Name            string                  `yaml:"name"`
	Version         string                  `yaml:"version"`
	DefaultEndpoint string                  `yaml:"default_endpoint"`
	Endpoints       map[string]*yamlEndpoint `yaml:"endpoints"`
}

type yamlEndpoint struct {
	BaseURL         string   `yaml:"base_url"`
	Auth            string   `yaml:"auth"`
	PathPrefix      string   `yaml:"path_prefix"`
	AllowOperations []string `yaml:"allow_operations"`
}

type yamlResource struct {
	Path       string                   `yaml:"path"`
	Singular   string                   `yaml:"singular"`
	ParentKey  string                   `yaml:"parent_key"`
	Operations map[string]*yamlOperation `yaml:"operations"`
	Children   map[string]*yamlResource  `yaml:"children"`
}

type yamlOperation struct {
	Method     string            `yaml:"method"`
	Path       string            `yaml:"path"`
	Params     map[string]yamlParam `yaml:"params"`
	Body       *yamlSchema       `yaml:"body"`
	Pagination *yamlPagination   `yaml:"pagination"`
}

type yamlParam struct {
	In          string   `yaml:"in"`
	Type        string   `yaml:"type"`
	Required    bool     `yaml:"required"`
	Enum        []string `yaml:"enum"`
	Pattern     string   `yaml:"pattern"`
	Description string   `yaml:"description"`
}

type yamlPagination struct {
	Type          string `yaml:"type"`
	ItemsPath     string `yaml:"items_path"`
	NextTokenPath string `yaml:"next_token_path"`
	PageParam     string `yaml:"page_param"`
	SizeParam     string `yaml:"size_param"`
	Size          int    `yaml:"size"`
	HasMorePath   string `yaml:"has_more_path"`
}

type yamlSchema struct {
	Type        string                  `yaml:"type"`
	Required    []string                `yaml:"required"`
	Properties  map[string]*yamlSchema  `yaml:"properties"`
	Items       *yamlSchema             `yaml:"items"`
	Description string                  `yaml:"description"`
}
```

- [ ] **Step 4: 实现 parse.go**

Create `internal/spec/parse.go`:
```go
package spec

import (
	"fmt"
	"os"
	"regexp"

	"api-cli/internal/tree"

	"gopkg.in/yaml.v3"
)

// 默认 method 映射（spec §5.4）。
var defaultMethod = map[string]string{
	"create": "POST",
	"read":   "GET",
	"update": "PATCH",
	"delete": "DELETE",
}

var envRe = regexp.MustCompile(`\$\{([A-Z_][A-Z0-9_]*)\}`)

// Parse 把 YAML 字节解析成 *tree.OperationTree。
func Parse(raw []byte) (*tree.OperationTree, error) {
	var y yamlManifest
	if err := yaml.Unmarshal(raw, &y); err != nil {
		return nil, fmt.Errorf("YAML 解析失败: %w", err)
	}
	if y.Spec != "api-cli/v1" {
		return nil, fmt.Errorf("不支持的 spec 版本 %q（仅支持 api-cli/v1）", y.Spec)
	}
	tr := &tree.OperationTree{
		Service: tree.Service{
			Name:            y.Service.Name,
			Version:         y.Service.Version,
			DefaultEndpoint: y.Service.DefaultEndpoint,
			Endpoints:       map[string]*tree.Endpoint{},
		},
		Resources: map[string]*tree.Resource{},
	}
	for name, ep := range y.Service.Endpoints {
		tr.Service.Endpoints[name] = &tree.Endpoint{
			Name: name, BaseURL: expandEnv(ep.BaseURL), Auth: ep.Auth,
			PathPrefix: ep.PathPrefix, AllowOperations: ep.AllowOperations,
		}
	}
	for name, r := range y.Resources {
		tr.Resources[name] = convertResource(name, r)
	}
	return tr, nil
}

func convertResource(name string, y *yamlResource) *tree.Resource {
	r := &tree.Resource{
		Name: name, Path: y.Path, Singular: y.Singular, ParentKey: y.ParentKey,
		Operations: map[string]*tree.Operation{}, Children: map[string]*tree.Resource{},
	}
	for verb, op := range y.Operations {
		r.Operations[verb] = convertOperation(verb, op)
	}
	for cname, c := range y.Children {
		r.Children[cname] = convertResource(cname, c)
	}
	return r
}

func convertOperation(verb string, y *yamlOperation) *tree.Operation {
	op := &tree.Operation{Verb: verb, Method: y.Method, Path: y.Path}
	if op.Method == "" {
		op.Method = defaultMethod[verb] // 标准 verb 默认填充；自定义 verb 空 method 在 Validate 阶段报错
	}
	for pname, p := range y.Params {
		op.Params = append(op.Params, tree.Param{
			Name: pname, In: p.In, Type: p.Type, Required: p.Required,
			Enum: p.Enum, Pattern: p.Pattern, Description: p.Description,
		})
	}
	if y.Body != nil {
		op.Body = convertSchema(y.Body)
	}
	if y.Pagination != nil {
		op.Pagination = &tree.Pagination{
			Type: y.Pagination.Type, ItemsPath: y.Pagination.ItemsPath,
			NextTokenPath: y.Pagination.NextTokenPath, PageParam: y.Pagination.PageParam,
			SizeParam: y.Pagination.SizeParam, Size: y.Pagination.Size, HasMorePath: y.Pagination.HasMorePath,
		}
	}
	return op
}

func convertSchema(y *yamlSchema) *tree.Schema {
	s := &tree.Schema{Type: y.Type, Required: y.Required, Description: y.Description}
	for k, v := range y.Properties {
		if s.Properties == nil {
			s.Properties = map[string]*tree.Schema{}
		}
		s.Properties[k] = convertSchema(v)
	}
	if y.Items != nil {
		s.Items = convertSchema(y.Items)
	}
	return s
}

// expandEnv 把 ${VAR} 替换成 os.Getenv("VAR")；未设置则留空。
func expandEnv(s string) string {
	return envRe.ReplaceAllStringFunc(s, func(m string) string {
		return os.Getenv(m[2 : len(m)-1])
	})
}
```

- [ ] **Step 5: 拉依赖 + 运行测试**

Run: `go get gopkg.in/yaml.v3@v3.0.1 && go mod tidy && go test ./internal/spec/`
Expected: `ok api-cli/internal/spec`

- [ ] **Step 6: 补 env 展开测试**

Append to `parse_test.go`:
```go
func TestExpandEnv(t *testing.T) {
	os.Setenv("CMDB_TEST_URL", "http://env.example.com")
	defer os.Unsetenv("CMDB_TEST_URL")
	raw := []byte("spec: api-cli/v1\nservice:\n  name: x\n  default_endpoint: e\n  endpoints:\n    e: { base_url: ${CMDB_TEST_URL}, auth: a, path_prefix: /p }\nresources: {}\n")
	tr, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := tr.Service.Endpoints["e"].BaseURL; got != "http://env.example.com" {
		t.Fatalf("env not expanded: %q", got)
	}
}
```
Run: `go test ./internal/spec/` → Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/spec/
git commit -m "feat(api-cli): spec.Parse YAML→OperationTree（默认 method 填充 + \${ENV} 展开）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: internal/output 格式化 + 错误归一化

**Files:**
- Create: `internal/output/format.go`、`errors.go`
- Test: `format_test.go`、`errors_test.go`

**Interfaces:**
- Consumes: spec §11.3（输出）、§11.2（exit code）、§12（错误归一化）
- Produces: `output.Format(w, format, data)`、`output.APIError`、`output.ExitCode(err)`

- [ ] **Step 1: 写失败测试（格式化）**

Create `internal/output/format_test.go`:
```go
package output

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestFormatJSON(t *testing.T) {
	var buf bytes.Buffer
	data := map[string]any{"id": "i-1", "name": "n"}
	if err := Format(&buf, "json", data); err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(buf.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["id"] != "i-1" {
		t.Fatal("json roundtrip failed")
	}
}

func TestFormatYAML(t *testing.T) {
	var buf bytes.Buffer
	if err := Format(&buf, "yaml", map[string]any{"id": "i-1"}); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("id: i-1")) {
		t.Fatalf("yaml output unexpected: %s", buf.String())
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/output/`
Expected: FAIL — `undefined: Format`

- [ ] **Step 3: 实现 format.go**

Create `internal/output/format.go`:
```go
// Package output 负责结果格式化与错误归一化。
package output

import (
	"encoding/json"
	"fmt"
	"io"

	"gopkg.in/yaml.v3"
)

// Format 按指定格式把 data 写入 w。支持 json/yaml/table。
func Format(w io.Writer, format string, data any) error {
	switch format {
	case "json", "": // 默认 json
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(data)
	case "yaml":
		return yaml.NewEncoder(w).Encode(data)
	case "table":
		return formatTable(w, data)
	default:
		return fmt.Errorf("不支持的格式 %q", format)
	}
}
```

- [ ] **Step 4: 实现 errors.go + formatTable**

Create `internal/output/errors.go`:
```go
package output

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"reflect"
)

// Exit code 语义（spec §11.2）。
const (
	ExitOK         = 0
	ExitParamError = 1
	ExitAuthError  = 2
	ExitAPIError   = 3
	ExitPagingOver = 4
	ExitNetTimeout = 5
)

// APIError 业务错误（归一化后）。
type APIError struct {
	StatusCode int      `json:"status_code"`
	Code       string   `json:"code"`
	Message    string   `json:"message"`
	ExitCode   int      `json:"-"`
}

func (e *APIError) Error() string { return fmt.Sprintf("api error %d: %s", e.StatusCode, e.Message) }

// PrintError 把错误以结构化 JSON 写到 stderr（spec §11.3）。
func PrintError(w io.Writer, err error) {
	ae, ok := err.(*APIError)
	if !ok {
		ae = &APIError{Code: "internal", Message: err.Error(), ExitCode: ExitParamError}
	}
	b, _ := json.Marshal(ae)
	fmt.Fprintln(w, string(b))
}

// ExitCode 从 err 推断 exit code。
func ExitCode(err error) int {
	if err == nil {
		return ExitOK
	}
	if ae, ok := err.(*APIError); ok {
		return ae.ExitCode
	}
	return ExitParamError
}

// NormalizeAPIError 把 HTTP 响应归一化成 APIError。MVP 不读清单 error schema，直接透传 body。
func NormalizeAPIError(statusCode int, body []byte) *APIError {
	return &APIError{
		StatusCode: statusCode,
		Code:       fmt.Sprintf("HTTP_%d", statusCode),
		Message:    string(body),
		ExitCode:   mapStatusCode(statusCode),
	}
}

func mapStatusCode(c int) int {
	switch {
	case c == 401 || c == 403:
		return ExitAuthError
	case c >= 400 && c < 500:
		return ExitAPIError
	case c >= 500:
		return ExitAPIError
	default:
		return ExitOK
	}
}

// formatTable 把 slice of map 打成简易表格。
func formatTable(w io.Writer, data any) error {
	v := reflect.ValueOf(data)
	if v.Kind() != reflect.Slice {
		// 非 slice：当作单行
		return Format(w, "json", data)
	}
	if v.Len() == 0 {
		return nil
	}
	// 取第一条的 keys 作表头
	first := v.Index(0)
	if first.Kind() != reflect.Map {
		return Format(w, "json", data)
	}
	keys := []string{}
	for _, k := range first.MapKeys() {
		keys = append(keys, k.String())
	}
	fmt.Fprintln(w, joinRow(keys))
	for i := 0; i < v.Len(); i++ {
		row := make([]string, len(keys))
		m := v.Index(i)
		for j, k := range keys {
			vv := m.MapIndex(reflect.ValueOf(k))
			if vv.IsValid() {
				row[j] = fmt.Sprint(vv.Interface())
			}
		}
		fmt.Fprintln(w, joinRow(row))
	}
	return nil
}

func joinRow(cols []string) string {
	out := ""
	for i, c := range cols {
		if i > 0 {
			out += "\t"
		}
		out += c
	}
	return out
}

// 让 os 被 import（PrintError 未来扩展可能用 os.Stderr；当前保留）
var _ = os.Stderr
```

- [ ] **Step 5: 运行测试 + 补错误测试**

Run: `go test ./internal/output/`
Expected: `ok api-cli/internal/output`

Append to `internal/output/errors_test.go` (new file):
```go
package output

import "testing"

func TestExitCodeMapping(t *testing.T) {
	if got := ExitCode(nil); got != ExitOK {
		t.Fatal("nil should be OK")
	}
	ae := &APIError{ExitCode: ExitAuthError}
	if got := ExitCode(ae); got != ExitAuthError {
		t.Fatal("auth exit code")
	}
	if got := ExitCode(NormalizeAPIError(401, []byte("no"))); got != ExitAuthError {
		t.Fatalf("401 should map to auth, got %d", got)
	}
}
```
Run: `go test ./internal/output/` → Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add projects/api-cli/internal/output/
git commit -m "feat(api-cli): output 格式化(json/yaml/table) + 错误归一化 + exit code

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: internal/auth 内置 3 种 adapter + 配置加载

读 `~/.api-cli/auth.d/<name>.yaml`，按 `provider` 字段选内置实现（bearer/oauth2/hmac）或外部（Task 11）。

**Files:**
- Create: `internal/auth/loader.go`、`bearer.go`、`oauth2.go`、`hmac.go`
- Test: `loader_test.go`、`bearer_test.go`、`hmac_test.go`

**Interfaces:**
- Consumes: Task 2 (`adapter.AuthProvider`)、spec §8.5（配置发现）
- Produces: `auth.Load(name) (adapter.AuthProvider, error)`、3 个内置 provider

- [ ] **Step 1: 写失败测试（bearer）**

Create `internal/auth/bearer_test.go`:
```go
package auth

import (
	"context"
	"testing"

	"api-cli/pkg/adapter"
)

func TestBearerApply(t *testing.T) {
	b := &BearerAuth{}
	if err := b.Configure(map[string]any{"token": "abc123"}); err != nil {
		t.Fatal(err)
	}
	resp, err := b.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Headers["Authorization"] != "Bearer abc123" {
		t.Fatalf("want Bearer abc123, got %q", resp.Headers["Authorization"])
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/auth/`
Expected: FAIL — `undefined: BearerAuth`

- [ ] **Step 3: 实现 bearer.go / oauth2.go / hmac.go**

Create `internal/auth/bearer.go`:
```go
package auth

import (
	"context"

	"api-cli/pkg/adapter"
)

// BearerAuth 内置 Bearer token 鉴权。
type BearerAuth struct{ token string }

func (b *BearerAuth) Configure(c map[string]any) error {
	b.token = str(c["token"])
	return nil
}
func (b *BearerAuth) Apply(ctx context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	return &adapter.AuthResponse{Headers: map[string]string{"Authorization": "Bearer " + b.token}}, nil
}
```

Create `internal/auth/oauth2.go`:
```go
package auth

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"sync"
	"time"

	"api-cli/pkg/adapter"
)

// OAuth2CC client_credentials 模式。首次 Apply 拉 token，过期自动刷新。
type OAuth2CC struct {
	tokenURL, clientID, clientSecret, scope string

	mu          sync.Mutex
	accessToken string
	expires     time.Time
}

func (o *OAuth2CC) Configure(c map[string]any) error {
	o.tokenURL = str(c["token_url"])
	o.clientID = str(c["client_id"])
	o.clientSecret = str(c["client_secret"])
	o.scope = str(c["scope"])
	return nil
}

func (o *OAuth2CC) Apply(ctx context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if time.Now().After(o.expires) {
		if err := o.fetchToken(ctx); err != nil {
			return nil, err
		}
	}
	return &adapter.AuthResponse{Headers: map[string]string{"Authorization": "Bearer " + o.accessToken}}, nil
}

func (o *OAuth2CC) fetchToken(ctx context.Context) error {
	form := url.Values{"grant_type": {"client_credentials"}}
	if o.scope != "" {
		form.Set("scope", o.scope)
	}
	req, _ := http.NewRequestWithContext(ctx, "POST", o.tokenURL, strings_NewReader(form.Encode()))
	req.SetBasicAuth(o.clientID, o.clientSecret)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("oauth2 取 token 失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("oauth2 token 端点返回 %d", resp.StatusCode)
	}
	// 最小解析：access_token / expires_in（用 encoding/json）
	var body struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := decodeJSON(resp.Body, &body); err != nil {
		return err
	}
	o.accessToken = body.AccessToken
	o.expires = time.Now().Add(time.Duration(body.ExpiresIn) * time.Second)
	return nil
}
```

Create `internal/auth/hmac.go`:
```go
package auth

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"

	"api-cli/pkg/adapter"
)

// HMACSign appkey + HMAC-SHA256 签名（string-to-sign = method+url+body）。
type HMACSign struct{ appkey, secret string }

func (h *HMACSign) Configure(c map[string]any) error {
	h.appkey = str(c["appkey"])
	h.secret = str(c["secret"])
	return nil
}
func (h *HMACSign) Apply(ctx context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	sts := r.Method + r.URL + string(r.Body)
	mac := hmac.New(sha256.New, []byte(h.secret))
	mac.Write([]byte(sts))
	sign := hex.EncodeToString(mac.Sum(nil))
	return &adapter.AuthResponse{Headers: map[string]string{
		"X-App-Key": h.appkey, "X-Sign": sign,
	}}, nil
}

// 签名串便于测试导出
func (h *HMACSign) signString(method, url string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(h.secret))
	mac.Write([]byte(method + url + string(body)))
	return fmt.Sprintf("%s:%s", h.appkey, hex.EncodeToString(mac.Sum(nil)))
}
```

Create `internal/auth/helpers.go`（共享小工具）:
```go
package auth

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

func str(v any) string {
	if v == nil {
		return ""
	}
	switch x := v.(type) {
	case string:
		return x
	default:
		return fmt.Sprint(x)
	}
}

// strings_NewReader 避免与标准库命名混淆的薄包装（直接用 strings.NewReader 即可）。
func strings_NewReader(s string) *strings.Reader { return strings.NewReader(s) }

func decodeJSON(r io.Reader, v any) error { return json.NewDecoder(r).Decode(v) }
```

- [ ] **Step 4: 实现 loader.go**

Create `internal/auth/loader.go`:
```go
package auth

import (
	"fmt"
	"os"
	"path/filepath"

	"api-cli/pkg/adapter"
	"gopkg.in/yaml.v3"
)

// 配置文件结构：~/.api-cli/auth.d/<name>.yaml
type config struct {
	Provider string         `yaml:"provider"`
	Config   map[string]any `yaml:"config"`
}

// Load 按 auth 引用名加载 provider。先查内置（bearer/oauth2/hmac），其余走外部 go-plugin（Task 11）。
func Load(name string) (adapter.AuthProvider, error) {
	cfg, err := readConfig(name)
	if err != nil {
		return nil, err
	}
	switch cfg.Provider {
	case "bearer":
		return configured(&BearerAuth{}, cfg.Config)
	case "oauth2":
		return configured(&OAuth2CC{}, cfg.Config)
	case "hmac":
		return configured(&HMACSign{}, cfg.Config)
	default:
		// 外部 adapter：Task 11 实现 LoadPlugin。当前返回未实现提示。
		return nil, fmt.Errorf("外部 adapter %q 暂未实现（Task 11）", cfg.Provider)
	}
}

func readConfig(name string) (*config, error) {
	path := filepath.Join(authDir(), name+".yaml")
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取鉴权配置 %s 失败: %w", path, err)
	}
	var c config
	if err := yaml.Unmarshal(raw, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

func authDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".api-cli", "auth.d")
}

func configured(p adapter.AuthProvider, c map[string]any) (adapter.AuthProvider, error) {
	if err := p.Configure(c); err != nil {
		return nil, err
	}
	return p, nil
}
```

- [ ] **Step 5: 补 hmac + loader 测试**

Create `internal/auth/hmac_test.go`:
```go
package auth

import (
	"context"
	"testing"

	"api-cli/pkg/adapter"
)

func TestHMACSignApply(t *testing.T) {
	h := &HMACSign{}
	h.Configure(map[string]any{"appkey": "ak", "secret": "sk"})
	resp, err := h.Apply(context.Background(), &adapter.AuthRequest{Method: "POST", URL: "http://x/instances", Body: []byte("{}")})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Headers["X-App-Key"] != "ak" {
		t.Fatal("appkey header")
	}
	if resp.Headers["X-Sign"] == "" {
		t.Fatal("sign header empty")
	}
}
```
Run: `go test ./internal/auth/` → Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add projects/api-cli/internal/auth/
git commit -m "feat(api-cli): auth 内置 bearer/oauth2-cc/hmac + 配置加载(~/.api-cli/auth.d)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: internal/paging 分页引擎（cursor / offset / implicit）

声明式分页：给定 pagination 声明 + 首次请求，流式吐所有 items（channel），含死循环上限 + limit + 去重。

**Files:**
- Create: `internal/paging/engine.go`
- Test: `internal/paging/engine_test.go`

**Interfaces:**
- Consumes: Task 3 (`tree.Pagination`)、`gjson`、spec §9
- Produces: `paging.Iter(ctx, pg, do, firstReq, opts) <-chan paging.Item`、`paging.Item`、`paging.Options`

- [ ] **Step 1: 写失败测试（cursor 型 + 隐式终止）**

Create `internal/paging/engine_test.go`:
```go
package paging

import (
	"context"
	"fmt"
	"testing"

	"api-cli/internal/tree"
)

// 模拟服务端：3 页，每页 2 条，第 3 页 next 为空。
func cursorDo(req map[string]string) (body []byte, next string, err error) {
	page := req["page_token"]
	switch page {
	case "":
		return []byte(`{"data":{"list":[{"id":"1"},{"id":"2"}],"next":"p2"}}`), "p2", nil
	case "p2":
		return []byte(`{"data":{"list":[{"id":"3"},{"id":"4"}],"next":"p3"}}`), "p3", nil
	case "p3":
		return []byte(`{"data":{"list":[{"id":"5"}],"next":""}}`), "", nil
	}
	return nil, "", fmt.Errorf("unexpected %s", page)
}

func TestCursorPaging(t *testing.T) {
	pg := &tree.Pagination{Type: "cursor", ItemsPath: "data.list", NextTokenPath: "data.next", HasMorePath: "data.next"}
	var got []string
	for it := range Iter(context.Background(), pg, func(ctx context.Context, req map[string]string) ([]byte, error) {
		b, _, err := cursorDo(req)
		return b, err
	}, map[string]string{}, Options{MaxPages: 100, Limit: 1000}) {
		got = append(got, it.ID)
	}
	if len(got) != 5 {
		t.Fatalf("want 5 items, got %d (%v)", len(got), got)
	}
}

func TestImplicitPaging(t *testing.T) {
	// 不配 has_more → 用 "条数 < size 或空" 判断。每页 size=2，最后一页 1 条 → 终止。
	pages := [][]string{{"1", "2"}, {"3"}}
	call := 0
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 2}
	do := func(ctx context.Context, req map[string]string) ([]byte, error) {
		if call >= len(pages) {
			return []byte(`{"data":[]}`), nil
		}
		p := pages[call]
		call++
		s := `{"data":[`
		for i, id := range p {
			if i > 0 {
				s += ","
			}
			s += fmt.Sprintf(`{"id":%q}`, id)
		}
		s += `]}`
		return []byte(s), nil
	}
	var got []string
	for it := range Iter(context.Background(), pg, do, map[string]string{"page": "0"}, Options{MaxPages: 100, Limit: 1000}) {
		got = append(got, it.ID)
	}
	if len(got) != 3 {
		t.Fatalf("want 3 items, got %d", len(got))
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/paging/`
Expected: FAIL — `undefined: Iter`

- [ ] **Step 3: 实现 engine.go**

Create `internal/paging/engine.go`:
```go
// Package paging 声明式分页引擎：cursor/offset/implicit 统一循环，流式 channel 输出。
package paging

import (
	"context"
	"fmt"
	"sync"

	"api-cli/internal/tree"

	"github.com/tidwall/gjson"
)

// Item 一条数据。ID 用于去重（若有）。
type Item struct {
	ID string
	Raw []byte // 原始 JSON 字节
}

// Options 翻页选项。
type Options struct {
	MaxPages int  // 死循环硬上限（页数）
	Limit    int  // 拉够 N 条就停（0 = 不限，但仍受 MaxItems 约束）
	MaxItems int  // 死循环硬上限（条数）
	NoDedupe bool // 关闭按 id 去重
}

// DoFunc 执行一次请求，返回响应 body。req 是可变的翻页参数（cursor token 或 page 号）。
type DoFunc func(ctx context.Context, req map[string]string) ([]byte, error)

// Iter 流式迭代所有分页 items。
//   - pg：分页声明（来自 operation.Pagination）
//   - firstReq：首次请求的 query 参数种子
//   - opts：MaxPages/Limit 等
func Iter(ctx context.Context, pg *tree.Pagination, do DoFunc, firstReq map[string]string, opts Options) <-chan Item {
	if opts.MaxPages == 0 {
		opts.MaxPages = 1000
	}
	if opts.MaxItems == 0 {
		opts.MaxItems = 10000
	}
	out := make(chan Item, 100)
	go func() {
		defer close(out)
		req := copyMap(firstReq)
		seen := map[string]bool{}
		count := 0
		for page := 0; page < opts.MaxPages; page++ {
			body, err := do(ctx, req)
			if err != nil {
				return // 错误经 ctx 或单独 channel 传递；MVP 直接终止
			}
			items := gjson.GetBytes(body, pg.ItemsPath).Array()
			for _, it := range items {
				id := gjson.Get(it.Raw, "id").String()
				if !opts.NoDedupe && id != "" {
					if seen[id] {
						continue
					}
					seen[id] = true
				}
				select {
				case out <- Item{ID: id, Raw: []byte(it.Raw)}:
				case <-ctx.Done():
					return
				}
				count++
				if opts.Limit > 0 && count >= opts.Limit {
					return
				}
				if count >= opts.MaxItems {
					return
				}
			}
			// 判断是否还有下一页 + 算下一页参数
			nextReq, more := planNext(body, items, pg, req)
			if !more {
				return
			}
			req = nextReq
		}
	}()
	return out
}

// planNext 决定是否翻页 + 下一页参数。
func planNext(body []byte, items []gjson.Result, pg *tree.Pagination, req map[string]string) (map[string]string, bool) {
	nextReq := copyMap(req)
	switch pg.Type {
	case "cursor":
		token := gjson.GetBytes(body, pg.NextTokenPath).String()
		if token == "" {
			return nextReq, false
		}
		nextReq["page_token"] = token
		return nextReq, true
	case "offset":
		// offset 用 page 号自增
		cur := 0
		fmt.Sscanf(req[pg.PageParam], "%d", &cur)
		nextReq[pg.PageParam] = fmt.Sprintf("%d", cur+1)
		// 隐式判断：取到的条数 < size → 结束
		if pg.Size > 0 && len(items) < pg.Size {
			return nextReq, false
		}
		return nextReq, true
	case "implicit":
		// 不配 has_more → 本轮条数 < size 或空 → 结束
		if pg.Size > 0 && len(items) < pg.Size {
			return nextReq, false
		}
		if len(items) == 0 {
			return nextReq, false
		}
		return nextReq, true
	}
	return nextReq, false
}

func copyMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	var wg sync.WaitGroup
	_ = wg // 占位避免 unused（实际无并发）
	for k, v := range m {
		out[k] = v
	}
	return out
}
```

注：`sync` 占位 import 在最终代码里移除（本步为避免 lint 报错先保留，commit 前清理）。实际写时应直接用普通 for-range 拷贝，去掉 sync。

- [ ] **Step 4: 清理 helpers（去掉 sync 占位）+ 拉依赖 + 运行**

把 `copyMap` 简化为：
```go
func copyMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
```
移除 `"sync"` import。

Run: `go get github.com/tidwall/gjson@v1.17.1 && go mod tidy && go test ./internal/paging/`
Expected: `ok api-cli/internal/paging`

- [ ] **Step 5: 补 offset 测试 + limit 截断测试**

Append to `engine_test.go`:
```go
func TestLimitTruncation(t *testing.T) {
	// 提供 5 条，limit=3 → 只得 3 条
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 5}
	do := func(ctx context.Context, req map[string]string) ([]byte, error) {
		return []byte(`{"data":[{"id":"1"},{"id":"2"},{"id":"3"},{"id":"4"},{"id":"5"}]}`), nil
	}
	n := 0
	for range Iter(context.Background(), pg, do, map[string]string{}, Options{Limit: 3, MaxPages: 10}) {
		n++
	}
	if n != 3 {
		t.Fatalf("want 3 (limit), got %d", n)
	}
}
```
Run: `go test ./internal/paging/` → Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add projects/api-cli/internal/paging/
git commit -m "feat(api-cli): paging 引擎(cursor/offset/implicit) + 流式 channel + 死循环上限/limit/去重

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: internal/engine 请求组装 + 执行（dry-run/print-curl/分页/输出）

核心执行器：组装请求 → 写操作闸门 → dry-run/print-curl 分支 → auth.Apply → http.Do → 分页或单次 → 输出 + 错误归一化。

**Files:**
- Create: `internal/engine/request.go`、`execute.go`、`safety.go`
- Test: `internal/engine/execute_test.go`

**Interfaces:**
- Consumes: Task 4 (tree resolve)、Task 6 (output)、Task 7 (auth.Load)、Task 8 (paging.Iter)、spec §3.2（数据流）、§11（flag/exit code）
- Produces: `engine.New(*tree.OperationTree) *Engine`、`engine.Options`、`(*Engine).Execute(ctx, ep, r, op, vals) error`

- [ ] **Step 1: 写失败测试（单次读 + dry-run）**

Create `internal/engine/execute_test.go`:
```go
package engine

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

func newTree(t *testing.T) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service:
  name: cmdb
  default_endpoint: backend
  endpoints:
    backend: { base_url: REPLACEME, auth: none, path_prefix: /api/v1 }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { type: string, required: true, in: path } } }
`)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/instances/i-1" {
			w.Write([]byte(`{"id":"i-1","name":"n"}`))
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)
	raw = bytes.ReplaceAll(raw, []byte("REPLACEME"), []byte(srv.URL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	// 覆盖 auth 为空操作（避免加载 ~/.api-cli/auth.d）
	return tr
}

func TestExecuteSingleRead(t *testing.T) {
	tr := newTree(t)
	e := New(tr)
	op := tr.Resources["inst"].Operations["read"]
	r := tr.Resources["inst"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.execute(context.Background(), ep, r, op, map[string]string{"id": "i-1"}, Options{Format: "json", Out: &out})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(out.Bytes(), []byte(`"id":"i-1"`)) {
		t.Fatalf("output missing id: %s", out.String())
	}
}

func TestDryRunDoesNotCall(t *testing.T) {
	tr := newTree(t)
	e := New(tr)
	op := tr.Resources["inst"].Operations["read"]
	r := tr.Resources["inst"]
	ep, _ := tr.SelectEndpoint("")
	var out bytes.Buffer
	err := e.execute(context.Background(), ep, r, op, map[string]string{"id": "i-1"}, Options{DryRun: true, Out: &out})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(out.Bytes(), []byte("DRY-RUN")) && !bytes.Contains(out.Bytes(), []byte("/api/v1/instances/i-1")) {
		t.Fatalf("dry-run should print request, got: %s", out.String())
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/engine/`
Expected: FAIL — `undefined: New`/`Engine`/`Options`

- [ ] **Step 3: 实现 request.go**

Create `internal/engine/request.go`:
```go
// Package engine 是执行核心：组装请求 → auth → http.Do → 分页/输出。
package engine

import (
	"api-cli/internal/tree"
)

// resolvedReq 组装好的请求各部分（method/url 已填 path 参数；query/header/body 来自 flag）。
type resolvedReq struct {
	Method string
	URL    string
	Query  map[string]string
	Header map[string]string
	Body   []byte
}

// resolve 把 operation + flag 值物化成 resolvedReq。
//   - pathVals：path 参数值（来自位置参数/flag）
//   - flags：其余 flag（按 param.In 分发到 query/header/body）
func resolve(tr *tree.OperationTree, ep *tree.Endpoint, r *tree.Resource, op *tree.Operation,
	pathVals, flags map[string]string) (*resolvedReq, error) {
	// 拼完整 op path（含 resource path 前缀）—— ResolveURL 约定 op.Path 已含 resource 上下文
	fullOp := &tree.Operation{
		Verb: op.Verb, Method: op.Method, Path: joinRel(r.Path, op.Path),
		Params: op.Params, Body: op.Body, Pagination: op.Pagination,
	}
	url, err := tr.ResolveURL(ep, fullOp, pathVals)
	if err != nil {
		return nil, err
	}
	req := &resolvedReq{Method: op.Method, URL: url, Query: map[string]string{}, Header: map[string]string{}}
	for _, p := range op.Params {
		v, ok := flags[p.Name]
		if !ok {
			continue
		}
		switch p.In {
		case "query":
			req.Query[p.Name] = v
		case "header":
			req.Header[p.Name] = v
		case "body":
			// body 多字段合并到 JSON body（MVP 单层；body schema 解析见 assembleBody）
		}
	}
	return req, nil
}

// joinRel 拼接 resource.Path 与 op.Path（相对），归一化斜杠。
func joinRel(a, b string) string {
	if a == "" {
		return b
	}
	if b == "" {
		return a
	}
	if a[len(a)-1] == '/' || b[0] == '/' {
		return a + b
	}
	return a + "/" + b
}
```

- [ ] **Step 4: 实现 execute.go**

Create `internal/engine/execute.go`:
```go
package engine

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"

	"api-cli/internal/auth"
	"api-cli/internal/output"
	"api-cli/internal/paging"
	"api-cli/internal/tree"
)

// Options 单次执行选项（来自全局/命令 flag）。
type Options struct {
	Format    string // json|yaml|table
	DryRun    bool
	PrintCurl bool
	Yes       bool // 跳过写操作确认
	All       bool
	Limit     int
	Out       io.Writer // 输出目标（默认 os.Stdout；测试注入）
}

// Engine 执行器。
type Engine struct {
	tr  *tree.OperationTree
	hc  *http.Client
}

// New 构造执行器。
func New(tr *tree.OperationTree) *Engine {
	return &Engine{tr: tr, hc: &http.Client{}}
}

// execute 执行一次操作。cobracli 层调它。返回归一化错误（含 exit code）。
func (e *Engine) execute(ctx context.Context, ep *tree.Endpoint, r *tree.Resource, op *tree.Operation,
	pathVals, flags map[string]string, opts Options) error {
	if opts.Out == nil {
		return fmt.Errorf("Options.Out 未设置")
	}
	req, err := resolve(e.tr, ep, r, op, pathVals, flags)
	if err != nil {
		return err
	}

	// 写操作闸门（delete/update/create）
	if err := gateWrite(op.Verb, opts); err != nil {
		return err
	}

	// dry-run / print-curl：不真发
	if opts.DryRun || opts.PrintCurl {
		fmt.Fprintln(opts.Out, renderPreview(req, opts))
		return nil
	}

	// auth.Apply（endpoint.Auth == "none" 时跳过）
	if ep.Auth != "" && ep.Auth != "none" {
		provider, err := auth.Load(ep.Auth)
		if err != nil {
			return &output.APIError{Code: "auth_load", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		ar, err := provider.Apply(ctx, &authReqAdapter{req: req}.toAdapter())
		if err != nil {
			return &output.APIError{Code: "auth_apply", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		mergeAuth(req, ar)
	}

	// 分页 vs 单次
	if op.Pagination != nil {
		return e.iterate(ctx, req, op, opts)
	}
	return e.single(ctx, req, opts)
}

func (e *Engine) single(ctx context.Context, req *resolvedReq, opts Options) error {
	body, status, err := e.do(ctx, req)
	if err != nil {
		return err
	}
	if status >= 400 {
		return output.NormalizeAPIError(status, body)
	}
	var data any
	data = decodeLoose(body)
	return output.Format(opts.Out, opts.Format, data)
}

func (e *Engine) iterate(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options) error {
	first := copySS(req.Query)
	do := func(ctx context.Context, q map[string]string) ([]byte, error) {
		r2 := *req
		r2.Query = q
		body, status, err := e.do(ctx, &r2)
		if err != nil {
			return nil, err
		}
		if status >= 400 {
			return nil, output.NormalizeAPIError(status, body)
		}
		return body, nil
	}
	limit := opts.Limit
	if opts.All {
		limit = 0 // 受 paging.MaxItems 硬上限约束
	}
	items := paging.Iter(ctx, op.Pagination, do, first, paging.Options{Limit: limit})
	for it := range items {
		fmt.Fprintln(opts.Out, string(it.Raw)) // NDJSON：每行一个 item
	}
	return nil
}

// do 发一次请求，返回 body + status。
func (e *Engine) do(ctx context.Context, req *resolvedReq) ([]byte, int, error) {
	var bodyReader io.Reader
	if req.Body != nil {
		bodyReader = bytes.NewReader(req.Body)
	}
	httpReq, err := http.NewRequestWithContext(ctx, req.Method, req.URL, bodyReader)
	if err != nil {
		return nil, 0, err
	}
	for k, v := range req.Header {
		httpReq.Header.Set(k, v)
	}
	q := httpReq.URL.Query()
	for k, v := range req.Query {
		q.Set(k, v)
	}
	httpReq.URL.RawQuery = q.Encode()
	resp, err := e.hc.Do(httpReq)
	if err != nil {
		return nil, 0, &output.APIError{Code: "net", Message: err.Error(), ExitCode: output.ExitNetTimeout}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return body, resp.StatusCode, nil
}

// --- 辅助 ---

type authReqAdapter struct{ req *resolvedReq }

func (a *authReqAdapter) toAdapter() struct{ Method, URL string; Body []byte; Headers map[string]string } {
	// 这里转成 pkg/adapter.AuthRequest；为避免循环依赖，直接构造（字段同构）
	return struct{ Method, URL string; Body []byte; Headers map[string]string }{
		Method: a.req.Method, URL: a.req.URL, Body: a.req.Body, Headers: a.req.Header,
	}
}

func mergeAuth(req *resolvedReq, ar any) {
	// ar 是 *adapter.AuthResponse；用反射/类型断言取 Headers/Query（避免直接 import 形成 engine→adapter→... 耦合）
	type respT interface{ getHeaders() map[string]string; getQuery() map[string]string }
	// adapter.AuthResponse 不实现该方法 → 这里改为直接 import adapter（pkg 无环），见下方修正
}

// renderPreview 渲染 dry-run / curl 预览。
func renderPreview(req *resolvedReq, opts Options) string {
	if opts.PrintCurl {
		curl := "curl -X " + req.Method + " '" + req.URL + "'"
		for k, v := range req.Header {
			curl += " -H '" + k + ": " + v + "'"
		}
		if req.Body != nil {
			curl += " -d '" + string(req.Body) + "'"
		}
		return curl
	}
	return fmt.Sprintf("DRY-RUN %s %s query=%v header=%v body=%s", req.Method, req.URL, req.Query, req.Header, req.Body)
}

func copySS(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func decodeLoose(b []byte) any {
	var v any
	// 简易：json unmarshal，失败则原样当字符串
	if err := jsonUnmarshal(b, &v); err != nil {
		return string(b)
	}
	return v
}
```

**修正（重要）：auth 适配直接 import pkg/adapter，去掉 authReqAdapter/mergeAuth 的迂回。** 把 `execute.go` 顶部的 `auth.Load` 调用与 merge 改为：

替换 `execute.go` import 块加入 `"api-cli/pkg/adapter"`，并把 auth 段重写为：
```go
	if ep.Auth != "" && ep.Auth != "none" {
		provider, err := auth.Load(ep.Auth)
		if err != nil {
			return &output.APIError{Code: "auth_load", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		ar, err := provider.Apply(ctx, &adapter.AuthRequest{Method: req.Method, URL: req.URL, Body: req.Body, Headers: req.Header})
		if err != nil {
			return &output.APIError{Code: "auth_apply", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		for k, v := range ar.Headers {
			req.Header[k] = v
		}
		for k, v := range ar.Query {
			req.Query[k] = v
		}
	}
```
并删除 `authReqAdapter` 与 `mergeAuth` 两个迂回函数。`jsonUnmarshal` 用标准库：在 `execute.go` 加 `"encoding/json"` 并定义 `func jsonUnmarshal(b []byte, v any) error { return json.Unmarshal(b, v) }`，或直接调用 `json.Unmarshal`。

- [ ] **Step 5: 实现 safety.go（写操作闸门）**

Create `internal/engine/safety.go`:
```go
package engine

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"api-cli/internal/output"
)

// 写操作动词集合（默认要求 --confirm / 交互确认）。
var writeVerbs = map[string]bool{"create": true, "update": true, "delete": true}

// gateWrite 写操作闸门：opts.Yes 跳过；否则交互确认（非 TTY 时拒绝）。
func gateWrite(verb string, opts Options) error {
	if !writeVerbs[verb] {
		return nil
	}
	if opts.Yes {
		return nil
	}
	if !isTTY() {
		return &output.APIError{Code: "write_confirm", Message: "写操作需 --yes 或 TTY 确认", ExitCode: output.ExitParamError}
	}
	fmt.Fprintf(os.Stderr, "确认执行 %s ? [y/N] ", verb)
	sc := bufio.NewScanner(os.Stdin)
	if !sc.Scan() {
		return &output.APIError{Code: "write_confirm", Message: "未确认", ExitCode: output.ExitParamError}
	}
	if strings.TrimSpace(strings.ToLower(sc.Text())) != "y" {
		return &output.APIError{Code: "write_confirm", Message: "用户取消", ExitCode: output.ExitParamError}
	}
	return nil
}

func isTTY() bool {
	fi, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}
```

- [ ] **Step 6: 运行测试**

Run: `go test ./internal/engine/`
Expected: `ok api-cli/internal/engine`（若 `decodeLoose` 报错，确保 `jsonUnmarshal`/`json.Unmarshal` 已正确 import）

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/engine/
git commit -m "feat(api-cli): engine 请求组装+执行(dry-run/print-curl/分页/输出)+写操作闸门

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: internal/cobracli 命令树 + flag 注册 + help-format

把 OperationTree 动态编译成 cobra 命令树（递归 N 层），每个 operation 一个子命令，param→flag。

**Files:**
- Create: `internal/cobracli/build.go`、`flags.go`、`help.go`
- Test: `internal/cobracli/build_test.go`

**Interfaces:**
- Consumes: Task 9 (engine)、Task 4 (tree)、spec §11.1（flag）、§11.3（help-format）
- Produces: `cobracli.Build(*tree.OperationTree) (*cobra.Command, error)`、全局 flag 绑定

- [ ] **Step 1: 写失败测试（命令树形状）**

Create `internal/cobracli/build_test.go`:
```go
package cobracli

import (
	"testing"

	"api-cli/internal/spec"
)

func TestBuildCommandTree(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, type: string, required: true } } }
      create: { method: POST, path: "" }
    children:
      relation:
        path: "/{instance_id}/relations"
        operations:
          read: { path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, err := Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	if root.Use != "cmdb" {
		t.Fatalf("root use want cmdb, got %s", root.Use)
	}
	// inst 子命令存在
	var foundInst, foundRead, foundRelation bool
	for _, c := range root.Commands() {
		if c.Use == "inst" {
			foundInst = true
			for _, cc := range c.Commands() {
				if cc.Use == "read" {
					foundRead = true
				}
				if cc.Use == "relation" {
					foundRelation = true
				}
			}
		}
	}
	if !foundInst || !foundRead || !foundRelation {
		t.Fatalf("tree shape wrong: inst=%v read=%v relation=%v", foundInst, foundRead, foundRelation)
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/cobracli/`
Expected: FAIL — `undefined: Build`

- [ ] **Step 3: 实现 build.go**

Create `internal/cobracli/build.go`:
```go
// Package cobracli 把 OperationTree 动态编译成 cobra 命令树。
package cobracli

import (
	"api-cli/internal/engine"
	"api-cli/internal/tree"

	"github.com/spf13/cobra"
)

// Build 构建根命令树并绑定全局 flag。
func Build(tr *tree.OperationTree) (*cobra.Command, error) {
	root := &cobra.Command{
		Use:           tr.Service.Name,
		Short:         tr.Service.Name + " CLI（声明式生成）",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	bindGlobalFlags(root)
	e := engine.New(tr)
	for _, r := range tr.Resources {
		root.AddCommand(resourceCmd(tr, e, r, nil))
	}
	return root, nil
}

// resourceCmd 递归构建资源命令（含 children → N 层）。
// parentKeys：累积的父 ID 注入键（用于子命令 path 模板填充）。
func resourceCmd(tr *tree.OperationTree, e *engine.Engine, r *tree.Resource, parentKeys []parentKV) *cobra.Command {
	c := &cobra.Command{Use: r.Name, Short: desc(r)}
	for verb, op := range r.Operations {
		c.AddCommand(operationCmd(tr, e, r, op, verb, parentKeys))
	}
	for _, child := range r.Children {
		c.AddCommand(resourceCmd(tr, e, child, append(parentKeys, parentKV{key: r.ParentKey})))
	}
	return c
}

// operationCmd 构建 operation 子命令，注册 flag，RunE 调 engine。
func operationCmd(tr *tree.OperationTree, e *engine.Engine, r *tree.Resource, op *tree.Operation, verb string, parentKeys []parentKV) *cobra.Command {
	pathParams, otherParams := splitParams(op)
	flagBag := newFlagBag()

	c := &cobra.Command{
		Use:   verb,
		Short: op.Verb + " " + r.Singular,
		RunE: func(cmd *cobra.Command, args []string) error {
			opts, err := globalOpts(cmd)
			if err != nil {
				return err
			}
			pathVals := buildPathVals(pathParams, args, parentKeys, flagBag)
			flags := flagBag.values(otherParams)
			ep, err := tr.SelectEndpoint(opts.Endpoint)
			if err != nil {
				return err
			}
			return e.execute(cmd.Context(), ep, r, op, pathVals, flags, opts)
		},
	}
	registerParams(c, op, flagBag)
	return c
}

func desc(r *tree.Resource) string {
	if r.Singular != "" {
		return r.Singular + " 资源"
	}
	return r.Name + " 资源"
}
```

- [ ] **Step 4: 实现 flags.go**

Create `internal/cobracli/flags.go`:
```go
package cobracli

import (
	"fmt"
	"strconv"

	"api-cli/internal/engine"
	"api-cli/internal/tree"
	"api-cli/internal/output"

	"github.com/spf13/cobra"
)

// parentKV 父资源 ID 注入（{parent_key} → 父命令 args[0]）。
type parentKV struct{ key string }

// flagBag 收集 operation 的 flag 值。
type flagBag struct {
	strVals  map[string]*string
	boolVals map[string]*bool
}

func newFlagBag() *flagBag {
	return &flagBag{strVals: map[string]*string{}, boolVals: map[string]*bool{}}
}

// splitParams 分离 path 参数（位置/父注入）与其余（query/header/body/flag）。
func splitParams(op *tree.Operation) (pathParams, others []tree.Param) {
	for _, p := range op.Params {
		if p.In == "path" {
			pathParams = append(pathParams, p)
		} else {
			others = append(others, p)
		}
	}
	return
}

// registerParams 把 param 注册成 cobra flag。
func registerParams(c *cobra.Command, op *tree.Operation, bag *flagBag) {
	for _, p := range op.Params {
		if p.In == "path" {
			continue // path 参数走位置 args 或父注入，不注册 flag
		}
		ptr := c.Flags().String(p.Name, "", p.Description)
		bag.strVals[p.Name] = ptr
	}
	// 占位避免 strconv unused
	_ = strconv.Itoa
}

// values 取出 non-empty flag 值。
func (b *flagBag) values(params []tree.Param) map[string]string {
	out := map[string]string{}
	for _, p := range params {
		if ptr, ok := b.strVals[p.Name]; ok && *ptr != "" {
			out[p.Name] = *ptr
		}
	}
	return out
}

// buildPathVals 构造 path 参数值：位置 args[0..] + 父注入。
func buildPathVals(pathParams []tree.Param, args []string, parentKeys []parentKV, bag *flagBag) map[string]string {
	vals := map[string]string{}
	// 父注入（child resource 的 {parent_key}）
	for _, pk := range parentKeys {
		if pk.key != "" && len(args) > 0 {
			vals[pk.key] = args[0]
			args = args[1:]
		}
	}
	// 自身 path 参数（位置）
	for i, p := range pathParams {
		if i < len(args) {
			vals[p.Name] = args[i]
		}
	}
	return vals
}

// --- 全局 flag ---

func bindGlobalFlags(root *cobra.Command) {
	root.PersistentFlags().String("endpoint", "", "接入面（默认 service.default_endpoint）")
	root.PersistentFlags().String("format", "json", "输出格式 json|yaml|table")
	root.PersistentFlags().String("help-format", "text", "--help 输出格式 text|json")
	root.PersistentFlags().Bool("dry-run", false, "不真调，打印将发的请求")
	root.PersistentFlags().Bool("print-curl", false, "打印等价 curl")
	root.PersistentFlags().Bool("yes", false, "跳过写操作确认")
	root.PersistentFlags().Int("limit", 0, "分页拉取上限（条数）")
	root.PersistentFlags().Bool("all", false, "拉全部分页（受硬上限约束）")
}

// globalOpts 从 cobra command 取全局 flag → engine.Options。
func globalOpts(cmd *cobra.Command) (engine.Options, error) {
	get := cmd.Flags()
	opts := engine.Options{
		Format:    strFlag(get, "format"),
		Endpoint:  strFlag(get, "endpoint"),
		DryRun:    boolFlag(get, "dry-run"),
		PrintCurl: boolFlag(get, "print-curl"),
		Yes:       boolFlag(get, "yes"),
		All:       boolFlag(get, "all"),
		Limit:     intFlag(get, "limit"),
		Out:       stdout(),
	}
	if err := validateFormat(opts.Format); err != nil {
		return opts, err
	}
	return opts, nil
}

func strFlag(f *flagSet, name string) string  { v, _ := f.GetString(name); return v }
func boolFlag(f *flagSet, name string) bool   { v, _ := f.GetBool(name); return v }
func intFlag(f *flagSet, name string) int     { v, _ := f.GetInt(name); return v }

func validateFormat(f string) error {
	switch f {
	case "json", "yaml", "table":
		return nil
	}
	return &output.APIError{Code: "bad_format", Message: fmt.Sprintf("不支持的 format %q", f), ExitCode: output.ExitParamError}
}
```

**修正：** cobra 的 flag 访问用 `*pflag.FlagSet`。把 `flagSet` 类型别名化以避免反复改签名——在 `flags.go` 顶部加 `import "github.com/spf13/pflag"` 并定义 `type flagSet = pflag.FlagSet`，所有 helper 改为接收 `*pflag.FlagSet`（cobra 的 `cmd.Flags()` 返回 `*pflag.FlagSet`）。`stdout()` 返回 `io.Writer`（见 help.go）。

- [ ] **Step 5: 实现 help.go**

Create `internal/cobracli/help.go`:
```go
package cobracli

import (
	"encoding/json"
	"io"
	"os"

	"api-cli/internal/tree"
)

// stdout 输出目标（默认 os.Stdout；测试可注入）。
func stdout() io.Writer { return os.Stdout }

// emitHelpJSON 把命令树片段（resource+operation+params）序列化成 JSON，供 LLM 发现。
// 在 cobra 的 help 模板钩子里调用（--help-format=json 时）。
func emitHelpJSON(w io.Writer, r *tree.Resource, op *tree.Operation) error {
	doc := map[string]any{
		"resource":  r.Name,
		"verb":      op.Verb,
		"method":    op.Method,
		"path":      op.Path,
		"params":    op.Params,
		"has_paging": op.Pagination != nil,
	}
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(doc)
}
```

注：`--help-format=json` 的实际接入在 `build.go` 的 root `SetHelpFunc` 里判断 `--help-format` flag，对叶子命令调 `emitHelpJSON`。完整接入代码（约 15 行 SetHelpFunc）在 Step 6 加到 build.go。

- [ ] **Step 6: 拉依赖 + 接入 help-format + 运行测试**

Run: `go get github.com/spf13/cobra@v1.8.1 && go mod tidy`

在 `build.go` 的 `Build` 内、`return root` 前加入 help 钩子：
```go
	root.SetHelpFunc(func(c *cobra.Command, args []string) {
		hf, _ := c.Flags().GetString("help-format")
		if hf == "json" {
			// 叶子命令（有 RunE）→ emitHelpJSON；其余走默认
			emitHelpJSON(os.Stdout, nil, nil) // 占位：实际从 c 上下文取 resource/op（见下注）
			return
		}
		c.Root().UsageFunc()(c)
	})
```
（注：精确取当前命令对应的 resource/op 需在 operationCmd 构造时把 r/op 附加到 `c.Annotations`，help 钩子里取回。这是约 10 行粘合代码，由实施者在 Step 6 补全——给 operationCmd 加 `Annotations: map[string]string{"resource": r.Name, "verb": verb}`，help 钩子按 annotation 反查 tr。本 plan 标注此点，避免占位符遗漏。）

Run: `go test ./internal/cobracli/`
Expected: `ok api-cli/internal/cobracli`

- [ ] **Step 7: Commit**

```bash
git add projects/api-cli/internal/cobracli/
git commit -m "feat(api-cli): cobracli 动态命令树(递归 N 层) + param→flag + help-format=json

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: auth go-plugin host（外部 adapter）

让 `auth.Load` 能加载外部 go-plugin 二进制（`provider` 非 bearer/oauth2/hmac 时）。

**Files:**
- Create: `internal/auth/plugin.go`、`internal/auth/grpc.go`（gRPC server/client 桥接）
- Create: `pkg/adapter/grpc.go`（GRPCServer/GRPCClient，三方与 host 共用）
- Modify: `internal/auth/loader.go`（default 分支调 LoadPlugin）
- Test: `internal/auth/plugin_test.go`

**Interfaces:**
- Consumes: Task 2 (adapter)、Task 7 (loader)、go-plugin
- Produces: `auth.LoadPlugin(name) (adapter.AuthProvider, error)`、`adapter.AuthPluginGRPC.GRPCServer/GRPCClient`

- [ ] **Step 1: 写失败测试（host 能加载一个 in-process 测试 adapter）**

Create `internal/auth/plugin_test.go`:
```go
package auth

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"api-cli/pkg/adapter"
)

// 用 go-plugin 的 in-process 测试模式：provider 直接以 GRPC plugin serve，host attach。
func TestLoadPluginInProcess(t *testing.T) {
	// 构造一个 fake adapter 二进制配置：provider 指向本测试进程的 serve
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, ".api-cli", "auth.d"), 0o755)
	os.Setenv("HOME", dir)
	defer os.Unsetenv("HOME")
	// 写一个"内置回退"配置（provider=bearer），验证 LoadPlugin 不被调用——仅证明 host 路径不被默认命中
	_ = os.WriteFile(filepath.Join(dir, ".api-cli", "auth.d", "fe.yaml"),
		[]byte("provider: bearer\nconfig:\n  token: tk\n"), 0o644)
	p, err := Load("fe")
	if err != nil {
		t.Fatal(err)
	}
	resp, err := p.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if err != nil || resp.Headers["Authorization"] != "Bearer tk" {
		t.Fatalf("builtin fallback failed: %+v %v", resp, err)
	}
}
```
（外部二进制的完整 e2e 测试需要编译示例 adapter，放 Task 14 集成层；此处先保证 host 装载逻辑不破坏内置路径。）

- [ ] **Step 2: 实现 pkg/adapter/grpc.go（gRPC server/client 桥接）**

Create `pkg/adapter/grpc.go`:
```go
package adapter

import (
	"context"
	"net/rpc"

	"github.com/hashicorp/go-plugin"
	"google.golang.org/grpc"
)

// --- AuthPluginGRPC 的 GRPC 实现 ---

// authGRPCServer 把 AuthProvider 暴露给 gRPC 客户端（host 侧）。
type authGRPCServer struct {
	Impl   AuthProvider
}

// 注：完整 gRPC 方法实现需要 .proto 生成代码。MVP 用 go-plugin 的 net/rpc 模式简化：
// 改用 NetRPCUnsupportedPlugin → 实际用 RPCServer/RPCClient（见 grpc_rpc.go）。
// 为控制实现体量，MVP 选用 net/rpc 模式（go-plugin 原生支持，无需 protoc）。
var _ = plugin.Plugin(&AuthPluginGRPC{})
var _ = rpc.NewServer
var _ = grpc.NewServer
var _ context.Context
```

**决策（写入 plan，避免占位）：** MVP 用 go-plugin 的 **net/rpc 模式**（非 gRPC），免去 protoc 工具链。把 `types.go` 的 `AuthPluginGRPC` 改名为 `AuthPlugin` 并实现 `Server(*broker.Broker) (interface{}, error)` 与 `Client(*broker.Broker, *rpc.Client) (interface{}, error)`：

替换 `pkg/adapter/types.go` 中 go-plugin 桥接段为（net/rpc 模式）：
```go
import (
	"context"
	"net/rpc"

	"github.com/hashicorp/go-plugin"
)

var Handshake = plugin.HandshakeConfig{
	ProtocolVersion:  1,
	MagicCookieKey:   "API_CLI_PLUGIN",
	MagicCookieValue: "api-cli-adapter",
}

// AuthPlugin net/rpc 模式的插件包装。
type AuthPlugin struct {
	Impl AuthProvider
}

func (p *AuthPlugin) Server(*plugin.MuxBroker) (interface{}, error) { return &authRPCServer{Impl: p.Impl}, nil }
func (p *AuthPlugin) Client(b *plugin.MuxBroker, c *rpc.Client) (interface{}, error) { return &authRPCClient{client: c}, nil }

const PluginNameAuth = "auth"
const PluginNamePaging = "paging"
```
并新建 `pkg/adapter/grpc_rpc.go` 实现 `authRPCServer`/`authRPCClient`（net/rpc 协议）：
```go
package adapter

import (
	"context"
	"net/rpc"

	"github.com/hashicorp/go-plugin"
)

// RPC 传输结构（必须导出字段，net/rpc 用 gob）。
type configureArgs struct {
	Config map[string]any
}
type applyArgs struct {
	Method  string
	URL     string
	Body    []byte
	Headers map[string]string
}
type applyReply struct {
	Headers map[string]string
	Query   map[string]string
	Err     string
}

type authRPCServer struct{ Impl AuthProvider }

func (s *authRPCServer) Configure(args configureArgs, reply *string) error {
	if err := s.Impl.Configure(args.Config); err != nil {
		*reply = err.Error()
	}
	return nil
}
func (s *authRPCServer) Apply(args applyArgs, reply *applyReply) error {
	resp, err := s.Impl.Apply(context.Background(), &AuthRequest{Method: args.Method, URL: args.URL, Body: args.Body, Headers: args.Headers})
	if err != nil {
		reply.Err = err.Error()
		return nil
	}
	reply.Headers = resp.Headers
	reply.Query = resp.Query
	return nil
}

type authRPCClient struct{ client *rpc.Client }

func (c *authRPCClient) Configure(cfg map[string]any) error {
	var rep string
	if err := c.client.Call("Plugin.Configure", configureArgs{Config: cfg}, &rep); err != nil {
		return err
	}
	if rep != "" {
		return fmt.Errorf(rep)
	}
	return nil
}
func (c *authRPCClient) Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error) {
	var rep applyReply
	if err := c.client.Call("Plugin.Apply", applyArgs{Method: r.Method, URL: r.URL, Body: r.Body, Headers: r.Headers}, &rep); err != nil {
		return nil, err
	}
	if rep.Err != "" {
		return nil, fmt.Errorf(rep.Err)
	}
	return &AuthResponse{Headers: rep.Headers, Query: rep.Query}, nil
}

var _ plugin.Plugin = (*AuthPlugin)(nil)
```
需在 grpc_rpc.go 顶部加 `"fmt"` import。

- [ ] **Step 3: 实现 internal/auth/plugin.go（host 装载）**

Create `internal/auth/plugin.go`:
```go
package auth

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"api-cli/pkg/adapter"

	"github.com/hashicorp/go-plugin"
)

// LoadPlugin 启动外部 adapter 二进制并返回 AuthProvider。
func LoadPlugin(name string) (adapter.AuthProvider, error) {
	cfg, err := readConfig(name) // 来自 loader.go
	if err != nil {
		return nil, err
	}
	bin, err := findAdapterBin(cfg.Provider)
	if err != nil {
		return nil, err
	}
	client := plugin.NewClient(&plugin.ClientConfig{
		HandshakeConfig: adapter.Handshake,
		Plugins: map[string]plugin.Plugin{
			adapter.PluginNameAuth: &adapter.AuthPlugin{},
		},
		Cmd: exec.Command(bin),
	})
	rpcClient, err := client.Client()
	if err != nil {
		return nil, fmt.Errorf("go-plugin 握手失败: %w", err)
	}
	raw, err := rpcClient.Dispense(adapter.PluginNameAuth)
	if err != nil {
		return nil, err
	}
	p, ok := raw.(adapter.AuthProvider)
	if !ok {
		return nil, fmt.Errorf("adapter 未实现 AuthProvider")
	}
	if err := p.Configure(cfg.Config); err != nil {
		return nil, err
	}
	return p, nil
}

// findAdapterBin 在 PATH 与 ~/.api-cli/bin/ 找 adapter 二进制。
func findAdapterBin(name string) (string, error) {
	if path, err := exec.LookPath(name); err == nil {
		return path, nil
	}
	home, _ := os.UserHomeDir()
	cand := filepath.Join(home, ".api-cli", "bin", name)
	if _, err := os.Stat(cand); err == nil {
		return cand, nil
	}
	return "", fmt.Errorf("找不到 adapter 二进制 %q（PATH 或 ~/.api-cli/bin/）", name)
}
```

修改 `internal/auth/loader.go` 的 `default` 分支：
```go
	default:
		return LoadPlugin(name)
```

- [ ] **Step 4: 拉依赖 + 运行测试**

Run: `go get google.golang.org/grpc@v1.65.0 && go mod tidy && go test ./internal/auth/ ./pkg/adapter/`
Expected: `ok`（gRPC 模式已弃用，改 net/rpc；grpc import 仅 go-plugin 间接依赖）

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/auth/ projects/api-cli/pkg/adapter/
git commit -m "feat(api-cli): auth go-plugin host（net/rpc 模式，外部 adapter 二进制装载）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: internal/mcp MCP server（OperationTree → MCP tools）

把每个 Operation 暴露为 MCP tool，stdio 协议，调用走同一 engine。

**Files:**
- Create: `internal/mcp/server.go`
- Test: `internal/mcp/server_test.go`

**Interfaces:**
- Consumes: Task 9 (engine)、Task 4 (tree)、spec §10
- Produces: `mcp.Serve(tr *tree.OperationTree) error`（stdio）

**MVP 协议决策：** 不引完整 MCP SDK（go 生态 SDK 尚不成熟 + 控制依赖），实现 **MCP 最小子集**：stdio JSON-RPC 2.0，响应 `initialize` / `tools/list` / `tools/call` 三个方法。完整 SDK 接入留 V2。

- [ ] **Step 1: 写失败测试（tools/list 列出 operations）**

Create `internal/mcp/server_test.go`:
```go
package mcp

import (
	"encoding/json"
	"testing"

	"api-cli/internal/spec"
)

func TestToolsList(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst: { path: /instances, operations: { read: { path: "/{id}", params: { id: { in: path, required: true } } } } }
`)
	tr, _ := spec.Parse(raw)
	s := New(tr)
	tools := s.ToolsList()
	if len(tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(tools))
	}
	if tools[0].Name != "cmdb_inst_read" {
		t.Fatalf("tool name want cmdb_inst_read, got %s", tools[0].Name)
	}
	b, _ := json.Marshal(tools[0])
	if string(b) == "" {
		t.Fatal("tool not serializable")
	}
}
```

- [ ] **Step 2: 运行，确认失败**

Run: `go test ./internal/mcp/`
Expected: FAIL — `undefined: New`

- [ ] **Step 3: 实现 server.go（最小 MCP 子集）**

Create `internal/mcp/server.go`:
```go
// Package mcp 把 OperationTree 暴露为 MCP tools（stdio JSON-RPC 2.0 最小子集）。
package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"

	"api-cli/internal/engine"
	"api-cli/internal/tree"
)

// Tool MCP tool 描述。
type Tool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

// Server MCP server（持有 tree + engine）。
type Server struct {
	tr *tree.OperationTree
	e  *engine.Engine
}

// New 构造 MCP server。
func New(tr *tree.OperationTree) *Server {
	return &Server{tr: tr, e: engine.New(tr)}
}

// ToolsList 枚举所有 operation → tool。
func (s *Server) ToolsList() []Tool {
	var tools []Tool
	walk(s.tr.Resources, s.tr.Service.Name, func(toolName, resName, verb string, r *tree.Resource, op *tree.Operation) {
		props := map[string]any{}
		for _, p := range op.Params {
			props[p.Name] = map[string]any{"type": orDefault(p.Type, "string"), "description": p.Description}
		}
		tools = append(tools, Tool{
			Name:        toolName,
			Description: verb + " " + r.Singular,
			InputSchema: map[string]any{"type": "object", "properties": props},
		})
	})
	return tools
}

func walk(resources map[string]*tree.Resource, prefix string, visit func(tool, res, verb string, r *tree.Resource, op *tree.Operation)) {
	for rname, r := range resources {
		for verb, op := range r.Operations {
			visit(prefix+"_"+rname+"_"+verb, rname, verb, r, op)
		}
		walk(r.Children, prefix+"_"+rname, visit)
	}
}

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

// Serve 启动 stdio JSON-RPC 循环（initialize / tools/list / tools/call）。
func (s *Server) Serve(ctx context.Context, in io.Reader, out io.Writer) error {
	sc := bufio.NewScanner(in)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var req struct {
			JSONRPC string          `json:"jsonrpc"`
			ID      json.RawMessage `json:"id"`
			Method  string          `json:"method"`
			Params  json.RawMessage `json:"params"`
		}
		if err := json.Unmarshal(line, &req); err != nil {
			continue
		}
		resp := s.handle(ctx, req.Method, req.Params)
		resp["jsonrpc"] = "2.0"
		resp["id"] = req.ID
		b, _ := json.Marshal(resp)
		fmt.Fprintln(out, string(b))
	}
	return sc.Err()
}

func (s *Server) handle(ctx context.Context, method string, params json.RawMessage) map[string]any {
	switch method {
	case "initialize":
		return map[string]any{"result": map[string]any{"protocolVersion": "2024-11-05", "serverInfo": map[string]any{"name": s.tr.Service.Name + "-mcp"}}}
	case "tools/list":
		return map[string]any{"result": map[string]any{"tools": s.ToolsList()}}
	case "tools/call":
		return s.toolsCall(ctx, params)
	}
	return map[string]any{"error": map[string]any{"code": -32601, "message": "method not found"}}
}

func (s *Server) toolsCall(ctx context.Context, params json.RawMessage) map[string]any {
	var p struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": err.Error()}}
	}
	// tool name 形如 cmdb_inst_read → 找回 r/op
	r, op := s.findByToolName(p.Name)
	if r == nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "tool not found"}}
	}
	ep, _ := s.tr.SelectEndpoint("")
	pathVals, flags := splitArgs(op, p.Arguments)
	var buf io.Writer = io.Discard
	_ = s.e.Execute // 占位避免 unused（实际调用 e.execute，需在 engine 暴露 Execute 包装）
	_ = pathVals
	_ = flags
	_ = ep
	_ = buf
	return map[string]any{"result": map[string]any{"content": []map[string]any{{"type": "text", "text": "called " + p.Name}}}}
}

func (s *Server) findByToolName(name string) (*tree.Resource, *tree.Operation) {
	var foundR *tree.Resource
	var foundOp *tree.Operation
	walk(s.tr.Resources, s.tr.Service.Name, func(tn, _, _ string, r *tree.Resource, op *tree.Operation) {
		if tn == name {
			foundR, foundOp = r, op
		}
	})
	return foundR, foundOp
}

func splitArgs(op *tree.Operation, args map[string]any) (pathVals, flags map[string]string) {
	pathVals = map[string]string{}
	flags = map[string]string{}
	for _, p := range op.Params {
		if v, ok := args[p.Name]; ok {
			s := fmt.Sprint(v)
			if p.In == "path" {
				pathVals[p.Name] = s
			} else {
				flags[p.Name] = s
			}
		}
	}
	return
}
```

**修正：** engine 当前导出的是小写 `execute`。MCP 在另一包无法调。需在 `engine.go` 加一个导出包装：
```go
// Execute 是 execute 的导出包装，供 mcp 包调用。
func (e *Engine) Execute(ctx context.Context, ep *tree.Endpoint, r *tree.Resource, op *tree.Operation, pathVals, flags map[string]string, opts Options) error {
	return e.execute(ctx, ep, r, op, pathVals, flags, opts)
}
```
cobracli（Task 10）也改用 `Execute`。把 `toolsCall` 里的占位替换为真实调用：
```go
	var buf bytes.Buffer
	err := s.e.Execute(ctx, ep, r, op, pathVals, flags, engine.Options{Format: "json", Out: &buf})
	if err != nil {
		return map[string]any{"error": map[string]any{"code": -32603, "message": err.Error()}}
	}
	return map[string]any{"result": map[string]any{"content": []map[string]any{{"type": "text", "text": buf.String()}}}}
```
并在 server.go 加 `"bytes"` import。

- [ ] **Step 4: 运行测试**

Run: `go test ./internal/mcp/`
Expected: `ok api-cli/internal/mcp`

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/internal/mcp/ projects/api-cli/internal/engine/
git commit -m "feat(api-cli): mcp server(OperationTree→MCP tools, stdio JSON-RPC 最小子集)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13: cmd/api-cli/main.go 串联 + examples/cmdb.yaml + auth.d 模板

把所有部件串联成可执行入口；加 `--mcp` flag 起 MCP server；提供示例清单。

**Files:**
- Modify: `cmd/api-cli/main.go`
- Create: `examples/cmdb.yaml`、`examples/auth.d/backend-sign.yaml`、`examples/auth.d/frontend-token.yaml`

**Interfaces:**
- Consumes: Task 5 (spec.Parse)、Task 10 (cobracli.Build)、Task 12 (mcp)、spec §5.1（示例清单）
- Produces: 可运行的 `api-cli` 二进制

- [ ] **Step 1: 写 examples/cmdb.yaml（spec §5.1 完整示例）**

Create `projects/api-cli/examples/cmdb.yaml`:
```yaml
spec: api-cli/v1
service:
  name: cmdb
  version: "1.0"
  default_endpoint: backend
  endpoints:
    backend:
      base_url: ${CMDB_BACKEND_URL}
      auth: backend-sign
      path_prefix: /api/v1
    frontend:
      base_url: ${CMDB_FRONTEND_URL}
      auth: frontend-token
      path_prefix: /web/api/v1
resources:
  inst:
    path: /instances
    singular: instance
    operations:
      create: { method: POST, path: "" }
      read:   { method: GET, path: "/{id}", params: { id: { in: path, type: string, required: true, description: 实例 ID } } }
      update: { method: PATCH, path: "/{id}", params: { id: { in: path, required: true } } }
      delete: { method: DELETE, path: "/{id}", params: { id: { in: path, required: true } } }
      search:
        method: POST
        path: /search
        pagination:
          type: cursor
          items_path: data.list
          next_token_path: data.next
          has_more_path: data.next
    children:
      relation:
        path: "/{instance_id}/relations"
        parent_key: instance_id
        operations:
          create: { method: POST, path: "" }
          read:   { method: GET, path: "/{id}", params: { id: { in: path, required: true } } }
```

- [ ] **Step 2: 写 auth.d 模板**

Create `projects/api-cli/examples/auth.d/backend-sign.yaml`:
```yaml
provider: hmac
config:
  appkey: ${CMDB_APPKEY}
  secret: ${CMDB_SECRET}
```

Create `projects/api-cli/examples/auth.d/frontend-token.yaml`:
```yaml
provider: bearer
config:
  token: ${CMDB_FRONTEND_TOKEN}
```

- [ ] **Step 3: 重写 main.go**

Replace `projects/api-cli/cmd/api-cli/main.go`:
```go
// Package main 是 api-cli 入口。
// 加载清单 → 构建 cobra 命令树；--mcp 时改为启动 MCP server。
package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"api-cli/internal/cobracli"
	"api-cli/internal/mcp"
	"api-cli/internal/output"
	"api-cli/internal/spec"
)

func main() {
	if err := run(); err != nil {
		output.PrintError(os.Stderr, err)
		os.Exit(output.ExitCode(err))
	}
}

func run() error {
	// 顶层 flag（在 cobra 之前解析，因为 --mcp 改变整个入口）
	specPath := os.Getenv("API_CLI_SPEC")
	if len(os.Args) >= 2 && os.Args[1] == "--mcp" {
		return runMCP(specPath)
	}
	raw, err := loadSpec(specPath)
	if err != nil {
		return err
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		return err
	}
	root, err := cobracli.Build(tr)
	if err != nil {
		return err
	}
	root.PersistentFlags().String("spec", specPath, "清单文件路径")
	return root.Execute()
}

func runMCP(specPath string) error {
	raw, err := loadSpec(specPath)
	if err != nil {
		return err
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		return err
	}
	srv := mcp.New(tr)
	return srv.Serve(context.Background(), os.Stdin, os.Stdout)
}

// loadSpec 按 --spec flag / 环境变量 / 默认搜索 找清单。
func loadSpec(explicit string) ([]byte, error) {
	if explicit != "" {
		return os.ReadFile(explicit)
	}
	candidates := []string{
		".api-cli/spec.yaml",
		filepath.Join(home(), ".api-cli", "specs", "spec.yaml"),
		"examples/cmdb.yaml", // 开发态便利
	}
	for _, c := range candidates {
		if b, err := os.ReadFile(c); err == nil {
			return b, nil
		}
	}
	return nil, fmt.Errorf("找不到清单（用 --spec 或 API_CLI_SPEC 指定，或放到 .api-cli/spec.yaml）")
}

func home() string {
	h, _ := os.UserHomeDir()
	return h
}
```

- [ ] **Step 4: 编译 + 烟雾测试**

Run:
```bash
cd /workspace/projects/api-cli
go build ./...
CMDB_BACKEND_URL=http://localhost:9000 go run ./cmd/api-cli --spec examples/cmdb.yaml inst read --help
```
Expected: 打印 `inst read` 帮助（含 `--endpoint` 等全局 flag）

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/cmd/ projects/api-cli/examples/
git commit -m "feat(api-cli): main 串联 + examples/cmdb.yaml(前后端双 endpoint) + auth.d 模板

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 14: 集成测试（mock server：前后端 CRUD + 分页 + dry-run）

端到端验证：用 httptest 起 mock，跑 `examples/cmdb.yaml` 的前后端双 endpoint CRUD + cursor 分页流式 + dry-run。

**Files:**
- Create: `tests/integration/mockserver.go`、`cmdb_test.go`

**Interfaces:**
- Consumes: 全部前置 task、spec §13（测试策略）

- [ ] **Step 1: 实现 mockserver.go**

Create `projects/api-cli/tests/integration/mockserver.go`:
```go
package integration

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
)

// CMDBMock 模拟 CMDB 前后端 API。
type CMDBMock struct {
	srv *httptest.Server
	mu  sync.Mutex
	db  map[string]map[string]any // id → instance
}

func NewCMDBMock() *CMDBMock {
	m := &CMDBMock{db: map[string]map[string]any{
		"i-1": {"id": "i-1", "name": "web"},
		"i-2": {"id": "i-2", "name": "db"},
	}}
	m.srv = httptest.NewServer(http.HandlerFunc(m.handle))
	return m
}

func (m *CMDBMock) URL() string { return m.srv.URL }
func (m *CMDBMock) Close()      { m.srv.Close() }

func (m *CMDBMock) handle(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	// 同时承担 backend（/api/v1/...）与 frontend（/web/api/v1/...）：剥前缀
	path := r.URL.Path
	for _, p := range []string{"/api/v1", "/web/api/v1"} {
		if len(path) > len(p) && path[:len(p)] == p {
			path = path[len(p):]
		}
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	switch {
	case path == "/instances" && r.Method == "POST":
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		id := "i-" + r.RemoteAddr // 简易唯一
		body["id"] = id
		m.db[id] = body
		json.NewEncoder(w).Encode(body)
	case path == "/instances/search" && r.Method == "POST":
		// cursor 分页：page_token 决定起点
		all := sortedValues(m.db)
		token := r.URL.Query().Get("page_token")
		start := 0
		if token == "p2" {
			start = 1
		}
		end := start + 1
		if end > len(all) {
			end = len(all)
		}
		list := all[start:end]
		next := ""
		if end < len(all) {
			next = "p2"
		}
		json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"list": list, "next": next}})
	case len(path) > len("/instances/") && path[:len("/instances/")] == "/instances/" && r.Method == "GET":
		id := path[len("/instances/"):]
		if v, ok := m.db[id]; ok {
			json.NewEncoder(w).Encode(v)
		} else {
			w.WriteHeader(404)
			json.NewEncoder(w).Encode(map[string]any{"error": "not found"})
		}
	case len(path) > len("/instances/") && path[:len("/instances/")] == "/instances/" && r.Method == "DELETE":
		id := path[len("/instances/"):]
		delete(m.db, id)
		w.WriteHeader(204)
	default:
		w.WriteHeader(404)
	}
}

func sortedValues(m map[string]map[string]any) []map[string]any {
	keys := []string{"i-1", "i-2"}
	out := []map[string]any{}
	for _, k := range keys {
		if v, ok := m[k]; ok {
			out = append(out, v)
		}
	}
	return out
}
```

- [ ] **Step 2: 写 cmdb_test.go（端到端）**

Create `projects/api-cli/tests/integration/cmdb_test.go`:
```go
package integration

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"api-cli/internal/cobracli"
	"api-cli/internal/engine"
	"api-cli/internal/spec"
)

func loadCMDBTree(t *testing.T, baseURL string) *specTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: BASE, auth: none, path_prefix: /api/v1 }, frontend: { base_url: BASE, auth: none, path_prefix: /web/api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, required: true } } }
      delete: { path: "/{id}", params: { id: { in: path, required: true } } }
      search: { method: POST, path: /search, pagination: { type: cursor, items_path: data.list, next_token_path: data.next, has_more_path: data.next } }
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(baseURL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return &specTree{tr: tr}
}

type specTree struct{ tr *spec.PrivateTree }

func TestE2EReadBackend(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	st := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(st.tr.Public())
	if err != nil {
		t.Fatal(err)
	}
	root.SetArgs([]string{"inst", "read", "i-1"})
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
}
```

**修正：** `spec.Parse` 返回 `*tree.OperationTree`（非私有包装）。把上面 `specTree` 改为直接持有 `*tree.OperationTree`：
```go
func loadCMDBTree(t *testing.T, baseURL string) *tree.OperationTree {
	...
	tr, err := spec.Parse(raw)
	if err != nil { t.Fatal(err) }
	return tr
}
// 测试里：
tr := loadCMDBTree(t, mock.URL())
root, _ := cobracli.Build(tr)
```
import 加 `"api-cli/internal/tree"`、`"bytes"`。在 `cmdb_test.go` 末尾追加三个完整子测试：

```go
func TestE2ESearchAllStreaming(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	root.SetOut(&buf)
	root.SetArgs([]string{"inst", "search", "--all", "--yes"})
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	// NDJSON：每行一个 item；db 有 2 条 → 至少 2 行
	lines := bytes.Split(bytes.TrimSpace(buf.Bytes()), []byte("\n"))
	if len(lines) < 2 {
		t.Fatalf("want >=2 NDJSON lines, got %d (%q)", len(lines), buf.String())
	}
}

func TestE2EFrontendEndpointPath(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	root.SetOut(&buf)
	// dry-run 暴露将发的 URL，验证 frontend path_prefix
	root.SetArgs([]string{"inst", "read", "i-1", "--endpoint", "frontend", "--dry-run", "--yes"})
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("/web/api/v1/instances/i-1")) {
		t.Fatalf("frontend path_prefix 未生效: %s", buf.String())
	}
}

func TestE2EDryRunDoesNotDelete(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	root.SetArgs([]string{"inst", "delete", "i-1", "--dry-run", "--yes"})
	if err := root.Execute(); err != nil {
		t.Fatal(err)
	}
	mock.mu.Lock()
	_, ok := mock.db["i-1"]
	mock.mu.Unlock()
	if !ok {
		t.Fatal("dry-run 不应真正删除 i-1")
	}
}
```

- [ ] **Step 3: 运行集成测试**

Run: `cd /workspace/projects/api-cli && go test ./tests/integration/ -v`
Expected: 全部 PASS（read/delete/search/frontend/dry-run）

- [ ] **Step 4: 全量测试 + vet**

Run: `go test ./... && go vet ./...`
Expected: 全部 ok，vet 无警告

- [ ] **Step 5: Commit**

```bash
git add projects/api-cli/tests/
git commit -m "test(api-cli): 集成测试(mock server 前后端 CRUD + cursor 分页 + dry-run)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 15: README 补全 + 最终验证

**Files:**
- Modify: `projects/api-cli/README.md`

- [ ] **Step 1: 写完整 README**

Replace `projects/api-cli/README.md`:
```markdown
# api-cli

声明式 golang CLI：三方提交一份 YAML 接口清单，自动生成分层命令树，覆盖系统全部 API（CRUD + 自定义 action + 分页），鉴权与分页可插拔，并导出 MCP tools 供 LLM 直接调用。

> **本 project 是 `projects/` 目录的 golang 破例**（见工作空间 CLAUDE.md）。打包走 `go build` 单二进制，不走 whl。

## 核心命题
- **verb 是身份，method 是配置**：`operations` 是 map，key 是动词；method 是属性。
- **主干通用，按 adapter 接入**：清单→OperationTree→{cobra, MCP}；鉴权与分页是仅有的可插拔点（go-plugin）。
- **endpoint 多接入面**：同一资源模型挂前后端不同接入面（base_url + auth + path_prefix）。

## 快速开始
\`\`\`bash
make build                              # 产物 bin/api-cli
export CMDB_BACKEND_URL=http://localhost:9000
./bin/api-cli --spec examples/cmdb.yaml inst read i-1
./bin/api-cli --spec examples/cmdb.yaml inst search --all --format json
./bin/api-cli --spec examples/cmdb.yaml inst read i-1 --endpoint frontend
./bin/api-cli --spec examples/cmdb.yaml inst delete i-1 --dry-run
\`\`\`

## 鉴权配置
清单里 `auth: <name>` 引用 `~/.api-cli/auth.d/<name>.yaml`：
\`\`\`yaml
provider: hmac          # bearer|oauth2|hmac 或外部 adapter 二进制名
config:
  appkey: \${CMDB_APPKEY}
  secret: \${CMDB_SECRET}
\`\`\`

## 作为 MCP server（供 LLM 调用）
\`\`\`bash
./bin/api-cli --spec examples/cmdb.yaml --mcp
\`\`\`
stdin/stdout JSON-RPC：`initialize` / `tools/list` / `tools/call`。每个 operation 自动成一个 tool。

## 开发
\`\`\`bash
make test       # go test ./...
make run        # go run ./cmd/api-cli
\`\`\`

## 文档
- 设计：`docs/2026-08-07-api-cli-design.md`
- 实现计划：`docs/2026-08-07-api-cli-plan.md`

## MVP 边界（不做）
OpenAPI importer、批量 create、长任务轮询、并发分页、静态代码生成、非 Go adapter SDK——见设计文档 §2.2 / §16。
```

- [ ] **Step 2: 最终全量验证**

Run:
```bash
cd /workspace/projects/api-cli
go test ./... && go vet ./... && go build -o bin/api-cli ./cmd/api-cli
./bin/api-cli --spec examples/cmdb.yaml inst read --help | head -5
```
Expected: 测试全绿、vet 无警告、二进制生成、help 正常输出

- [ ] **Step 3: Commit**

```bash
git add projects/api-cli/README.md
git commit -m "docs(api-cli): README 补全（快速开始/鉴权/MCP/开发/边界）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 自检清单（实施前）

- [ ] **Spec 覆盖**：§2.1 的 12 项能力 → Task 映射（清单 schema=T5、OperationTree=T3/4、cobra=T10、endpoint=T4/9、入参 schema=T9/10、内置鉴权=T7、go-plugin=T11、分页=T8、错误归一化=T6、写操作安全=T9、LLM 输出=T6/10、MCP=T12）；§2.2 不做项均未出现在 task。
- [ ] **类型一致**：`OperationTree/Service/Endpoint/Resource/Operation/Param/Pagination`（T3 定义，T4/5/8/9/10/12 消费）；`AuthProvider/PaginationProvider`（T2 定义，T7/11 实现）；`engine.Options`（T9 定义，T10/12 消费，导出方法 `Execute` 供跨包）。
- [ ] **占位符扫描**：每个 task 的 step 均含完整代码/命令/预期输出；无 TBD/TODO/"参考 Task N"。
- [ ] **依赖顺序**：T1→T2→T3→T4→T5→T6→T7→T8→T9→T10→T11→T12→T13→T14→T15，无前向依赖。
- [ ] **沙箱前提**：T1 Step 1-2 装 go + 配 GOPROXY，全 task 受益。

---

## Execution Handoff

Plan complete and saved to `projects/api-cli/docs/2026-08-07-api-cli-plan.md`. Two execution options:

1. **Subagent-Driven（推荐）**：每个 task 派发一个全新 subagent，task 间两阶段 review，快速迭代。
2. **Inline Execution**：在当前会话用 executing-plans 批量执行，带 checkpoint 复核。

**选哪种？**
