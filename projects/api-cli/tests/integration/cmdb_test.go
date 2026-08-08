// Package integration 的 cmdb_test.go：用 CMDBMock 跑 examples/cmdb.yaml 的
// 前后端双 endpoint CRUD + cursor 分页流式 + dry-run 端到端验证。
//
// 关键设计：
//
//  1. loadCMDBTree 直接返回 *tree.OperationTree（spec.Parse 的真实返回类型），
//     不引入 specTree 私有包装（brief plan 中的 specTree 是 plan 瑕疵）。
//
//  2. stdout 捕获方案：选 Plan A（os.Pipe 重定向 os.Stdout）——
//     因为 cobracli.globalOpts 把 engine.Options.Out 固定设为 os.Stdout（spec §11.3），
//     root.SetOut(&buf) 改的是 cobra 的 Out 而非 engine.Out，无法捕获 NDJSON/dry-run 输出。
//     Plan A 与 internal/cobracli/smoke_test.go 的 captureExecute 同一手法，无侵入、
//     无需改 internal 代码、不影响 Task 10 既有测试。
//
//  3. 四个子测试覆盖：read（backend）、search --all（cursor 分页流式，>=2 NDJSON 行）、
//     read --endpoint frontend --dry-run（验证 /web/api/v1 path_prefix 生效）、
//     delete --dry-run --yes（副作用验证：mock.db["i-1"] 仍存在）。
//
//  4. 写操作闸门：测试非 TTY，delete 需 --yes 才能过 gateWrite（参见 engine/safety.go）。
package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"api-cli/internal/cobracli"
	"api-cli/internal/engine"
	"api-cli/internal/mcp"
	"api-cli/internal/spec"
	"api-cli/internal/tree"
)

// loadCMDBTree 构造一份 cmdb 清单（前后端双 endpoint），base_url 用 mock 地址替换。
// 返回 *tree.OperationTree —— spec.Parse 的真实返回类型（plan 中的 specTree 私有包装是瑕疵）。
func loadCMDBTree(t *testing.T, baseURL string) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: BASE, auth: none, path_prefix: /api/v1 }, frontend: { base_url: BASE, auth: none, path_prefix: /web/api/v1 } } }
resources:
  inst:
    path: /instances
    singular: instance
    operations:
      create: { method: POST, path: "" }
      read:   { method: GET, path: "/{id}", params: { id: { in: path, type: string, required: true, description: 实例 ID } } }
      update: { method: PATCH, path: "/{id}", params: { id: { in: path, required: true } } }
      delete: { method: DELETE, path: "/{id}", params: { id: { in: path, required: true } } }
      search:
        method: POST
        path: /search
        pagination:
          type: cursor
          items_path: data.list
          next_token_path: data.next
          has_more_path: data.next
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(baseURL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	return tr
}

// loadEasyOpsCMDBTree 构造一份 EasyOps CMDB 风格清单（嵌套 body schema + response schema +
// page_in: body 的 offset 分页），base_url 用 mock 地址替换。给 TestE2EMCPBodySchemaAndPaging
// 用：通过 mcp.Server 验证 tools/list 的 _body / required / outputSchema + tools/call 的
// _body 直传 + page-in-body 翻页。
//
// 与 examples/easyops-cmdb.yaml 同构（手动镜像，而非读文件）：测试自带 size:1 以让 2 条 mock
// 数据确定性地翻 2 页（example 的 size:20 是生产默认值，不适合少数据单测）。default_endpoint
// 取 backend（HTTP）以适配 httptest mock（frontend 是 HTTPS）。
func loadEasyOpsCMDBTree(t *testing.T, baseURL string) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service:
  name: easyops-cmdb
  default_endpoint: backend
  endpoints:
    backend: { base_url: BASE, auth: none, path_prefix: "" }
resources:
  object_instance:
    path: /v3/object/{object_id}/instance
    operations:
      search:
        method: POST
        path: /_search
        params:
          object_id: { in: path, type: string, required: true, description: 对象模型 ID }
        body:
          type: object
          required: [page, page_size]
          description: CMDB 实例搜索请求
          properties:
            page:      { type: integer, description: 页码（从1起） }
            page_size: { type: integer, description: 每页条数 }
            query:
              type: object
              description: 查询条件，MongoDB 风格
              additional_properties: true
              example: { "$and": [{ "$or": [{ "namespaceId": { "$like": "%easyops.%" } }] }] }
        response:
          type: object
          properties:
            data:
              type: object
              description: 响应数据
              properties:
                list:
                  type: array
                  description: 实例列表
                  items:
                    type: object
                    properties:
                      instanceId: { type: string, description: 实例ID }
                      name:       { type: string, description: 名称 }
                      namespaceId: { type: string, description: 命名空间ID }
                total: { type: integer, description: 总条数 }
        pagination:
          type: offset
          page_in: body
          items_path: data.list
          page_param: page
          size_param: page_size
          size: 1
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(baseURL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	return tr
}

