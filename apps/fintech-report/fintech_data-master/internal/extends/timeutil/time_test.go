package timeutil

import (
	"reflect"
	"testing"
	"time"
)

func TestNowTime(t *testing.T) {
	tests := []struct {
		name string
		want time.Time
	}{
		{},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NowTime()
		})
	}
}

func TestParseTimeStr(t *testing.T) {
	type args struct {
		timeStr string
	}
	tests := []struct {
		name    string
		args    args
		want    time.Time
		wantErr bool
	}{
		{
			name: "",
			args: args{
				timeStr: "2020-12-23 21:11:52",
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ParseTimeStr(tt.args.timeStr)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseTimeStr() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}

func TestParseTimeStrToUnix(t *testing.T) {
	type args struct {
		timeStr string
	}
	tests := []struct {
		name    string
		args    args
		want    int64
		wantErr bool
	}{
		{
			name: "",
			args: args{
				timeStr: "2020-12-23 21:11:52",
			},
			want:    1608729112,
			wantErr: false,
		},
		{
			name: "",
			args: args{
				timeStr: "fail",
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := ParseTimeStrToUnix(tt.args.timeStr)
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseTimeStrToUnix() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("ParseTimeStrToUnix() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestDefaultTimeLimit(t *testing.T) {
	type args struct {
		timeFunc NowTimeFunc
		dayBack  int
	}
	tests := []struct {
		name  string
		args  args
		want  int
		want1 int
	}{
		{
			name: "",
			args: args{
				timeFunc: NowTime,
				dayBack:  30,
			},
			want:  0,
			want1: 0,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			DefaultTimeLimit(tt.args.timeFunc, tt.args.dayBack)
		})
	}
}

func TestToday(t *testing.T) {
	tests := []struct {
		name string
		want time.Time
	}{
		{
			name: "",
			want: time.Time{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			Today()
		})
	}
}

func TestGetDateTimeByTime(t *testing.T) {
	type args struct {
		t time.Time
	}
	tests := []struct {
		name string
		args args
		want time.Time
	}{
		{
			name: "",
			args: args{
				t: time.Unix(1486057371, 0),
			},
			want: time.Unix(1486051200, 0),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetDateTimeByTime(tt.args.t); !reflect.DeepEqual(got.Unix(), tt.want.Unix()) {
				t.Errorf("GetDateTimeByTime() = %v, want %v", got, tt.want)
			}
		})
	}
}
