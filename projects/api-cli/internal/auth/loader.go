package auth

import (
	"fmt"
	"os"
	"path/filepath"

	"api-cli/pkg/adapter"
	"gopkg.in/yaml.v3"
)

// config 是 ~/.api-cli/auth.d/<name>.yaml 的结构。
type config struct {
	Provider string         `yaml:"provider"`
	Config   map[string]any `yaml:"config"`
}

// Load 按 auth 引用名加载 provider。
// 先查内置（bearer/oauth2/hmac），其余走外部 go-plugin（Task 11 实现）。
func Load(name string) (adapter.AuthProvider, error) {
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
		// 外部 adapter：Task 11 实现 LoadPlugin。
		return nil, fmt.Errorf("外部 adapter %q 暂未实现（Task 11）", cfg.Provider)
	}
}

func readConfig(name string) (*config, error) {
	path := filepath.Join(authDir(), name+".yaml")
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