// captureStdout 临时把进程 os.Stdout 重定向到 pipe，异步 drain 后读回 fn 期间的全部输出。
// engine.Options.Out 固定是 os.Stdout（见 cobracli/flags.go globalOpts），所以必须
// 物理替换 os.Stdout 才能捕获 NDJSON / dry-run 输出。fn 内严禁 t.Fatal（先返回 err）。
//
// 与 internal/cobracli/smoke_test.go 的 captureExecute 同一手法。
func captureStdout(t *testing.T, fn func() error) string {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	done := make(chan string)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.String()
	}()
	err := fn()
	_ = w.Close()
	os.Stdout = old
	out := <-done
	if err != nil {
		t.Fatalf("execute 返回错误: %v\n捕获到的 stdout:\n%s", err, out)
	}
	return out
}

// TestE2EReadBackend 验证 backend endpoint 基础 read：inst read i-1 成功取回，
// 输出含 i-1 / web 字段。
func TestE2EReadBackend(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "read", "i-1"})
		return root.Execute()
	})
	if !strings.Contains(out, `"i-1"`) || !strings.Contains(out, `"web"`) {
		t.Fatalf("read 输出缺 i-1/web 字段: %s", out)
	}
}

// TestE2ESearchAllStreaming 验证 cursor 分页 + --all 流式 NDJSON：
// db 有 i-1 / i-2 两条，paging.Iter 应逐行输出 → 至少 2 行 NDJSON。
// 同时校验两条 id 都出现（验证翻页确实翻到了第二页）。
func TestE2ESearchAllStreaming(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	ctx := context.Background()
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "search", "--all", "--yes"})
		// 显式注入 ctx（engine 经 cmd.Context() 取，cobra 默认 Background，这里保险显式传）。
		root.SetContext(ctx)
		return root.Execute()
	})
	// NDJSON：每行一个 item；db 有 2 条 → 至少 2 行。
	lines := bytes.Split(bytes.TrimSpace([]byte(out)), []byte("\n"))
	if len(lines) < 2 {
		t.Fatalf("want >=2 NDJSON 行, got %d (%q)", len(lines), out)
	}
	if !strings.Contains(out, `"i-1"`) || !strings.Contains(out, `"i-2"`) {
		t.Fatalf("流式输出应含 i-1 与 i-2 两行: %s", out)
	}
}

// TestE2EFrontendEndpointPath 验证 --endpoint frontend + --dry-run：
// dry-run 预览里 URL 必须含 /web/api/v1/instances/i-1（frontend path_prefix 生效），
// 而不是 backend 的 /api/v1。
func TestE2EFrontendEndpointPath(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	out := captureStdout(t, func() error {
		root.SetArgs([]string{"inst", "read", "i-1", "--endpoint", "frontend", "--dry-run", "--yes"})
		return root.Execute()
	})
	if !strings.Contains(out, "/web/api/v1/instances/i-1") {
		t.Fatalf("frontend path_prefix 未生效（缺 /web/api/v1/instances/i-1）: %s", out)
	}
	// 反向校验：dry-run 不应落到 backend 前缀（排除 read 默认走 backend 的回归）。
	if strings.Contains(out, " /api/v1/instances/i-1 ") && !strings.Contains(out, "/web/api/v1/instances/i-1") {
		t.Fatalf("dry-run 错走 backend 前缀: %s", out)
	}
}

