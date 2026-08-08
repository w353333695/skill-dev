package engine

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"api-cli/internal/output"
)

// writeVerbs 写操作动词集合（默认要求 --yes / 交互确认）。
// read/list 等只读动词放行。
var writeVerbs = map[string]bool{"create": true, "update": true, "delete": true}

// gateWrite 写操作闸门：
//   - 非写操作：放行
//   - opts.Yes=true：跳过确认（脚本 / CI 场景）
//   - 否则需要 TTY 交互确认；非 TTY（管道/重定向）直接拒绝，避免误触
func gateWrite(verb string, opts Options) error {
	if !writeVerbs[verb] {
		return nil
	}
	if opts.Yes {
		return nil
	}
	if !isTTY() {
		return &output.APIError{
			Code:     "write_confirm",
			Message:  "写操作需 --yes 或 TTY 确认",
			ExitCode: output.ExitParamError,
		}
	}
	fmt.Fprintf(os.Stderr, "确认执行 %s ? [y/N] ", verb)
	sc := bufio.NewScanner(os.Stdin)
	if !sc.Scan() {
		return &output.APIError{
			Code:     "write_confirm",
			Message:  "未确认",
			ExitCode: output.ExitParamError,
		}
	}
	if strings.TrimSpace(strings.ToLower(sc.Text())) != "y" {
		return &output.APIError{
			Code:     "write_confirm",
			Message:  "用户取消",
			ExitCode: output.ExitParamError,
		}
	}
	return nil
}

// isTTY 判断 stdin 是否为字符设备（终端）。
func isTTY() bool {
	fi, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}
