package paging

import (
	"context"
	"fmt"
	"testing"

	"api-cli/internal/tree"
)

// 模拟服务端：3 页，每页 2 条，第 3 页 next 为空。
func cursorDo(req map[string]string) (body []byte, next string, err error) {
	page := req["page_token"]
	switch page {
	case "":
		return []byte(`{"data":{"list":[{"id":"1"},{"id":"2"}],"next":"p2"}}`), "p2", nil
	case "p2":
		return []byte(`{"data":{"list":[{"id":"3"},{"id":"4"}],"next":"p3"}}`), "p3", nil
	case "p3":
		return []byte(`{"data":{"list":[{"id":"5"}],"next":""}}`), "", nil
	}
	return nil, "", fmt.Errorf("unexpected %s", page)
}

func TestCursorPaging(t *testing.T) {
	pg := &tree.Pagination{Type: "cursor", ItemsPath: "data.list", NextTokenPath: "data.next", HasMorePath: "data.next"}
	var got []string
	for it := range Iter(context.Background(), pg, func(ctx context.Context, req map[string]string) ([]byte, error) {
		b, _, err := cursorDo(req)
		return b, err
	}, map[string]string{}, Options{MaxPages: 100, Limit: 1000}) {
		got = append(got, it.ID)
	}
	if len(got) != 5 {
		t.Fatalf("want 5 items, got %d (%v)", len(got), got)
	}
}

func TestImplicitPaging(t *testing.T) {
	// 不配 has_more → 用 "条数 < size 或空" 判断。每页 size=2，最后一页 1 条 → 终止。
	pages := [][]string{{"1", "2"}, {"3"}}
	call := 0
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 2}
	do := func(ctx context.Context, req map[string]string) ([]byte, error) {
		if call >= len(pages) {
			return []byte(`{"data":[]}`), nil
		}
		p := pages[call]
		call++
		s := `{"data":[`
		for i, id := range p {
			if i > 0 {
				s += ","
			}
			s += fmt.Sprintf(`{"id":%q}`, id)
		}
		s += `]}`
		return []byte(s), nil
	}
	var got []string
	for it := range Iter(context.Background(), pg, do, map[string]string{"page": "0"}, Options{MaxPages: 100, Limit: 1000}) {
		got = append(got, it.ID)
	}
	if len(got) != 3 {
		t.Fatalf("want 3 items, got %d", len(got))
	}
}

func TestLimitTruncation(t *testing.T) {
	// 提供 5 条，limit=3 → 只得 3 条
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 5}
	do := func(ctx context.Context, req map[string]string) ([]byte, error) {
		return []byte(`{"data":[{"id":"1"},{"id":"2"},{"id":"3"},{"id":"4"},{"id":"5"}]}`), nil
	}
	n := 0
	for range Iter(context.Background(), pg, do, map[string]string{}, Options{Limit: 3, MaxPages: 10}) {
		n++
	}
	if n != 3 {
		t.Fatalf("want 3 (limit), got %d", n)
	}
}