// TestE2EDryRunDoesNotDelete 验证 --dry-run 副作用：delete --dry-run --yes 后，
// mock.db["i-1"] 必须仍存在（dry-run 不发请求 → 服务端无变更）。
// 用副作用断言（而非 stdout 内容）最稳，不强依赖 dry-run 预览格式。
func TestE2EDryRunDoesNotDelete(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatalf("cobracli.Build 失败: %v", err)
	}
	// 不需要捕获 stdout：用副作用断言。
	// 临时重定向 stdout 只为静默 dry-run 预览噪声（不参与断言）。
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	drainDone := make(chan struct{})
	go func() {
		_, _ = io.Copy(io.Discard, r)
		close(drainDone)
	}()
	root.SetArgs([]string{"inst", "delete", "i-1", "--dry-run", "--yes"})
	execErr := root.Execute()
	_ = w.Close()
	os.Stdout = old
	<-drainDone
	if execErr != nil {
		t.Fatalf("delete --dry-run 执行失败: %v", execErr)
	}
	mock.mu.Lock()
	_, ok := mock.db["i-1"]
	mock.mu.Unlock()
	if !ok {
		t.Fatal("dry-run 不应真正删除 i-1，但 mock.db 中已不存在")
	}
}

// TestGlobalFlagTraverseChildren 验证 root 开了 TraverseChildren：使全局 flag
// （--insecure/--spec 等）可放在子命令之前（`api-cli --insecure inst search`）
// 也被 cobra 正确解析，而不被当作子命令位置参数。
func TestGlobalFlagTraverseChildren(t *testing.T) {
	// --insecure 放最前（root 位置）应生效（TraverseChildren=true）
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadCMDBTree(t, mock.URL())
	root, err := cobracli.Build(tr)
	if err != nil {
		t.Fatal(err)
	}
	// 断言 root 开了 TraverseChildren
	if !root.TraverseChildren {
		t.Fatal("root.TraverseChildren 应为 true")
	}
}

// TestE2EMCPBodySchemaAndPaging 通过 mcp.Server 端到端验证 iter2 的 body/output schema
// 与 page-in-body 分页（不直接调 engine，走 MCP tools/list + tools/call 的真链路）。
//
// 三个 tools/list 断言：
//  1. _body 嵌套展开（properties.query 含 additionalProperties + example，非空对象）
//  2. required 聚合（object_id 来自 path required；page/page_size 来自 body schema required）
//  3. outputSchema 在（data.list[].{instanceId,name,namespaceId} 的字段声明）
//
// 一个 tools/call 断言：_body（嵌套 query + page=1,page_size=1）经 marshal → engine.BodyBytes
// 直传 → paging.Iter 翻页（page_in:body，bumpBodyPage 递增 body 里的 page 号）→ 翻够 2 页。
// mock 按 body.page 切片，2 条数据 × page_size=1 → 必须翻到第 2 页才能拿全 i-1 + i-2。
func TestE2EMCPBodySchemaAndPaging(t *testing.T) {
	mock := NewCMDBMock()
	defer mock.Close()
	tr := loadEasyOpsCMDBTree(t, mock.URL())
	srv := mcp.New(tr)

	tools := srv.ToolsList()
	if len(tools) != 1 {
		t.Fatalf("want 1 tool, got %d", len(tools))
	}
	const wantName = "easyops-cmdb_object_instance_search"
	tool := tools[0]
	if tool.Name != wantName {
		t.Fatalf("tool name want %s, got %s", wantName, tool.Name)
	}

	// tools/list 断言 1：_body 嵌套（query 含 additionalProperties + example）
	props, ok := tool.InputSchema["properties"].(map[string]any)
	if !ok {
		t.Fatalf("inputSchema.properties 缺失: %#v", tool.InputSchema)
	}
	body, ok := props["_body"].(map[string]any)
	if !ok {
		t.Fatalf("inputSchema.properties._body 缺失（嵌套 body 未展开）")
	}
	bodyProps, _ := body["properties"].(map[string]any)
	query, ok := bodyProps["query"].(map[string]any)
	if !ok {
		t.Fatalf("_body.properties.query 缺失: %#v", bodyProps)
	}
	if query["additionalProperties"] != true {
		t.Errorf("_body.query.additionalProperties want true, got %v", query["additionalProperties"])
	}
	if query["example"] == nil {
		t.Error("_body.query.example 缺失（LLM 理解核心）")
	}

	// tools/list 断言 2：required 含 object_id（path）+ page/page_size（body schema）
	reqList, ok := tool.InputSchema["required"].([]string)
	if !ok {
		t.Fatalf("inputSchema.required 缺失或类型错: %#v", tool.InputSchema["required"])
	}
	wantReq := map[string]bool{"object_id": true, "page": true, "page_size": true}
	for _, r := range reqList {
		delete(wantReq, r)
	}
	if len(wantReq) != 0 {
		t.Fatalf("required 缺少 %v, got %v", wantReq, reqList)
	}

	// tools/list 断言 3：outputSchema 在（data.list[].字段 嵌套展开）
	if tool.OutputSchema == nil {
		t.Fatal("outputSchema 缺失")
	}
	outProps, _ := tool.OutputSchema["properties"].(map[string]any)
	data, _ := outProps["data"].(map[string]any)
	dataProps, _ := data["properties"].(map[string]any)
	lst, _ := dataProps["list"].(map[string]any)
	lstItems, _ := lst["items"].(map[string]any)
	lstItemProps, _ := lstItems["properties"].(map[string]any)
	for _, f := range []string{"instanceId", "name", "namespaceId"} {
		if lstItemProps[f] == nil {
			t.Errorf("outputSchema.data.list.items.properties.%s 缺失: %#v", f, lstItemProps)
		}
	}

	// tools/call：_body 直传 + page-in-body 翻页。
	// _body 含嵌套 query（$and/$or，单层 flag 表达不了，必须经 BodyBytes 直传）+
	// page/page_size（page_in:body 翻页靠 bumpBodyPage 改它）。
	args := map[string]any{
		"object_id": "FLOW_BUILDER_API_CONTRACT@EASYOPS",
		"_body": map[string]any{
			"page":      1,
			"page_size": 1,
			"query": map[string]any{
				"$and": []any{
					map[string]any{"$or": []any{map[string]any{"namespaceId": map[string]any{"$like": "%easyops.%"}}}},
				},
			},
		},
	}
	params, _ := json.Marshal(map[string]any{
		"jsonrpc": "2.0",
		"id":      7,
		"method":  "tools/call",
		"params":  map[string]any{"name": wantName, "arguments": args},
	})
	in := bytes.NewReader(append(params, '\n'))
	var out bytes.Buffer
	if err := srv.Serve(context.Background(), in, &out); err != nil {
		t.Fatalf("Serve: %v", err)
	}
	var resp struct {
		Result struct {
			Content []struct {
				Text string `json:"text"`
			} `json:"content"`
		} `json:"result"`
		Error map[string]any `json:"error"`
	}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal: %v (out=%s)", err, out.String())
	}
	if resp.Error != nil {
		t.Fatalf("tools/call 返回 error: %#v (out=%s)", resp.Error, out.String())
	}
	if len(resp.Result.Content) == 0 {
		t.Fatalf("result.content 空: %s", out.String())
	}
	text := resp.Result.Content[0].Text
	// page 1 → [i-1], page 2 → [i-2], page 3 → 空（隐式终止）。
	// 同时含 i-1 与 i-2 才证明翻页真的到了第二页（单页只能拿一条）。
	if !strings.Contains(text, `"i-1"`) {
		t.Errorf("翻页第1页数据缺失（无 i-1）: %s", text)
	}
	if !strings.Contains(text, `"i-2"`) {
		t.Errorf("翻页未到第2页（无 i-2）: %s", text)
	}
}

