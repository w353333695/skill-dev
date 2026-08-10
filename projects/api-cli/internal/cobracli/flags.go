package cobracli

import (
	"fmt"
	"os"
	"time"

	"api-cli/internal/engine"
	"api-cli/internal/output"
	"api-cli/internal/tree"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// parentKV 父资源 ID 注入条目：{parent_key} 取父命令 args[0]。
type parentKV struct{ key string }

// flagBag 收集 operation 上每个 non-path param 的 flag 值指针。
// MVP 统一以 String flag 注册（type 校验交给后端；简单可用）。
type flagBag struct {
	strVals map[string]*string // 非 path 参数当前都按字符串收
}

func newFlagBag() *flagBag {
	return &flagBag{strVals: map[string]*string{}}
}

// splitParams 把 operation.Params 分成 path（位置/父注入）与 others（→ flag）。
func splitParams(op *tree.Operation) (pathParams, others []tree.Param) {
	for _, p := range op.Params {
		if p.In == "path" {
			pathParams = append(pathParams, p)
		} else {
			others = append(others, p)
		}
	}
	return
}

// registerParams 把 non-path param 注册成 cobra String flag。
// path 参数走位置 args 或父注入，不注册成 flag（避免双重入口）。
func registerParams(c *cobra.Command, op *tree.Operation, bag *flagBag) {
	for _, p := range op.Params {
		if p.In == "path" {
			continue
		}
		ptr := c.Flags().String(p.Name, "", p.Description)
		bag.strVals[p.Name] = ptr
	}
}

// values 取出 non-empty 的 flag 值，传给 engine 当 query/header/body 参数。
// 空 string 不传：让后端用默认值或必填校验报错。
func (b *flagBag) values(params []tree.Param) map[string]string {
	out := map[string]string{}
	for _, p := range params {
		if ptr, ok := b.strVals[p.Name]; ok && *ptr != "" {
			out[p.Name] = *ptr
		}
	}
	return out
}

// buildPathVals 构造 path 参数值：先填父注入（按 parentKeys 顺序吃 args[0..]），
// 再填自身 path 参数（吃剩余 args）。
//
// 注：parentKeys 仅在 child resource 命令链上累积；同一 args 列表里
// 父注入段在子命令消费前已被父级 args[0] 占用——cobra 子命令收到的 args
// 已剥掉父级，故这里把 args[0] 同时视作「本层 parent_key 值」即可。
func buildPathVals(pathParams []tree.Param, args []string, parentKeys []parentKV) map[string]string {
	vals := map[string]string{}
	idx := 0
	// 父注入：每条非空 key 消耗一个位置 arg
	for _, pk := range parentKeys {
		if pk.key == "" {
			continue
		}
		if idx < len(args) {
			vals[pk.key] = args[idx]
			idx++
		}
	}
	// 自身 path 参数：位置
	for _, p := range pathParams {
		if idx < len(args) {
			vals[p.Name] = args[idx]
			idx++
		}
	}
	return vals
}

// --- 全局 flag（spec §11.1） ---

// bindGlobalFlags 在 root 注册所有 Persistent flag，子命令继承。
func bindGlobalFlags(root *cobra.Command) {
	root.PersistentFlags().String("endpoint", "", "接入面（默认 service.default_endpoint）")
	root.PersistentFlags().String("format", "json", "输出格式 json|yaml|table")
	root.PersistentFlags().String("help-format", "text", "--help 输出格式 text|json")
	root.PersistentFlags().Bool("dry-run", false, "不真调，打印将发的请求")
	root.PersistentFlags().Bool("print-curl", false, "打印等价 curl")
	root.PersistentFlags().Bool("yes", false, "跳过写操作确认")
	root.PersistentFlags().Int("limit", 0, "分页拉取上限（条数）")
	root.PersistentFlags().Bool("all", false, "拉全部分页（受硬上限约束）")
	root.PersistentFlags().String("body-file", "", "请求 body JSON 文件路径（覆盖 body 参数，支持复杂/嵌套 body）")
	root.PersistentFlags().Bool("insecure", false, "跳过 TLS 证书校验（自签证书）")
	root.PersistentFlags().Duration("timeout", 0, "HTTP 超时（如 30s、500ms；0=不限）")
	root.PersistentFlags().StringP("output", "o", "", "输出到文件（binary 响应落盘 / 文本写文件，默认 stdout）")
}

// globalOpts 从 cobra command 取全局 flag → engine.Options。
// Out 默认指向 os.Stdout（spec §11.3）；--output 非空时改指向 os.Create 打开的文件，
// 并把句柄同时填进 OutCloser——RunE 在 Execute 后 defer Close（统一落盘生命周期）。
// endpoint 名不进 Options（Task 9 的 Options 无该字段），
// 由 operationCmd.RunE 单独取 --endpoint flag 后调 tr.SelectEndpoint。
func globalOpts(cmd *cobra.Command) (engine.Options, error) {
	f := cmd.Flags()
	opts := engine.Options{
		Format:    strFlag(f, "format"),
		DryRun:    boolFlag(f, "dry-run"),
		PrintCurl: boolFlag(f, "print-curl"),
		Yes:       boolFlag(f, "yes"),
		All:       boolFlag(f, "all"),
		Limit:     intFlag(f, "limit"),
		BodyFile:  strFlag(f, "body-file"),
		Insecure:  boolFlag(f, "insecure"),
		Timeout:   durationFlag(f, "timeout"),
		Out:       stdout(),
	}
	// --output/-o：非空 → 落盘。os.Create 失败（权限/路径不存在）转 APIError 退 param 错。
	// engine 不持有文件句柄，只写 opts.Out；句柄由 cobracli RunE defer Close。
	if out := strFlag(f, "output"); out != "" {
		fout, err := os.Create(out)
		if err != nil {
			return opts, &output.APIError{Code: "output_file", Message: err.Error(), ExitCode: output.ExitParamError}
		}
		opts.Out = fout
		opts.OutCloser = fout
	}
	if err := validateFormat(opts.Format); err != nil {
		return opts, err
	}
	return opts, nil
}

// strFlag/boolFlag/intFlag 是对 *pflag.FlagSet 的零副作用取值 helper。
// controller #3：cobra cmd.Flags() 返回 *pflag.FlagSet，helper 直接吃这个类型。
func strFlag(f *pflag.FlagSet, name string) string {
	v, _ := f.GetString(name)
	return v
}
func boolFlag(f *pflag.FlagSet, name string) bool {
	v, _ := f.GetBool(name)
	return v
}
func intFlag(f *pflag.FlagSet, name string) int {
	v, _ := f.GetInt(name)
	return v
}
func durationFlag(f *pflag.FlagSet, name string) time.Duration {
	v, _ := f.GetDuration(name)
	return v
}

// validateFormat 校验 --format 取值。
func validateFormat(f string) error {
	switch f {
	case "json", "yaml", "table":
		return nil
	}
	return &output.APIError{Code: "bad_format", Message: fmt.Sprintf("不支持的 format %q", f), ExitCode: output.ExitParamError}
}
