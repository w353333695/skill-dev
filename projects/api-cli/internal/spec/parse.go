package spec

import (
	"fmt"
	"os"
	"regexp"

	"api-cli/internal/tree"

	"gopkg.in/yaml.v3"
)

// 默认 method 映射（spec §5.4）。
var defaultMethod = map[string]string{
	"create": "POST",
	"read":   "GET",
	"update": "PATCH",
	"delete": "DELETE",
}

var envRe = regexp.MustCompile(`\$\{([A-Z_][A-Z0-9_]*)\}`)

// Parse 把 YAML 字节解析成 *tree.OperationTree。
func Parse(raw []byte) (*tree.OperationTree, error) {
	var y yamlManifest
	if err := yaml.Unmarshal(raw, &y); err != nil {
		return nil, fmt.Errorf("YAML 解析失败: %w", err)
	}
	if y.Spec != "api-cli/v1" {
		return nil, fmt.Errorf("不支持的 spec 版本 %q（仅支持 api-cli/v1）", y.Spec)
	}
	tr := &tree.OperationTree{
		Service: tree.Service{
			Name:            y.Service.Name,
			Version:         y.Service.Version,
			DefaultEndpoint: y.Service.DefaultEndpoint,
			Endpoints:       map[string]*tree.Endpoint{},
		},
		Resources: map[string]*tree.Resource{},
	}
	for name, ep := range y.Service.Endpoints {
		tr.Service.Endpoints[name] = &tree.Endpoint{
			Name: name, BaseURL: expandEnv(ep.BaseURL), Auth: ep.Auth,
			PathPrefix: ep.PathPrefix, Host: ep.Host, AllowOperations: ep.AllowOperations,
		}
	}
	for name, r := range y.Resources {
		tr.Resources[name] = convertResource(name, r)
	}
	return tr, nil
}

func convertResource(name string, y *yamlResource) *tree.Resource {
	r := &tree.Resource{
		Name: name, Path: y.Path, Singular: y.Singular, ParentKey: y.ParentKey,
		Operations: map[string]*tree.Operation{}, Children: map[string]*tree.Resource{},
	}
	for verb, op := range y.Operations {
		r.Operations[verb] = convertOperation(verb, op)
	}
	for cname, c := range y.Children {
		r.Children[cname] = convertResource(cname, c)
	}
	return r
}

func convertOperation(verb string, y *yamlOperation) *tree.Operation {
	op := &tree.Operation{Verb: verb, Method: y.Method, Path: y.Path}
	if op.Method == "" {
		op.Method = defaultMethod[verb] // 标准 verb 默认填充；自定义 verb 空 method 在 Validate 阶段报错
	}
	for pname, p := range y.Params {
		op.Params = append(op.Params, tree.Param{
			Name: pname, In: p.In, Type: p.Type, Required: p.Required,
			Enum: p.Enum, Pattern: p.Pattern, Description: p.Description,
		})
	}
	if y.Body != nil {
		op.Body = convertSchema(y.Body)
	}
	if y.Response != nil {
		op.Response = convertSchema(y.Response)
	}
	if y.Pagination != nil {
		op.Pagination = &tree.Pagination{
			Type: y.Pagination.Type, ItemsPath: y.Pagination.ItemsPath,
			NextTokenPath: y.Pagination.NextTokenPath, PageParam: y.Pagination.PageParam,
			SizeParam: y.Pagination.SizeParam, Size: y.Pagination.Size, HasMorePath: y.Pagination.HasMorePath,
			PageIn: y.Pagination.PageIn,
		}
	}
	return op
}

func convertSchema(y *yamlSchema) *tree.Schema {
	s := &tree.Schema{Type: y.Type, Required: y.Required, Description: y.Description}
	for k, v := range y.Properties {
		if s.Properties == nil {
			s.Properties = map[string]*tree.Schema{}
		}
		s.Properties[k] = convertSchema(v)
	}
	if y.Items != nil {
		s.Items = convertSchema(y.Items)
	}
	s.Example = y.Example
	s.AdditionalProperties = y.AdditionalProperties
	return s
}

// expandEnv 把 ${VAR} 替换成 os.Getenv("VAR")；未设置则留空。
func expandEnv(s string) string {
	return envRe.ReplaceAllStringFunc(s, func(m string) string {
		return os.Getenv(m[2 : len(m)-1])
	})
}
