// Package paging 声明式分页引擎：cursor/offset/implicit 统一循环，流式 channel 输出。
package paging

import (
	"context"
	"fmt"

	"api-cli/internal/tree"

	"github.com/tidwall/gjson"
)

// Item 一条数据。ID 用于去重（若有）。
type Item struct {
	ID  string
	Raw []byte // 原始 JSON 字节
}

// Options 翻页选项。
type Options struct {
	MaxPages int  // 死循环硬上限（页数）
	Limit    int  // 拉够 N 条就停（0 = 不限，但仍受 MaxItems 约束）
	MaxItems int  // 死循环硬上限（条数）
	NoDedupe bool // 关闭按 id 去重
}

// DoFunc 执行一次请求，返回响应 body。req 是可变的翻页参数（cursor token 或 page 号）。
type DoFunc func(ctx context.Context, req map[string]string) ([]byte, error)

// Iter 流式迭代所有分页 items。
//   - pg：分页声明（来自 operation.Pagination）
//   - firstReq：首次请求的 query 参数种子
//   - opts：MaxPages/Limit 等
func Iter(ctx context.Context, pg *tree.Pagination, do DoFunc, firstReq map[string]string, opts Options) <-chan Item {
	if opts.MaxPages == 0 {
		opts.MaxPages = 1000
	}
	if opts.MaxItems == 0 {
		opts.MaxItems = 10000
	}
	out := make(chan Item, 100)
	go func() {
		defer close(out)
		req := copyMap(firstReq)
		seen := map[string]bool{}
		count := 0
		for page := 0; page < opts.MaxPages; page++ {
			body, err := do(ctx, req)
			if err != nil {
				return // 错误经 ctx 或单独 channel 传递；MVP 直接终止
			}
			items := gjson.GetBytes(body, pg.ItemsPath).Array()
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
			// 判断是否还有下一页 + 算下一页参数
			nextReq, more := planNext(body, items, pg, req)
			if !more {
				return
			}
			req = nextReq
		}
	}()
	return out
}

// planNext 决定是否翻页 + 下一页参数。
func planNext(body []byte, items []gjson.Result, pg *tree.Pagination, req map[string]string) (map[string]string, bool) {
	nextReq := copyMap(req)
	switch pg.Type {
	case "cursor":
		token := gjson.GetBytes(body, pg.NextTokenPath).String()
		if token == "" {
			return nextReq, false
		}
		nextReq["page_token"] = token
		return nextReq, true
	case "offset":
		// offset 用 page 号自增
		cur := 0
		fmt.Sscanf(req[pg.PageParam], "%d", &cur)
		nextReq[pg.PageParam] = fmt.Sprintf("%d", cur+1)
		// 隐式判断：取到的条数 < size → 结束
		if pg.Size > 0 && len(items) < pg.Size {
			return nextReq, false
		}
		return nextReq, true
	case "implicit":
		// 不配 has_more → 本轮条数 < size 或空 → 结束
		if pg.Size > 0 && len(items) < pg.Size {
			return nextReq, false
		}
		if len(items) == 0 {
			return nextReq, false
		}
		return nextReq, true
	}
	return nextReq, false
}

// copyMap 浅拷贝一个 map[string]string，避免翻页间共享底层数据。
func copyMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
