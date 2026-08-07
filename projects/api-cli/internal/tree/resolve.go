// resolve.go 实现 OperationTree 的 URL 物化与命令路径定位。
// 详见 brief task-4；ResolveURL 签名相对 brief 做了一处修正（见函数注释）。
package tree

import (
	"fmt"
	"strings"
)

// SelectEndpoint 按名字选接入面；空名用 service.DefaultEndpoint。
func (t *OperationTree) SelectEndpoint(name string) (*Endpoint, error) {
	if name == "" {
		name = t.Service.DefaultEndpoint
	}
	ep, ok := t.Service.Endpoints[name]
	if !ok {
		return nil, fmt.Errorf("endpoint %q 不存在", name)
	}
	return ep, nil
}

// ResolveURL 物化完整 URL：base_url + path_prefix + resource.path + operation.path，
// 再把 {param} 模板替换成 vals 提供的值。
//
// 签名说明（相对 brief 的修正）：op 不持有 resource 引用，但物化 URL 必须含
// resource.Path（如 /instances），否则拼出来的 URL 不正确。因此把 resource 作为
// 显式参数传入。后续 Task 9 engine 调用处需相应多传一个 r。
//
// 注：vals 只覆盖 path 参数；query/header/body 由 engine 单独处理。
func (t *OperationTree) ResolveURL(ep *Endpoint, r *Resource, op *Operation, vals map[string]string) (string, error) {
	if ep == nil {
		return "", fmt.Errorf("endpoint 为空")
	}
	if r == nil {
		return "", fmt.Errorf("resource 为空")
	}
	if op == nil {
		return "", fmt.Errorf("operation 为空")
	}
	// 1. 拼接 base + prefix + resource.path + operation.path
	full := joinPath(ep.BaseURL, ep.PathPrefix, r.Path, op.Path)
	// 2. 填 {param} 模板：仅 path 类参数；缺值且必填时报错
	for _, p := range op.Params {
		if p.In != "path" {
			continue
		}
		v, ok := vals[p.Name]
		if !ok {
			if p.Required {
				return "", fmt.Errorf("缺少 path 参数 %s", p.Name)
			}
			// 可选 path 参数缺值：原样保留 {name}，由调用方自行处理（MVP 罕见）
			continue
		}
		full = strings.ReplaceAll(full, "{"+p.Name+"}", v)
	}
	return full, nil
}

// joinPath 拼接多段路径，归一化斜杠（避免 //）。
// 第一段若含 "://"（scheme），保留其原有的双斜杠。
func joinPath(segs ...string) string {
	if len(segs) == 0 {
		return ""
	}
	out := segs[0]
	for _, s := range segs[1:] {
		if out != "" && !strings.HasSuffix(out, "/") && s != "" && !strings.HasPrefix(s, "/") {
			out += "/"
		}
		out += s
	}
	// 合并中间多余的斜杠（但保留 scheme:// 的双斜杠）
	out = strings.ReplaceAll(out, "://", "\x00SCHEME\x00")
	out = strings.ReplaceAll(out, "//", "/")
	out = strings.ReplaceAll(out, "\x00SCHEME\x00", "://")
	return out
}

// FindOperation 按命令路径（如 ["inst","read"] 或 ["inst","<id>","relation","read"]）定位资源与动作。
// 返回最终命中的 Resource 与 Operation。中间的占位段（如父资源 id）跳过。
func (t *OperationTree) FindOperation(path []string) (*Resource, *Operation, error) {
	if len(path) < 2 {
		return nil, nil, fmt.Errorf("命令路径过短")
	}
	res, ok := t.Resources[path[0]]
	if !ok {
		return nil, nil, fmt.Errorf("资源 %q 不存在", path[0])
	}
	return findInResource(res, path[1:])
}

// findInResource 递归在 resource 内定位：交替跳过 id 占位段 + 进入 children/operations。
func findInResource(r *Resource, segs []string) (*Resource, *Operation, error) {
	if len(segs) == 0 {
		return nil, nil, fmt.Errorf("缺少动词")
	}
	// 先尝试 segs[0] 为 verb
	if op, ok := r.Operations[segs[0]]; ok {
		return r, op, nil
	}
	// 否则 segs[0] 是 id 占位，segs[1] 应是 child 资源名
	if len(segs) >= 3 {
		if r.Children == nil {
			return nil, nil, fmt.Errorf("子资源 %q 不存在（资源 %q 无 children）", segs[1], r.Name)
		}
		child, ok := r.Children[segs[1]]
		if !ok {
			return nil, nil, fmt.Errorf("子资源 %q 不存在", segs[1])
		}
		return findInResource(child, segs[2:])
	}
	return nil, nil, fmt.Errorf("无法定位动作：%v", segs)
}
