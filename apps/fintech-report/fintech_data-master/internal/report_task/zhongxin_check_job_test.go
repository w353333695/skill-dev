package report_task

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/timer"
	history2 "go.easyops.local/fintech_data/mock/history"
	"go.easyops.local/fintech_data/mock/report_task"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewZhongXinCheckJobManager(t *testing.T) {
	type args struct {
		historyService history.TaskHistory
		configService  ConfigService
		reportChecker  ReportChecker
		reportConf     config.ReportConf
	}
	tests := []struct {
		name string
		args args
		want timer.JobManager
	}{
		{
			name: "normal",
			args: args{
				historyService: nil,
				configService:  nil,
				reportChecker:  nil,
				reportConf:     config.ReportConf{},
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewZhongXinCheckJobManager(tt.args.historyService, tt.args.configService, tt.args.reportChecker, tt.args.reportConf)
		})
	}
}

func Test_zhongXinCheckJobManager_GetName(t *testing.T) {
	type fields struct {
		historyService history.TaskHistory
		configService  ConfigService
		reportChecker  ReportChecker
		reportConf     config.ReportConf
		timeNowFunc    timeutil.NowTimeFunc
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name:   "normal",
			fields: fields{},
			want:   "zhongxin_report_check",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := &zhongXinCheckJobManager{
				historyService: tt.fields.historyService,
				configService:  tt.fields.configService,
				reportChecker:  tt.fields.reportChecker,
				reportConf:     tt.fields.reportConf,
				nowTimeFunc:    tt.fields.timeNowFunc,
			}
			if got := c.GetName(); got != tt.want {
				t.Errorf("GetName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_zhongXinCheckJobManager_ListJob(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		historyService history.TaskHistory
		configService  ConfigService
		reportChecker  ReportChecker
		reportConf     config.ReportConf
		timeNowFunc    timeutil.NowTimeFunc
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []timer.Job
		wantErr bool

		taskList  []*fintech_data.ReportTask
		searchErr error

		globalConfig *fintech_data.ReportGlobalConfig
		getErr       error
	}{
		{
			name:   "get config fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			taskList: []*fintech_data.ReportTask{
				{
					TaskId: "fakeId",
				},
			},
			globalConfig: &fintech_data.ReportGlobalConfig{
				ClientId: "xxxx",
			},
			want: []timer.Job{
				&zhongXinCheckJob{
					reportTask: &fintech_data.ReportTask{
						TaskId: "fakeId",
					},
					globalConf: &fintech_data.ReportGlobalConfig{
						ClientId: "xxxx",
					},
					reportChecker: nil,
				},
			},
		},
		{
			name:   "get config fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			taskList: []*fintech_data.ReportTask{
				{
					TaskId: "fakeId",
				},
			},
			getErr:  fmt.Errorf("mock fail"),
			want:    nil,
			wantErr: true,
		},
		{
			name:   "search job fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			searchErr: fmt.Errorf("mock fail"),
			want:      nil,
			wantErr:   true,
		},
		{
			name:   "no job",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			want:    nil,
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchAllTask(ctx, getCheckTaskQuery(), nil, 50, 1607180986, 1609772986).
				Return(tt.taskList, tt.searchErr).Times(1)

			configMock := report_task.NewMockConfigService(ctrl)
			configMock.EXPECT().GetConfig(tt.args.ctx).Return(tt.globalConfig, tt.getErr).MaxTimes(1)
			c := &zhongXinCheckJobManager{
				historyService: historyMock,
				configService:  configMock,
				reportChecker:  tt.fields.reportChecker,
				reportConf:     config.ReportConf{TimeLimit: 30},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			got, err := c.ListJob(tt.args.ctx)
			if (err != nil) != tt.wantErr {
				t.Errorf("ListJob() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ListJob() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_zhongXinCheckJob_Do(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportTask    *fintech_data.ReportTask
		globalConf    *fintech_data.ReportGlobalConfig
		reportChecker ReportChecker
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		jobErr error
	}{
		{
			name: "",
			fields: fields{
				reportTask:    nil,
				globalConf:    nil,
				reportChecker: nil,
			},
			args: args{
				ctx: ctx,
			},
			wantErr: true,
			jobErr:  fmt.Errorf("mock fail"),
		},
		{
			name: "normal",
			fields: fields{
				reportTask: &fintech_data.ReportTask{
					ObjectId: "server",
					TaskId:   "fakeId",
				},
				globalConf:    nil,
				reportChecker: nil,
			},
			args: args{
				ctx: ctx,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			checkerMock := report_task.NewMockReportChecker(ctrl)
			checkerMock.EXPECT().TaskCheck(tt.args.ctx, tt.fields.reportTask, tt.fields.globalConf).Return(tt.jobErr).Times(1)
			c := &zhongXinCheckJob{
				reportTask:    tt.fields.reportTask,
				globalConf:    tt.fields.globalConf,
				reportChecker: checkerMock,
			}
			if err := c.Do(tt.args.ctx); (err != nil) != tt.wantErr {
				t.Errorf("Do() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinCheckJob_GetLockName(t *testing.T) {
	type fields struct {
		reportTask    *fintech_data.ReportTask
		globalConf    *fintech_data.ReportGlobalConfig
		reportChecker ReportChecker
	}
	type args struct {
		org int
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   string
	}{
		{
			name: "",
			fields: fields{
				reportTask: &fintech_data.ReportTask{
					ObjectId: "server",
					TaskId:   "fakeId",
				},
				globalConf:    nil,
				reportChecker: nil,
			},
			args: args{
				org: 8888,
			},
			want: fmt.Sprintf("fintech:report:check:8888:check:server:fakeId"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := &zhongXinCheckJob{
				reportTask:    tt.fields.reportTask,
				globalConf:    tt.fields.globalConf,
				reportChecker: tt.fields.reportChecker,
			}
			if got := c.GetLockName(tt.args.org); got != tt.want {
				t.Errorf("GetLockName() = %v, want %v", got, tt.want)
			}
		})
	}
}
