package engine

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"

	"api-cli/internal/auth"
	"api-cli/internal/output"
	"api-cli/internal/paging"
	"api-cli/internal/tree"
	"api-cli/pkg/adapter"
)

// Options 单次执行选项（来自全局/命令 flag）。
type Options struct {
	Format    string    // json|yaml|table（空 = json）
	DryRun    bool      // 不真发，打印请求预览
	PrintCurl bool      // 不真发，打印等价 curl 命令
	Yes       bool      // 跳过写操作确认
	All       bool      // 分页：拉到尽头（受 paging.MaxItems 硬上限约束）
	Limit     int       // 分页：拉够 N 条就停（0 = 不限）
	BodyFile  string    // 请求 body JSON 文件路径（覆盖 body 参数；支持复杂/嵌套 body）
	BodyBytes []byte    // 请求 body 字节（MCP _body marshal 后注入；优先级最高，覆盖 --body-file/body flag）
	Insecure  bool      // 跳过 TLS 证书校验（自签证书场景）
	Out       io.Writer // 输出目标（默认 os.Stdout；测试注入 bytes.Buffer）
}

// Engine 执行器。可被 cobracli/mcp 共用。
type Engine struct {
	tr         *tree.OperationTree
	hc         *http.Client // 默认安全 client
	insecureHC *http.Client // --insecure 时用（lazy，sync.Once）
	once       sync.Once
}

// New 构造执行器。
func New(tr *tree.OperationTree) *Engine {
	return &Engine{tr: tr, hc: &http.Client{}}
}

// insecureClient lazy 构造跳过 TLS 校验的 client（自签证书场景）。
// sync.Once 保证全局只创建一个，MCP 长驻高频也复用。
func (e *Engine) insecureClient() *http.Client {
	e.once.Do(func() {
		e.insecureHC = &http.Client{Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		}}
	})
	return e.insecureHC
}

