// Package spec 把 YAML 清单解析成 *tree.OperationTree。
package spec

// yamlManifest 与清单 1:1 映射的中间结构。
type yamlManifest struct {
	Spec      string                   `yaml:"spec"`
	Service   yamlService              `yaml:"service"`
	Resources map[string]*yamlResource `yaml:"resources"`
	Schemas   map[string]*yamlSchema   `yaml:"schemas"`
}

type yamlService struct {
	Name            string                   `yaml:"name"`
	Version         string                   `yaml:"version"`
	DefaultEndpoint string                   `yaml:"default_endpoint"`
	Endpoints       map[string]*yamlEndpoint `yaml:"endpoints"`
}

type yamlEndpoint struct {
	BaseURL         string            `yaml:"base_url"`
	Auth            string            `yaml:"auth"`
	PathPrefix      string            `yaml:"path_prefix"`
	Host            string            `yaml:"host"`
	AllowOperations []string          `yaml:"allow_operations"`
	Headers         map[string]string `yaml:"headers"` // endpoint 级固定 header（每个请求都带，如 easyops 的 org/user）
}

type yamlResource struct {
	Description string                    `yaml:"description"`
	Path        string                    `yaml:"path"`
	Singular    string                    `yaml:"singular"`
	ParentKey   string                    `yaml:"parent_key"`
	Operations  map[string]*yamlOperation `yaml:"operations"`
	Children    map[string]*yamlResource  `yaml:"children"`
}

type yamlOperation struct {
	Description string               `yaml:"description"`
	Method      string               `yaml:"method"`
	Path        string               `yaml:"path"`
	ContentType string               `yaml:"content_type"`
	Params      map[string]yamlParam `yaml:"params"`
	Body        *yamlSchema          `yaml:"body"`
	Response    *yamlSchema          `yaml:"response"`
	Pagination  *yamlPagination      `yaml:"pagination"`
}

type yamlParam struct {
	In          string   `yaml:"in"`
	Type        string   `yaml:"type"`
	Required    bool     `yaml:"required"`
	Enum        []string `yaml:"enum"`
	Pattern     string   `yaml:"pattern"`
	Format      string   `yaml:"format"`
	Description string   `yaml:"description"`
}

type yamlPagination struct {
	Type          string `yaml:"type"`
	ItemsPath     string `yaml:"items_path"`
	NextTokenPath string `yaml:"next_token_path"`
	PageParam     string `yaml:"page_param"`
	SizeParam     string `yaml:"size_param"`
	Size          int    `yaml:"size"`
	HasMorePath   string `yaml:"has_more_path"`
	PageIn        string `yaml:"page_in"`
}

type yamlSchema struct {
	Type                 string                 `yaml:"type"`
	Required             []string               `yaml:"required"`
	Properties           map[string]*yamlSchema `yaml:"properties"`
	Items                *yamlSchema            `yaml:"items"`
	Description          string                 `yaml:"description"`
	Format               string                 `yaml:"format"`
	Example              any                    `yaml:"example"`
	AdditionalProperties *bool                  `yaml:"additional_properties"`
}