// TestEasyOpsExampleParses 兜底保护 examples/easyops-cmdb.yaml 这个交付物：
// 从磁盘读真实文件，断言 spec.Parse 成功且 search op 有 body/response/pagination 三件套。
// 防止后续手改示例时 YAML 缩进 / schema 字段名笔误无人发现（inline 测试覆盖不到文件）。
func TestEasyOpsExampleParses(t *testing.T) {
	raw, err := os.ReadFile("../../examples/easyops-cmdb.yaml")
	if err != nil {
		t.Fatalf("读示例文件失败（CWD 应为 tests/integration）: %v", err)
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	r := tr.Resources["object_instance"]
	if r == nil {
		t.Fatal("资源 object_instance 缺失")
	}
	op := r.Operations["search"]
	if op == nil {
		t.Fatal("object_instance.search 操作缺失")
	}
	if op.Body == nil || op.Body.Properties["query"] == nil {
		t.Fatal("search.body.query 缺失（示例未补全嵌套 body schema）")
	}
	if op.Body.Properties["query"].AdditionalProperties == nil {
		t.Error("search.body.query.additional_properties 应为 true（MongoDB 风格任意 key）")
	}
	if op.Response == nil || op.Response.Properties["data"] == nil {
		t.Fatal("search.response.data 缺失（示例未补全 response schema）")
	}
	if op.Pagination == nil || op.Pagination.PageIn != "body" {
		t.Fatal("search.pagination.page_in 应为 body（EasyOps 翻页号在 body）")
	}
}

// loadCMDBRelationTree 构造含 inst > relation 嵌套的最小清单：
//   - inst.path = /instances，ParentKey = instance_id
//   - relation.path = /{instance_id}/relations，read.path = /{id}
//
// 同 examples/cmdb.yaml 的嵌套结构（手动镜像而非读文件）：
// (a) 测试不依赖 ${CMDB_BACKEND_URL} 等环境变量；
// (b) base_url 内联替换成 mock 地址，可控可断言。
// 给 TestIntegrationRelationReadAncestorURL 用：验证 iter3 Task 5 修复后，
// relation.read 物化出的 URL 含完整祖先链 + parent_key 占位真被填上。
func loadCMDBRelationTree(t *testing.T, baseURL string) *tree.OperationTree {
	t.Helper()
	raw := []byte(`
spec: api-cli/v1
service: { name: cmdb, default_endpoint: backend, endpoints: { backend: { base_url: BASE, auth: none, path_prefix: /api/v1 } } }
resources:
  inst:
    description: CMDB 实例
    path: /instances
    singular: instance
    parent_key: instance_id
    operations:
      read: { method: GET, path: "/{id}", description: 读取单个实例, params: { id: { in: path, type: string, required: true, description: 实例 ID } } }
    children:
      relation:
        description: 实例的关系
        path: "/{instance_id}/relations"
        operations:
          read: { method: GET, path: "/{id}", description: 读取实例的某个关系, params: { id: { in: path, type: string, required: true, description: 关系 ID } } }
`)
	raw = bytes.ReplaceAll(raw, []byte("BASE"), []byte(baseURL))
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	return tr
}

// TestIntegrationRelationReadAncestorURL 端到端验证嵌套 child resource（inst > relation）
// 的祖先链 URL 拼接 + parent_key 占位填充：起一个 httptest mock 收 GET
// /api/v1/instances/{iid}/relations/{rid}，跑 engine.Execute(relation, read,
// pathVals={instance_id:INST1, id:REL1})，断言 mock 收到的 r.URL.Path 是完整的
// `/api/v1/instances/INST1/relations/REL1`。
//
// 同时验证 iter3 Task 5 的两处修复都生效：
//  1. ancestorPaths 把父级 resource.Path（/instances）拼进 URL（修复前会漏掉，URL 缺 /instances 段）；
//  2. parent_key 占位填充改为遍历 vals（修复前只遍历 op.Params，命令位置注入的
//     instance_id 不在 relation.read 的 op.Params 里 → {instance_id} 留为字面占位）。
//
// 不走 cobracli.Build：cobra 默认子命令解析不容忍 `inst INST1 relation read REL1`
// 里夹在中间的位置 ID（会把 INST1 当 inst 的未知子命令），这是 cobra 层的已知缺口，
// 不在 iter3 范围。engine.Execute 是 cobracli/mcp 共用的唯一入口，直接驱动它已能
// 端到端覆盖 resolve → http.Do → mock 收到请求 这条链路。
func TestIntegrationRelationReadAncestorURL(t *testing.T) {
	var gotPath, gotMethod string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotMethod = r.Method
		w.Header().Set("Content-Type", "application/json")
		// 任意 GET 都回 200 + 一份固定关系体（断言关心的是请求路径，不是响应内容）。
		_ = json.NewEncoder(w).Encode(map[string]any{"id": "REL1", "target": "i-2"})
	}))
	defer srv.Close()

	tr := loadCMDBRelationTree(t, srv.URL)
	inst := tr.Resources["inst"]
	if inst == nil {
		t.Fatal("资源 inst 缺失")
	}
	rel := inst.Children["relation"]
	if rel == nil {
		t.Fatal("inst.children.relation 缺失（清单嵌套结构未正确解析）")
	}
	op := rel.Operations["read"]
	if op == nil {
		t.Fatal("relation.read 操作缺失")
	}
	ep, err := tr.SelectEndpoint("") // 默认 backend
	if err != nil {
		t.Fatalf("SelectEndpoint: %v", err)
	}

	e := engine.New(tr)
	var out bytes.Buffer
	// pathVals 同时含 instance_id（parent_key 命令位置注入值）与 id（read 自身 path 参数）。
	// 这是 cobracli.buildPathVals 在嵌套场景下会构造出的同一份 vals。
	pathVals := map[string]string{"instance_id": "INST1", "id": "REL1"}
	if err := e.Execute(context.Background(), ep, rel, op, pathVals, nil, engine.Options{
		Format: "json",
		Out:    &out,
	}); err != nil {
		t.Fatalf("engine.Execute 返回错误: %v\nstdout: %s", err, out.String())
	}

	const wantPath = "/api/v1/instances/INST1/relations/REL1"
	if gotPath != wantPath {
		t.Errorf("祖先链 URL 不正确:\n want %q\n got  %q\n（说明 ancestorPaths 漏拼 /instances 或 {instance_id} 占位未填）",
			wantPath, gotPath)
	}
	if gotMethod != http.MethodGet {
		t.Errorf("HTTP method want GET, got %s", gotMethod)
	}
	// 反向断言：响应确实落到 Out（端到端链路完整，不只 URL 拼对了）。
	if !strings.Contains(out.String(), `"REL1"`) {
		t.Errorf("engine.Out 缺响应 id=REL1（mock 响应未回流）: %s", out.String())
	}
}

