package auth

import (
	"context"

	"api-cli/pkg/adapter"
)

// BearerAuth 内置 Bearer token 鉴权。token → Authorization: Bearer <token>。
type BearerAuth struct{ token string }

func (b *BearerAuth) Configure(c map[string]any) error {
	b.token = str(c["token"])
	return nil
}

func (b *BearerAuth) Apply(_ context.Context, _ *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	return &adapter.AuthResponse{Headers: map[string]string{"Authorization": "Bearer " + b.token}}, nil
}
