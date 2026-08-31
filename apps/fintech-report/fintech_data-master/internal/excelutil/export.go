package excelutil

import (
	"fmt"
	"io"
	"strconv"

	"github.com/360EntSecGroup-Skylar/excelize"

	"go.easyops.local/fintech_data/internal/types"
)

const defaultSheet = "Sheet1"

func GenHeaders(filename string) map[string]string {
	headers := map[string]string{
		"Content-Type":              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"Content-Transfer-Encoding": "binary",
		"Content-Disposition":       fmt.Sprintf("attachment; filename=%s.xlsx", filename),
	}
	return headers
}

type Exporter interface {
	types.FileExporter

	WriteExcelHeader(headers []HeaderCell) error
	WriteRow(value map[string]interface{}) error
}

type NewExporterFunc func(filename string) Exporter

func NewExporter(filename string) Exporter {
	file := excelize.NewFile()
	return &excelStream{
		filename: filename,
		file:     file,
		startRow: 1,
	}
}

type excelStream struct {
	filename string
	file     *excelize.File

	startRow     int
	headerColMap map[string]int
}

type HeaderCell struct {
	Name string
	Id   string
}

func (s *excelStream) WriteExcelHeader(headers []HeaderCell) error {
	headerColMap := make(map[string]int)
	for idx, cell := range headers {
		headerColMap[cell.Id] = idx
		axis, _ := CoordinatesToCellName(idx+1, s.startRow)
		s.file.SetCellValue(defaultSheet, axis, cell.Name)
	}
	s.headerColMap = headerColMap
	s.startRow += 1
	return nil
}

func (s *excelStream) WriteRow(value map[string]interface{}) error {
	for k, v := range value {
		if colID, ok := s.headerColMap[k]; ok {
			axis, _ := CoordinatesToCellName(colID+1, s.startRow)
			s.file.SetCellValue(defaultSheet, axis, v)
		}
	}
	s.startRow += 1
	return nil
}

func (s *excelStream) Write(w io.Writer) bool {
	err := s.file.Write(w)
	return err == nil
}

func (s *excelStream) SetHeader(h types.Header) {
	header := GenHeaders(s.filename)
	for k, v := range header {
		h.Header(k, v)
	}
}

func CoordinatesToCellName(col, row int) (string, error) {
	if col < 1 || row < 1 {
		return "", fmt.Errorf("invalid cell coordinates [%d, %d]", col, row)
	}
	colname := ColumnNumberToName(col)
	return colname + strconv.Itoa(row), nil
}

func ColumnNumberToName(num int) string {
	var col string
	for num > 0 {
		col = string(rune((num-1)%26+65)) + col
		num = (num - 1) / 26
	}
	return col
}
