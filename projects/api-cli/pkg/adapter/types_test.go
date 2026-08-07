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

func (s *stubAuth) Configure(config map[string]any) error { return nil }
func (s *stubAuth) Apply(ctx context.Context, r *AuthRequest) (*AuthResponse, error) {
	return &AuthResponse{Headers: map[string]string{"Authorization": "Bearer x"}}, nil
}

type stubPaging struct{}

func (s *stubPaging) Next(resp []byte, headers map[string]string, state map[string]any) (*PagingResult, error) {
	return &PagingResult{Items: []any{}, HasNext: false}, nil
}
