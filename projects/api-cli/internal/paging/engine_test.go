package paging

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"api-cli/internal/tree"

	"github.com/tidwall/gjson"
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
	for it := range Iter(context.Background(), pg, func(ctx context.Context, body []byte, req map[string]string) ([]byte, error) {
		b, _, err := cursorDo(req)
		return b, err
	}, nil, map[string]string{}, Options{MaxPages: 100, Limit: 1000}) {
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
	do := func(ctx context.Context, body []byte, req map[string]string) ([]byte, error) {
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
	for it := range Iter(context.Background(), pg, do, nil, map[string]string{"page": "0"}, Options{MaxPages: 100, Limit: 1000}) {
		got = append(got, it.ID)
	}
	if len(got) != 3 {
		t.Fatalf("want 3 items, got %d", len(got))
	}
}

func TestLimitTruncation(t *testing.T) {
	// 提供 5 条，limit=3 → 只得 3 条
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 5}
	do := func(ctx context.Context, body []byte, req map[string]string) ([]byte, error) {
		return []byte(`{"data":[{"id":"1"},{"id":"2"},{"id":"3"},{"id":"4"},{"id":"5"}]}`), nil
	}
	n := 0
	for range Iter(context.Background(), pg, do, nil, map[string]string{}, Options{Limit: 3, MaxPages: 10}) {
		n++
	}
	if n != 3 {
		t.Fatalf("want 3 (limit), got %d", n)
	}
}

// TestIterPropagatesError 验证 do 出错时错误经 Item.Err 反馈给消费方，
// 而不是静默 close channel（旧实现：错误被吞，消费方拿到截断数据无感）。
// 第一页正常返回 2 条，第二页 do 返回 "server exploded" → 应在收到首页 2 条后
// 收到一个 Item{Err:...}，消费方据此感知失败。
func TestIterPropagatesError(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 2}
	calls := 0
	do := func(ctx context.Context, body []byte, req map[string]string) ([]byte, error) {
		calls++
		if calls == 1 {
			return []byte(`{"data":[{"id":"1"},{"id":"2"}]}`), nil
		}
		return nil, fmt.Errorf("server exploded")
	}
	var got []string
	var iterErr error
	for it := range Iter(context.Background(), pg, do, nil, map[string]string{}, Options{MaxPages: 10}) {
		if it.Err != nil {
			iterErr = it.Err
			break
		}
		got = append(got, it.ID)
	}
	if iterErr == nil {
		t.Fatal("want error propagated via Item.Err, got nil（错误被静默吞掉）")
	}
	if !strings.Contains(iterErr.Error(), "server exploded") {
		t.Fatalf("错误信息丢失，got %v", iterErr)
	}
	if len(got) != 2 {
		t.Fatalf("错误前应已投递首页 2 条，got %d 条", len(got))
	}
}

// TestIterErrorClosesChannel 验证发出 Item{Err} 后 channel 正常 close
// （消费方 range 能终止，不死锁）。
func TestIterErrorClosesChannel(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data", Size: 2}
	do := func(ctx context.Context, body []byte, req map[string]string) ([]byte, error) {
		return nil, fmt.Errorf("immediate failure")
	}
	done := make(chan struct{})
	var sawErr bool
	go func() {
		defer close(done)
		for it := range Iter(context.Background(), pg, do, nil, map[string]string{}, Options{MaxPages: 10}) {
			if it.Err != nil {
				sawErr = true
			}
		}
	}()
	<-done
	if !sawErr {
		t.Fatal("首请求即出错：应收到 Item{Err} 且 channel 随后 close")
	}
}

// TestPageInBodyPaging 验证 page 在 body 时翻页改 body 不改 query。
// page_in=body：do 收 body，按 body.page 翻页；3 页（page=1→2→3），
// 第 3 页返回 < size 终止。下一页的 page 号由 bumpBodyPage 改 body 副本。
func TestPageInBodyPaging(t *testing.T) {
	// page 在 body：do 收 body，按 body.page 翻页；3 页（page=1→2→3），第 3 页返回 < size 终止
	pages := map[string][]string{
		"1": {"a", "b"},
		"2": {"c", "d"},
		"3": {"e"}, // < size=2 → 终止
	}
	pg := &tree.Pagination{Type: "offset", PageIn: "body", ItemsPath: "data", PageParam: "page", SizeParam: "page_size", Size: 2}
	do := func(ctx context.Context, body []byte, query map[string]string) ([]byte, error) {
		page := gjson.GetBytes(body, "page").String()
		if page == "" {
			page = "1"
		}
		items := pages[page]
		s := `{"data":[`
		for i, id := range items {
			if i > 0 {
				s += ","
			}
			s += fmt.Sprintf(`{"id":%q}`, id)
		}
		s += `]}`
		return []byte(s), nil
	}
	var got []string
	for it := range Iter(context.Background(), pg, do, []byte(`{"page":1,"page_size":2}`), map[string]string{}, Options{MaxPages: 10}) {
		got = append(got, it.ID)
	}
	want := []string{"a", "b", "c", "d", "e"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

// TestIterCappedEmitsErrCapped 验证 MaxItems 触顶时 Iter 发出 Item{Err:ErrCapped}，
// 区别于真实翻页错误（DoFunc 失败）——消费方据此打 warning + exit 4，而非把截断当失败。
//
// 触发条件：每页 5 条，opts.MaxItems=3 → 第 3 条后命中硬上限，应发 ErrCapped 再 close。
// 旧实现：触顶静默 return，消费方拿到截断数据 exit 0 无感。
func TestIterCappedEmitsErrCapped(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data.list", Size: 10}
	// 每页 5 条，MaxItems=3 → 触顶
	resp := []byte(`{"data":{"list":[{"id":"a"},{"id":"b"},{"id":"c"},{"id":"d"},{"id":"e"}]}}`)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		return resp, nil
	}
	items := Iter(context.Background(), pg, do, nil, nil, Options{MaxItems: 3})
	var capped bool
	count := 0
	for it := range items {
		if it.Err != nil && it.Err == ErrCapped {
			capped = true
		}
		count++
	}
	if !capped {
		t.Fatalf("want ErrCapped when MaxItems hit, got %d items no cap", count)
	}
}

// TestIterEmitsTotal 验证 Iter 把响应信封里的 total 经 Item.Total 传出（仅首条 item 携带）。
// totalPath 默认 = itemsPath 父 + ".total"；data.list -> data.total。
func TestIterEmitsTotal(t *testing.T) {
	pg := &tree.Pagination{Type: "implicit", ItemsPath: "data.list", Size: 10}
	// 响应信封含 data.total=3 + data.list 一条
	resp := []byte(`{"data":{"total":3,"list":[{"id":"a"}]}}`)
	do := func(ctx context.Context, body []byte, q map[string]string) ([]byte, error) {
		return resp, nil
	}
	items := Iter(context.Background(), pg, do, nil, nil, Options{Limit: 10})
	var gotTotal *int
	count := 0
	for it := range items {
		if it.Total != nil {
			gotTotal = it.Total
		}
		if it.Err != nil {
			t.Fatalf("unexpected err: %v", it.Err)
		}
		count++
	}
	if gotTotal == nil || *gotTotal != 3 {
		t.Fatalf("want total=3, got %v", gotTotal)
	}
	if count != 1 {
		t.Fatalf("want 1 item, got %d", count)
	}
}
