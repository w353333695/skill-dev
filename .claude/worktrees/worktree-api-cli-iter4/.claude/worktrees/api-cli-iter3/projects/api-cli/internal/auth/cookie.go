package auth

import (
	"context"

	"api-cli/pkg/adapter"
)

// CookieAuth session cookie 鉴权：把配置里的 cookie 串原样注入 Cookie header。
// 适用前端浏览器 session（PHPSESSID 等）。cookie 会过期，需定期更新配置。
type CookieAuth struct{ cookie string }

func (c *CookieAuth) Configure(cfg map[string]any) error {
	c.cookie = str(cfg["cookie"])
	return nil
}

func (c *CookieAuth) Apply(ctx context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	return &adapter.AuthResponse{Headers: map[string]string{"Cookie": c.cookie}}, nil
}
