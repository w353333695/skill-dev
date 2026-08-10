// Package engine 是 api-cli 的执行核心：组装请求 → 写操作闸门 → auth 注入 →
// http.Do → 分页/单次 → 输出 + 错误归一化。它把 tree（模型）/output（格式化）/
// auth（鉴权）/paging（分页）四个内部包串成一条数据流（spec §3.2）。
package engine

import (
	"encoding/json"
	"fmt"

	"api-cli/internal/tree"
)

// resolvedReq 组装好的请求各部分。
//   - Method/URL 已填 path 参数（ResolveURL 物化）
//   - Query/Header/Body 来自 flag（按 param.In 分发）
//   - Host 来自 endpoint.Host（自定义 Host header，IP 直连场景）
type resolvedReq struct {
	Method string
	URL    string
	Host   string
	Query  map[string]string
	Header map[string]string
	Body   []byte
}

// resolve 把 operation + flag 值物化成 resolvedReq。
//   - pathVals：path 参数值（来自位置参数 / --id flag）
//   - flags：其余 flag（按 param.In 分发到 query/header/body）
//
// URL 物化委托给 tree.ResolveURL —— 后者签名 (ep, r, op, vals) 内部已拼
// r.Path + op.Path，engine 不再二次拼接（controller 修正 #1）。
func resolve(tr *tree.OperationTree, ep *tree.Endpoint, r *tree.Resource, op *tree.Operation,
	pathVals, flags map[string]string) (*resolvedReq, error) {
	url, err := tr.ResolveURL(ep, r, op, pathVals)
	if err != nil {
		return nil, err
	}
	req := &resolvedReq{Method: op.Method, URL: url, Host: ep.Host, Query: map[string]string{}, Header: map[string]string{}}

	// body 参数：MVP 单层 JSON 对象（key=param.Name, value=flag 字符串）。
	// 命中任意 body 参数才 marshal，避免无 body 时打印 "null"。
	bodyParams := map[string]string{}
	for _, p := range op.Params {
		v, ok := flags[p.Name]
		if !ok {
			continue
		}
		switch p.In {
		case "query":
			req.Query[p.Name] = v
		case "header":
			req.Header[p.Name] = v
		case "body":
			bodyParams[p.Name] = v
		}
	}
	if len(bodyParams) > 0 {
		b, err := json.Marshal(bodyParams)
		if err != nil {
			return nil, fmt.Errorf("body 序列化失败: %w", err)
		}
		req.Body = b
	}
	return req, nil
}
