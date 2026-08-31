package types

import (
	"reflect"
	"testing"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
)

func TestIsEndStatus(t *testing.T) {
	type args struct {
		status string
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			name: "",
			args: args{
				status: StatusReporting,
			},
			want: false,
		},
		{
			name: "",
			args: args{
				status: StatusSuccess,
			},
			want: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := IsEndStatus(tt.args.status); got != tt.want {
				t.Errorf("IsEndStatus() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetStatusByType(t *testing.T) {
	type args struct {
		status string
	}
	tests := []struct {
		name string
		args args
		want []string
	}{
		{
			name: "",
			args: args{
				status: StatusSuccess,
			},
			want: []string{StatusSuccess},
		},
		{
			name: "",
			args: args{
				status: StatusPartialSuccess,
			},
			want: []string{StatusPartialSuccess},
		},
		{
			name: "",
			args: args{
				status: StatusFail,
			},
			want: []string{StatusFail},
		},
		{
			name: "",
			args: args{
				status: "running",
			},
			want: []string{StatusReporting, StatusInitial, StatusResulting},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetStatusByType(tt.args.status); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetStatusByType() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConvertStatus(t *testing.T) {
	type args struct {
		status string
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			args: args{
				status: StatusResulting,
			},
			want: "执行中",
		},
		{
			args: args{
				status: StatusSuccess,
			},
			want: "成功",
		},
		{
			args: args{
				status: StatusPartialSuccess,
			},
			want: "部分成功",
		},
		{
			args: args{
				status: StatusFail,
			},
			want: "失败",
		},
		{
			args: args{
				status: StatusConflict,
			},
			want: "冲突",
		},
		{
			args: args{
				status: StatusNoReport,
			},
			want: "暂无数据",
		},
		{
			args: args{
				status: "other",
			},
			want: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ConvertStatus(tt.args.status); got != tt.want {
				t.Errorf("ConvertStatus() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestSwitchMoreHighLevelStatusReportTask(t *testing.T) {
	type args struct {
		task1 *fintech_data.ReportTask
		task2 *fintech_data.ReportTask
	}
	task1 := &fintech_data.ReportTask{Status: StatusResulting}
	task2 := &fintech_data.ReportTask{Status: StatusPendingCheck}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			args: args{
				task1: task1,
				task2: &fintech_data.ReportTask{Status: StatusWithWarn},
			},
			want: StatusResulting,
		},
		{
			args: args{
				task1: task1,
				task2: task2,
			},
			want: StatusPendingCheck,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := SwitchMoreHighLevelStatus(tt.args.task1.Status, tt.args.task2.Status); got != tt.want {
				t.Errorf("SwitchMoreHighLevelStatusReportTask() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConvertInstanceStatus(t *testing.T) {
	type args struct {
		status string
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "StatusPendingCheck",
			args: args{
				status: StatusPendingCheck,
			},
			want: "执行中",
		},
		{
			name: "Success",
			args: args{
				status: StatusSuccess,
			},
			want: "成功",
		},
		{
			name: "Warning",
			args: args{
				status: StatusWithWarn,
			},
			want: "警告",
		},
		{
			name: "FailTypeReporting",
			args: args{
				status: FailTypeReporting,
			},
			want: "失败",
		},
		{
			name: "can not find type",
			args: args{
				status: "wrong type",
			},
			want: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ConvertInstanceStatus(tt.args.status); got != tt.want {
				t.Errorf("ConvertInstanceStatus() = %v, want %v", got, tt.want)
			}
		})
	}
}
