package report_task

import (
	"context"
	"fmt"
	"reflect"
	"testing"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/types"
	history2 "go.easyops.local/fintech_data/mock/history"
	report_center2 "go.easyops.local/fintech_data/mock/report_center"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewZhongXinChecker(t *testing.T) {
	type args struct {
		reportCenter    report_center.Service
		taskHistory     history.TaskHistory
		centerData      history.CenterData
		objStat         history.ObjectStat
		historyRecorder history.Recorder
		reportConf      config.ReportConf
		mongoClient     pmongo.ClientInterface
	}
	tests := []struct {
		name string
		args args
		want ReportChecker
	}{
		{
			name: "",
			args: args{
				reportCenter: nil,
				taskHistory:  nil,
				centerData:   nil,
				reportConf:   config.ReportConf{},
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewZhongXinChecker(nil, tt.args.reportCenter, tt.args.taskHistory, tt.args.centerData, tt.args.objStat, tt.args.historyRecorder, tt.args.reportConf, tt.args.mongoClient, nil)
		})
	}
}

func Test_zhongXinChecker_TaskCheck(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx        context.Context
		reportTask *fintech_data.ReportTask
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		getErr  error
		wantErr bool
	}{
		{
			name:   "get task fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					Status:    types.StatusResulting,
					StartTime: "2021-01-03 15:09:46",
				},
				globalConf: nil,
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name:   "resulting",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					Status:    types.StatusResulting,
					StartTime: "2021-01-03 15:09:46",
				},
				globalConf: nil,
			},
			wantErr: true,
		},
		{
			name:   "reporting",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					Status:    types.StatusReporting,
					StartTime: "2021-01-03 15:09:46",
				},
				globalConf: nil,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().GetTask(ctx, tt.args.reportTask.TaskId).Return(tt.args.reportTask, tt.getErr).Times(1)
			fields := map[string]interface{}{
				"_id":                true,
				"facilityDescriptor": true,
			}
			historyMock.EXPECT().SearchInstanceLimit(ctx, getTaskInstanceQuery(tt.args.reportTask), fields, 10, 1609657786, 1609772986, gomock.Any()).
				Return(nil, fmt.Errorf("mock fail")).MaxTimes(1)

			c := &zhongXinChecker{
				reportCenter: tt.fields.reportCenter,
				taskHistory:  historyMock,
				centerData:   tt.fields.centerData,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if err := c.TaskCheck(tt.args.ctx, tt.args.reportTask, tt.args.globalConf); (err != nil) != tt.wantErr {
				t.Errorf("TaskCheck() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_taskResultCheck(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx        context.Context
		reportTask *fintech_data.ReportTask
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		searchInstanceLimit *history.InstanceLimitResult

		searchInstanceLimit2 *history.InstanceLimitResult
		searchInstanceErr    error

		branchList      []*fintech_data.ReportBranch
		searchBranchErr error
		updateTaskErr   error
	}{
		{
			name: "search instance with branchId error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			searchInstanceLimit: &history.InstanceLimitResult{},
			searchInstanceErr:   fmt.Errorf("search instance with branchId error"),
			wantErr:             true,
		},

		{
			name: "search all branch error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			searchInstanceLimit:  &history.InstanceLimitResult{},
			searchInstanceLimit2: &history.InstanceLimitResult{},
			searchBranchErr:      fmt.Errorf("search all branch error"),
			wantErr:              true,
		},

		{
			name: "update task error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 3,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			searchInstanceLimit:  &history.InstanceLimitResult{},
			searchInstanceLimit2: &history.InstanceLimitResult{},
			updateTaskErr:        fmt.Errorf("update task error"),
			wantErr:              true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)

			fields1 := map[string]interface{}{
				"_id":                true,
				"facilityDescriptor": true,
			}
			historyMock.EXPECT().SearchInstanceLimit(ctx, getTaskInstanceQuery(tt.args.reportTask), fields1, 10, 1609657786, 1609772986, gomock.Any()).
				Return(tt.searchInstanceLimit, nil).MaxTimes(1)

			fields2 := map[string]interface{}{
				"data":    false,
				"showKey": false,
			}
			historyMock.EXPECT().SearchInstanceLimit(ctx, getTaskInstanceQueryWithBranchIdCondition(tt.args.reportTask),
				fields2, 10, 1609657786, 1609772986, gomock.Any()).
				Return(tt.searchInstanceLimit2, tt.searchInstanceErr).MaxTimes(1)

			query := []*monthly_model.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.TaskId),
				},
			}
			historyMock.EXPECT().SearchAllBranch(ctx, query, nil, 5000, 1609657786, 1609772986).Return(tt.branchList, tt.searchBranchErr).MaxTimes(1)

			historyMock.EXPECT().UpdateTask(ctx, tt.args.reportTask.TaskId, tt.args.reportTask).Return(tt.updateTaskErr).MaxTimes(1)

			test := &testRedisMock{t: t}
			c := &zhongXinChecker{
				newLockFunc: test.testNewLockFunc,
				taskHistory: historyMock,
				timeNowFunc: testNowTime,
				reportConf:  config.ReportConf{SearchBatch: 10},
			}
			if err := c.taskResultCheck(tt.args.ctx, tt.args.reportTask, tt.args.globalConf); (err != nil) != tt.wantErr {
				t.Errorf("taskResultCheck() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateInstanceBranchId(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx        context.Context
		reportTask *fintech_data.ReportTask
		globalConf *fintech_data.ReportGlobalConfig
		st         int
		et         int
	}

	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		searchInstanceLimit *history.InstanceLimitResult
		searchInstanceErr   error

		branchIdResp      *report_center.BranchIdResponse
		searchBranchIdErr error

		updateInstanceErr error
	}{
		{
			name: "SearchInstanceLimit error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceErr: fmt.Errorf("SearchInstanceLimit error"),
			wantErr:           true,
		},

		{
			name: "instance list len is 0",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{},
		},

		{
			name: "SelectBranchId error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			searchBranchIdErr: fmt.Errorf("SelectBranchId error"),
			wantErr:           true,
		},

		{
			name: "SelectBranchId resp code error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			branchIdResp: &report_center.BranchIdResponse{
				Code: report_center.ZhongXinCodeReportFail,
			},
			wantErr: true,
		},

		{
			name: "convertBranchIdResponse error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			branchIdResp: &report_center.BranchIdResponse{
				Code: report_center.ZhongXinCodeReportSuccess,
				Data: "",
			},
			wantErr: true,
		},

		{
			name: "UpdateInstance error",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			branchIdResp: &report_center.BranchIdResponse{
				Code: report_center.ZhongXinCodeReportSuccess,
				Data: []interface{}{
					map[string]interface{}{
						"branchId":           "branchId111",
						"facilityDescriptor": "aaa",
						"groupId":            "groupId",
					},
				},
			},
			updateInstanceErr: fmt.Errorf("UpdateInstance error"),
			wantErr:           true,
		},

		{
			name: "success",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1609657786,
				et:         1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			branchIdResp: &report_center.BranchIdResponse{
				Code: report_center.ZhongXinCodeReportSuccess,
				Data: []interface{}{
					map[string]interface{}{
						"branchId":           "branchId111",
						"facilityDescriptor": "aaa",
						"groupId":            "groupId",
					},
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			searchFields := map[string]interface{}{
				"_id":                true,
				"facilityDescriptor": true,
			}
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchInstanceLimit(tt.args.ctx, getTaskInstanceQuery(tt.args.reportTask), searchFields, 10, 1609657786, 1609772986, gomock.Any()).
				Return(tt.searchInstanceLimit, tt.searchInstanceErr).Times(1)

			reportCenterMock := report_center2.NewMockService(ctrl)
			branchIdRequest := report_center.BranchIdRequest{
				DataType: getReportDataType(tt.args.reportTask.ObjectId),
				DataList: []string{"aaa"},
			}
			reportCenterMock.EXPECT().SelectBranchId(ctx, branchIdRequest, tt.args.globalConf).Return(tt.branchIdResp, tt.searchBranchIdErr).MaxTimes(1)

			updateInstance := &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				BranchId:           "branchId111",
			}
			historyMock.EXPECT().UpdateInstance(tt.args.ctx, updateInstance.DataId, updateInstance, []string{"branchId"}).Return(tt.updateInstanceErr).MaxTimes(1)

			c := &zhongXinChecker{
				reportCenter: reportCenterMock,
				taskHistory:  historyMock,
				centerData:   tt.fields.centerData,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if err := c.updateInstanceBranchId(tt.args.ctx, tt.args.reportTask, tt.args.globalConf, tt.args.st, tt.args.et); (err != nil) != tt.wantErr {
				t.Errorf("updateInstanceBranchId() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_dealWithInstanceCheckResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx         context.Context
		reportTask  *fintech_data.ReportTask
		globalConf  *fintech_data.ReportGlobalConfig
		reportCount *history.ReportCount
		st          int
		et          int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		searchInstanceLimit *history.InstanceLimitResult
		searchInstanceErr   error

		checkResp              *report_center.CheckResponse
		instanceResultCheckErr error

		updateInstance    *fintech_data.ReportInstance
		updateInstanceErr error
	}{
		{
			name:   "SearchInstanceLimit error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf:  &fintech_data.ReportGlobalConfig{},
				reportCount: &history.ReportCount{},
				st:          1609657786,
				et:          1609772986,
			},
			searchInstanceErr: fmt.Errorf("SearchInstanceLimit error"),
			updateInstance:    &fintech_data.ReportInstance{},
			wantErr:           true,
		},

		{
			name:   "instanceResultCheck error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf:  &fintech_data.ReportGlobalConfig{},
				reportCount: &history.ReportCount{},
				st:          1609657786,
				et:          1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						BranchId:           "branchId111",
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			instanceResultCheckErr: fmt.Errorf("instanceResultCheck error"),
			updateInstance: &fintech_data.ReportInstance{
				BranchId:           "branchId111",
				DataId:             "111",
				FacilityDescriptor: "aaa",
				Status:             types.FailTypeResult,
				IsFail:             true,
				Retryable:          true,
				Code:               report_center.CodeDataHandleFail,
				Ts:                 1609772986,
			},
			wantErr: true,
		},

		{
			name:   "UpdateInstance error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf:  &fintech_data.ReportGlobalConfig{},
				reportCount: &history.ReportCount{},
				st:          1609657786,
				et:          1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						BranchId:           "branchId111",
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId111",
				Code:     report_center.CodeHandleFail,
			},
			updateInstance: &fintech_data.ReportInstance{
				BranchId:           "branchId111",
				DataId:             "111",
				FacilityDescriptor: "aaa",
				Status:             types.FailTypeResult,
				IsFail:             true,
				Retryable:          true,
				Code:               report_center.CodeDataHandleFail,
				Ts:                 1609772986,
			},
			updateInstanceErr: fmt.Errorf("UpdateInstance error"),
			wantErr:           true,
		},

		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				globalConf:  &fintech_data.ReportGlobalConfig{},
				reportCount: &history.ReportCount{},
				st:          1609657786,
				et:          1609772986,
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						BranchId:           "branchId111",
						DataId:             "111",
						FacilityDescriptor: "aaa",
					},
				},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId111",
				Code:     report_center.CodeHandleFail,
			},

			updateInstance: &fintech_data.ReportInstance{
				BranchId:           "branchId111",
				DataId:             "111",
				FacilityDescriptor: "aaa",
				Status:             types.FailTypeResult,
				IsFail:             true,
				Retryable:          true,
				Code:               report_center.CodeDataHandleFail,
				Ts:                 1609772986,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			fields := map[string]interface{}{
				"data":    false,
				"showKey": false,
			}
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchInstanceLimit(tt.args.ctx, getTaskInstanceQueryWithBranchIdCondition(tt.args.reportTask), fields, 10, 1609657786, 1609772986, gomock.Any()).
				Return(tt.searchInstanceLimit, tt.searchInstanceErr).Times(1)

			reportCenterMock := report_center2.NewMockService(ctrl)
			checkRequest := report_center.CheckRequest{
				BranchId: "branchId111",
			}
			reportCenterMock.EXPECT().CheckReportResult(ctx, checkRequest, tt.args.globalConf).Return(tt.checkResp, tt.instanceResultCheckErr).MaxTimes(1)

			historyMock.EXPECT().UpdateInstance(tt.args.ctx, tt.updateInstance.DataId, tt.updateInstance, []string{"code", "msg", "isFail", "status", "retryable"}).Return(tt.updateInstanceErr).MaxTimes(1)

			c := &zhongXinChecker{
				reportCenter: reportCenterMock,
				taskHistory:  historyMock,
				centerData:   tt.fields.centerData,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if err := c.dealWithInstanceCheckResult(tt.args.ctx, tt.args.reportTask, tt.args.globalConf, tt.args.reportCount, tt.args.st, tt.args.et); (err != nil) != tt.wantErr {
				t.Errorf("parseBranchResult() = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateBranchResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx        context.Context
		reportTask *fintech_data.ReportTask
		st         int
		et         int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		branchList      []*fintech_data.ReportBranch
		searchBranchErr error

		searchInstanceLimit *history.InstanceLimitResult
		searchInstanceErr   error

		updateBranch    *fintech_data.ReportBranch
		updateBranchErr error
	}{
		{
			name:   "SearchAllBranch error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				st: 1609657786,
				et: 1609772986,
			},
			searchBranchErr: fmt.Errorf("SearchAllBranch error"),
			wantErr:         true,
		},

		{
			name:   "SearchInstanceLimit error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				st: 1609657786,
				et: 1609772986,
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:      "inner1",
					ReportStatus: types.StatusSuccess,
				},
			},
			searchInstanceErr: fmt.Errorf("SearchInstanceLimit error"),
			wantErr:           true,
		},

		{
			name:   "update branch error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 2,
				},
				st: 1609657786,
				et: 1609772986,
			},

			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:      "inner1",
					ReportStatus: types.StatusSuccess,
				},
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						BranchId:           "branchId111",
						DataId:             "111",
						FacilityDescriptor: "aaa",
						Status:             types.StatusSuccess,
					},
					{
						BranchId:           "branchId111",
						DataId:             "222",
						FacilityDescriptor: "bbb",
						Status:             types.StatusWithWarn,
					},
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				InnerId:      "inner1",
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusWithWarn,
				CheckStatus:  types.StatusWithWarn,
				SuccessTotal: 2,
			},
			updateBranchErr: fmt.Errorf("update branch error"),
			wantErr:         true,
		},

		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 2,
				},
				st: 1609657786,
				et: 1609772986,
			},

			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:      "inner1",
					ReportStatus: types.StatusSuccess,
				},
			},
			searchInstanceLimit: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						BranchId:           "branchId111",
						DataId:             "111",
						FacilityDescriptor: "aaa",
						Status:             types.StatusSuccess,
					},
					{
						BranchId:           "branchId111",
						DataId:             "222",
						FacilityDescriptor: "bbb",
						Status:             types.StatusWithWarn,
					},
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				InnerId:      "inner1",
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusWithWarn,
				CheckStatus:  types.StatusWithWarn,
				SuccessTotal: 2,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			query := []*monthly_model.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.TaskId),
				},
			}
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchAllBranch(tt.args.ctx, query, nil, 5000, tt.args.st, tt.args.et).Return(tt.branchList, tt.searchBranchErr).MaxTimes(1)

			queryInstance := []*monthly_model.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.TaskId),
				},
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("inner1"),
				},
			}
			fields := map[string]interface{}{
				"data":    false,
				"showKey": false,
			}
			historyMock.EXPECT().SearchInstanceLimit(tt.args.ctx, queryInstance, fields, 10, tt.args.st, tt.args.et, gomock.Any()).Return(tt.searchInstanceLimit, tt.searchInstanceErr).MaxTimes(1)

			historyMock.EXPECT().UpdateBranch(tt.args.ctx, "inner1", tt.updateBranch, []string{"successTotal", "failTotal", "checkStatus", "totalStatus"}).Return(tt.updateBranchErr).MaxTimes(1)

			c := &zhongXinChecker{
				reportCenter: tt.fields.reportCenter,
				taskHistory:  historyMock,
				centerData:   tt.fields.centerData,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if _, err := c.updateBranchResult(tt.args.ctx, tt.args.reportTask, tt.args.st, tt.args.et); (err != nil) != tt.wantErr {
				t.Errorf("updateBranchResult() = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateTaskResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx         context.Context
		reportTask  *fintech_data.ReportTask
		reportCount *history.ReportCount
		warning     bool
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateTask    *fintech_data.ReportTask
		updateTaskErr error
	}{
		{
			name:   "UpdateTask error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime:    "2021-01-03 15:09:46",
					TaskId:       "taskId1",
					DataTotal:    2,
					SuccessTotal: 1,
					FailTotal:    1,
				},
				reportCount: &history.ReportCount{},
				warning:     true,
			},
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				DataTotal:    2,
				SuccessTotal: 1,
				FailTotal:    1,
				EndTime:      "2021-01-04 15:09:46",
				Status:       types.StatusPartialSuccess,
				FailType:     types.FailTypeResult,
				Msg:          fmt.Sprintf("任务上报数据成功%d个，失败%d个", 1, 1),
			},
			updateTaskErr: fmt.Errorf("UpdateTask error"),
			wantErr:       true,
		},

		{
			name:   "saveReportHistory and updateObjectStat error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime:    "2021-01-03 15:09:46",
					TaskId:       "taskId1",
					DataTotal:    2,
					SuccessTotal: 1,
					FailTotal:    1,
				},
				reportCount: &history.ReportCount{
					Inserted: 1,
				},
				warning: true,
			},
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				DataTotal:    2,
				SuccessTotal: 1,
				FailTotal:    1,
				EndTime:      "2021-01-04 15:09:46",
				Status:       types.StatusPartialSuccess,
				FailType:     types.FailTypeResult,
				Msg:          fmt.Sprintf("任务上报数据成功%d个，失败%d个", 1, 1),
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {

			historyMock := history2.NewMockTaskHistory(ctrl)

			historyMock.EXPECT().UpdateTask(tt.args.ctx, tt.updateTask.TaskId, tt.updateTask).Return(tt.updateTaskErr).MaxTimes(1)

			centerDataMock := history2.NewMockCenterData(ctrl)
			centerDataMock.EXPECT().Count(ctx, map[string]interface{}{"objectId": tt.args.reportTask.ObjectId}).Return(0, fmt.Errorf("saveReportHistory error")).MaxTimes(1)

			statMock := history2.NewMockObjectStat(ctrl)
			statMock.EXPECT().Get(ctx, tt.args.reportTask.ObjectId).Return(nil, fmt.Errorf("updateObjectStat error")).MaxTimes(1)

			test := &testRedisMock{t: t}
			c := &zhongXinChecker{
				newLockFunc:  test.testNewLockFunc,
				reportCenter: tt.fields.reportCenter,
				taskHistory:  historyMock,
				centerData:   centerDataMock,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
				objStat:      statMock,
			}
			if err := c.updateTaskResult(tt.args.ctx, tt.args.reportTask, tt.args.reportCount, tt.args.warning); (err != nil) != tt.wantErr {
				t.Errorf("updateBranchResult() = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateInstanceResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx          context.Context
		reportTask   *fintech_data.ReportTask
		checkResp    *report_center.CheckResponse
		instanceList []*fintech_data.ReportInstance
		batchCount   *batchCountStatics
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateInstance    *fintech_data.ReportInstance
		updateInstanceErr error

		upsertErr error
		removeErr error
	}{
		{
			name:   "reportType new centerData upsert error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				checkResp: &report_center.CheckResponse{
					Code: report_center.CodeDataHasFail,
					Data: []report_center.CheckData{
						{
							FacilityDescriptor: "bbb",
						},
					},
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
						ReportType:         report_center.ReportTypeNew,
					},
				},
				batchCount: &batchCountStatics{},
			},
			updateInstance: &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				ReportType:         report_center.ReportTypeNew,
				Status:             types.StatusSuccess,
				Ts:                 1609772986,
			},

			upsertErr: fmt.Errorf("upsert error"),
			wantErr:   true,
		},

		{
			name:   "check response code is CodeHandling",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId111",
					Code:     report_center.CodeHandling,
					Msg:      "数据处理中",
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
						ReportType:         report_center.ReportTypeNew,
					},
				},
				batchCount: &batchCountStatics{},
			},
			updateInstance: &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				ReportType:         report_center.ReportTypeNew,
				Status:             types.StatusSuccess,
				Ts:                 1609772986,
			},
		},

		{
			name:   "reportType update centerData upsert error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				checkResp: &report_center.CheckResponse{
					Code: report_center.CodeDataHasFail,
					Data: []report_center.CheckData{
						{
							FacilityDescriptor: "bbb",
						},
					},
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
						ReportType:         report_center.ReportTypeUpdate,
					},
				},
				batchCount: &batchCountStatics{},
			},
			updateInstance: &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				ReportType:         report_center.ReportTypeUpdate,
				Status:             types.StatusSuccess,
				Ts:                 1609772986,
			},

			upsertErr: fmt.Errorf("upsert error"),
			wantErr:   true,
		},

		{
			name:   "reportType delete centerData remove error",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				checkResp: &report_center.CheckResponse{
					Code: report_center.CodeDataHasFail,
					Data: []report_center.CheckData{
						{
							FacilityDescriptor: "bbb",
						},
					},
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
						ReportType:         report_center.ReportTypeDelete,
					},
				},
				batchCount: &batchCountStatics{},
			},
			updateInstance: &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				ReportType:         report_center.ReportTypeDelete,
				Status:             types.StatusSuccess,
				Ts:                 1609772986,
			},

			removeErr: fmt.Errorf("remove error"),
			wantErr:   true,
		},

		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 1,
				},
				checkResp: &report_center.CheckResponse{
					Code: report_center.CodeDataHasFail,
					Data: []report_center.CheckData{
						{
							FacilityDescriptor: "bbb",
						},
					},
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "111",
						FacilityDescriptor: "aaa",
						ReportType:         report_center.ReportTypeDelete,
					},
				},
				batchCount: &batchCountStatics{},
			},
			updateInstance: &fintech_data.ReportInstance{
				DataId:             "111",
				FacilityDescriptor: "aaa",
				ReportType:         report_center.ReportTypeDelete,
				Status:             types.StatusSuccess,
				Ts:                 1609772986,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().UpdateInstance(tt.args.ctx, tt.updateInstance.DataId, tt.updateInstance, []string{"code", "msg", "isFail", "status", "retryable"}).Return(tt.updateInstanceErr).MaxTimes(1)

			centerMock := history2.NewMockCenterData(ctrl)
			centerMock.EXPECT().Upsert(ctx, gomock.Any()).Return(nil, tt.upsertErr).MaxTimes(1)
			centerMock.EXPECT().RemoveAll(ctx, gomock.Any()).Return(tt.removeErr).MaxTimes(1)

			c := &zhongXinChecker{
				taskHistory: historyMock,
				centerData:  centerMock,
				timeNowFunc: testNowTime,
				reportConf:  config.ReportConf{SearchBatch: 10},
			}
			if err := c.updateInstanceResult(tt.args.ctx, tt.args.reportTask, tt.args.checkResp, tt.args.instanceList, tt.args.batchCount); (err != nil) != tt.wantErr {
				t.Errorf("parseBranchResult() = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_saveInstResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		ctx        context.Context
		instRes    report_center.CheckData
		reportInst *fintech_data.ReportInstance
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateInst *fintech_data.ReportInstance
	}{
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				instRes: report_center.CheckData{
					Code: report_center.CodeDataValid,
				},
				reportInst: &fintech_data.ReportInstance{TaskId: "fakeId"},
			},
			updateInst: &fintech_data.ReportInstance{
				TaskId: "fakeId",
				Code:   report_center.CodeDataValid,
				Status: types.StatusSuccess,
			},
			wantErr: false,
		},
		{
			name:   "warn",
			fields: fields{},
			args: args{
				ctx: ctx,
				instRes: report_center.CheckData{
					Code: report_center.CodeDataValidWithWarning,
				},
				reportInst: &fintech_data.ReportInstance{TaskId: "fakeId"},
			},
			updateInst: &fintech_data.ReportInstance{
				TaskId: "fakeId",
				Code:   report_center.CodeDataValidWithWarning,
				Status: types.StatusWithWarn,
			},
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				instRes: report_center.CheckData{
					Code: report_center.CodeDataHandleFail,
					Msg:  "handle fail",
				},
				reportInst: &fintech_data.ReportInstance{TaskId: "fakeId"},
			},
			updateInst: &fintech_data.ReportInstance{
				TaskId:    "fakeId",
				Retryable: true,
				Code:      report_center.CodeDataHandleFail,
				Msg:       "handle fail",
				IsFail:    true,
				Status:    types.FailTypeResult,
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().UpdateInstance(tt.args.ctx, tt.args.reportInst.DataId, tt.updateInst, []string{"code", "msg", "isFail", "status", "retryable"}).Return(nil).Times(1)
			c := &zhongXinChecker{
				reportCenter: tt.fields.reportCenter,
				taskHistory:  historyMock,
				centerData:   tt.fields.centerData,
				timeNowFunc:  tt.fields.timeNowFunc,
				reportConf:   tt.fields.reportConf,
			}
			if err := c.saveInstResult(tt.args.ctx, tt.args.instRes, tt.args.reportInst); (err != nil) != tt.wantErr {
				t.Errorf("saveInstResult() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateBranchStatus(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		branch       *fintech_data.ReportBranch
		instanceList []*fintech_data.ReportInstance
	}
	tests := []struct {
		name string
		args args

		want *fintech_data.ReportBranch
	}{
		{
			name: "branch reportStatus fail",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusFail,
					DataTotal:    1,
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusFail,
				DataTotal:    1,
				FailTotal:    1,
			},
		},

		{
			name: "branch status resulting",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusPartialSuccess,
					DataTotal:    3,
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						Status: types.StatusResulting,
					},
					{
						Status: types.FailTypeResult,
					},
					{
						Status: types.StatusSuccess,
					},
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusPartialSuccess,
				TotalStatus:  types.StatusResulting,
				CheckStatus:  types.StatusResulting,
				DataTotal:    3,
				SuccessTotal: 1,
				FailTotal:    1,
			},
		},

		{
			name: "branch status partialSuccess",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusSuccess,
					DataTotal:    2,
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						Status: types.FailTypeResult,
					},
					{
						Status: types.StatusSuccess,
					},
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusPartialSuccess,
				CheckStatus:  types.StatusPartialSuccess,
				DataTotal:    2,
				SuccessTotal: 1,
				FailTotal:    1,
			},
		},

		{
			name: "branch status warning",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusSuccess,
					DataTotal:    2,
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						Status: types.StatusWithWarn,
					},
					{
						Status: types.StatusSuccess,
					},
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusWithWarn,
				CheckStatus:  types.StatusWithWarn,
				DataTotal:    2,
				SuccessTotal: 2,
				FailTotal:    0,
			},
		},

		{
			name: "branch status success",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusSuccess,
					DataTotal:    2,
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						Status: types.StatusSuccess,
					},
					{
						Status: types.StatusSuccess,
					},
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusSuccess,
				CheckStatus:  types.StatusSuccess,
				DataTotal:    2,
				SuccessTotal: 2,
				FailTotal:    0,
			},
		},

		{
			name: "branch status fail",
			args: args{
				branch: &fintech_data.ReportBranch{
					ReportStatus: types.StatusSuccess,
					DataTotal:    2,
				},
				instanceList: []*fintech_data.ReportInstance{
					{
						Status: types.FailTypeResult,
					},
					{
						Status: types.FailTypeResult,
					},
				},
			},
			want: &fintech_data.ReportBranch{
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusFail,
				CheckStatus:  types.StatusFail,
				DataTotal:    2,
				SuccessTotal: 0,
				FailTotal:    2,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			updateBranchStatus(tt.args.branch, tt.args.instanceList)
			if !reflect.DeepEqual(tt.args.branch, tt.want) {
				t.Errorf("updateBranchStatus() error want= %v", tt.want)
			}
		})
	}
}

