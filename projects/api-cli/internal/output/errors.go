package output

import (
	"encoding/json"
	"fmt"
	"io"
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
// 已重构为导出的 FormatTable（见 format.go），支持 headers 中文表头映射。
// joinRow 仍在此文件供 FormatTable 复用。

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
