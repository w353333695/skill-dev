// Package integration 是 api-cli 的端到端集成测试：用 httptest 起 mock server，
// 跑 examples/cmdb.yaml 的前后端双 endpoint CRUD + cursor 分页流式 + dry-run。
//
// mockserver.go 提供 CMDBMock：一个 httptest server，同时承担 backend
// （/api/v1/...）与 frontend（/web/api/v1/...）两套接入面——按 URL 前缀剥后
// 路由到同一份内存 db。cursor 分页用固定 page_token=p2 切片。
package integration

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
)

// CMDBMock 模拟 CMDB 前后端 API。
//
//   - db：内存数据，id → instance；初始含 i-1 / i-2 两条（供 read/search/delete 验证）。
//   - srv：httptest.Server，handler 剥前缀后按 (path, method) 分发。
//
// 线程安全：所有读写经 mu 保护（paging 异步拉取可能与主线程断言并发）。
type CMDBMock struct {
	srv *httptest.Server
	mu  sync.Mutex
	db  map[string]map[string]any // id → instance
}

// NewCMDBMock 启动 mock server，预置 i-1 / i-2 两条数据。
func NewCMDBMock() *CMDBMock {
	m := &CMDBMock{db: map[string]map[string]any{
		"i-1": {"id": "i-1", "name": "web"},
		"i-2": {"id": "i-2", "name": "db"},
	}}
	m.srv = httptest.NewServer(http.HandlerFunc(m.handle))
	return m
}

// URL 返回 mock server 监听地址（前端 / 后端共用同一 host:port）。
func (m *CMDBMock) URL() string { return m.srv.URL }

// Close 停止 mock server。
func (m *CMDBMock) Close() { m.srv.Close() }

// handle 统一入口：剥 /api/v1 或 /web/api/v1 前缀后按 (path, method) 路由。
//
// 路由表（剥前缀后的 path）：
//   - POST   /instances                          → 创建（简易 id 生成）
//   - POST   /instances/search                   → cursor 分页查询（query page_token=p2 切第二页）
//   - POST   .../instance/_search                → EasyOps 风格 offset 分页（page-in-body：读 body.page 切片）
//   - GET    /instances/{id}                     → 读取单条
//   - DELETE /instances/{id}                     → 删除（204）
//   - 其余 → 404
func (m *CMDBMock) handle(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	// 同时承担 backend（/api/v1/...）与 frontend（/web/api/v1/...）：剥前缀。
	// 注意：先试更长的前缀语义上更安全，但 /web/api/v1 与 /api/v1 互不前缀重叠，
	// 顺序无影响（参见 cmdb_test.go 中 TestPrefixStripping 的等价验证）。
	path := r.URL.Path
	for _, p := range []string{"/api/v1", "/web/api/v1"} {
		if len(path) > len(p) && path[:len(p)] == p {
			path = path[len(p):]
		}
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	switch {
	case path == "/instances" && r.Method == "POST":
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		id := "i-" + r.RemoteAddr // 简易唯一（端口维度足以区分单测）
		body["id"] = id
		m.db[id] = body
		_ = json.NewEncoder(w).Encode(body)
	case path == "/instances/search" && r.Method == "POST":
		// cursor 分页：page_token=p2 → 从第二条起；每页 1 条；末页 next=""。
		all := sortedValues(m.db)
		token := r.URL.Query().Get("page_token")
		start := 0
		if token == "p2" {
			start = 1
		}
		end := start + 1
		if end > len(all) {
			end = len(all)
		}
		list := all[start:end]
		next := ""
		if end < len(all) {
			next = "p2"
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"list": list, "next": next}})
	case strings.HasSuffix(path, "/instance/_search") && r.Method == "POST":
		// EasyOps 风格 offset 分页（page-in-body）：翻页号在请求 body 而非 query。
		// 读 body.page / body.page_size 决定切哪一段；越界返回空 list（让引擎按
		// "条数 < size" 隐式终止）。响应包成 {data:{list,total}}（items_path=data.list）。
		var body struct {
			Page     int `json:"page"`
			PageSize int `json:"page_size"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.Page <= 0 {
			body.Page = 1
		}
		if body.PageSize <= 0 {
			body.PageSize = 20
		}
		all := sortedValues(m.db)
		start := (body.Page - 1) * body.PageSize
		end := start + body.PageSize
		if start > len(all) {
			start = len(all)
		}
		if end > len(all) {
			end = len(all)
		}
		list := all[start:end]
		_ = json.NewEncoder(w).Encode(map[string]any{
			"data": map[string]any{"list": list, "total": len(all)},
		})
	case len(path) > len("/instances/") && path[:len("/instances/")] == "/instances/" && r.Method == "GET":
		id := path[len("/instances/"):]
		if v, ok := m.db[id]; ok {
			_ = json.NewEncoder(w).Encode(v)
		} else {
			w.WriteHeader(http.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": "not found"})
		}
	case len(path) > len("/instances/") && path[:len("/instances/")] == "/instances/" && r.Method == "DELETE":
		id := path[len("/instances/"):]
		delete(m.db, id)
		w.WriteHeader(http.StatusNoContent)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

// sortedValues 按 i-1 → i-2 的固定顺序返回 db 值。
// 固定顺序使分页切片可预期（Go map 迭代顺序不确定，不能直接遍历）。
func sortedValues(m map[string]map[string]any) []map[string]any {
	keys := []string{"i-1", "i-2"}
	out := []map[string]any{}
	for _, k := range keys {
		if v, ok := m[k]; ok {
			out = append(out, v)
		}
	}
	return out
}
