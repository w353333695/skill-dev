package cobracli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"api-cli/internal/tree"

	"github.com/spf13/cobra"
)

// stdout 输出目标（默认 os.Stdout；测试可换。
// controller #2：globalOpts.Out 设为 os.Stdout）。
func stdout() io.Writer { return os.Stdout }

// emitHelpJSON 把命令树片段（resource+operation+params）序列化成 JSON，
// 供 --help-format=json 的 LLM 发现场景消费（spec §11.3）。
// controller #5：字段含 resource/verb/method/path/params/has_paging。
func emitHelpJSON(w io.Writer, r *tree.Resource, op *tree.Operation) error {
	doc := map[string]any{
		"resource":   r.Name,
		"verb":       op.Verb,
		"method":     op.Method,
		"path":       op.Path,
		"params":     op.Params,
		"has_paging": op.Pagination != nil,
	}
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(doc)
}

// helpFunc 返回 cobra 的 SetHelpFunc 回调。
//
// 行为：
//   - 取 --help-format flag；非 "json" 走 cobra 默认帮助。
//   - json 模式下，若当前命令有 Annotations（resource/verb），
//     从 OperationTree 反查 Resource/Operation，调 emitHelpJSON；
//     反查失败（如 annotations 指向已删资源）回退默认帮助。
//   - 非叶子命令（无 Annotations）也走默认帮助（在 N 层资源树上导航）。
//
// controller #4：完整接入，不留占位。
func helpFunc(tr *tree.OperationTree) func(c *cobra.Command, args []string) {
	return func(c *cobra.Command, args []string) {
		hf, _ := c.Flags().GetString("help-format")
		if hf == "json" {
			ann := c.Annotations
			if rname, verb, ok := fromAnnotations(ann); ok {
				if r, op, err := locate(tr, rname, verb); err == nil {
					if err := emitHelpJSON(stdout(), r, op); err == nil {
						return
					}
					// emitHelpJSON 出错时回退默认帮助（避免死寂）。
					fmt.Fprintln(os.Stderr, "help: 序列化失败，回退默认帮助:", err)
				}
			}
		}
		// 默认帮助：让 cobra 用内置模板渲染到 stdout。
		c.Root().UsageFunc()(c)
	}
}

// fromAnnotations 从命令 Annotations 取 resource/verb；缺任一即不是叶子 operation 命令。
func fromAnnotations(ann map[string]string) (resource, verb string, ok bool) {
	if ann == nil {
		return "", "", false
	}
	r, vr := ann["resource"], ann["verb"]
	if r == "" || vr == "" {
		return "", "", false
	}
	return r, vr, true
}

// locate 在 OperationTree 顶层 resources 里按名字 + verb 找 resource & operation。
// MVP：operation 命令不嵌在 child resource 下（child 有自己的 operationCmd，
// Annotations 是 child 的 resource 名，仍能在 tr.Resources 顶层命中——因为 child
// 在树里是父 resource 的子节点，但 operation 命令的 Annotation.resource 我们设的是
// 当前 r.Name。对 child 来说 r.Name=child 名，需要递归找。
// 这里写一个轻量递归查找，避免误报反查失败）。
func locate(tr *tree.OperationTree, rname, verb string) (*tree.Resource, *tree.Operation, error) {
	for _, r := range tr.Resources {
		if op, err := locateIn(r, rname, verb); err == nil {
			return op.r, op.op, nil
		}
	}
	return nil, nil, fmt.Errorf("未找到 resource=%s verb=%s", rname, verb)
}

type opHit struct {
	r  *tree.Resource
	op *tree.Operation
}

// locateIn 在子树内（含 children 递归）定位 resource+verb。
func locateIn(r *tree.Resource, rname, verb string) (opHit, error) {
	if r.Name == rname {
		if op, ok := r.Operations[verb]; ok {
			return opHit{r: r, op: op}, nil
		}
		// 名字命中但无该 verb：直接报错，不再下钻（防歧义）
		return opHit{}, fmt.Errorf("resource %q 无 verb %q", rname, verb)
	}
	for _, c := range r.Children {
		if op, err := locateIn(c, rname, verb); err == nil {
			return op, nil
		}
	}
	return opHit{}, fmt.Errorf("子树 %q 未命中 %s/%s", r.Name, rname, verb)
}
