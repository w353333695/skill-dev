package task

import (
	"context"
	"fmt"
	"reflect"
	"testing"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	message "go.easyops.local/contracts/protorepo-fintech_data/task"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/report_task"
	task_types "go.easyops.local/fintech_data/internal/types"
	report_center2 "go.easyops.local/fintech_data/mock/report_center"
	report_rule2 "go.easyops.local/fintech_data/mock/report_rule"
	report_task2 "go.easyops.local/fintech_data/mock/report_task"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func Test_taskService_DebugToken(t *testing.T) {
	ctrl := gomock.NewController(t)
	type fields struct {
		reportCenter report_center.Service
	}
	type args struct {
		ctx     context.Context
		request *message.DebugTokenRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.DebugTokenResponse
		wantErr bool

		getErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &message.DebugTokenRequest{
					GrantType:    "fake",
					ClientId:     "client_id",
					ClientSecret: "secret",
				},
			},
			want: &message.DebugTokenResponse{
				AccessToken: "fakeToken",
				ExpiresIn:   3600,
			},
			wantErr: false,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &message.DebugTokenRequest{
					GrantType:    "fake",
					ClientId:     "client_id",
					ClientSecret: "secret",
				},
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		centerMock := report_center2.NewMockService(ctrl)
		centerMock.EXPECT().GetToken(tt.args.ctx, report_center.TokenRequest{
			ClientId:     tt.args.request.ClientId,
			ClientSecret: tt.args.request.ClientSecret,
			GrantType:    tt.args.request.GrantType,
		}, nil).Return(&report_center.TokenInfo{
			AccessToken: "fakeToken",
			ExpiresIn:   3600,
		}, tt.getErr).Times(1)
		t.Run(tt.name, func(t1 *testing.T) {
			t := &taskService{
				reportCenter: centerMock,
			}
			got, err := t.DebugToken(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t1.Errorf("DebugToken() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t1.Errorf("DebugToken() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestNewTaskService(t *testing.T) {
	type args struct {
		reportCenter  report_center.Service
		ruleService   report_rule.Service
		configService report_task.ConfigService
		reportService report_task.ReportService
	}
	tests := []struct {
		name string
		args args
		want *taskService
	}{
		{
			name: "",
			args: args{},
			want: &taskService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewTaskService(tt.args.reportCenter, tt.args.configService, tt.args.ruleService, tt.args.reportService)
		})
	}
}

func Test_taskService_GetGlobalConfig(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type fields struct {
		reportCenter      report_center.Service
		taskConfigService report_task.ConfigService
	}
	type args struct {
		ctx     context.Context
		request *types.Empty
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportGlobalConfig
		wantErr bool

		config *fintech_data.ReportGlobalConfig
		getErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: context.Background(),
			},
			want: &fintech_data.ReportGlobalConfig{
				ClientId: "xxx",
			},
			config: &fintech_data.ReportGlobalConfig{
				ClientId: "xxx",
			},
			wantErr: false,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_task2.NewMockConfigService(ctrl)
			serviceMock.EXPECT().GetConfig(tt.args.ctx).Return(tt.config, tt.getErr).Times(1)
			s := &taskService{
				reportCenter:  tt.fields.reportCenter,
				configService: serviceMock,
			}
			got, err := s.GetGlobalConfig(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetTaskConfig() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetTaskConfig() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_taskService_UpdateGlobalConfig(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type fields struct {
		reportCenter      report_center.Service
		taskConfigService report_task.ConfigService
	}
	type args struct {
		ctx     context.Context
		request *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *types.Empty
		wantErr bool

		updateErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &fintech_data.ReportGlobalConfig{
					ClientId: "xxx",
				},
			},
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &fintech_data.ReportGlobalConfig{
					ClientId: "xxx",
				},
			},
			wantErr:   true,
			updateErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_task2.NewMockConfigService(ctrl)
			serviceMock.EXPECT().UpdateConfig(tt.args.ctx, &fintech_data.ReportGlobalConfig{
				ClientId: "xxx",
			}).Return(tt.updateErr).MaxTimes(1)
			s := &taskService{
				reportCenter:  tt.fields.reportCenter,
				configService: serviceMock,
			}
			got, err := s.UpdateGlobalConfig(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("UpdateTaskConfig() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("UpdateTaskConfig() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_taskService_ReportData(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "easyops"})
	type fields struct {
		reportCenter  report_center.Service
		ruleService   report_rule.Service
		configService report_task.ConfigService
		reportService report_task.ReportService
	}
	type args struct {
		ctx     context.Context
		request *message.ReportDataRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.ReportDataResponse
		wantErr bool

		globalConfig *fintech_data.ReportGlobalConfig
		getErr1      error

		reportConf *fintech_data.ReportObjectConf
		getErr2    error

		taskErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.ReportDataRequest{ObjectId: "server"},
			},
			want:         &message.ReportDataResponse{TaskId: "taskId"},
			wantErr:      false,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:   &fintech_data.ReportObjectConf{ObjectId: "server"},
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.ReportDataRequest{ObjectId: "server"},
			},
			wantErr: true,
			getErr1: fmt.Errorf("mock fail"),
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.ReportDataRequest{ObjectId: "server"},
			},
			wantErr:      true,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			getErr2:      fmt.Errorf("mock fail"),
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.ReportDataRequest{ObjectId: "server"},
			},
			wantErr:      true,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:   &fintech_data.ReportObjectConf{ObjectId: "server"},
			taskErr:      fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_task2.NewMockConfigService(ctrl)
			serviceMock.EXPECT().GetConfig(tt.args.ctx).Return(tt.globalConfig, tt.getErr1).Times(1)

			ruleMock := report_rule2.NewMockService(ctrl)
			ruleMock.EXPECT().GetRule(tt.args.ctx, tt.args.request.ObjectId).Return(
				tt.reportConf, tt.getErr2).MaxTimes(1)

			reportMock := report_task2.NewMockReportService(ctrl)
			reportMock.EXPECT().CreateTask(gomock.Any(), task_types.CreateTaskRequest{
				GlobalConfig: tt.globalConfig,
				ObjectConf:   tt.reportConf,
				Method:       task_types.ManualCreate,
			}).Return("taskId", tt.taskErr).MaxTimes(1)
			s := &taskService{
				reportCenter:  tt.fields.reportCenter,
				ruleService:   ruleMock,
				configService: serviceMock,
				reportService: reportMock,
			}
			got, err := s.ReportData(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportData() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportData() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_taskService_RequestAudit(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "easyops"})
	type fields struct {
		reportCenter  report_center.Service
		ruleService   report_rule.Service
		configService report_task.ConfigService
		reportService report_task.ReportService
	}
	type args struct {
		ctx     context.Context
		request *message.RequestAuditRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		globalConfig    *fintech_data.ReportGlobalConfig
		getConfigErr    error
		requestAuditErr error

		reportConf *fintech_data.ReportObjectConf
	}{
		{
			name:   "ok",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.RequestAuditRequest{ObjectId: "server", St: "2021-12-03 09:02:05"},
			},
			wantErr:      false,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:   &fintech_data.ReportObjectConf{ObjectId: "server"},
		},
		{
			name:   "get config err",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.RequestAuditRequest{ObjectId: "server", St: "2021-12-03 09:02:05"},
			},
			getConfigErr: fmt.Errorf("err"),
			wantErr:      true,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:   &fintech_data.ReportObjectConf{ObjectId: "server"},
		},
		{
			name:   "create task err",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.RequestAuditRequest{ObjectId: "server", St: "2021-12-03 09:02:05"},
			},
			requestAuditErr: fmt.Errorf("err"),
			wantErr:         true,
			globalConfig:    &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:      &fintech_data.ReportObjectConf{ObjectId: "server"},
		},
		{
			name:   "parse time err",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: &message.RequestAuditRequest{ObjectId: "server", St: "2021/12/03 09:02:05"},
			},
			wantErr:      true,
			globalConfig: &fintech_data.ReportGlobalConfig{ClientId: "haha"},
			reportConf:   &fintech_data.ReportObjectConf{ObjectId: "server"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_task2.NewMockConfigService(ctrl)
			serviceMock.EXPECT().GetConfig(tt.args.ctx).Return(tt.globalConfig, tt.getConfigErr).MaxTimes(1)

			reportMock := report_task2.NewMockReportService(ctrl)
			reportMock.EXPECT().CreateAuditTask(gomock.Any(), true, tt.args.request.BranchList, tt.globalConfig, int64(1638493325), int64(1638493325), tt.args.request.ObjectId, tt.args.request.TaskId).Return(tt.requestAuditErr).AnyTimes()
			s := &taskService{
				reportCenter:  tt.fields.reportCenter,
				configService: serviceMock,
				reportService: reportMock,
			}
			_, err := s.RequestAudit(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportData() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}
