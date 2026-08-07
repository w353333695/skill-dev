// Package output 负责结果格式化与错误归一化。
package output

import (
	"encoding/json"
	"fmt"
	"io"

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
		return formatTable(w, data)
	default:
		return fmt.Errorf("不支持的格式 %q", format)
	}
}
