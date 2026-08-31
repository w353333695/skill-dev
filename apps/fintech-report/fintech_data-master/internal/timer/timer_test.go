package timer

import (
	"context"
	"testing"
	"time"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/slog"
)

func TestNewTimer(t *testing.T) {
	type args struct {
		logger      slog.Logger
		timerConfig config.TimerConfig
		timerTask   Task
		runInternal int
	}
	tests := []struct {
		name string
		args args
		want *timerService
	}{
		{
			name: "",
			args: args{},
			want: &timerService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewTimer(tt.args.logger, tt.args.timerConfig, tt.args.timerTask)
		})
	}
}

type fakeTimerTask struct {
}

func (t *fakeTimerTask) Run(ctx context.Context) {
	println("start fake job", timeutil.NowTime().Format(timeutil.TimeFormat))
	time.Sleep(time.Second)
	println("end fake job", timeutil.NowTime().Format(timeutil.TimeFormat))
}

func (t *fakeTimerTask) GetInternal() int {
	return 3
}

func Test_timerService_RunTimeTask(t *testing.T) {
	ctx, _ := context.WithTimeout(context.Background(), time.Second*10)
	type fields struct {
		logger      slog.Logger
		timerConfig config.TimerConfig
		timerTask   Task
		nowTimeFunc timeutil.NowTimeFunc
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				logger:      slog.Noop(),
				timerConfig: config.TimerConfig{},
				timerTask:   &fakeTimerTask{},
				nowTimeFunc: func() time.Time {
					ti, _ := time.Parse(timeutil.TimeFormat, "2011-12-31 04:23:59")
					return ti
				},
			},
			args: args{
				ctx: ctx,
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &timerService{
				logger:      tt.fields.logger,
				timerConfig: tt.fields.timerConfig,
				timerTask:   tt.fields.timerTask,
				nowTimeFunc: tt.fields.nowTimeFunc,
			}
			if err := s.RunTimeTask(tt.args.ctx); (err != nil) != tt.wantErr {
				t.Errorf("RunTimeTask() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_timerService_getStartInterval(t *testing.T) {
	type fields struct {
		logger      slog.Logger
		timerConfig config.TimerConfig
		timerTask   Task
		runInternal int
		nowTimeFunc timeutil.NowTimeFunc
	}
	tests := []struct {
		name   string
		fields fields
		want   time.Duration
	}{
		{
			name: "",
			fields: fields{
				nowTimeFunc: func() time.Time {
					ti, _ := time.Parse(timeutil.TimeFormat, "2020-12-23 17:20:45")
					return ti
				},
			},
			want: 15 * time.Second,
		},
		{
			name: "",
			fields: fields{
				nowTimeFunc: func() time.Time {
					ti, _ := time.Parse(timeutil.TimeFormat, "2020-12-23 17:20:00")
					return ti
				},
			},
			want: 0 * time.Second,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &timerService{
				logger:      tt.fields.logger,
				timerConfig: tt.fields.timerConfig,
				timerTask:   tt.fields.timerTask,
				nowTimeFunc: tt.fields.nowTimeFunc,
			}
			if got := s.getStartInterval(); got != tt.want {
				t.Errorf("getStartInterval() = %v, want %v", got, tt.want)
			}
		})
	}
}
