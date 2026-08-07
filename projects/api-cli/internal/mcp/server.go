// Package mcp 把 OperationTree 暴露为 MCP tools（stdio JSON-RPC 2.0 最小子集）。
//
// MVP 协议决策：不引完整 MCP SDK（go 生态 SDK 尚不成熟 + 控制依赖），
// 只实现三个方法：initialize / tools/list / tools/call。完整 SDK 接入留 V2。
//
// tools/call 反查 r/op 后调同一 engine.Execute（与 cobracli 共用执行路径）。
package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"

	"api-cli/internal/engine"
	"api-cli/internal/tree"
)

// Tool MCP tool 描述。InputSchema 用 map[string]any 直接序列化为 JSON Schema object。
type Tool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

// Server MCP server（持有 tree + engine；engine 内含 http.Client，可复用）。
type Server struct {
	tr *tree.OperationTree
	e  *engine.Engine
}

// New 构造 MCP server。
func New(tr *tree.OperationTree) *Server {
	return &Server{tr: tr, e: engine.New(tr)}
}

// ToolsList 枚举所有 operation → tool。
// tool 命名规则：service + "_" + resource_chain + "_" + verb（如 cmdb_inst_read）。
// resource_chain 含从顶层到当前 resource 的所有节点名（嵌套 children 时为 inst_relation）。
func (s *Server) ToolsList() []Tool {
	var tools []Tool
	walk(s.tr.Resources, s.tr.Service.Name, func(toolName, _, verb string, r *tree.Resource, op *tree.Operation) {
		props := map[string]any{}
		for _, p := range op.Params {
			props[p.Name] = map[string]any{
				"type":        orDefault(p.Type, "string"),
				"description": p.Description,
			}
		}
		desc := verb + " " + orDefault(r.Singular, r.Name)
		tools = append(tools, Tool{
			Name:        toolName,
			Description: desc,
			InputSchema: map[string]any{
				"type":       "object",
				"properties": props,
			},
		})
	})
	return tools
}

// walk 深度优先遍历 resource 树，prefix 是当前 resource 链（不含 verb）。
// 回调签名：visit(toolName, resName, verb, r, op)；toolName = prefix + "_" + verb。
func walk(resources map[string]*tree.Resource, prefix string,
	visit func(tool, res, verb string, r *tree.Resource, op *tree.Operation)) {
	for rname, r := range resources {
		for verb, op := range r.Operations {
			visit(prefix+"_"+rname+"_"+verb, rname, verb, r, op)
		}
		walk(r.Children, prefix+"_"+rname, visit)
	}
}

// orDefault 空字符串回落到默认值。
func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

// Serve 启动 stdio JSON-RPC 循环（initialize / tools/list / tools/call）。
// 逐行读，逐行写；空行跳过；解析失败的行静默忽略（避免坏输入打断整个会话）。
// 每个响应都带 jsonrpc=2.0 + 原请求 id（含通知 id=null 的边界情况）。
func (s *Server) Serve(ctx context.Context, in io.Reader, out io.Writer) error {
	sc := bufio.NewScanner(in)
	// MCP 单条消息可能携带较大 body schema，给到 1MB 上限。
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var req struct {
			JSONRPC string          `json:"jsonrpc"`
			ID      json.RawMessage `json:"id"`
			Method  string          `json:"method"`
			Params  json.RawMessage `json:"params"`
		}
		if err := json.Unmarshal(line, &req); err != nil {
			continue
		}
		resp := s.handle(ctx, req.Method, req.Params)
		// 通知（id 缺省）不出 result/error 之外的回包字段；这里仍回写以方便客户端定位。
		resp["jsonrpc"] = "2.0"
		if len(req.ID) > 0 {
			resp["id"] = json.RawMessage(req.ID)
		} else {
			resp["id"] = nil
		}
		b, _ := json.Marshal(resp)
		fmt.Fprintln(out, string(b))
	}
	return sc.Err()
}

// handle 派发 method → result/error。返回 map[string]any 由 Serve 拼装。
func (s *Server) handle(ctx context.Context, method string, params json.RawMessage) map[string]any {
	switch method {
	case "initialize":
		return map[string]any{
			"result": map[string]any{
				"protocolVersion": "2024-11-05",
				"serverInfo": map[string]any{
					"name":    s.tr.Service.Name + "-mcp",
					"version": "0.1.0",
				},
				"capabilities": map[string]any{
					"tools": map[string]any{},
				},
			},
		}
	case "tools/list":
		return map[string]any{"result": map[string]any{"tools": s.ToolsList()}}
	case "tools/call":
		return s.toolsCall(ctx, params)
	}
	return map[string]any{"error": map[string]any{"code": -32601, "message": "method not found: " + method}}
}

// toolsCall 反查 r/op → 分参 → engine.Execute。
// 成功：result.content[0].text = Execute 写入 buf 的内容；
// 失败：error.code = -32602（参数错）/ -32603（执行错）。
func (s *Server) toolsCall(ctx context.Context, params json.RawMessage) map[string]any {
	var p struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "invalid params: " + err.Error()}}
	}
	// tool name 形如 cmdb_inst_read → 反查 resource 与 operation。
	r, op := s.findByToolName(p.Name)
	if r == nil || op == nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "tool not found: " + p.Name}}
	}
	ep, err := s.tr.SelectEndpoint("") // 空名走 service.DefaultEndpoint
	if err != nil {
		return map[string]any{"error": map[string]any{"code": -32602, "message": "endpoint: " + err.Error()}}
	}
	pathVals, flags := splitArgs(op, p.Arguments)
	var buf bytes.Buffer
	if err := s.e.Execute(ctx, ep, r, op, pathVals, flags, engine.Options{
		Format: "json",
		Out:    &buf,
	}); err != nil {
		return map[string]any{"error": map[string]any{"code": -32603, "message": err.Error()}}
	}
	return map[string]any{
		"result": map[string]any{
			"content": []map[string]any{
				{"type": "text", "text": buf.String()},
			},
		},
	}
}

// findByToolName 遍历 resource 树，按 tool name 命中后返回 r/op。
// 命中第一个即返回（tool name 在清单正确前提下唯一）。
func (s *Server) findByToolName(name string) (*tree.Resource, *tree.Operation) {
	var foundR *tree.Resource
	var foundOp *tree.Operation
	walk(s.tr.Resources, s.tr.Service.Name, func(tn, _, _ string, r *tree.Resource, op *tree.Operation) {
		if tn == name && foundR == nil {
			foundR, foundOp = r, op
		}
	})
	return foundR, foundOp
}

// splitArgs 按 op.Params 的 in 字段把 arguments 拆成 pathVals / flags（query|header|body）。
// 缺省的参数不入字典（engine.resolve 会在必填时报错）。值统一转字符串（engine 仅消费字符串）。
func splitArgs(op *tree.Operation, args map[string]any) (pathVals, flags map[string]string) {
	pathVals = map[string]string{}
	flags = map[string]string{}
	for _, p := range op.Params {
		v, ok := args[p.Name]
		if !ok {
			continue
		}
		s := fmt.Sprint(v)
		if p.In == "path" {
			pathVals[p.Name] = s
		} else {
			flags[p.Name] = s
		}
	}
	return
}
