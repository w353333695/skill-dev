package auth

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"api-cli/pkg/adapter"

	"github.com/hashicorp/go-plugin"
)

// LoadPlugin 启动外部 adapter 二进制（go-plugin net/rpc 模式）并返回已 Configure 的 AuthProvider。
//
// 流程：
//  1. readConfig 读 ~/.api-cli/auth.d/<name>.yaml 拿到 provider 名（外部二进制名）+ config 段。
//  2. findAdapterBin 在 PATH 和 ~/.api-cli/bin/ 找可执行文件。
//  3. plugin.NewClient 启动子进程并完成 go-plugin 握手（Handshake + Magic Cookie）。
//  4. Dispense(adapter.PluginNameAuth) 拿到 authRPCClient（实现 AuthProvider）。
//  5. 用 cfg.Config 调 Configure 注入配置。
//
// 返回的 AuthProvider 由 go-plugin 子进程支撑；调用方用完应通过 client.Kill() 关闭进程。
// 当前 MVP 不暴露 client 句柄（进程生命周期由 process 退出时一并清理），Task 14 再细化。
func LoadPlugin(name string) (adapter.AuthProvider, error) {
	cfg, err := readConfig(name)
	if err != nil {
		return nil, err
	}
	bin, err := findAdapterBin(cfg.Provider)
	if err != nil {
		return nil, err
	}

	// 注意：这里把 client 句柄丢了，所以本函数没有显式 Kill 通道。
	// go-plugin 子进程在 host 进程退出时（rpcClient 关闭/父进程死）会被一并回收，
	// MVP 单进程 CLI 场景足够；长驻 daemon 场景需 Task 14 暴露关闭通道。
	client := plugin.NewClient(&plugin.ClientConfig{
		HandshakeConfig: adapter.Handshake,
		Plugins: map[string]plugin.Plugin{
			adapter.PluginNameAuth: &adapter.AuthPlugin{},
		},
		Cmd: exec.Command(bin),
	})

	rpcClient, err := client.Client()
	if err != nil {
		client.Kill()
		return nil, fmt.Errorf("go-plugin 握手失败 (%s): %w", cfg.Provider, err)
	}
	raw, err := rpcClient.Dispense(adapter.PluginNameAuth)
	if err != nil {
		client.Kill()
		return nil, fmt.Errorf("Dispense %s 失败: %w", adapter.PluginNameAuth, err)
	}
	p, ok := raw.(adapter.AuthProvider)
	if !ok {
		client.Kill()
		return nil, fmt.Errorf("外部 adapter %s 未实现 adapter.AuthProvider", cfg.Provider)
	}
	if err := p.Configure(cfg.Config); err != nil {
		client.Kill()
		return nil, fmt.Errorf("外部 adapter %s Configure 失败: %w", cfg.Provider, err)
	}
	return p, nil
}

// findAdapterBin 按名字找外部 adapter 二进制：
//  1. exec.LookPath 在 PATH 里找（系统安装的 adapter）。
//  2. $HOME/.api-cli/bin/<name> 用户私有目录（无需 sudo 即可加新 adapter）。
//
// 找不到返回含 name 的错误，便于调用方在配置错误时定位。
func findAdapterBin(name string) (string, error) {
	if path, err := exec.LookPath(name); err == nil {
		return path, nil
	}
	home, _ := os.UserHomeDir()
	cand := filepath.Join(home, ".api-cli", "bin", name)
	if _, err := os.Stat(cand); err == nil {
		return cand, nil
	}
	return "", fmt.Errorf("找不到 adapter 二进制 %q（PATH 或 %s）", name, cand)
}
