package output

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestFormatJSON(t *testing.T) {
	var buf bytes.Buffer
	data := map[string]any{"id": "i-1", "name": "n"}
	if err := Format(&buf, "json", data); err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(buf.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["id"] != "i-1" {
		t.Fatal("json roundtrip failed")
	}
}

func TestFormatYAML(t *testing.T) {
	var buf bytes.Buffer
	if err := Format(&buf, "yaml", map[string]any{"id": "i-1"}); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("id: i-1")) {
		t.Fatalf("yaml output unexpected: %s", buf.String())
	}
}

func TestFormatTableWithHeaders(t *testing.T) {
	var buf bytes.Buffer
	data := []map[string]any{{"id": "i-1", "name": "n"}}
	headers := map[string]string{"id": "实例ID", "name": "名称"}
	if err := FormatTable(&buf, data, headers); err != nil {
		t.Fatal(err)
	}
	// 表头用 headers 的中文（按 key 升序：id < name）
	if !bytes.Contains(buf.Bytes(), []byte("实例ID")) || !bytes.Contains(buf.Bytes(), []byte("名称")) {
		t.Fatalf("表头未用中文: %s", buf.String())
	}
}
