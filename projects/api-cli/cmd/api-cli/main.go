// Package main 是 api-cli 入口。
// 加载清单 → 构建 cobra 命令树；--mcp 时改为启动 MCP server。
//
// 顶层 flag（--spec / --mcp）必须在 cobra 命令树构建之前解析：
//   - --spec 决定加载哪份清单，而清单决定整棵命令树的结构（resource/operation）；
//   - --mcp 改变整个入口（不再走 cobra，改跑 MCP server）。
//
// 所以这两个 flag 不能作为 cobra 的 persistent flag（cobra 解析时树已建好），
// 而是用 parseTopFlags 从 os.Args 起始段先抽走，剩余 token 再交给 cobra。
package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"api-cli/internal/cobracli"
	"api-cli/internal/mcp"
	"api-cli/internal/output"
	"api-cli/internal/spec"
)

func main() {
	if err := run(); err != nil {
		output.PrintError(os.Stderr, err)
		os.Exit(output.ExitCode(err))
	}
}

func run() error {
	specFlag, mcpMode, rest := parseTopFlags(os.Args[1:])
	// 解析优先级：--spec flag > API_CLI_SPEC 环境变量 > 默认搜索
	specPath := specFlag
	if specPath == "" {
		specPath = os.Getenv("API_CLI_SPEC")
	}
	if mcpMode {
		return runMCP(specPath)
	}
	raw, err := loadSpec(specPath)
	if err != nil {
		return err
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		return err
	}
	root, err := cobracli.Build(tr)
	if err != nil {
		return err
	}
	root.SetArgs(rest)
	return root.Execute()
}

func runMCP(specPath string) error {
	raw, err := loadSpec(specPath)
	if err != nil {
		return err
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		return err
	}
	srv := mcp.New(tr)
	return srv.Serve(context.Background(), os.Stdin, os.Stdout)
}

// loadSpec 按 --spec flag / 环境变量 / 默认搜索 找清单。
func loadSpec(explicit string) ([]byte, error) {
	if explicit != "" {
		return os.ReadFile(explicit)
	}
	candidates := []string{
		".api-cli/spec.yaml",
		filepath.Join(home(), ".api-cli", "specs", "spec.yaml"),
		"examples/cmdb.yaml", // 开发态便利
	}
	for _, c := range candidates {
		if b, err := os.ReadFile(c); err == nil {
			return b, nil
		}
	}
	return nil, fmt.Errorf("找不到清单（用 --spec 或 API_CLI_SPEC 指定，或放到 .api-cli/spec.yaml）")
}

func home() string {
	h, _ := os.UserHomeDir()
	return h
}

// parseTopFlags 从 args 起始段（首个子命令之前）抽取顶层 --spec / --mcp。
//
// 为什么要手写扫描而非 pflag：这俩 flag 必须在 cobra 之前解析（见包注释），
// 但 pflag 一旦遇到未知的子命令 flag（--fields/--endpoint/--help 等）会报错或吞掉，
// 破坏后续 cobra 解析。这里只认 --spec/--mcp 两个名字，遇到首个非 flag token
// （子命令起点）即停，把剩余原样交还 cobra。
//
// 返回 (specPath, mcpMode, rest)：
//   - specPath：--spec 的值（--spec <val> 或 --spec=<val>）；未给为 ""。
//   - mcpMode：--mcp / --mcp=true 出现即为 true（修 M5：不再只认 os.Args[1]）。
//   - rest：从首个子命令开始的全部 token，交给 cobra。
//
// 注意：--spec / --mcp 出现在子命令之后不被消费（原样进 rest），因为它们此时是
// 子命令的 flag 语义；顶层入口只认"子命令之前"的它们。
func parseTopFlags(args []string) (specPath string, mcpMode bool, rest []string) {
	i := 0
	for i < len(args) {
		a := args[i]
		switch {
		case a == "--":
			// POSIX 分隔符：之后全部是 positional，top 段结束
			rest = args[i+1:]
			return
		case a == "--mcp" || a == "--mcp=true":
			mcpMode = true
			i++
		case a == "--mcp=false":
			mcpMode = false
			i++
		case a == "--spec":
			// 下一个 token 是值；末尾无值则当作未给（loadSpec/env 兜底）
			if i+1 < len(args) {
				specPath = args[i+1]
				i += 2
			} else {
				i++
			}
		case strings.HasPrefix(a, "--spec="):
			specPath = strings.TrimPrefix(a, "--spec=")
			i++
		case isFlagToken(a):
			// 其他 flag（如顶层误写的 -h，或尚未到子命令就出现的子命令 flag）：
			// 不认识它是否吃值，保守只跳过它本身，不吞下一个 token，
			// 保证 rest 保留完整语义给 cobra 重新解析。
			i++
		default:
			// 首个非 flag token = 子命令起点，top 段结束
			rest = args[i:]
			return
		}
	}
	rest = nil
	return
}

// isFlagToken 判断一个 token 是否是 flag（以 "-" 开头，但不只是 "-"）。
func isFlagToken(a string) bool {
	return len(a) > 1 && a[0] == '-'
}
