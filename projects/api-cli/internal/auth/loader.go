package auth

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"api-cli/pkg/adapter"
	"gopkg.in/yaml.v3"
)

// config 是 ~/.api-cli/auth.d/<name>.yaml 的结构。
type config struct {
	Provider string         `yaml:"provider"`
	Config   map[string]any `yaml:"config"`
}

// providerCache 进程内 provider 缓存，按配置文件的绝对路径为键。
//
// 为什么按路径而非 provider 名：
//   - engine.Execute 每个请求都调 Load，外部 adapter（LoadPlugin）每次启新 go-plugin
//     子进程；不加缓存 → 子进程泄漏 + client 句柄丢失。命中缓存直接返回首次构造的实例。
//   - 键含 HOME（authDir() 读 os.UserHomeDir），不同 HOME 下同名 provider 路径不同 →
//     天然隔离，既有测试（每个用 t.TempDir 设独立 HOME）不会被全局 cache 串扰。
//
// 并发：单线程 CLI 场景足够；仍加锁保护，构造期间短暂释放锁以避免阻塞其他读，
// 回锁后做 "已存在则用旧的" 兜底，保证同名只缓存一个实例。
var (
	providerCache = make(map[string]adapter.AuthProvider)
	providerMu    sync.Mutex
)

// Load 按 auth 引用名加载 provider，命中进程内缓存则直接返回。
// 先查内置（bearer/oauth2/hmac），其余走外部 go-plugin（Task 11 实现）。
func Load(name string) (adapter.AuthProvider, error) {
	key := configPath(name)

	providerMu.Lock()
	if p, ok := providerCache[key]; ok {
		providerMu.Unlock()
		return p, nil
	}
	providerMu.Unlock()

	p, err := loadUncached(name)
	if err != nil {
		return nil, err
	}

	providerMu.Lock()
	defer providerMu.Unlock()
	// 并发兜底：若他人已先一步存入，复用已有的（保证单例）；否则本次构造入缓存。
	if existing, ok := providerCache[key]; ok {
		return existing, nil
	}
	providerCache[key] = p
	return p, nil
}

// loadUncached 读配置 + 构造 provider（内置直接 new，外部走 LoadPlugin）。
// 不查缓存、不写缓存，供 Load 的 cache-miss 路径调用。
func loadUncached(name string) (adapter.AuthProvider, error) {
	cfg, err := readConfig(name)
	if err != nil {
		return nil, err
	}
	switch cfg.Provider {
	case "bearer":
		return configured(&BearerAuth{}, cfg.Config)
	case "oauth2":
		return configured(&OAuth2CC{}, cfg.Config)
	case "hmac":
		return configured(&HMACSign{}, cfg.Config)
	default:
		// 外部 adapter：go-plugin 启动子进程装载（net/rpc 模式）。
		return LoadPlugin(name)
	}
}

func readConfig(name string) (*config, error) {
	path := configPath(name)
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取鉴权配置 %s 失败: %w", path, err)
	}
	var c config
	if err := yaml.Unmarshal(raw, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

// configPath 返回 auth 引用名对应的配置文件绝对路径（也作 provider cache 键）。
func configPath(name string) string {
	return filepath.Join(authDir(), name+".yaml")
}

func authDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".api-cli", "auth.d")
}

func configured(p adapter.AuthProvider, c map[string]any) (adapter.AuthProvider, error) {
	if err := p.Configure(c); err != nil {
		return nil, err
	}
	return p, nil
}
