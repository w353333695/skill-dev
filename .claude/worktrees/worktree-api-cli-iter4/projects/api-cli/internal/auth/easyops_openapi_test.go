package auth

import (
	"context"
	"strings"
	"testing"

	"api-cli/pkg/adapter"
)

// TestBuildStringToSign 用固定输入验证 7 段换行拼接（与 EasyOps openapi 协议对齐）。
// 期望值与协议文档示例一致：method\n + path\n + parameters\n + contentType\n + contentMD5\n + timestamp\n + accessKey，
// 末尾 accessKey 后无换行。空段（GET 的 Parameters、GET 的 Content-MD5）保留为空串，换行仍在。
func TestBuildStringToSign(t *testing.T) {
	// GET 场景：有 query 参数 → Parameters 段非空；Content-MD5 空。
	got := buildStringToSign(
		"GET", "/cmdb/object/list", "page1pageSize30",
		"application/json", "", "1460314842", "AK123",
	)
	want := strings.Join([]string{
		"GET",
		"/cmdb/object/list",
		"page1pageSize30",
		"application/json",
		"",
		"1460314842",
		"AK123",
	}, "\n")
	if got != want {
		t.Fatalf("GET buildStringToSign mismatch:\nwant=%q\n got=%q", want, got)
	}

	// POST 场景：无 query 参数 → Parameters 空；body 的 md5 hex 进 Content-MD5。
	postMD5 := "50b6137335559d7afac1144578f8e178" // md5("{\"name\":\"foo\"}")
	gotPost := buildStringToSign(
		"POST", "/tools/flow/execution", "",
		"application/json", postMD5, "1460314842", "AK123",
	)
	wantPost := strings.Join([]string{
		"POST",
		"/tools/flow/execution",
		"",
		"application/json",
		postMD5,
		"1460314842",
		"AK123",
	}, "\n")
	if gotPost != wantPost {
		t.Fatalf("POST buildStringToSign mismatch:\nwant=%q\n got=%q", wantPost, gotPost)
	}
}

// TestSign 用已知向量验证 HMAC-SHA1 hex 输出（40 字符）。
// 期望值由 python：hmac.new(key.encode(), msg.encode(), hashlib.sha1).hexdigest() 离线算得。
func TestSign(t *testing.T) {
	cases := []struct {
		name         string
		secretKey    string
		stringToSign string
		want         string
	}{
		{
			name:         "simple_vector",
			secretKey:    "secret-key",
			stringToSign: "hello\nworld",
			want:         "fa442b4043bf4cc709cb96bfac2c1f12f7bbea41",
		},
		{
			name:         "easyops_get",
			secretKey:    "mysecret",
			stringToSign: "GET\n/cmdb/object/list\npage1pageSize30\napplication/json\n\n1460314842\nAK123",
			want:         "f598b0c4c387a0edec453555b6635b57763b64b2",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := sign(c.secretKey, c.stringToSign)
			if len(got) != 40 {
				t.Fatalf("signature len = %d, want 40 (HMAC-SHA1 hex)", len(got))
			}
			if got != c.want {
				t.Fatalf("sign mismatch:\n want=%q\n  got=%q", c.want, got)
			}
		})
	}
}

// TestEasyOpsOpenAPIApply 端到端验证 Apply：GET + Query → 签名后 Query 含 accesskey/signature/expires，
// Headers 含 host。签名值与离线 python 向量比对（用固定 timestamp + 固定 StringToSign 保证可重现）。
func TestEasyOpsOpenAPIApply(t *testing.T) {
	p := &EasyOpsOpenAPI{}
	if err := p.Configure(map[string]any{
		"access_key": "AK123",
		"secret_key": "mysecret",
		"host":       "openapi.easyops-only.com",
	}); err != nil {
		t.Fatal(err)
	}

	resp, err := p.Apply(context.Background(), &adapter.AuthRequest{
		Method:  "GET",
		URL:     "http://192.168.1.1/cmdb/object/list?page=1&pageSize=30",
		Query:   map[string]string{"page": "1", "pageSize": "30"},
		Headers: map[string]string{"content-type": "application/json"},
	})
	if err != nil {
		t.Fatal(err)
	}

	// Query 三件套齐全。
	if resp.Query["accesskey"] != "AK123" {
		t.Fatalf("accesskey mismatch: got %q", resp.Query["accesskey"])
	}
	sig := resp.Query["signature"]
	if sig == "" || len(sig) != 40 {
		t.Fatalf("signature invalid: %q (len=%d)", sig, len(sig))
	}
	expires := resp.Query["expires"]
	if expires == "" {
		t.Fatal("expires empty")
	}

	// host header 注入。
	if resp.Headers["host"] != "openapi.easyops-only.com" {
		t.Fatalf("host header mismatch: got %q", resp.Headers["host"])
	}

	// 用同一 expires 复算签名，断言与 Apply 内部一致（验证 timestamp 同时用作 expires）。
	expectSig := sign("mysecret",
		buildStringToSign("GET", "/cmdb/object/list", "page1pageSize30",
			"application/json", "", expires, "AK123"))
	if sig != expectSig {
		t.Fatalf("signature not reproducible:\n expect=%q\n   got=%q", expectSig, sig)
	}
}

// TestEasyOpsOpenAPIApplyPOST 验证 POST：Content-MD5 来自 body 的 md5 hex，
// Parameters 为空，签名可重现。
func TestEasyOpsOpenAPIApplyPOST(t *testing.T) {
	p := &EasyOpsOpenAPI{}
	p.Configure(map[string]any{
		"access_key": "AK123",
		"secret_key": "mysecret",
		"host":       "openapi.easyops-only.com",
	})

	body := []byte("{\"name\":\"foo\"}")
	resp, err := p.Apply(context.Background(), &adapter.AuthRequest{
		Method:  "POST",
		URL:     "http://192.168.1.1/tools/flow/execution",
		Body:    body,
		Headers: map[string]string{"content-type": "application/json"},
	})
	if err != nil {
		t.Fatal(err)
	}
	expires := resp.Query["expires"]
	// POST 期望签名：md5(body)=50b6137335559d7afac1144578f8e178，Parameters 空。
	expectSig := sign("mysecret",
		buildStringToSign("POST", "/tools/flow/execution", "",
			"application/json", "50b6137335559d7afac1144578f8e178", expires, "AK123"))
	if resp.Query["signature"] != expectSig {
		t.Fatalf("POST signature mismatch:\n expect=%q\n   got=%q", expectSig, resp.Query["signature"])
	}
}

// TestEasyOpsOpenAPIConfigureMissing 校验缺少 secret_key 时 Configure 报错（防静默失败）。
func TestEasyOpsOpenAPIConfigureMissing(t *testing.T) {
	p := &EasyOpsOpenAPI{}
	if err := p.Configure(map[string]any{"access_key": "AK"}); err == nil {
		t.Fatal("want error when secret_key missing, got nil")
	}
}
