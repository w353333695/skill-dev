package excelutil

import (
	"bytes"
	"testing"

	"go.easyops.local/fintech_data/internal/types"
)

type mockHeader struct {
}

func (h mockHeader) Header(key, value string) {

}

func Test_excelStream_SetHeader(t *testing.T) {
	type fields struct {
		filename     string
		startRow     int
		headerColMap map[string]int
	}
	type args struct {
		h types.Header
	}
	tests := []struct {
		name   string
		fields fields
		args   args
	}{
		{
			args: args{
				h: mockHeader{},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &excelStream{
				filename:     tt.fields.filename,
				startRow:     tt.fields.startRow,
				headerColMap: tt.fields.headerColMap,
			}
			s.SetHeader(tt.args.h)
		})
	}
}

func Test_excelStream_Exporter(t *testing.T) {
	exporter := NewExporter("test")
	err := exporter.WriteExcelHeader([]HeaderCell{{Name: "一", Id: "one"}, {Name: "二", Id: "two"}})
	if err != nil {
		t.Errorf("WriteExcelHeader() error = %v", err)
		return
	}

	values := []map[string]interface{}{
		{"one": "1", "two": "2"},
		{"one": "yi"},
	}
	for _, v := range values {
		err := exporter.WriteRow(v)
		if err != nil {
			t.Errorf("WriteRow() error = %v", err)
			return
		}
	}

	buf := bytes.Buffer{}
	if !exporter.Write(&buf) {
		t.Errorf("Write() error")
		return
	}

	return
}

func TestCoordinatesToCellName(t *testing.T) {
	type args struct {
		col int
		row int
	}
	tests := []struct {
		name    string
		args    args
		want    string
		wantErr bool
	}{
		{
			args: args{
				col: 0,
				row: 1,
			},
			wantErr: true,
		},
		{
			args: args{
				col: 1,
				row: 1,
			},
			want: "A1",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := CoordinatesToCellName(tt.args.col, tt.args.row)
			if (err != nil) != tt.wantErr {
				t.Errorf("CoordinatesToCellName() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("CoordinatesToCellName() got = %v, want %v", got, tt.want)
			}
		})
	}
}
