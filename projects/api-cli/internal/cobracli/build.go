// Package cobracli 把 OperationTree 动态编译成 cobra 命令树。
//
// 入口：Build(*tree.OperationTree) → *cobra.Command。
// 行为：每个 resource → 一个 resource 命令（递归 children → N 层），
// 每个 operation → 一个 verb 子命令，non-path 参数注册成 flag，
// RunE 调 engine.Execute 完成请求组装/执行/输出。
// 全局 Persistent flag（--endpoint/--format/--help-format/--dry-run/--print-curl/--yes/--limit/--all）
// 在 root 注册，子命令继承。--help-format=json 时 root 的 HelpFunc 把叶子命令
// 反查 OperationTree 后序列化成结构化 JSON（供 LLM 发现）。
package cobracli

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"api-cli/internal/engine"
	"api-cli/internal/tree"

	"github.com/spf13/cobra"
)

// ErrHelpRequested 表示 --help-format != text 触发了 help（非错误，main 据此 exit 0）。
// cobra 的内置 --help 检查在 PersistentPreRunE 之前，无法靠它；改为在此主动拦截：
// help-format 非 text 时调 cmd.Help()（复用 helpFunc）并返回 sentinel，让 cobra 跳过 RunE。
var ErrHelpRequested = errors.New("help requested via --help-format")

// Build 构建根命令树并绑定全局 flag 与 help 钩子。
func Build(tr *tree.OperationTree) (*cobra.Command, error) {
	root := &cobra.Command{
		Use:              tr.Service.Name,
		Short:            tr.Service.Name + " CLI（声明式生成）",
		SilenceUsage:     true,
		SilenceErrors:    true,
		TraverseChildren: true, // 全局 flag（--insecure/--spec）可放子命令前
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			hf, _ := cmd.Flags().GetString("help-format")
			if hf != "text" {
				if err := cmd.Help(); err != nil {
					return err
				}
				return ErrHelpRequested
			}
			return nil
		},
	}
	bindGlobalFlags(root)
	e := engine.New(tr)
	for _, r := range tr.Resources {
		root.AddCommand(resourceCmd(tr, e, r, nil))
	}
	root.AddCommand(explainCmd(tr))
	root.SetHelpFunc(helpFunc(tr))
	return root, nil
}

// resourceCmd 递归构建资源命令（含 children → N 层）。
// parentKeys：累积的父 ID 注入键（{parent_key} → 父命令 args[0]）。
func resourceCmd(tr *tree.OperationTree, e *engine.Engine, r *tree.Resource, parentKeys []parentKV) *cobra.Command {
	c := &cobra.Command{Use: r.Name, Short: desc(r)}
	for verb, op := range r.Operations {
		c.AddCommand(operationCmd(tr, e, r, op, verb, parentKeys))
	}
	for _, child := range r.Children {
		// 进入 child 时把当前 resource 的 ParentKey 累积进 parentKeys；
		// child path 模板里的 {parent_key} 用父命令 args[0] 填。
		c.AddCommand(resourceCmd(tr, e, child, append(parentKeys, parentKV{key: r.ParentKey})))
	}
	return c
}

// operationCmd 构建 operation 子命令：注册 flag，RunE 调 engine。
// Annotations 把 resource/verb 别在命令上，供 help-format=json 反查。
func operationCmd(tr *tree.OperationTree, e *engine.Engine, r *tree.Resource, op *tree.Operation, verb string, parentKeys []parentKV) *cobra.Command {
	pathParams, otherParams := splitParams(op)
	bag := newFlagBag()

	c := &cobra.Command{
		Use:   verb,
		Short: op.Verb + " " + r.Singular,
		Annotations: map[string]string{
			"resource": r.Name,
			"verb":     verb,
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			opts, err := globalOpts(cmd)
			if err != nil {
				return err
			}
			pathVals := buildPathVals(pathParams, args, parentKeys)
			flags := bag.values(otherParams)
			// endpoint 名取自 --endpoint flag（空 → SelectEndpoint 走 service.default_endpoint）。
			// Task 9 engine.Options 无 Endpoint 字段，所以这里单独取 flag 后传 *tree.Endpoint 进 engine。
			epName, _ := cmd.Flags().GetString("endpoint")
			ep, err := tr.SelectEndpoint(epName)
			if err != nil {
				return err
			}
			return e.Execute(cmd.Context(), ep, r, op, pathVals, flags, opts)
		},
	}
	registerParams(c, op, bag)
	return c
}

// desc 给 resource 命令拼一句中文短描述。
func desc(r *tree.Resource) string {
	if r.Singular != "" {
		return r.Singular + " 资源"
	}
	return r.Name + " 资源"
}

// explainCmd: api-cli explain <resource> <verb> → 输出 operation 的 input+output schema（json）。
// 给人/LLM 一份结构化描述（resource/verb/method/path/params/input_body/output），
// 不发请求、不需要 endpoint；从 OperationTree 直接查。资源/操作不存在 → 非零退出。
func explainCmd(tr *tree.OperationTree) *cobra.Command {
	return &cobra.Command{
		Use:   "explain [resource] [verb]",
		Short: "输出某 operation 的 input/output schema（给人/LLM）",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			r, ok := tr.Resources[args[0]]
			if !ok {
				return fmt.Errorf("资源 %q 不存在", args[0])
			}
			op, ok := r.Operations[args[1]]
			if !ok {
				return fmt.Errorf("操作 %q 不存在", args[1])
			}
			doc := map[string]any{
				"resource": r.Name,
				"verb":     op.Verb,
				"method":   op.Method,
				"path":     op.Path,
				"params":   op.Params,
			}
			if op.Body != nil {
				doc["input_body"] = op.Body.ToJSONSchema()
			}
			if op.Response != nil {
				doc["output"] = op.Response.ToJSONSchema()
			}
			enc := json.NewEncoder(os.Stdout)
			enc.SetIndent("", "  ")
			return enc.Encode(doc)
		},
	}
}
