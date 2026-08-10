package engine

import (
	"bytes"
	"fmt"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"

	"api-cli/internal/tree"
)

// buildMultipart 构造 multipart/form-data 请求体（文件 part + 普通表单字段 part）。
//   - format=binary 的 param：value 视为本地文件路径，读文件内容写 part（filename=base）
//   - in=formData 的普通 param：WriteField
//   - query/header param 不在此处理（仍由 resolve 主流程分发）
//
// 返回 body 字节 + 含 boundary 的 Content-Type。
func buildMultipart(op *tree.Operation, flags map[string]string) ([]byte, string, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	for _, p := range op.Params {
		v, ok := flags[p.Name]
		if !ok || v == "" {
			continue
		}
		switch {
		case p.Format == "binary":
			fw, err := w.CreateFormFile(p.Name, filepath.Base(v))
			if err != nil {
				return nil, "", err
			}
			f, err := os.Open(v)
			if err != nil {
				return nil, "", fmt.Errorf("打开上传文件 %q 失败: %w", v, err)
			}
			if _, err := io.Copy(fw, f); err != nil {
				f.Close()
				return nil, "", err
			}
			f.Close()
		case p.In == "formData":
			if err := w.WriteField(p.Name, v); err != nil {
				return nil, "", err
			}
		}
	}
	if err := w.Close(); err != nil {
		return nil, "", err
	}
	return buf.Bytes(), w.FormDataContentType(), nil
}
