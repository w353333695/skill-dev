package auth

import (
	"context"
	"testing"

	"api-cli/pkg/adapter"
)

func TestHMACSignApply(t *testing.T) {
	h := &HMACSign{}
	if err := h.Configure(map[string]any{"appkey": "ak", "secret": "sk"}); err != nil {
		t.Fatal(err)
	}
	resp, err := h.Apply(context.Background(), &adapter.AuthRequest{
		Method: "POST",
		URL:    "http://x/instances",
		Body:   []byte("{}"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Headers["X-App-Key"] != "ak" {
		t.Fatalf("want X-App-Key=ak, got %q", resp.Headers["X-App-Key"])
	}
	if resp.Headers["X-Sign"] == "" {
		t.Fatal("X-Sign header empty")
	}
}

// TestHMACSignStable 断言同一输入签名幂等（便于跨端复算）。
func TestHMACSignStable(t *testing.T) {
	h := &HMACSign{}
	h.Configure(map[string]any{"appkey": "ak", "secret": "sk"})
	r1, _ := h.Apply(context.Background(), &adapter.AuthRequest{Method: "POST", URL: "/u", Body: []byte("b")})
	r2, _ := h.Apply(context.Background(), &adapter.AuthRequest{Method: "POST", URL: "/u", Body: []byte("b")})
	if r1.Headers["X-Sign"] != r2.Headers["X-Sign"] {
		t.Fatal("hmac 签名不稳定")
	}
}
