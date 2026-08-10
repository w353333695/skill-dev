package auth

import (
	"context"
	"testing"

	"api-cli/pkg/adapter"
)

func TestCookieAuthApply(t *testing.T) {
	c := &CookieAuth{}
	if err := c.Configure(map[string]any{"cookie": "PHPSESSID=abc; foo=bar"}); err != nil {
		t.Fatal(err)
	}
	resp, err := c.Apply(context.Background(), &adapter.AuthRequest{Method: "GET", URL: "http://x"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Headers["Cookie"] != "PHPSESSID=abc; foo=bar" {
		t.Fatalf("cookie header mismatch: %q", resp.Headers["Cookie"])
	}
}