// Execute 执行一次操作。cobracli（Task 10）/mcp（Task 12）的唯一入口。
// 返回归一化错误（*output.APIError 携 ExitCode）；调用方用 output.ExitCode 取退出码。
//
// 流程：resolve → body-file 覆盖 → gateWrite → dry-run/print-curl → auth.Apply → 选 client → 分页 or 单次 → 错误归一化 → 输出。
func (e *Engine) Execute(ctx context.Context, ep *tree.Endpoint, r *tree.Resource, op *tree.Operation,
	pathVals, flags map[string]string, opts Options) error {
	if opts.Out == nil {
		return &output.APIError{Code: "engine_options", Message: "Options.Out 未设置", ExitCode: output.ExitParamError}
	}
	req, err := resolve(e.tr, ep, r, op, pathVals, flags)
	if err != nil {
		return &output.APIError{Code: "resolve", Message: err.Error(), ExitCode: output.ExitParamError}
	}

	// body-file：覆盖 req.Body（支持复杂/嵌套 body，弥补单层 body 参数的不足）。
	if opts.BodyFile != "" {
		b, err := os.ReadFile(opts.BodyFile)
		if err != nil {
			return &output.APIError{Code: "body_file", Message: err.Error(), ExitCode: output.ExitParamError}
		}
		req.Body = b
	}

	// BodyBytes（MCP _body）：最高优先级，覆盖 --body-file 和 body 参数。
	// 用途：MCP tools/call 的 _body 是嵌套对象，单层 body flag（string map）marshal 不出来；
	// 由 mcp/server.go 提前 marshal 成字节，经此通道直传，绕过 resolve 的 flat 限制。
	if len(opts.BodyBytes) > 0 {
		req.Body = opts.BodyBytes
	}

	// 写操作闸门（create/update/delete 需 --yes 或 TTY 交互确认）。
	if err := gateWrite(op.Verb, opts); err != nil {
		return err
	}

	// dry-run / print-curl：渲染预览，不发请求。
	if opts.DryRun || opts.PrintCurl {
		fmt.Fprintln(opts.Out, renderPreview(req, opts))
		return nil
	}

	// auth.Apply：endpoint.Auth 空 / "none" 时跳过；其余按名加载 provider。
	// 直接 import pkg/adapter 构造 AuthRequest，删去 authReqAdapter/mergeAuth 迂回（controller 修正 #2）。
	if ep.Auth != "" && ep.Auth != "none" {
		provider, err := auth.Load(ep.Auth)
		if err != nil {
			return &output.APIError{Code: "auth_load", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		ar, err := provider.Apply(ctx, &adapter.AuthRequest{
			Method: req.Method, URL: req.URL, Body: req.Body, Headers: req.Header, Query: req.Query,
		})
		if err != nil {
			return &output.APIError{Code: "auth_apply", Message: err.Error(), ExitCode: output.ExitAuthError}
		}
		for k, v := range ar.Headers {
			req.Header[k] = v
		}
		for k, v := range ar.Query {
			req.Query[k] = v
		}
	}

	// 选 client：--insecure 用跳过 TLS 校验的（自签证书）。
	hc := e.hc
	if opts.Insecure {
		hc = e.insecureClient()
	}

	// 分页 vs 单次。
	if op.Pagination != nil {
		return e.iterate(ctx, req, op, opts, hc)
	}
	return e.single(ctx, req, op, opts, hc)
}

// single 发一次请求，把响应 decode 后整体交给 output.Format。
// format=table 时用 responseHeaders(op) 抽 Response schema 的字段 description 作中文表头。
func (e *Engine) single(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options, hc *http.Client) error {
	body, status, err := e.do(ctx, req, hc)
	if err != nil {
		return err
	}
	if status >= 400 {
		return output.NormalizeAPIError(status, body)
	}
	data := decodeLoose(body)
	if opts.Format == "table" {
		return output.FormatTable(opts.Out, data, responseHeaders(op))
	}
	return output.Format(opts.Out, opts.Format, data)
}

// responseHeaders 从 op.Response 抽 字段→description 映射（table 中文表头）。
// 响应若是 {data:{list:[{...}]}}，取 list 元素的 properties（这才是表格行对应的 schema）；
// 否则取 Response 顶层 properties。无 Response / 无 properties 返回空 map（退回用字段名）。
func responseHeaders(op *tree.Operation) map[string]string {
	h := map[string]string{}
	if op == nil || op.Response == nil || op.Response.Properties == nil {
		return h
	}
	target := op.Response
	if d := op.Response.Properties["data"]; d != nil && d.Properties != nil {
		if lst := d.Properties["list"]; lst != nil && lst.Items != nil {
			target = lst.Items
		}
	}
	if target.Properties == nil {
		return h
	}
	for k, v := range target.Properties {
		if v != nil && v.Description != "" {
			h[k] = v.Description
		}
	}
	return h
}

// iterate 走 paging.Iter 流式 NDJSON：每行一个 item.Raw（已是 JSON）。
// firstQuery = req.Query 作为翻页种子（cursor/offset 参数由 paging 引擎注入/递增）；
// firstBody = req.Body 用于 page-in-body（PageIn=body 时翻页改 body 副本的 page 号）。
//
// 错误反馈：paging.Iter 的 DoFunc（即下方 do）出错时，Iter 会发一个 Item{Err}
// 再 close channel。do 已把网络错误归一化成 *output.APIError{ExitNetTimeout}、
// 把 HTTP >= 400 归一化成 NormalizeAPIError；这里收到 it.Err 直接返回，
// 保证翻页中途失败时 Execute 返回非 nil err（exit 非 0），不让截断数据蒙混过关。
func (e *Engine) iterate(ctx context.Context, req *resolvedReq, op *tree.Operation, opts Options, hc *http.Client) error {
	first := copySS(req.Query)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		r2 := *req
		r2.Query = q
		if len(body) > 0 {
			r2.Body = body // page-in-body 翻页改 body（bumpBodyPage 递增后的副本）
		}
		b, status, err := e.do(ctx, &r2, hc)
		if err != nil {
			return nil, err
		}
		if status >= 400 {
			return nil, output.NormalizeAPIError(status, b)
		}
		return b, nil
	}
	limit := opts.Limit
	if opts.All {
		limit = 0 // 0 = 不限，受 paging.Options.MaxItems 硬上限约束
	}
	items := paging.Iter(ctx, op.Pagination, do, req.Body, first, paging.Options{Limit: limit})
	for it := range items {
		if it.Err != nil {
			// do 已归一化；若上层传入非 *output.APIError，兜底包一层保证带 exit code。
			if _, ok := it.Err.(*output.APIError); ok {
				return it.Err
			}
			return &output.APIError{Code: "paging", Message: it.Err.Error(), ExitCode: output.ExitNetTimeout}
		}
		fmt.Fprintln(opts.Out, string(it.Raw))
	}
	return nil
}

// do 发一次 HTTP 请求，返回 body + status。网络错误归一化成 ExitNetTimeout/ExitNet 类。
func (e *Engine) do(ctx context.Context, req *resolvedReq, hc *http.Client) ([]byte, int, error) {
	var bodyReader io.Reader
	if req.Body != nil {
		bodyReader = bytes.NewReader(req.Body)
	}
	httpReq, err := http.NewRequestWithContext(ctx, req.Method, req.URL, bodyReader)
	if err != nil {
		return nil, 0, &output.APIError{Code: "build_request", Message: err.Error(), ExitCode: output.ExitParamError}
	}
	// endpoint.Host 设了就覆盖 httpReq.Host（Go 的 Request.Host 优先于 Header["Host"]），
	// 用于 IP 直连 + 自定义 Host 的场景（如 EasyOps openapi 走 openapi.easyops-only.com）。
	if req.Host != "" {
		httpReq.Host = req.Host
	}
	for k, v := range req.Header {
		// Go 的 client 不会发 Header map 里的 Host（Request.Write 用 req.Host，忽略 Header["Host"]）；
		// 故 auth provider（如 easyops-openapi）回传的 host header 在此转写回 httpReq.Host，否则被静默丢弃。
		// auth host 覆盖 endpoint.Host：auth 是接入方案的权威声明。
		if strings.EqualFold(k, "host") {
			httpReq.Host = v
			continue
		}
		httpReq.Header.Set(k, v)
	}
	q := httpReq.URL.Query()
	for k, v := range req.Query {
		q.Set(k, v)
	}
	httpReq.URL.RawQuery = q.Encode()

	resp, err := hc.Do(httpReq)
	if err != nil {
		return nil, 0, &output.APIError{Code: "net", Message: err.Error(), ExitCode: output.ExitNetTimeout}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return body, resp.StatusCode, nil
}

// renderPreview 渲染 dry-run / curl 预览。
func renderPreview(req *resolvedReq, opts Options) string {
	if opts.PrintCurl {
		curl := "curl -X " + req.Method + " '" + req.URL + "'"
		for k, v := range req.Header {
			curl += " -H '" + k + ": " + v + "'"
		}
		if req.Body != nil {
			curl += " -d '" + string(req.Body) + "'"
		}
		if opts.Insecure {
			curl += " --insecure"
		}
		return curl
	}
	return fmt.Sprintf("DRY-RUN %s %s insecure=%v query=%v header=%v body=%s",
		req.Method, req.URL, opts.Insecure, req.Query, req.Header, req.Body)
}

// copySS 浅拷贝 map[string]string。
func copySS(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// decodeLoose 宽松 decode：JSON 成功就用对象，失败原样当字符串（避免非 JSON 响应炸）。
func decodeLoose(b []byte) any {
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return string(b)
	}
	return v
}
