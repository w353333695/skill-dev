package types

import "io"

type Header interface {
	Header(key, value string)
}

type FileExporter interface {
	SetHeader(h Header)
	Write(w io.Writer) bool
}
