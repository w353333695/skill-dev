// Package adapter 是 api-cli 的对外扩展契约。
// 三方写鉴权/分页 adapter 时 import 本包，实现其中的接口。
package adapter

import (
	"context"

	"github.com/hashicorp/go-plugin"
)

// AuthProvider 鉴权 adapter 契约。内置 3 种与外部 go-plugin 都实现它。
type AuthProvider interface {
	// Configure 启动时灌配置（token/appkey/secret 等，来自 ~/.api-cli/auth.d/<name>.yaml 的 config 段）。
	Configure(config map[string]any) error
	// Apply 每个请求前调用，返回要追加的 headers/query。主程序合并进真实 *http.Request。
	Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error)
}

// AuthRequest 是给 adapter 的请求快照。用 []byte 而非 io.Reader，因跨进程要能序列化。
// Query 让签名类 adapter（如 easyops-openapi）能把已有 query 参数纳入签名串。
type AuthRequest struct {
	Method  string
	URL     string
	Body    []byte
	Headers map[string]string
	Query   map[string]string
	DryRun  bool // dry-run/print-curl 时 true：有状态 provider（oauth2）跳过刷新；无状态 provider 忽略
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
	Items   []any          // 本页数据条目
	HasNext bool           // 是否还有下一页
	State   map[string]any // 下一页状态（透传回下一次 Next）
}

// Handshake 是 go-plugin 握手配置（主程序与外部 adapter 二进制必须用同样的值）。
// gRPC 桥接（Server/Client 包装类型）由 Task 11（host）实现，此处只放共享常量，避免循环依赖。
var Handshake = plugin.HandshakeConfig{
	ProtocolVersion:  1,
	MagicCookieKey:   "API_CLI_PLUGIN",
	MagicCookieValue: "api-cli-adapter",
}

// PluginNameAuth 鉴权 adapter 在 plugin map 里用的 key。
const PluginNameAuth = "auth"

// PluginNamePaging 分页 adapter 在 plugin map 里用的 key。
const PluginNamePaging = "paging"
