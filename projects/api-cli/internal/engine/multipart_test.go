package engine

import (
	"bytes"
	"mime/multipart"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"api-cli/internal/tree"
)

func TestBuildMultipart(t *testing.T) {
	// 准备临时上传文件
	tmp := t.TempDir()
	fp := filepath.Join(tmp, "pkg.tar.gz")
	payload := []byte{0x1f, 0x8b, 0x08, 0x00, 0xAA, 0xBB}
	if err := os.WriteFile(fp, payload, 0o644); err != nil {
		t.Fatal(err)
	}
	op := &tree.Operation{
		Verb:        "upload",
		Method:      "POST",
		ContentType: "multipart-form-data",
		Params: []tree.Param{
			{Name: "file", In: "formData", Format: "binary", Required: true},
			{Name: "kind", In: "formData"},
			{Name: "token", In: "header"}, // 不进 multipart
		},
	}
	flags := map[string]string{"file": fp, "kind": "tool", "token": "abc"}
	body, ct, err := buildMultipart(op, flags)
	if err != nil {
		t.Fatalf("buildMultipart: %v", err)
	}
	if !strings.HasPrefix(ct, "multipart/form-data; boundary=") {
		t.Errorf("Content-Type = %q, want multipart/form-data; boundary=", ct)
	}
	// 解析回 multipart，校验字段 + 文件
	r := multipart.NewReader(bytes.NewReader(body), strings.TrimPrefix(ct, "multipart/form-data; boundary="))
	kindSet, fileSet := false, false
	for {
		part, err := r.NextPart()
		if err != nil {
			break
		}
		switch part.FormName() {
		case "kind":
			buf := new(bytes.Buffer)
			buf.ReadFrom(part)
			if buf.String() != "tool" {
				t.Errorf("kind field = %q, want tool", buf.String())
			}
			kindSet = true
		case "file":
			if part.FileName() != "pkg.tar.gz" {
				t.Errorf("file filename = %q, want pkg.tar.gz", part.FileName())
			}
			buf := new(bytes.Buffer)
			buf.ReadFrom(part)
			if !bytes.Equal(buf.Bytes(), payload) {
				t.Errorf("file content mismatch")
			}
			fileSet = true
		}
	}
	if !kindSet || !fileSet {
		t.Errorf("未完整解析 multipart：kind=%v file=%v", kindSet, fileSet)
	}
}

func TestBuildMultipartFileMissing(t *testing.T) {
	op := &tree.Operation{
		ContentType: "multipart-form-data",
		Params:      []tree.Param{{Name: "file", In: "formData", Format: "binary", Required: true}},
	}
	_, _, err := buildMultipart(op, map[string]string{"file": "/no/such/file.tar.gz"})
	if err == nil {
		t.Error("文件不存在应报错")
	}
}
