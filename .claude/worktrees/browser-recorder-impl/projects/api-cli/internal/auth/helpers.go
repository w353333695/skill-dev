package auth

import "fmt"

// str 把 map[string]any 配置值安全转成字符串。
// nil → ""；string 原样；其余类型用 fmt.Sprint。
func str(v any) string {
	if v == nil {
		return ""
	}
	switch x := v.(type) {
	case string:
		return x
	default:
		return fmt.Sprint(x)
	}
}
