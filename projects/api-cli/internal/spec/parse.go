package spec

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"

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
		headers := make(map[string]string, len(ep.Headers))
		for k, v := range ep.Headers {
			headers[k] = expandEnv(v) // endpoint 级 header 值也支持 ${ENV} 占位
		}
		tr.Service.Endpoints[name] = &tree.Endpoint{
			Name: name, BaseURL: expandEnv(ep.BaseURL), Auth: ep.Auth,
			PathPrefix: ep.PathPrefix, Host: ep.Host, AllowOperations: ep.AllowOperations,
			Headers: headers,
		}
	}
	for name, r := range y.Resources {
		tr.Resources[name] = convertResource(name, r)
	}
	// lint：二进制相关声明校验（err 级，阻断 Parse）
	if err := lintBinary(tr); err != nil {
		return nil, err
	}
	// lint：child resource 缺 parent_key 占位 → 警告（URL 可能缺父 ID）
	for _, r := range tr.Resources {
		lintParentKey(r, os.Stderr)
	}
	return tr, nil
}

// lintBinary 校验二进制相关声明（content_type 取值 / format=binary 的 in 约束 /
// response.format=binary 不含结构 / binary × pagination 互斥）。err 级，阻断 Parse。
func lintBinary(tr *tree.OperationTree) error {
	var firstErr error
	check := func(op *tree.Operation) {
		if firstErr != nil {
			return
		}
		ct := op.ContentType
		if ct != "" && ct != "json" && ct != "multipart-form-data" {
			firstErr = fmt.Errorf("operation %q: content_type %q 非法（允许 json/multipart-form-data）", op.Verb, ct)
			return
		}
		for _, p := range op.Params {
			if p.Format == "binary" && p.In != "formData" {
				firstErr = fmt.Errorf("operation %q: param %q format=binary 必须 in=formData（当前 in=%q）", op.Verb, p.Name, p.In)
				return
			}
		}
		if op.Response != nil && op.Response.Format == "binary" {
			if len(op.Response.Properties) > 0 || op.Response.Items != nil {
				firstErr = fmt.Errorf("operation %q: response.format=binary 不能再声明 properties/items", op.Verb)
				return
			}
			if op.Pagination != nil {
				firstErr = fmt.Errorf("operation %q: response.format=binary 不支持 pagination（二进制响应不分页）", op.Verb)
				return
			}
		}
	}
	var walk func(*tree.Resource)
	walk = func(r *tree.Resource) {
		for _, op := range r.Operations {
			check(op)
		}
		for _, c := range r.Children {
			walk(c)
		}
	}
	for _, r := range tr.Resources {
		walk(r)
	}
	return firstErr
}

// lintParentKey 递归检查：对每个有 ParentKey 的 resource，其每个 child 的 Path
// 应含 {<ParentKey>} 占位（否则祖先链拼出的 URL 会缺父 ID，且无报错——声明式静默错）。
func lintParentKey(r *tree.Resource, w io.Writer) {
	for _, c := range r.Children {
		if r.ParentKey != "" && !strings.Contains(c.Path, "{"+r.ParentKey+"}") {
			fmt.Fprintf(w, "警告: resource %q 的 parent_key %q 未在子资源 %q 的 path %q 中出现（URL 可能缺父 ID）\n",
				r.Name, r.ParentKey, c.Name, c.Path)
		}
		lintParentKey(c, w)
	}
}

func convertResource(name string, y *yamlResource) *tree.Resource {
	r := &tree.Resource{
		Name: name, Description: y.Description, Path: y.Path, Singular: y.Singular, ParentKey: y.ParentKey,
		Operations: map[string]*tree.Operation{}, Children: map[string]*tree.Resource{},
	}
	for verb, op := range y.Operations {
		r.Operations[verb] = convertOperation(verb, op)
	}
	for cname, c := range y.Children {
		child := convertResource(cname, c)
		child.Parent = r // 回填祖先链指针（T4 ResolveURL 与 T3 description 富化共用）
		r.Children[cname] = child
	}
	return r
}

func convertOperation(verb string, y *yamlOperation) *tree.Operation {
	op := &tree.Operation{Verb: verb, Method: y.Method, Path: y.Path, Description: y.Description, ContentType: y.ContentType}
	if op.Method == "" {
		op.Method = defaultMethod[verb] // 标准 verb 默认填充；自定义 verb 空 method 在 Validate 阶段报错
	}
	for pname, p := range y.Params {
		op.Params = append(op.Params, tree.Param{
			Name: pname, In: p.In, Type: p.Type, Required: p.Required,
			Enum: p.Enum, Pattern: p.Pattern, Format: p.Format, Description: p.Description,
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
	s := &tree.Schema{Type: y.Type, Required: y.Required, Description: y.Description, Format: y.Format}
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
