package auth

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"

	"api-cli/pkg/adapter"
)

// HMACSign appkey + HMAC-SHA256 签名。
// string-to-sign = method + url + body；输出 X-App-Key + X-Sign。
type HMACSign struct{ appkey, secret string }

func (h *HMACSign) Configure(c map[string]any) error {
	h.appkey = str(c["appkey"])
	h.secret = str(c["secret"])
	return nil
}

func (h *HMACSign) Apply(_ context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	mac := hmac.New(sha256.New, []byte(h.secret))
	mac.Write([]byte(r.Method + r.URL + string(r.Body)))
	return &adapter.AuthResponse{Headers: map[string]string{
		"X-App-Key": h.appkey,
		"X-Sign":    hex.EncodeToString(mac.Sum(nil)),
	}}, nil
}
