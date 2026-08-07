package auth

import (
	"context"
	"crypto/hmac"
	"crypto/md5"
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"

	"api-cli/pkg/adapter"
)

// EasyOpsOpenAPI 实现 EasyOps 平台 openapi 的自定义 HMAC-SHA1 签名鉴权（非标准协议）。
//
// 签名后 accesskey/signature/expires 放 query，host header 由 Configure 注入（openapi 走
// openapi.easyops-only.com）。协议见 /tmp/openapi-doc.md：
//
//	StringToSign = HTTP-Verb\n + URL(资源路径)\n + Parameters\n + Content-Type\n +
//	               Content-MD5\n + Date(timestamp)\n + AccessKey
//
// 其中 Parameters 仅 GET 有，按 key 升序以 key+value 串联（无分隔符）；
// Content-MD5 仅 POST/PUT 有，为 body 的 md5 hex。Signature = HMAC-SHA1(secret_key, StringToSign) hex。
// expires = 签名时用的 timestamp（同一值既进 StringToSign 也作为 expires query）。
type EasyOpsOpenAPI struct {
	accessKey string
	secretKey string
	host      string
}

func (e *EasyOpsOpenAPI) Configure(c map[string]any) error {
	e.accessKey = str(c["access_key"])
	e.secretKey = str(c["secret_key"])
	e.host = str(c["host"])
	if e.accessKey == "" {
		return fmt.Errorf("easyops-openapi: access_key 未配置")
	}
	if e.secretKey == "" {
		return fmt.Errorf("easyops-openapi: secret_key 未配置")
	}
	return nil
}

func (e *EasyOpsOpenAPI) Apply(_ context.Context, r *adapter.AuthRequest) (*adapter.AuthResponse, error) {
	// 1. 资源路径：从 r.URL 取 Path（签名串的 URL = 资源路径，不含 host/query）。
	path := extractPath(r.URL)

	// 2. Parameters：仅 GET 有，按 key 升序以 key+value 串联。
	params := buildParameters(r.Method, r.Query)

	// 3. Content-Type：默认 application/json。
	contentType := r.Headers["content-type"]
	if contentType == "" {
		contentType = "application/json"
	}

	// 4. Content-MD5：POST/PUT 时取 body 的 md5 hex；其余空串。
	contentMD5 := ""
	if r.Method == "POST" || r.Method == "PUT" {
		sum := md5.Sum(r.Body)
		contentMD5 = hex.EncodeToString(sum[:])
	}

	// 5. Timestamp：同一值既作 StringToSign 的 Date 段，也作 expires query。
	timestamp := fmt.Sprintf("%d", time.Now().Unix())

	// 6/7. 组签名串 + HMAC-SHA1。
	stringToSign := buildStringToSign(r.Method, path, params, contentType, contentMD5, timestamp, e.accessKey)
	signature := sign(e.secretKey, stringToSign)

	return &adapter.AuthResponse{
		Query: map[string]string{
			"accesskey": e.accessKey,
			"signature": signature,
			"expires":   timestamp,
		},
		Headers: map[string]string{
			"host":         e.host,
			"content-type": contentType, // docx 要求 headers 总含 content-type（GET 也带，且与签名串的 Content-Type 段一致）
		},
	}, nil
}

// buildStringToSign 按协议拼 7 段换行签名串（末尾 accessKey 后无换行）。
// 抽成纯函数便于单测（固定 timestamp 验证签名可重现）。
func buildStringToSign(method, path, params, contentType, contentMD5, timestamp, accessKey string) string {
	return strings.Join([]string{
		method,
		path,
		params,
		contentType,
		contentMD5,
		timestamp,
		accessKey,
	}, "\n")
}

// sign HMAC-SHA1 hex 输出（40 字符）。抽成纯函数便于单测用已知向量比对。
func sign(secretKey, stringToSign string) string {
	mac := hmac.New(sha1.New, []byte(secretKey))
	mac.Write([]byte(stringToSign))
	return hex.EncodeToString(mac.Sum(nil))
}

// buildParameters 仅 GET 把 query 按 key 升序以 key+value 串联（无分隔符）；
// 非 GET 返回空串（协议规定 POST/PUT 的 Parameters 段为空）。
func buildParameters(method string, query map[string]string) string {
	if method != "GET" || len(query) == 0 {
		return ""
	}
	keys := make([]string, 0, len(query))
	for k := range query {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var b strings.Builder
	for _, k := range keys {
		b.WriteString(k)
		b.WriteString(query[k])
	}
	return b.String()
}

// extractPath 从完整 URL 取资源路径（不含 host/query）；解析失败退回原串兜底。
func extractPath(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	return u.Path
}
