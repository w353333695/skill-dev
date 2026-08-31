package report_task

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

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

func testNowTime() time.Time {
	t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
	return t
}

func TestNewChecker(t *testing.T) {
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
			NewChecker(nil, tt.args.reportCenter, tt.args.taskHistory, tt.args.centerData, tt.args.objStat, tt.args.historyRecorder, tt.args.reportConf, tt.args.mongoClient, nil)
		})
	}
}

func Test_checker_TaskCheck(t *testing.T) {
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
			historyMock.EXPECT().SearchAllBranch(ctx, getTaskBranchQuery(tt.args.reportTask),
				nil, 10, 1609657786, 1609772986).
				Return(nil, fmt.Errorf("mock fail")).MaxTimes(1)

			c := &checker{
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

func Test_checker_branchResultCheck(t *testing.T) {
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
		branch      *fintech_data.ReportBranch
		globalConf  *fintech_data.ReportGlobalConfig
		reportCount *history.ReportCount
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		checkResp *report_center.CheckResponse
		checkErr  error

		updateBranch    *fintech_data.ReportBranch
		updateBranchErr error

		searchResp *history.InstanceLimitResult
		searchErr  error

		upsertList []*history.ReportMetaData
		upsertInfo *history.ChangeInfo
		upsertErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				globalConf:  nil,
				reportCount: &history.ReportCount{},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeDataHasFail,
				Msg:      "批次存在失败",
				Data: []report_center.CheckData{
					{
						Code:               report_center.CodeDataInValid,
						Msg:                "检查失败",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
			},
			checkErr: nil,
			updateBranch: &fintech_data.ReportBranch{
				BranchId:     "branchId1",
				InnerId:      "innerId1",
				Code:         report_center.CodeDataHasFail,
				Msg:          "批次存在失败",
				DataTotal:    2,
				FailTotal:    1,
				Inserted:     1,
				SuccessTotal: 1,
				CheckStatus:  types.StatusPartialSuccess,
				TotalStatus:  types.StatusPartialSuccess,
			},
			updateBranchErr: nil,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			searchErr: nil,
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id3",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					Ts:                 int32(1609657786),
					DataId:             "id3",
				},
			},
			upsertInfo: &history.ChangeInfo{Updated: 1},
			upsertErr:  nil,
		},
		{
			name:   "check fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				globalConf:  nil,
				reportCount: &history.ReportCount{},
			},
			wantErr:  true,
			checkErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "update branch fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				globalConf:  nil,
				reportCount: &history.ReportCount{},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeDataHasFail,
				Msg:      "批次存在失败",
				Data: []report_center.CheckData{
					{
						Code:               report_center.CodeDataInValid,
						Msg:                "检查失败",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
			},
			checkErr: nil,
			updateBranch: &fintech_data.ReportBranch{
				BranchId:     "branchId1",
				InnerId:      "innerId1",
				Code:         report_center.CodeDataHasFail,
				Msg:          "批次存在失败",
				DataTotal:    2,
				FailTotal:    1,
				Inserted:     1,
				SuccessTotal: 1,
				CheckStatus:  types.StatusPartialSuccess,
				TotalStatus:  types.StatusPartialSuccess,
			},
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id3",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					Ts:                 int32(1609657786),
					DataId:             "id3",
				},
			},
			upsertInfo:      &history.ChangeInfo{Updated: 1},
			updateBranchErr: fmt.Errorf("mock fail"),
			wantErr:         true,
		},
		{
			name:   "branch not end",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				globalConf:  nil,
				reportCount: &history.ReportCount{},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeHandling,
				Msg:      "处理中",
			},
			checkErr: nil,
			updateBranch: &fintech_data.ReportBranch{
				BranchId:    "branchId1",
				InnerId:     "innerId1",
				Code:        report_center.CodeHandling,
				Msg:         "处理中",
				DataTotal:   2,
				CheckStatus: types.StatusResulting,
				TotalStatus: types.StatusResulting,
			},
			updateBranchErr: nil,
		},
		{
			name:   "handle inst fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				globalConf:  nil,
				reportCount: &history.ReportCount{},
			},
			checkResp: &report_center.CheckResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeDataHasFail,
				Msg:      "批次存在失败",
				Data: []report_center.CheckData{
					{
						Code:               report_center.CodeDataInValid,
						Msg:                "检查失败",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
			},
			checkErr: nil,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			searchErr: nil,
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id3",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					Ts:                 1609657786,
					DataId:             "id3",
				},
			},
			upsertErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerMock := report_center2.NewMockService(ctrl)
			req := report_center.CheckRequest{BranchId: tt.args.branch.BranchId}
			centerMock.EXPECT().CheckReportResult(ctx, req, tt.args.globalConf).Return(tt.checkResp, tt.checkErr).Times(1)

			historyMock := history2.NewMockTaskHistory(ctrl)
			if tt.updateBranch != nil {
				historyMock.EXPECT().UpdateBranch(ctx, tt.args.branch.InnerId, tt.updateBranch, []string{}).Return(tt.updateBranchErr).Times(1)
			}

			historyMock.EXPECT().UpdateInstance(tt.args.ctx, gomock.Any(), gomock.Any(), []string{"code", "msg", "isFail", "status", "retryable", "handleStatus", "ts"}).Return(nil).AnyTimes()

			query := []*monthly_model.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue("taskId1"),
				},
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("innerId1"),
				},
			}
			searchFields := map[string]interface{}{
				"data":    false,
				"showKey": false,
			}
			historyMock.EXPECT().SearchInstanceLimit(tt.args.ctx, query, searchFields, 10, 1609657786, 1609772986, "").
				Return(tt.searchResp, tt.searchErr).MaxTimes(1)

			centerDataMock := history2.NewMockCenterData(ctrl)
			if len(tt.upsertList) > 0 {
				centerDataMock.EXPECT().Upsert(ctx, tt.upsertList).Return(tt.upsertInfo, tt.upsertErr).Times(1)
			}

			c := &checker{
				reportCenter: centerMock,
				taskHistory:  historyMock,
				centerData:   centerDataMock,
				timeNowFunc:  testNowTime,
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if err := c.branchResultCheck(tt.args.ctx, tt.args.reportTask, tt.args.branch, tt.args.globalConf, tt.args.reportCount); (err != nil) != tt.wantErr {
				t.Errorf("branchResultCheck() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_checker_handleInstanceResult(t *testing.T) {
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
		ctx           context.Context
		instResultMap map[string]report_center.CheckData
		reportTask    *fintech_data.ReportTask
		branch        *fintech_data.ReportBranch
		reportCount   *history.ReportCount
	}

	type updateData struct {
		dataId     string
		updateInst *fintech_data.ReportInstance
		updateErr  error
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		searchResp *history.InstanceLimitResult
		searchErr  error

		updateList []updateData

		upsertList []*history.ReportMetaData
		upsertInfo *history.ChangeInfo
		upsertErr  error

		removeList []*history.ReportMetaData
		removeErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				instResultMap: map[string]report_center.CheckData{
					"desc1": {
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
					"desc2": {
						Code:               report_center.CodeDataValid,
						Msg:                "成功",
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
				},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId: "innerId1",
				},
				reportCount: &history.ReportCount{},
			},
			wantErr: false,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
					{
						DataId:             "id2",
						InstanceId:         "id2",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			updateList: []updateData{
				{
					dataId: "id1",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
						IsFail:             true,
						Status:             types.FailTypeReporting,
						Ts:                 int32(1609657786),
						HandleStatus:       "pending",
					},
				},
				{
					dataId: "id2",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id2",
						InstanceId:         "id2",
						ObjectId:           "server",
						Code:               report_center.CodeDataValid,
						Msg:                "成功",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
						Status:             types.StatusSuccess,
						Ts:                 int32(1609657786),
					},
				},
				{
					dataId: "id3",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
						ReportType:         report_center.ReportTypeDelete,
						Status:             types.StatusSuccess,
						Ts:                 int32(1609657786),
					},
				},
			},
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id2",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate2",
					FacilityDescriptor: "desc2",
					Ts:                 int32(1609657786),
					DataId:             "id2",
				},
			},
			removeList: []*history.ReportMetaData{
				{
					InstanceId:         "id3",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					Ts:                 int32(1609657786),
					DataId:             "id3",
				},
			},
		},
		{
			name:   "all fail",
			fields: fields{},
			args: args{
				ctx:           ctx,
				instResultMap: map[string]report_center.CheckData{},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId:   "innerId1",
					Msg:       "数据处理失败",
					DataTotal: 3,
					FailTotal: 3,
				},
				reportCount: &history.ReportCount{},
			},
			wantErr: false,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
					{
						DataId:             "id2",
						InstanceId:         "id2",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			updateList: []updateData{
				{
					dataId: "id1",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						Code:               report_center.CodeDataHandleFail,
						Msg:                "数据处理失败",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
						Retryable:          true,
						IsFail:             true,
						Status:             types.FailTypeReporting,
						Ts:                 int32(1609657786),
						HandleStatus:       "pending",
					},
				},
				{
					dataId: "id2",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id2",
						InstanceId:         "id2",
						ObjectId:           "server",
						Code:               report_center.CodeDataHandleFail,
						Msg:                "数据处理失败",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
						Retryable:          true,
						IsFail:             true,
						Status:             types.FailTypeReporting,
						Ts:                 int32(1609657786),
						HandleStatus:       "pending",
					},
				},
				{
					dataId: "id3",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						Code:               report_center.CodeDataHandleFail,
						Msg:                "数据处理失败",
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
						Retryable:          true,
						IsFail:             true,
						Status:             types.FailTypeReporting,
						Ts:                 int32(1609657786),
						HandleStatus:       "pending",
					},
				},
			},
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				instResultMap: map[string]report_center.CheckData{
					"desc1": {
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId: "innerId1",
				},
				reportCount: &history.ReportCount{},
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "update instance fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				instResultMap: map[string]report_center.CheckData{
					"desc1": {
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
					"desc2": {
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
				},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId: "innerId1",
				},
				reportCount: &history.ReportCount{},
			},
			wantErr: true,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
					{
						DataId:             "id2",
						InstanceId:         "id2",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			updateList: []updateData{
				{
					dataId: "id1",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						Code:               report_center.CodeDataInValid,
						Msg:                "缺少必填字段",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
						IsFail:             true,
						Status:             types.FailTypeReporting,
						Ts:                 int32(1609657786),
						HandleStatus:       "pending",
					},
					updateErr: fmt.Errorf("mock fail"),
				},
			},
		},
		{
			name:   "upsert fail",
			fields: fields{},
			args: args{
				ctx:           ctx,
				instResultMap: map[string]report_center.CheckData{},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId: "innerId1",
				},
				reportCount: &history.ReportCount{},
			},
			wantErr: true,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
			},
			updateList: []updateData{
				{
					dataId: "id1",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
						Status:             types.StatusSuccess,
						Ts:                 int32(1609657786),
					},
				},
			},
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id1",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
					Ts:                 int32(1609657786),
					DataId:             "id1",
				},
			},
			upsertErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "remove fail",
			fields: fields{},
			args: args{
				ctx:           ctx,
				instResultMap: map[string]report_center.CheckData{},
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
				},
				branch: &fintech_data.ReportBranch{
					InnerId: "innerId1",
				},
				reportCount: &history.ReportCount{},
			},
			wantErr: true,
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
					},
				},
			},
			updateList: []updateData{
				{
					dataId: "id3",
					updateInst: &fintech_data.ReportInstance{
						DataId:             "id3",
						InstanceId:         "id3",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeDelete,
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
						Status:             types.StatusSuccess,
						Ts:                 int32(1609657786),
					},
				},
			},
			removeList: []*history.ReportMetaData{
				{
					InstanceId:         "id3",
					Version:            0,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					Ts:                 int32(1609657786),
					DataId:             "id3",
				},
			},
			removeErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			query := []*monthly_model.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue("taskId1"),
				},
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("innerId1"),
				},
			}
			searchFields := map[string]interface{}{
				"data":    false,
				"showKey": false,
			}
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchInstanceLimit(tt.args.ctx, query, searchFields, 10, 1609657786, 1609772986, "").
				Return(tt.searchResp, tt.searchErr).Times(1)

			for _, item := range tt.updateList {
				historyMock.EXPECT().UpdateInstance(tt.args.ctx, item.dataId, item.updateInst, []string{"code", "msg", "isFail", "status", "retryable", "handleStatus", "ts"}).
					Return(item.updateErr).Times(1)
			}

			centerMock := history2.NewMockCenterData(ctrl)
			if len(tt.upsertList) > 0 {
				centerMock.EXPECT().Upsert(ctx, tt.upsertList).Return(tt.upsertInfo, tt.upsertErr).Times(1)
			}

			if len(tt.removeList) > 0 {
				centerMock.EXPECT().RemoveAll(ctx, tt.removeList).Return(tt.removeErr).Times(1)
			}

			c := &checker{
				reportCenter: tt.fields.reportCenter,
				taskHistory:  historyMock,
				centerData:   centerMock,
				timeNowFunc:  testNowTime, // 确保 testNowTime 返回的时间与 int32(1609657786) 一致
				reportConf:   config.ReportConf{SearchBatch: 10},
			}
			if err := c.handleInstanceResult(tt.args.ctx, tt.args.instResultMap, tt.args.reportTask, tt.args.branch, tt.args.reportCount); (err != nil) != tt.wantErr {
				t.Errorf("handleInstanceResult() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_checker_parseBranchResult(t *testing.T) {
	type fields struct {
		reportCenter report_center.Service
		taskHistory  history.TaskHistory
		centerData   history.CenterData
		timeNowFunc  timeutil.NowTimeFunc
		reportConf   config.ReportConf
	}
	type args struct {
		checkResp *report_center.CheckResponse
		branch    *fintech_data.ReportBranch
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *fintech_data.ReportBranch
	}{
		{
			name:   "批次存在失败，全部失败",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeHandleFail,
					Msg:      "批次存在失败",
					Data:     []report_center.CheckData{},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 2,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:   2,
				FailTotal:   2,
				TotalStatus: types.StatusFail,
				CheckStatus: types.StatusFail,
				Code:        "WL-10007",
				Msg:         "批次存在失败",
			},
		},
		{
			name:   "has fail,部份成功",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeDataHasFail,
					Msg:      "批次存在失败",
					Data: []report_center.CheckData{
						{
							Code:               report_center.CodeDataInValid,
							Msg:                "检查失败",
							FacilityCategory:   "cate1",
							FacilityDescriptor: "desc1",
						},
					},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 2,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:    2,
				SuccessTotal: 1,
				FailTotal:    1,
				TotalStatus:  types.StatusPartialSuccess,
				CheckStatus:  types.StatusPartialSuccess,
				Code:         "WL-10008",
				Msg:          "批次存在失败",
			},
		},
		{
			name:   "all fail",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeHandleFail,
					Msg:      "批次存在失败",
					Data: []report_center.CheckData{
						{
							Code:               report_center.CodeDataInValid,
							Msg:                "检查失败",
							FacilityCategory:   "cate1",
							FacilityDescriptor: "desc1",
						},
					},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 1,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:   1,
				FailTotal:   1,
				TotalStatus: types.StatusFail,
				CheckStatus: types.StatusFail,
				Code:        "WL-10007",
				Msg:         "批次存在失败",
			},
		},
		{
			name:   "success",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeHandleSuccess,
					Msg:      "成功",
					Data:     []report_center.CheckData{},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 1},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:    1,
				SuccessTotal: 1,
				TotalStatus:  types.StatusSuccess,
				CheckStatus:  types.StatusSuccess,
				Code:         "WL-10009",
				Msg:          "成功",
			},
		},
		{
			name:   "exist warning",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeDataHasFail,
					Msg:      "存在警告",
					Data: []report_center.CheckData{
						{
							Code:               report_center.CodeDataValidWithWarning,
							Msg:                "警告",
							FacilityCategory:   "cate1",
							FacilityDescriptor: "desc1",
						},
					},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 1,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:    1,
				SuccessTotal: 1,
				TotalStatus:  types.StatusWithWarn,
				CheckStatus:  types.StatusWithWarn,
				Code:         "WL-10008",
				Msg:          "存在警告",
			},
		},
		{
			name:   "success but exist warning",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeHandleSuccess,
					Msg:      "成功",
					Data: []report_center.CheckData{
						{
							Code:               report_center.CodeDataValidWithWarning,
							Msg:                "警告",
							FacilityCategory:   "cate1",
							FacilityDescriptor: "desc1",
						},
					},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 1,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:    1,
				SuccessTotal: 1,
				TotalStatus:  types.StatusWithWarn,
				CheckStatus:  types.StatusWithWarn,
				Code:         "WL-10009",
				Msg:          "成功",
			},
		},
		{
			name:   "running",
			fields: fields{},
			args: args{
				checkResp: &report_center.CheckResponse{
					BranchId: "branchId1",
					Code:     report_center.CodeSaveSuccess,
					Msg:      "保存成功",
					Data:     []report_center.CheckData{},
				},
				branch: &fintech_data.ReportBranch{
					DataTotal: 1,
				},
			},
			want: &fintech_data.ReportBranch{
				DataTotal:   1,
				TotalStatus: types.StatusResulting,
				CheckStatus: types.StatusResulting,
				Code:        "WL-10005",
				Msg:         "保存成功",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := &checker{
				reportCenter: tt.fields.reportCenter,
				taskHistory:  tt.fields.taskHistory,
				centerData:   tt.fields.centerData,
				timeNowFunc:  tt.fields.timeNowFunc,
				reportConf:   tt.fields.reportConf,
			}
			if got := c.parseBranchResult(tt.args.checkResp, tt.args.branch); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("parseBranchResult() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_checker_saveInstResult(t *testing.T) {
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
				TaskId:       "fakeId",
				Code:         report_center.CodeDataValidWithWarning,
				Status:       types.StatusWithWarn,
				HandleStatus: report_center.HandleStatusPending,
				Ts:           0,
			},
			wantErr: false,
		},
		{
			name:   "handle fail",
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
				TaskId:       "fakeId",
				Retryable:    true,
				Code:         report_center.CodeDataHandleFail,
				Msg:          "handle fail",
				IsFail:       true,
				Status:       types.FailTypeReporting,
				HandleStatus: report_center.HandleStatusPending,
				Ts:           0,
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().UpdateInstance(tt.args.ctx, tt.args.reportInst.DataId, tt.updateInst, []string{"code", "msg", "isFail", "status", "retryable", "handleStatus", "ts"}).Return(nil).Times(1)
			c := &checker{
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

func Test_checker_taskResultCheck(t *testing.T) {
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
	type checkItem struct {
		checkReq  report_center.CheckRequest
		checkResp *report_center.CheckResponse
		checkErr  error
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		branchList []*fintech_data.ReportBranch
		searchErr  error

		checkList []checkItem

		searchResp *history.InstanceLimitResult
		upsertList []*history.ReportMetaData

		updateBranchList []*fintech_data.ReportBranch
		branchErr        error

		updateTask *fintech_data.ReportTask
		taskErr    error

		recordErr error

		statErr error
	}{
		{
			name: "normal",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 2,
					ObjectId:  "server",
					ConfigId:  "confId1",
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 1,
				},
				{
					BranchId:  "branchId2",
					InnerId:   "innerId2",
					DataTotal: 1,
				},
			},

			checkList: []checkItem{
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId1",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId1",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
						Data: []report_center.CheckData{
							{
								Code: report_center.CodeDataValidWithWarning,
							},
						},
					},
				},
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId2",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId2",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
			},
			updateBranchList: []*fintech_data.ReportBranch{
				{
					BranchId:     "branchId1",
					InnerId:      "innerId1",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusWithWarn,
					TotalStatus:  types.StatusWithWarn,
				},
				{
					BranchId:     "branchId2",
					InnerId:      "innerId2",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
			},
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
				NextId:  "",
				HasMore: false,
			},
			wantErr: false,

			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id1",
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
					Ts:                 int32(1609657786),
					DataId:             "id1",
				},
			},
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				Status:       types.StatusWithWarn,
				Msg:          fmt.Sprintf("任务上报数据成功%d个", 2),
				EndTime:      "2021-01-04 15:09:46",
				DataTotal:    2,
				SuccessTotal: 2,
				Inserted:     2,
				ObjectId:     "server",
				ConfigId:     "confId1",
			},
		},
		{
			name: "search fail",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 3,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name: "handle branch fail",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 3,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 2,
				},
				{
					BranchId:  "branchId2",
					InnerId:   "innerId2",
					DataTotal: 1,
				},
			},

			checkList: []checkItem{
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId1",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId1",
						Code:     report_center.CodeHandling,
						Msg:      "保存成功",
					},
				},
			},
			updateBranchList: []*fintech_data.ReportBranch{
				{
					BranchId:    "branchId1",
					InnerId:     "innerId1",
					Code:        report_center.CodeHandling,
					Msg:         "保存成功",
					DataTotal:   2,
					CheckStatus: types.StatusResulting,
					TotalStatus: types.StatusResulting,
				},
			},
			branchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name: "update task fail",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime:    "2021-01-03 15:09:46",
					TaskId:       "taskId1",
					DataTotal:    2,
					SuccessTotal: 1,
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 1,
				},
				{
					BranchId:    "branchId2",
					InnerId:     "innerId2",
					TotalStatus: types.StatusWithWarn,
					DataTotal:   1,
				},
			},

			checkList: []checkItem{
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId1",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId1",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId2",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId2",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
			},
			updateBranchList: []*fintech_data.ReportBranch{
				{
					BranchId:     "branchId1",
					InnerId:      "innerId1",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Updated:      1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
				{
					BranchId:     "branchId2",
					InnerId:      "innerId2",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Updated:      1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
			},
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
			},
			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id1",
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
					Ts:                 int32(1609657786),
					DataId:             "id1",
				},
			},

			wantErr: true,
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				Status:       types.StatusWithWarn,
				Msg:          fmt.Sprintf("任务上报数据成功%d个", 2),
				EndTime:      "2021-01-04 15:09:46",
				DataTotal:    2,
				SuccessTotal: 2,
				Updated:      1,
			},
			taskErr: fmt.Errorf("mock fail"),
		},
		{
			name: "record history fail",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 2,
					ObjectId:  "server",
					ConfigId:  "confId1",
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 1,
				},
				{
					BranchId:  "branchId2",
					InnerId:   "innerId2",
					DataTotal: 1,
				},
			},

			checkList: []checkItem{
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId1",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId1",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId2",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId2",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
			},
			updateBranchList: []*fintech_data.ReportBranch{
				{
					BranchId:     "branchId1",
					InnerId:      "innerId1",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
				{
					BranchId:     "branchId2",
					InnerId:      "innerId2",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
			},
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
				NextId:  "",
				HasMore: false,
			},
			wantErr: false,

			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id1",
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
					Ts:                 int32(1609657786),
					DataId:             "id1",
				},
			},
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				Status:       types.StatusSuccess,
				Msg:          fmt.Sprintf("任务上报数据成功%d个", 2),
				EndTime:      "2021-01-04 15:09:46",
				DataTotal:    2,
				SuccessTotal: 2,
				Inserted:     2,
				ObjectId:     "server",
				ConfigId:     "confId1",
			},
			recordErr: fmt.Errorf("mock fail"),
		},
		{
			name: "update object stat fail",
			args: args{
				ctx: ctx,
				reportTask: &fintech_data.ReportTask{
					StartTime: "2021-01-03 15:09:46",
					TaskId:    "taskId1",
					DataTotal: 2,
					ObjectId:  "server",
					ConfigId:  "confId1",
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					BranchId:  "branchId1",
					InnerId:   "innerId1",
					DataTotal: 1,
				},
				{
					BranchId:  "branchId2",
					InnerId:   "innerId2",
					DataTotal: 1,
				},
			},

			checkList: []checkItem{
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId1",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId1",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
				{
					checkReq: report_center.CheckRequest{
						BranchId: "branchId2",
					},
					checkResp: &report_center.CheckResponse{
						BranchId: "branchId2",
						Code:     report_center.CodeHandleSuccess,
						Msg:      "保存成功",
					},
				},
			},
			updateBranchList: []*fintech_data.ReportBranch{
				{
					BranchId:     "branchId1",
					InnerId:      "innerId1",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
				{
					BranchId:     "branchId2",
					InnerId:      "innerId2",
					Code:         report_center.CodeHandleSuccess,
					Msg:          "保存成功",
					DataTotal:    1,
					SuccessTotal: 1,
					Inserted:     1,
					CheckStatus:  types.StatusSuccess,
					TotalStatus:  types.StatusSuccess,
				},
			},
			searchResp: &history.InstanceLimitResult{
				InstanceList: []*fintech_data.ReportInstance{
					{
						DataId:             "id1",
						InstanceId:         "id1",
						ObjectId:           "server",
						ReportType:         report_center.ReportTypeNew,
						FacilityCategory:   "cate1",
						FacilityDescriptor: "desc1",
					},
				},
				NextId:  "",
				HasMore: false,
			},
			wantErr: false,

			upsertList: []*history.ReportMetaData{
				{
					InstanceId:         "id1",
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
					Ts:                 int32(1609657786),
					DataId:             "id1",
				},
			},
			updateTask: &fintech_data.ReportTask{
				StartTime:    "2021-01-03 15:09:46",
				TaskId:       "taskId1",
				Status:       types.StatusSuccess,
				Msg:          fmt.Sprintf("任务上报数据成功%d个", 2),
				EndTime:      "2021-01-04 15:09:46",
				DataTotal:    2,
				SuccessTotal: 2,
				Inserted:     2,
				ObjectId:     "server",
				ConfigId:     "confId1",
			},
			statErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchAllBranch(ctx, getTaskBranchQuery(tt.args.reportTask),
				nil, 10, 1609657786, 1609772986).
				Return(tt.branchList, tt.searchErr).Times(1)

			historyMock.EXPECT().SearchInstanceLimit(ctx, gomock.Any(), gomock.Any(), 10, 1609657786, 1609772986, "").
				Return(tt.searchResp, nil).MaxTimes(2)

			historyMock.EXPECT().UpdateInstance(tt.args.ctx, gomock.Any(), gomock.Any(), []string{"code", "msg", "isFail", "status", "retryable", "handleStatus", "ts"}).Return(nil).AnyTimes()

			reportCenterMock := report_center2.NewMockService(ctrl)
			for _, item := range tt.checkList {
				reportCenterMock.EXPECT().CheckReportResult(ctx, item.checkReq, tt.args.globalConf).Return(
					item.checkResp, item.checkErr).MaxTimes(1)
			}

			for _, branch := range tt.updateBranchList {
				historyMock.EXPECT().UpdateBranch(ctx, branch.InnerId, branch, []string{}).Return(tt.branchErr).MaxTimes(1)
			}

			historyMock.EXPECT().UpdateTask(ctx, "taskId1", tt.updateTask).Return(tt.taskErr).MaxTimes(1)

			centerDataMock := history2.NewMockCenterData(ctrl)
			centerDataMock.EXPECT().Upsert(ctx, tt.upsertList).Return(&history.ChangeInfo{Inserted: 1, Updated: 1}, nil).MaxTimes(1)
			centerDataMock.EXPECT().Upsert(ctx, tt.upsertList).Return(&history.ChangeInfo{Updated: 1}, nil).MaxTimes(1)
			centerDataMock.EXPECT().Count(ctx, map[string]interface{}{"objectId": tt.args.reportTask.ObjectId}).Return(10, nil).MaxTimes(1)

			recorderMock := history2.NewMockRecorder(ctrl)
			recorderMock.EXPECT().Save(ctx, history.ReportCount{Total: 10, Inserted: 2, Updated: 0, ObjectId: "server", InstanceId: "confId1", TaskId: "taskId1"}).Return(tt.recordErr).MaxTimes(1)

			statMock := history2.NewMockObjectStat(ctrl)
			statMock.EXPECT().Get(ctx, "server").Return(&history.StatData{ObjectId: "server", Total: 1, ReportTotal: 5}, nil).MaxTimes(1)
			statMock.EXPECT().Upsert(ctx, &history.StatData{
				ObjectId:    "server",
				Total:       10,
				ReportTotal: 7,
				FailTotal:   0,
				TS:          int32(testNowTime().Unix()),
				LastTaskId:  "taskId1",
			}).Return(nil, tt.statErr).MaxTimes(1)
			test := &testRedisMock{t: t}
			c := &checker{
				newLockFunc:     test.testNewLockFunc,
				reportCenter:    reportCenterMock,
				taskHistory:     historyMock,
				centerData:      centerDataMock,
				objStat:         statMock,
				historyRecorder: recorderMock,
				timeNowFunc:     testNowTime,
				reportConf:      config.ReportConf{SearchBatch: 10},
			}
			if err := c.taskResultCheck(tt.args.ctx, tt.args.reportTask, tt.args.globalConf); (err != nil) != tt.wantErr {
				t.Errorf("taskResultCheck() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_parseTaskReportStatus(t *testing.T) {
	type args struct {
		reportTask *fintech_data.ReportTask
		warning    bool
	}
	tests := []struct {
		name string
		args args
	}{
		{
			name: "success",
			args: args{
				warning: true,
				reportTask: &fintech_data.ReportTask{
					DataTotal:    4,
					SuccessTotal: 4,
					FailTotal:    0,
				},
			},
		},
		{
			name: "has fail",
			args: args{
				reportTask: &fintech_data.ReportTask{
					DataTotal:    4,
					FailTotal:    3,
					SuccessTotal: 1,
				},
			},
		},
		{
			name: "all fail",
			args: args{
				reportTask: &fintech_data.ReportTask{
					DataTotal: 4,
					FailTotal: 4,
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			parseTaskReportStatus(tt.args.reportTask, tt.args.warning)
		})
	}
}

func Test_checker_saveReportHistory(t *testing.T) {
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
			c := &checker{
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

func Test_checker_updateObjectStat(t *testing.T) {
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
			c := &checker{
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
