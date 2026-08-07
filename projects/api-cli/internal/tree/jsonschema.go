package tree

// ToJSONSchema 把 Schema 递归转成 JSON Schema（map[string]any），
// 供 mcp/cobracli 生成 inputSchema/outputSchema 复用。nil Schema 返回 nil。
//
// 约定：example 仅非 nil 时输出；additionalProperties 仅指针非 nil 时输出
// （区分"未声明"与"显式 false"）。
func (s *Schema) ToJSONSchema() map[string]any {
	if s == nil {
		return nil
	}
	m := map[string]any{}
	if s.Type != "" {
		m["type"] = s.Type
	}
	if s.Description != "" {
		m["description"] = s.Description
	}
	if len(s.Required) > 0 {
		m["required"] = s.Required
	}
	if s.Example != nil {
		m["example"] = s.Example
	}
	if s.AdditionalProperties != nil {
		m["additionalProperties"] = *s.AdditionalProperties
	}
	if len(s.Properties) > 0 {
		props := map[string]any{}
		for k, v := range s.Properties {
			props[k] = v.ToJSONSchema()
		}
		m["properties"] = props
	}
	if s.Items != nil {
		m["items"] = s.Items.ToJSONSchema()
	}
	return m
}
