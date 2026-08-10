// Package tree 是 api-cli 的内部统一模型（OperationTree）。
// 纯数据、零依赖（不 import cobra/net/http）。importer 产它，cobra/MCP/engine 消费它。
package tree

// OperationTree 清单解析后的统一模型。
type OperationTree struct {
	Service   Service
	Resources map[string]*Resource
}

// Service 服务级配置。
type Service struct {
	Name            string
	Version         string
	DefaultEndpoint string
	Endpoints       map[string]*Endpoint
}

// Endpoint 接入面：同一资源模型挂不同接入面的差异打包于此。
type Endpoint struct {
	Name            string
	BaseURL         string // 支持 ${ENV} 占位（parse 阶段展开）
	Auth            string // 引用 ~/.api-cli/auth.d/<name>.yaml
	PathPrefix      string
	Host            string   // 自定义 Host header（如 openapi 走 IP 直连 + 改 host 的场景）
	AllowOperations []string // 预留，MVP 不启用
	Headers         map[string]string // endpoint 级固定 header（每个请求都带）；值支持 ${ENV}，operation 级 header 参数可覆盖
}

// Resource 资源定义（命令树节点）。
type Resource struct {
	Name        string
	Description string // 资源用途（LLM 抉择 + cobra Short）；空 = 回退旧文案
	Path        string
	Singular    string
	ParentKey   string // 父 ID 注入到子命令 path 模板的键名
	Operations  map[string]*Operation
	Children    map[string]*Resource // 递归 → N 层
	Parent      *Resource            // 祖先链上溯指针（spec.Parse 回填）；顶层 resource 为 nil
}

// Operation 一个动作（verb 是身份，method 是配置）。
type Operation struct {
	Verb        string
	Method      string // 内部模型永远必填（parse 阶段对标准 verb 填默认值）
	Path        string // 相对 resource.Path，含 {param} 模板
	Description string // 操作用途（LLM 抉择 + cobra Short）；空 = 回退 verb+singular
	ContentType string // 请求体类型：空/"json" = JSON（默认）；"multipart-form-data" = 文件上传
	Params      []Param
	Body        *Schema     // nil = 无 body
	Response    *Schema     // nil = 无 response schema（outputSchema）
	Pagination  *Pagination // nil = 无分页
}

// Param 一个入参。
type Param struct {
	Name        string
	In          string // path|query|header|body|formData
	Type        string // 空 = any（透传）
	Required    bool
	Enum        []string
	Pattern     string
	Format      string // 空 = 普通；"binary" = 文件（仅 in=formData）
	Description string
	Example     any
}

// Pagination 分页声明。
type Pagination struct {
	Type          string // cursor|offset|implicit
	ItemsPath     string // GJSON path
	NextTokenPath string // cursor：从响应抽 next token 的路径
	PageParam     string // offset：请求页码参数名
	SizeParam     string // offset：请求每页大小参数名
	Size          int    // offset：每页大小
	HasMorePath   string // 空 → 引擎用 "本轮条数 < size 或 items 空" 隐式判断
	PageIn        string // page 在哪：空/"query" 默认 / "body"
}

// Schema 参数/body/response 的结构描述（MVP 用最小子集，支持 type/required/properties）。
type Schema struct {
	Type                 string
	Required             []string
	Properties           map[string]*Schema
	Items                *Schema // type=array 时
	Description          string
	Format               string // 空 = 普通；"binary" = 二进制流响应（仅 response 用）
	Example              any   // 动态结构示例（LLM 理解核心）
	AdditionalProperties *bool // 允许任意 key（MongoDB query 等）；nil = 不出现该字段
}