func Test_zhongXinChecker_saveReportHistory(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter    report_center.Service
		taskHistory     history.TaskHistory
		centerData      history.CenterData
		historyRecorder history.Recorder
		timeNowFunc     timeutil.NowTimeFunc
		reportConf      config.ReportConf
	}
	type args struct {
		ctx   context.Context
		count *history.ReportCount
		task  *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		countErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				count: &history.ReportCount{
					Inserted: 2,
				},
				task: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 3,
					ObjectId:  "server",
					ConfigId:  "confId1",
				},
			},
			wantErr: false,
		},
		{
			name:   "count fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				count: &history.ReportCount{
					Inserted: 2,
				},
				task: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 3,
					ObjectId:  "server",
					ConfigId:  "confId1",
				},
			},
			wantErr:  true,
			countErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		centerDataMock := history2.NewMockCenterData(ctrl)
		centerDataMock.EXPECT().Count(ctx, map[string]interface{}{"objectId": tt.args.task.ObjectId}).Return(10, tt.countErr).MaxTimes(1)

		recorderMock := history2.NewMockRecorder(ctrl)
		recorderMock.EXPECT().Save(ctx, history.ReportCount{Total: 10, Inserted: 2, ObjectId: "server", InstanceId: "confId1", TaskId: "taskId1"}).Return(nil).MaxTimes(1)

		t.Run(tt.name, func(t *testing.T) {
			c := &zhongXinChecker{
				reportCenter:    tt.fields.reportCenter,
				taskHistory:     tt.fields.taskHistory,
				centerData:      centerDataMock,
				historyRecorder: recorderMock,
				timeNowFunc:     tt.fields.timeNowFunc,
				reportConf:      tt.fields.reportConf,
			}
			if err := c.saveReportHistory(tt.args.ctx, tt.args.count, tt.args.task); (err != nil) != tt.wantErr {
				t.Errorf("saveReportHistory() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_updateObjectStat(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter    report_center.Service
		taskHistory     history.TaskHistory
		centerData      history.CenterData
		objStat         history.ObjectStat
		historyRecorder history.Recorder
		timeNowFunc     timeutil.NowTimeFunc
		reportConf      config.ReportConf
	}
	type args struct {
		ctx   context.Context
		count *history.ReportCount
		task  *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		getErr    error
		upsertErr error
	}{
		{
			name: "normal",
			args: args{
				ctx: ctx,
				count: &history.ReportCount{
					Total: 6,
				},
				task: &fintech_data.ReportTask{
					TaskId:    "haha",
					ObjectId:  "HOST",
					DataTotal: 2,
					FailTotal: 1,
				},
			},
			wantErr: false,
		},
		{
			name: "get fail",
			args: args{
				ctx: ctx,
				count: &history.ReportCount{
					Total: 6,
				},
				task: &fintech_data.ReportTask{
					TaskId:    "haha",
					ObjectId:  "HOST",
					DataTotal: 2,
					FailTotal: 1,
				},
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name: "upsert fail",
			args: args{
				ctx: ctx,
				count: &history.ReportCount{
					Total: 6,
				},
				task: &fintech_data.ReportTask{
					TaskId:    "haha",
					ObjectId:  "HOST",
					DataTotal: 2,
					FailTotal: 1,
				},
			},
			upsertErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			statMock := history2.NewMockObjectStat(ctrl)
			statMock.EXPECT().Get(ctx, "HOST").Return(&history.StatData{ObjectId: "HOST", Total: 1, ReportTotal: 5}, tt.getErr).Times(1)
			statMock.EXPECT().Upsert(ctx, &history.StatData{
				ObjectId:    "HOST",
				Total:       6,
				ReportTotal: 7,
				FailTotal:   1,
				TS:          int32(testNowTime().Unix()),
				LastTaskId:  "haha",
			}).Return(nil, tt.upsertErr).MaxTimes(1)
			c := &zhongXinChecker{
				reportCenter:    tt.fields.reportCenter,
				taskHistory:     tt.fields.taskHistory,
				centerData:      tt.fields.centerData,
				objStat:         statMock,
				historyRecorder: tt.fields.historyRecorder,
				timeNowFunc:     testNowTime,
				reportConf:      tt.fields.reportConf,
			}
			if err := c.updateObjectStat(tt.args.ctx, tt.args.count, tt.args.task); (err != nil) != tt.wantErr {
				t.Errorf("updateObjectStat() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_zhongXinChecker_convertBranchIdResponse(t *testing.T) {
	type args struct {
		resp interface{}
	}
	tests := []struct {
		name    string
		args    args
		want    []*report_center.BranchIdData
		wantErr bool
	}{
		{
			name: "not ok",
			args: args{
				resp: "",
			},
			wantErr: true,
		},

		{
			name: "marshal error",
			args: args{
				resp: []interface{}{
					func() {},
				},
			},
			wantErr: true,
		},

		{
			name: "unmarshal error",
			args: args{
				resp: []interface{}{
					map[string]interface{}{
						"branchId":           1,
						"groupId":            "GC112000000000020211202101021111",
						"facilityDescriptor": "0000000000000101-H-HDV-000000010",
					},
				},
			},
			wantErr: true,
		},

		{
			name: "success",
			args: args{
				resp: []interface{}{
					map[string]interface{}{
						"branchId":           "BC112000000000020211202101010123",
						"groupId":            "GC112000000000020211202101021111",
						"facilityDescriptor": "0000000000000101-H-HDV-000000010",
					},
				},
			},
			want: []*report_center.BranchIdData{
				{
					BranchId:           "BC112000000000020211202101010123",
					GroupId:            "GC112000000000020211202101021111",
					FacilityDescriptor: "0000000000000101-H-HDV-000000010",
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := convertBranchIdResponse(tt.args.resp)
			if (err != nil) != tt.wantErr {
				t.Errorf("convertBranchIdResponse() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("convertBranchIdResponse() got = %v, want %v", got, tt.want)
			}
		})
	}
}
