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
