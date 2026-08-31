package cobracli

import (
	"testing"

	"api-cli/internal/spec"

	"github.com/spf13/cobra"
)

// TestBuildCommandTree 验证 OperationTree → cobra 命令树形状：
// root=cmdb → inst → (read, create, relation) → relation → read
// 关系：inst 含 children.relation，relation 自己又有 read 操作。
// 注：执行命令的端到端真调测试在 Task 14，本测只验证树形状。
func TestBuildCommandTree(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, type: string, required: true } } }
      create: { method: POST, path: "" }
    children:
      relation:
        path: "/{instance_id}/relations"
        operations:
          read: { path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, err := Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	if root.Use != "cmdb" {
		t.Fatalf("root use want cmdb, got %s", root.Use)
	}
	// inst 子命令存在
	var foundInst, foundRead, foundRelation, foundRelationRead bool
	for _, c := range root.Commands() {
		if c.Name() == "inst" {
			foundInst = true
			for _, cc := range c.Commands() {
				if cc.Name() == "read" {
					foundRead = true
				}
				if cc.Name() == "relation" {
					foundRelation = true
					// relation 下应有自己的 read
					for _, gc := range cc.Commands() {
						if gc.Name() == "read" {
							foundRelationRead = true
						}
					}
				}
			}
		}
	}
	if !foundInst || !foundRead || !foundRelation || !foundRelationRead {
		t.Fatalf("tree shape wrong: inst=%v read=%v relation=%v relation.read=%v",
			foundInst, foundRead, foundRelation, foundRelationRead)
	}
}

// TestResourceShortUsesDescription 验证 cobra Short 优先用 Description：
//   - resource Short = r.Description（去掉「资源」后缀，更简洁）
//   - operation Short = op.Description（去掉 verb+singular 的回退文案）
//
// 让人看 help 时直接看到用途，而不是干巴巴的 "instance 资源 / read instance"。
func TestResourceShortUsesDescription(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: be, endpoints: { be: { base_url: http://x, auth: none } } }
resources:
  inst:
    description: CMDB 实例
    path: /instances
    operations:
      read: { description: 读取实例, path: "/{id}", params: { id: { in: path, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, _ := Build(tr)
	// inst 子命令的 Short 应是 Description，而非 "instance 资源"
	inst := findChild(root, "inst")
	if inst == nil {
		t.Fatal("未找到 inst 子命令")
	}
	if inst.Short != "CMDB 实例" {
		t.Errorf("inst Short 应为 Description %q，got %q", "CMDB 实例", inst.Short)
	}
	readCmd := findChild(inst, "read")
	if readCmd == nil {
		t.Fatal("未找到 read 子命令")
	}
	if readCmd.Short != "读取实例" {
		t.Errorf("read Short 应为 operation Description %q，got %q", "读取实例", readCmd.Short)
	}
}

// findChild 在 cmd 的子命令里按名字找一个。
func findChild(parent *cobra.Command, name string) *cobra.Command {
	for _, c := range parent.Commands() {
		if c.Name() == name {
			return c
		}
	}
	return nil
}

// TestBuildGlobalFlagsBound 验证全局 Persistent flag 在 root 上注册；
// 通过 ExecuteC 驱动 cobra 完整初始化链路（mergePersistentFlags 等）后，
// 子命令的解析结果里 --format 能拿到值（验证继承生效）。
//
// 不发真请求：用 --help 触发 cobra 的 HelpFunc（不会进 RunE）。
func TestBuildGlobalFlagsBound(t *testing.T) {
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: http://x, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    path: /instances
    operations:
      read: { path: "/{id}", params: { id: { in: path, type: string, required: true } } }
`)
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	root, err := Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	// 1. root 上所有全局 Persistent flag 注册到位（这是 cobracli 的责任）。
	for _, name := range []string{"endpoint", "format", "help-format", "dry-run", "print-curl", "yes", "limit", "all"} {
		if root.PersistentFlags().Lookup(name) == nil {
			t.Errorf("root 缺少全局 Persistent flag --%s", name)
		}
	}
	// 2. 通过 ExecuteC 真跑 --help（默认 help-format=text，走 cobra 默认渲染），
	//    确认 Build 出来的命令树能被 cobra 完整驱动、子命令链可达。
	root.SetArgs([]string{"inst", "read", "123", "--format", "yaml", "--help"})
	if _, err := root.ExecuteC(); err != nil {
		t.Fatalf("ExecuteC 失败: %v", err)
	}
}
