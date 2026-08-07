// Package paging 声明式分页引擎：cursor/offset/implicit 统一循环，流式 channel 输出。
package paging

import (
	"context"
	"encoding/json"
	"fmt"

	"api-cli/internal/tree"

	"github.com/tidwall/gjson"
)

// Item 一条数据。ID 用于去重（若有）。
//
// Err 非 nil 时表示翻页中途出错（DoFunc 返回 error）：此时 Raw 为空，
// 消费方（engine.iterate）应据此归一化错误返回，而非把截断数据当成完整结果。
// 出错的 Item 发出后 channel 立即 close。
type Item struct {
	ID  string
	Raw []byte // 原始 JSON 字节
	Err error  // 翻页中途错误（DoFunc 失败）；非 nil 时 Raw 为空
}

// Options 翻页选项。
type Options struct {
	MaxPages int  // 死循环硬上限（页数）
	Limit    int  // 拉够 N 条就停（0 = 不限，但仍受 MaxItems 约束）
	MaxItems int  // 死循环硬上限（条数）
	NoDedupe bool // 关闭按 id 去重
}

// DoFunc 执行一次请求，返回响应 body。body/query 是可变翻页参数（PageIn 决定改哪个）。
type DoFunc func(ctx context.Context, body []byte, query map[string]string) ([]byte, error)

// Iter 流式迭代所有分页 items。
//   - pg：分页声明（来自 operation.Pagination）
//   - firstBody：首次请求的 body 种子（page-in-body 翻页在此基础上改 page 号）
//   - firstQuery：首次请求的 query 参数种子（cursor/offset-in-query 在此基础上翻页）
//   - opts：MaxPages/Limit 等
func Iter(ctx context.Context, pg *tree.Pagination, do DoFunc, firstBody []byte, firstQuery map[string]string, opts Options) <-chan Item {
	if opts.MaxPages == 0 {
		opts.MaxPages = 1000
	}
	if opts.MaxItems == 0 {
		opts.MaxItems = 10000
	}
	out := make(chan Item, 100)
	go func() {
		defer close(out)
		body := append([]byte(nil), firstBody...) // 拷贝，翻页改副本
		req := copyMap(firstQuery)
		seen := map[string]bool{}
		count := 0
		for page := 0; page < opts.MaxPages; page++ {
			respBody, err := do(ctx, body, req)
			if err != nil {
				// 错误不能静默吞：发一个 Item{Err} 让消费方感知失败，
				// 再 close。select 兼顾 ctx 已取消的快路径。
				select {
				case out <- Item{Err: err}:
				case <-ctx.Done():
				}
				return
			}
			items := gjson.GetBytes(respBody, pg.ItemsPath).Array()
			for _, it := range items {
				id := gjson.Get(it.Raw, "id").String()
				if !opts.NoDedupe && id != "" {
					if seen[id] {
						continue
					}
					seen[id] = true
				}
				select {
				case out <- Item{ID: id, Raw: []byte(it.Raw)}:
				case <-ctx.Done():
					return
				}
				count++
				if opts.Limit > 0 && count >= opts.Limit {
					return
				}
				if count >= opts.MaxItems {
					return
				}
			}
			// 判断是否还有下一页 + 算下一页参数（body / query）
			nextBody, nextReq, more := planNext(respBody, items, pg, body, req)
			if !more {
				return
			}
			body = nextBody
			req = nextReq
		}
	}()
	return out
}

// planNext 决定是否翻页 + 下一页参数（可能改 body，可能改 query）。
//   - cursor：从响应抽 next token，写入 query.page_token
//   - offset + PageIn=body：终止判断后用 bumpBodyPage 改 body 副本的 page 号
//   - offset + 其他：page 号自增加入 query
//   - implicit：本轮条数 < size 或空 → 结束
func planNext(respBody []byte, items []gjson.Result, pg *tree.Pagination, body []byte, req map[string]string) ([]byte, map[string]string, bool) {
	nextReq := copyMap(req)
	switch pg.Type {
	case "cursor":
		token := gjson.GetBytes(respBody, pg.NextTokenPath).String()
		if token == "" {
			return body, nextReq, false
		}
		nextReq["page_token"] = token
		return body, nextReq, true
	case "offset":
		// 隐式终止判断（条数 < size）
		if pg.Size > 0 && len(items) < pg.Size {
			return body, nextReq, false
		}
		// 翻页参数位置：body 还是 query
		if pg.PageIn == "body" {
			nextBody := bumpBodyPage(body, pg.PageParam)
			return nextBody, nextReq, true
		}
		cur := 0
		fmt.Sscanf(req[pg.PageParam], "%d", &cur)
		nextReq[pg.PageParam] = fmt.Sprintf("%d", cur+1)
		return body, nextReq, true
	case "implicit":
		// 不配 has_more → 本轮条数 < size 或空 → 结束
		if pg.Size > 0 && len(items) < pg.Size {
			return body, nextReq, false
		}
		if len(items) == 0 {
			return body, nextReq, false
		}
		return body, nextReq, true
	}
	return body, nextReq, false
}

// bumpBodyPage 把 body JSON 里 page_param 的数字 +1（page-in-body 翻页）。
// 用于 PageIn=body 的 offset 分页：每翻一页把 body 里的 page 号递增。
// body 非 JSON / 字段缺失 / 类型异常时原样返回（不阻塞翻页，由 MaxPages 兜底）。
func bumpBodyPage(body []byte, pageParam string) []byte {
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		return body
	}
	cur := 0
	switch v := m[pageParam].(type) {
	case float64:
		cur = int(v)
	case string:
		fmt.Sscanf(v, "%d", &cur)
	}
	m[pageParam] = cur + 1
	out, err := json.Marshal(m)
	if err != nil {
		return body
	}
	return out
}

// copyMap 浅拷贝一个 map[string]string，避免翻页间共享底层数据。
func copyMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
