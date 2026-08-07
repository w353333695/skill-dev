package output

import (
	"encoding/json"
	"fmt"
	"io"
	"reflect"
)

// Exit code 语义（spec §11.2）。
const (
	ExitOK         = 0
	ExitParamError = 1
	ExitAuthError  = 2
	ExitAPIError   = 3
	ExitPagingOver = 4
	ExitNetTimeout = 5
)

// APIError 业务错误（归一化后）。
type APIError struct {
	StatusCode int      `json:"status_code"`
	Code       string   `json:"code"`
	Message    string   `json:"message"`
	ExitCode   int      `json:"-"`
}

func (e *APIError) Error() string { return fmt.Sprintf("api error %d: %s", e.StatusCode, e.Message) }

// PrintError 把错误以结构化 JSON 写到 stderr（spec §11.3）。
func PrintError(w io.Writer, err error) {
	ae, ok := err.(*APIError)
	if !ok {
		ae = &APIError{Code: "internal", Message: err.Error(), ExitCode: ExitParamError}
	}
	b, _ := json.Marshal(ae)
	fmt.Fprintln(w, string(b))
}

// ExitCode 从 err 推断 exit code。
func ExitCode(err error) int {
	if err == nil {
		return ExitOK
	}
	if ae, ok := err.(*APIError); ok {
		return ae.ExitCode
	}
	return ExitParamError
}

// NormalizeAPIError 把 HTTP 响应归一化成 APIError。MVP 不读清单 error schema，直接透传 body。
func NormalizeAPIError(statusCode int, body []byte) *APIError {
	return &APIError{
		StatusCode: statusCode,
		Code:       fmt.Sprintf("HTTP_%d", statusCode),
		Message:    string(body),
		ExitCode:   mapStatusCode(statusCode),
	}
}

func mapStatusCode(c int) int {
	switch {
	case c == 401 || c == 403:
		return ExitAuthError
	case c >= 400 && c < 500:
		return ExitAPIError
	case c >= 500:
		return ExitAPIError
	default:
		return ExitOK
	}
}

// formatTable 把 slice of map 打成简易表格。
func formatTable(w io.Writer, data any) error {
	v := reflect.ValueOf(data)
	if v.Kind() != reflect.Slice {
		// 非 slice：当作单行
		return Format(w, "json", data)
	}
	if v.Len() == 0 {
		return nil
	}
	// 取第一条的 keys 作表头
	first := v.Index(0)
	if first.Kind() != reflect.Map {
		return Format(w, "json", data)
	}
	keys := []string{}
	for _, k := range first.MapKeys() {
		keys = append(keys, k.String())
	}
	fmt.Fprintln(w, joinRow(keys))
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

func joinRow(cols []string) string {
	out := ""
	for i, c := range cols {
		if i > 0 {
			out += "\t"
		}
		out += c
	}
	return out
}
