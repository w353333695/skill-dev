// Package output 负责结果格式化与错误归一化。
package output

import (
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"sort"

	"gopkg.in/yaml.v3"
)

// Format 按指定格式把 data 写入 w。支持 json/yaml/table。
func Format(w io.Writer, format string, data any) error {
	switch format {
	case "json", "": // 默认 json
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(data)
	case "yaml":
		return yaml.NewEncoder(w).Encode(data)
	case "table":
		return FormatTable(w, data, nil)
	default:
		return fmt.Errorf("不支持的格式 %q", format)
	}
}

// FormatTable 把 slice of map 打成表格；headers[key]=中文表头（无则用 key）。
// 非 slice/非 map 回退 json。表头按 key 字典序（确定性，复用 sort.Strings）。
func FormatTable(w io.Writer, data any, headers map[string]string) error {
	v := reflect.ValueOf(data)
	if v.Kind() != reflect.Slice {
		// 非 slice：回退 json（保持与原 formatTable 行为一致）
		return Format(w, "json", data)
	}
	if v.Len() == 0 {
		return nil
	}
	first := v.Index(0)
	if first.Kind() != reflect.Map {
		return Format(w, "json", data)
	}
	keys := []string{}
	for _, k := range first.MapKeys() {
		keys = append(keys, k.String())
	}
	// 排序固化表头顺序：MapKeys 返回顺序未定义，不排序会导致同输入列序随机、不可重现。
	sort.Strings(keys)
	headRow := make([]string, len(keys))
	for i, k := range keys {
		if h, ok := headers[k]; ok && h != "" {
			headRow[i] = h
		} else {
			headRow[i] = k
		}
	}
	fmt.Fprintln(w, joinRow(headRow))
	for i := 0; i < v.Len(); i++ {
		row := make([]string, len(keys))
		m := v.Index(i)
		for j, k := range keys {
			vv := m.MapIndex(reflect.ValueOf(k))
			if vv.IsValid() {
				row[j] = fmt.Sprint(vv.Interface())
			}
		}
		fmt.Fprintln(w, joinRow(row))
	}
	return nil
}
