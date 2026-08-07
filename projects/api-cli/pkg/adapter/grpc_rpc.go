// Package adapter 的 net/rpc 桥接：go-plugin 用 net/rpc + gob 模式（非 gRPC），
// 免去 protoc 工具链，三方 adapter 只需实现 AuthProvider 接口即可被装载。
package adapter

import (
	"context"
	"fmt"
	"net/rpc"

	"github.com/hashicorp/go-plugin"
)

// AuthPlugin 是 go-plugin 的插件包装（net/rpc 模式）。
// Host 端：plugin.NewClient 的 Plugins map 里放 &AuthPlugin{}；
// Adapter 端：plugin.Serve 的 Plugins map 里放 &AuthPlugin{Impl: <三方实现>}。
//
// Server/Client 由本文件提供实现，bridge 到上面的 AuthProvider 接口。
type AuthPlugin struct {
	// Impl 仅 adapter 进程侧需要填：host 侧只用作协议描述符。
	Impl AuthProvider
}

// Server 由 plugin 进程侧（adapter 二进制）调用：把本地 Impl 暴露成 *authRPCServer。
// host 侧不会走这里（go-plugin 仅在 plugin 进程回调本方法）。
func (p *AuthPlugin) Server(*plugin.MuxBroker) (interface{}, error) {
	return &authRPCServer{Impl: p.Impl}, nil
}

// Client 由 host 侧调用：拿到 plugin 进程的 *rpc.Client 后包成 *authRPCClient。
func (p *AuthPlugin) Client(_ *plugin.MuxBroker, c *rpc.Client) (interface{}, error) {
	return &authRPCClient{client: c}, nil
}

// 编译期保证 AuthPlugin 实现 plugin.Plugin。
var _ plugin.Plugin = (*AuthPlugin)(nil)

// --- net/rpc 传输结构 ---
// go-plugin 的 net/rpc 用 gob 序列化，所有传输字段必须导出。

// configureArgs 是 Configure 方法的入参。
type configureArgs struct {
	Config map[string]any
}

// applyArgs 是 Apply 方法的入参。
type applyArgs struct {
	Method  string
	URL     string
	Body    []byte
	Headers map[string]string
	Query   map[string]string
}

// applyReply 是 Apply 方法的回包。Err 非空表示 adapter 内部出错（transport 层仍 return nil）。
type applyReply struct {
	Headers map[string]string
	Query   map[string]string
	Err     string
}

// authRPCServer 在 adapter 进程侧运行，把本地 AuthProvider 暴露给 host。
type authRPCServer struct{ Impl AuthProvider }

// Configure net/rpc 暴露方法。出错不返回 transport error，而是写到 *reply，
// 让 host 侧能拿到具体错误信息（go-plugin 对 transport error 会直接 kill 子进程）。
func (s *authRPCServer) Configure(args configureArgs, reply *string) error {
	if err := s.Impl.Configure(args.Config); err != nil {
		*reply = err.Error()
		return nil
	}
	*reply = ""
	return nil
}

// Apply net/rpc 暴露方法。同样把 Apply 内部错误序列化到 reply.Err，避免子进程被 kill。
// 注意：当前实现未把 ctx 的 cancel/deadline 透传给 adapter（net/rpc 不支持 ctx 流向）。
func (s *authRPCServer) Apply(args applyArgs, reply *applyReply) error {
	resp, err := s.Impl.Apply(context.Background(), &AuthRequest{
		Method:  args.Method,
		URL:     args.URL,
		Body:    args.Body,
		Headers: args.Headers,
		Query:   args.Query,
	})
	if err != nil {
		reply.Err = err.Error()
		return nil
	}
	reply.Headers = resp.Headers
	reply.Query = resp.Query
	return nil
}

// authRPCClient 在 host 侧运行，通过 *rpc.Client 调起 adapter 进程的 authRPCServer。
// 实现 AuthProvider 接口，所以 host 代码把它当普通 AuthProvider 用即可。
type authRPCClient struct{ client *rpc.Client }

// Configure 走 "Plugin.Configure"——go-plugin net/rpc 模式下服务端方法表前缀固定 "Plugin."。
func (c *authRPCClient) Configure(cfg map[string]any) error {
	var rep string
	if err := c.client.Call("Plugin.Configure", configureArgs{Config: cfg}, &rep); err != nil {
		return fmt.Errorf("rpc Configure 调用失败: %w", err)
	}
	if rep != "" {
		return fmt.Errorf("adapter Configure 失败: %s", rep)
	}
	return nil
}

// Apply 同上，序列化 applyReply.Err 为 Go error。
func (c *authRPCClient) Apply(_ context.Context, r *AuthRequest) (*AuthResponse, error) {
	var rep applyReply
	if err := c.client.Call("Plugin.Apply", applyArgs{
		Method:  r.Method,
		URL:     r.URL,
		Body:    r.Body,
		Headers: r.Headers,
		Query:   r.Query,
	}, &rep); err != nil {
		return nil, fmt.Errorf("rpc Apply 调用失败: %w", err)
	}
	if rep.Err != "" {
		return nil, fmt.Errorf("adapter Apply 失败: %s", rep.Err)
	}
	return &AuthResponse{Headers: rep.Headers, Query: rep.Query}, nil
}

// 编译期保证 authRPCClient 实现 AuthProvider（host 侧把它当 AuthProvider 用）。
var _ AuthProvider = (*authRPCClient)(nil)
