package tree

import (
	"reflect"
	"testing"
)

func TestSchemaToJSONSchema(t *testing.T) {
	b := true
	s := &Schema{
		Type:                 "object",
		Description:          "搜索请求",
		Required:             []string{"q"},
		Example:              map[string]any{"q": "foo"},
		AdditionalProperties: &b,
		Properties: map[string]*Schema{
			"q":    {Type: "string", Description: "关键词"},
			"tags": {Type: "array", Items: &Schema{Type: "string"}},
		},
	}
	got := s.ToJSONSchema()
	want := map[string]any{
		"type":                 "object",
		"description":          "搜索请求",
		"required":             []string{"q"},
		"example":              map[string]any{"q": "foo"},
		"additionalProperties": true,
		"properties": map[string]any{
			"q":    map[string]any{"type": "string", "description": "关键词"},
			"tags": map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ToJSONSchema mismatch\n got: %#v\nwant: %#v", got, want)
	}
}

func TestSchemaToJSONSchemaNil(t *testing.T) {
	var s *Schema
	if got := s.ToJSONSchema(); got != nil {
		t.Fatalf("nil Schema want nil, got %#v", got)
	}
}
