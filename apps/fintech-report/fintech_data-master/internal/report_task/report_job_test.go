package report_task

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/go-test/deep"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/timer"
	"go.easyops.local/fintech_data/internal/types"
	report_rule2 "go.easyops.local/fintech_data/mock/report_rule"
	"go.easyops.local/fintech_data/mock/report_task"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewJobManager(t *testing.T) {
	type args struct {
		configService ConfigService
		reportService ReportService
		ruleService   report_rule.Service
	}
	tests := []struct {
		name string
		args args
		want timer.JobManager
	}{
		{
			name: "",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewJobManager(tt.args.configService, tt.args.reportService, tt.args.ruleService)
		})
	}
}

func Test_jobManager_GetName(t *testing.T) {
	type fields struct {
		configService ConfigService
		reportService ReportService
		timeNowFunc   timeutil.NowTimeFunc
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name:   "",
			fields: fields{},
			want:   "report_task",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			j := &jobManager{
				configService: tt.fields.configService,
				reportService: tt.fields.reportService,
				nowTimeFunc:   tt.fields.timeNowFunc,
			}
			if got := j.GetName(); got != tt.want {
				t.Errorf("GetName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_jobManager_ListJob(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "easyop"})
	ctx = logctx.WithLogger(ctx, slog.Noop())
	reportMock := report_task.NewMockReportService(ctrl)
	ruleMock := report_rule2.NewMockService(ctrl)
	timeFunc := func() time.Time {
		t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
		return t
	}
	type fields struct {
		configService ConfigService
		reportService ReportService
		timeNowFunc   timeutil.NowTimeFunc
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

		globalConfig *fintech_data.ReportGlobalConfig
		getErr       error

		configList []*fintech_data.ReportObjectConf
		searchErr  error

		nextExecTime string
		updateErr    error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:      false,
			globalConfig: &fintech_data.ReportGlobalConfig{},
			configList: []*fintech_data.ReportObjectConf{
				{
					ObjectId:     "server",
					Crontab:      "1 * * * *",
					NextExecTime: "2019-12-04 16:01:00",
				},
			},
			want: []timer.Job{
				&reportJob{
					globalConfig:  &fintech_data.ReportGlobalConfig{},
					reportService: reportMock,
					reportConf: &fintech_data.ReportObjectConf{
						ObjectId:     "server",
						Crontab:      "1 * * * *",
						NextExecTime: "2019-12-04 16:01:00",
					},
					nowTimeFunc: timeFunc,
					ruleService: ruleMock,
				},
			},
		},
		{
			name:   "no rule",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:      false,
			globalConfig: &fintech_data.ReportGlobalConfig{},
			configList:   []*fintech_data.ReportObjectConf{},
		},
		{
			name:   "search rule fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "get config fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			configList: []*fintech_data.ReportObjectConf{
				{
					ObjectId:     "server",
					Crontab:      "1 * * * *",
					NextExecTime: "2019-12-04 16:01:00",
				},
			},
			wantErr: true,
			getErr:  fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			configMock := report_task.NewMockConfigService(ctrl)
			configMock.EXPECT().GetConfig(tt.args.ctx).Return(tt.globalConfig, tt.getErr).MaxTimes(1)
			ruleMock.EXPECT().SearchRule(tt.args.ctx, getNextRunQuery(), nil).Return(tt.configList, tt.searchErr).Times(1)
			j := &jobManager{
				configService: configMock,
				reportService: reportMock,
				ruleService:   ruleMock,
				nowTimeFunc:   timeFunc,
			}
			got, err := j.ListJob(tt.args.ctx)
			if (err != nil) != tt.wantErr {
				t.Errorf("ListJob() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if diff := deep.Equal(got, tt.want); len(diff) > 0 {
				t.Errorf("ListJob() got = %v, want %v, diff: %v", got, tt.want, diff)
			}
		})
	}
}

func Test_reportJob_Do(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "easyop"})
	ctx = logctx.WithLogger(ctx, slog.Noop())
	timeFunc := func() time.Time {
		t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
		return t
	}
	type fields struct {
		taskConfig    *fintech_data.ReportGlobalConfig
		reportService ReportService
		reportConf    *fintech_data.ReportObjectConf
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateCount int
		updateErr   error

		doTask  bool
		taskErr error
	}{
		{
			name: "normal",
			fields: fields{
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId:     "server",
					InstanceId:   "abc",
					Crontab:      "*/30 * * * *",
					NextExecTime: "2019-12-04 14:09:46",
				},
			},
			args: args{
				ctx: ctx,
			},
			updateCount: 1,
			doTask:      true,
			wantErr:     false,
		},
		{
			name: "not update",
			fields: fields{
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId:     "server",
					InstanceId:   "abc",
					Crontab:      "*/30 * * * *",
					NextExecTime: "2019-12-04 14:09:46",
				},
			},
			args: args{
				ctx: ctx,
			},
			updateCount: 0,
			wantErr:     false,
		},
		{
			name: "update rule fail",
			fields: fields{
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId:     "server",
					InstanceId:   "abc",
					Crontab:      "*/30 * * * *",
					NextExecTime: "2019-12-04 14:09:46",
				},
			},
			args: args{
				ctx: ctx,
			},
			updateErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name: "invalid crontab",
			fields: fields{
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId:     "server",
					InstanceId:   "abc",
					Crontab:      "*/30 * ---",
					NextExecTime: "2019-12-04 14:09:46",
				},
			},
			args: args{
				ctx: ctx,
			},
			wantErr: true,
		},
		{
			name: "task fail",
			fields: fields{
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId:     "server",
					InstanceId:   "abc",
					Crontab:      "*/30 * * * *",
					NextExecTime: "2019-12-04 14:09:46",
				},
			},
			args: args{
				ctx: ctx,
			},
			updateCount: 1,
			doTask:      true,
			taskErr:     fmt.Errorf("mock fail"),
			wantErr:     true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ruleMock := report_rule2.NewMockService(ctrl)
			updateConf := &fintech_data.ReportObjectConf{
				ObjectId:     "server",
				InstanceId:   "abc",
				Crontab:      "*/30 * * * *",
				NextExecTime: "2019-12-04 15:30:00",
			}
			ruleMock.EXPECT().UpdateRuleByQuery(tt.args.ctx,
				map[string]interface{}{"instanceId": "abc", "nextExecTime": "2019-12-04 14:09:46"},
				updateConf, []string{report_rule.NextExecTime}).Return(tt.updateCount, tt.updateErr).MaxTimes(1)
			reportMock := report_task.NewMockReportService(ctrl)
			if tt.doTask {
				reportMock.EXPECT().CreateTask(tt.args.ctx, types.CreateTaskRequest{
					GlobalConfig: tt.fields.taskConfig,
					ObjectConf:   tt.fields.reportConf,
					Method:       types.TimerCreate,
				}).Return("", tt.taskErr).Times(1)
			}
			r := reportJob{
				globalConfig:  tt.fields.taskConfig,
				reportService: reportMock,
				reportConf:    tt.fields.reportConf,
				ruleService:   ruleMock,
				nowTimeFunc:   timeFunc,
			}
			if err := r.Do(tt.args.ctx); (err != nil) != tt.wantErr {
				t.Errorf("Do() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_reportJob_GetJobName(t *testing.T) {
	type fields struct {
		taskConfig    *fintech_data.ReportGlobalConfig
		reportService ReportService
		reportConf    *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name: "",
			fields: fields{
				taskConfig: &fintech_data.ReportGlobalConfig{
					ClientId: "new",
				},
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId: "server",
				},
			},
			want: "server",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := reportJob{
				globalConfig:  tt.fields.taskConfig,
				reportService: tt.fields.reportService,
				reportConf:    tt.fields.reportConf,
			}
			if got := r.GetJobName(); got != tt.want {
				t.Errorf("GetJobName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_reportJob_GetLockName(t *testing.T) {
	type fields struct {
		taskConfig    *fintech_data.ReportGlobalConfig
		reportService ReportService
		reportConf    *fintech_data.ReportObjectConf
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
				taskConfig: &fintech_data.ReportGlobalConfig{
					ClientId: "new",
				},
				reportConf: &fintech_data.ReportObjectConf{
					ObjectId: "server",
				},
			},
			args: args{
				org: 8888,
			},
			want: fmt.Sprintf("fintech:data:report:%d:%s", 8888, "server"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := reportJob{
				globalConfig:  tt.fields.taskConfig,
				reportService: tt.fields.reportService,
				reportConf:    tt.fields.reportConf,
			}
			if got := r.GetLockName(tt.args.org); got != tt.want {
				t.Errorf("GetLockName() = %v, want %v", got, tt.want)
			}
		})
	}
}