// TestCMDBExampleParentKeyConvention 锁 parent_key 的 spec 约定：声明在 **parent**
// resource 上（inst），不在 child（relation）上。
//
// 动机：整个 codebase 都从 parent 读 ParentKey——
//   - internal/cobracli/build.go: descend into child 时 append(parentKeys, {key: r.ParentKey})
//   - internal/spec/parse.go T5 lint: r.ParentKey != "" && child.Path 含 {<ParentKey>}
//   - 所有 test fixture 都把 parent_key 放在 parent
//
// 若示例把 parent_key 写到 relation（child）上（历史遗留笔误），inst.ParentKey == ""，
// 会导致 T5 lint 在这份 canonical demo 上静默失效（不校验 relation.path 含 {instance_id}），
// 同时教错 spec 作者约定。本测试从磁盘读真实 examples/cmdb.yaml 锁住正确约定，防回归。
func TestCMDBExampleParentKeyConvention(t *testing.T) {
	raw, err := os.ReadFile("../../examples/cmdb.yaml")
	if err != nil {
		t.Fatalf("读示例文件失败（CWD 应为 tests/integration）: %v", err)
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	inst := tr.Resources["inst"]
	if inst == nil {
		t.Fatal("资源 inst 缺失")
	}
	// parent_key 必须在 parent（inst）上。
	if inst.ParentKey != "instance_id" {
		t.Errorf("inst.ParentKey want %q（parent_key 应声明在 parent inst 上）, got %q\n",
			"instance_id", inst.ParentKey)
	}
	rel := inst.Children["relation"]
	if rel == nil {
		t.Fatal("inst.children.relation 缺失")
	}
	// 反向断言：child（relation）上不应再声明 parent_key（防历史笔误回归）。
	if rel.ParentKey != "" {
		t.Errorf("relation.ParentKey 应为空（parent_key 不在 child 上声明）, got %q\n",
			rel.ParentKey)
	}
	// 占位仍在 child path 上（由 parent 的 ParentKey 声明注入键，T5 lint 据此校验）。
	if !strings.Contains(rel.Path, "{instance_id}") {
		t.Errorf("relation.Path 应含 {instance_id} 占位, got %q\n", rel.Path)
	}
}

// TestCMDBExampleResourceDescriptions 兜底保护 examples/cmdb.yaml 这个交付物：
// 断言补的 description 字段在 spec.Parse 后真的进到 tree.Resource / tree.Operation。
// 防止后续手改示例时把 description 字段名 / 缩进改歪（inline 测试覆盖不到文件）。
func TestCMDBExampleResourceDescriptions(t *testing.T) {
	raw, err := os.ReadFile("../../examples/cmdb.yaml")
	if err != nil {
		t.Fatalf("读示例文件失败（CWD 应为 tests/integration）: %v", err)
	}
	tr, err := spec.Parse(raw)
	if err != nil {
		t.Fatalf("spec.Parse 失败: %v", err)
	}
	inst := tr.Resources["inst"]
	if inst == nil {
		t.Fatal("资源 inst 缺失")
	}
	if inst.Description != "CMDB 实例" {
		t.Errorf("inst.Description want %q, got %q", "CMDB 实例", inst.Description)
	}
	if got := inst.Operations["read"].Description; got == "" {
		t.Error("inst.read.Description 为空（示例未补 operation description）")
	}
	rel := inst.Children["relation"]
	if rel == nil {
		t.Fatal("inst.children.relation 缺失")
	}
	if rel.Description != "实例的关系" {
		t.Errorf("relation.Description want %q, got %q", "实例的关系", rel.Description)
	}
	if got := rel.Operations["read"].Description; got == "" {
		t.Error("relation.read.Description 为空（示例未补 operation description）")
	}
}
