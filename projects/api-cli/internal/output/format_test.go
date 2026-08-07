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
