package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
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

func (o *OAuth2CC) Apply(ctx context.Context, _ *adapter.AuthRequest) (*adapter.AuthResponse, error) {
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
	req, err := http.NewRequestWithContext(ctx, "POST", o.tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return fmt.Errorf("oauth2 构造 token 请求失败: %w", err)
	}
	req.SetBasicAuth(o.clientID, o.clientSecret)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("oauth2 取 token 失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("oauth2 token 端点返回 %d", resp.StatusCode)
	}
	var body struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return fmt.Errorf("oauth2 解析 token 响应失败: %w", err)
	}
	o.accessToken = body.AccessToken
	o.expires = time.Now().Add(time.Duration(body.ExpiresIn) * time.Second)
	return nil
}
