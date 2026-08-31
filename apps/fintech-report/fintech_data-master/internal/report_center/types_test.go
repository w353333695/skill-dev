package report_center

import "testing"

func TestCheckResponse_IsEffected(t *testing.T) {
	type fields struct {
		BranchId string
		Code     string
		Msg      string
		Data     []CheckData
	}
	tests := []struct {
		name   string
		fields fields
		want   bool
	}{
		{
			name: "",
			fields: fields{
				BranchId: "abc",
				Code:     "abc",
				Msg:      "",
				Data:     nil,
			},
			want: true,
		},
		{
			name:   "",
			fields: fields{},
			want:   false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := &CheckResponse{
				BranchId: tt.fields.BranchId,
				Code:     tt.fields.Code,
				Msg:      tt.fields.Msg,
				Data:     tt.fields.Data,
			}
			if got := c.IsEffected(); got != tt.want {
				t.Errorf("IsEffected() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConvertReportType(t *testing.T) {
	type args struct {
		reportType string
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "ReportTypeNew",
			args: args{
				reportType: ReportTypeNew,
			},
			want: "新建",
		},
		{
			name: "ReportTypeDelete",
			args: args{
				reportType: ReportTypeDelete,
			},
			want: "删除",
		},
		{
			name: "ReportTypeUpdate",
			args: args{
				reportType: ReportTypeUpdate,
			},
			want: "更新",
		},
		{
			name: "can not find type",
			args: args{
				reportType: "wrong type",
			},
			want: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ConvertReportType(tt.args.reportType); got != tt.want {
				t.Errorf("ConvertReportType() = %v, want %v", got, tt.want)
			}
		})
	}
}
