// Package main 是 api-cli 入口。
// 加载清单 → 构建 cobra 命令树；--mcp 时改为启动 MCP server。
package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

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
	// 顶层 flag（在 cobra 之前解析，因为 --mcp 改变整个入口）
	specPath := os.Getenv("API_CLI_SPEC")
	if len(os.Args) >= 2 && os.Args[1] == "--mcp" {
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
	root.PersistentFlags().String("spec", specPath, "清单文件路径")
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
