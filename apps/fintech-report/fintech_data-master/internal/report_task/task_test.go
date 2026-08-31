package report_task

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/go-redis/redis/v8"
	"github.com/gogo/protobuf/proto"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/customer_settings"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_instance"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/types"
	history2 "go.easyops.local/fintech_data/mock/history"
	redismock "go.easyops.local/fintech_data/mock/redis"
	report_center2 "go.easyops.local/fintech_data/mock/report_center"
	report_instance2 "go.easyops.local/fintech_data/mock/report_instance"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	redislock "go.easyops.local/redis-helper/v8/lock"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

type testRedisMock struct {
	t *testing.T
}

func (t *testRedisMock) testNewLockFunc(redisClient redis.UniversalClient, lockKey string, lockExpiration int) redislock.Lock {
	ctrl := gomock.NewController(t.t)
	defer ctrl.Finish()
	lockMock := redismock.NewMockRedisLock(ctrl)
	lockMock.EXPECT().Lock().AnyTimes().Return(nil)
	lockMock.EXPECT().Unlock().AnyTimes().Return(nil)
	return lockMock
}

func TestNewReportService(t *testing.T) {
	type args struct {
		redisClient         redis.UniversalClient
		reportCenterService report_center.Service
		taskHistory         history.TaskHistory
		reportInstService   report_instance.Service
		reportConf          config.ReportConf
		mongoClient         pmongo.ClientInterface
	}
	tests := []struct {
		name string
		args args
		want ReportService
	}{
		{
			name: "",
			args: args{
				reportCenterService: nil,
				taskHistory:         nil,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewReportService(tt.args.redisClient, tt.args.reportCenterService, tt.args.taskHistory, tt.args.reportInstService, tt.args.reportConf, tt.args.mongoClient, nil)
		})
	}
}

func Test_reportService_CreateTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctxInput := logctx.WithLogger(context.Background(), slog.Noop())
	ctx := orguser.WithUser(ctxInput, orguser.OrgUser{User: "easyops", Org: 8888})

	type fields struct {
		reportCenterService report_center.Service
		taskHistory         history.TaskHistory
		timeNowFunc         timeutil.NowTimeFunc
		uidFunc             func() string
	}
	type args struct {
		ctx     context.Context
		request types.CreateTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    string
		wantErr bool

		lastTask  *fintech_data.ReportTask
		searchErr error

		createTask *fintech_data.ReportTask
		createErr  error
	}{
		{
			name:   "create success",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			createTask: &fintech_data.ReportTask{
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "easyops",
				Method:         string(types.ManualCreate),
				Status:         types.StatusInitial,
				StartTime:      "2021-01-04 15:09:46",
				LastReportTime: "",
			},
			want:    "fakeId",
			wantErr: false,
		},
		{
			name:   "is abandon",
			fields: fields{},
			args: args{
				ctx: ctxInput,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						Abandon:        true,
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
		},
		{
			name:   "initial fail",
			fields: fields{},
			args: args{
				ctx: ctxInput,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "create fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			createTask: &fintech_data.ReportTask{
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "easyops",
				Method:         string(types.ManualCreate),
				Status:         types.StatusInitial,
				StartTime:      "2021-01-04 15:09:46",
				LastReportTime: "",
			},
			createErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			taskHistoryMock := history2.NewMockTaskHistory(ctrl)
			taskHistoryMock.EXPECT().SearchOneTask(tt.args.ctx, gomock.Any(), gomock.Any(), 1601996986, 1609772986).
				Return(tt.lastTask, tt.searchErr).MaxTimes(1)
			taskHistoryMock.EXPECT().CreateTask(tt.args.ctx, tt.createTask).Return("fakeId", tt.createErr).MaxTimes(1)

			reportInstMock := report_instance2.NewMockService(ctrl)
			var searchTask *fintech_data.ReportTask
			if tt.createTask != nil {
				searchTask = proto.Clone(tt.createTask).(*fintech_data.ReportTask)
				searchTask.TaskId = "fakeId"
				reportInstMock.EXPECT().SearchReportInstance(ctx, tt.args.request, searchTask).
					Return(nil, tt.searchErr).MaxTimes(1)
			}

			taskHistoryMock.EXPECT().UpdateTask(ctx, "fakeId", &fintech_data.ReportTask{
				TaskId:         "fakeId",
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "easyops",
				Method:         string(types.ManualCreate),
				Status:         types.StatusNoReport,
				Msg:            "无需要上报实例",
				StartTime:      "2021-01-04 15:09:46",
				EndTime:        "2021-01-04 15:09:46",
				LastReportTime: "",
			}).Return(nil).MaxTimes(1)
			s := &reportService{
				reportCenter: tt.fields.reportCenterService,
				taskHistory:  taskHistoryMock,
				reportConf:   config.ReportConf{TimeLimit: 90, SearchBatch: 10},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				reportInstService: reportInstMock,
			}
			got, err := s.CreateTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("CreateTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("CreateTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_reportService_initialTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	ctx = orguser.WithUser(ctx, orguser.OrgUser{User: "easyops", Org: 8888})
	type fields struct {
		reportCenterService report_center.Service
		taskHistory         history.TaskHistory
		timeNowFunc         timeutil.NowTimeFunc
		uidFunc             func() string
	}
	type args struct {
		ctx     context.Context
		request types.CreateTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportTask
		wantErr bool

		lastTask  *fintech_data.ReportTask
		searchErr error
	}{
		{
			name:   "has last task",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			want: &fintech_data.ReportTask{
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "easyops",
				Status:         types.StatusInitial,
				Method:         string(types.ManualCreate),
				StartTime:      "2021-01-04 15:09:46",
				LastReportTime: "2020-12-30 22:11:22",
			},
			lastTask: &fintech_data.ReportTask{
				Status:    types.StatusSuccess,
				StartTime: "2020-12-30 22:11:22",
			},
			wantErr: false,
		},
		{
			name:   "no last task",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			want: &fintech_data.ReportTask{
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "easyops",
				Status:         types.StatusInitial,
				Method:         string(types.ManualCreate),
				StartTime:      "2021-01-04 15:09:46",
				LastReportTime: "",
			},
			wantErr: false,
		},
		{
			name:   "last task no end",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.TimerCreate,
				},
			},
			want: &fintech_data.ReportTask{
				ConfigId:       "configId",
				ObjectId:       "server",
				Sponsor:        "wc",
				Status:         types.StatusConflict,
				Msg:            "同模型任务lastId尚未结束",
				Method:         string(types.TimerCreate),
				StartTime:      "2021-01-04 15:09:46",
				LastReportTime: "2020-12-30 22:11:22",
				LastTaskId:     "lastId",
			},
			lastTask: &fintech_data.ReportTask{
				TaskId:    "lastId",
				Status:    types.StatusResulting,
				StartTime: "2020-12-30 22:11:22",
			},
			wantErr: false,
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					GlobalConfig: &fintech_data.ReportGlobalConfig{},
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId:     "configId",
						ObjectId:       "server",
						ConfigModifier: "wc",
					},
					Method: types.ManualCreate,
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			taskHistoryMock := history2.NewMockTaskHistory(ctrl)
			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.request.ObjectConf.ObjectId),
				},
				{
					Name:     "status",
					Operator: "ne",
					Value:    protostruct.ToValue(types.StatusConflict),
				},
				{
					Name:     "failType",
					Operator: "ne",
					Value:    protostruct.ToValue(types.FailTypeInitial),
				},
			}
			fields := map[string]interface{}{
				"startTime": true,
				"status":    true,
			}
			taskHistoryMock.EXPECT().SearchOneTask(tt.args.ctx, query, fields, 1601996986, 1609772986).
				Return(tt.lastTask, tt.searchErr).Times(1)
			s := &reportService{
				reportCenter: tt.fields.reportCenterService,
				taskHistory:  taskHistoryMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				uidFunc: func() string {
					return "fakeId"
				},
				reportConf: config.ReportConf{TimeLimit: 90},
			}
			got, err := s.initialTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("initialTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("initialTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_reportService_preReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctxInput := logctx.WithLogger(context.Background(), slog.Noop())
	ctx := orguser.WithUser(ctxInput, orguser.OrgUser{User: "easyops", Org: 8888})
	type fields struct {
		reportCenterService report_center.Service
		taskHistory         history.TaskHistory
		reportInstService   report_instance.Service
		timeNowFunc         timeutil.NowTimeFunc
		uidFunc             func() string
	}
	type args struct {
		ctx        context.Context
		request    types.CreateTaskRequest
		reportTask *fintech_data.ReportTask
	}
	type mockInfo struct {
		branch    *fintech_data.ReportBranch
		branchRes string
		branchErr error

		instList []*fintech_data.ReportInstance
		instErr  error
	}
	tests := []struct {
		name   string
		fields fields
		args   args

		reportList []*fintech_data.ReportInstance
		retryErr   error
		searchErr  error

		updateTask *fintech_data.ReportTask
		updateErr  error

		mockList []mockInfo

		reportUpdateTask *fintech_data.ReportTask
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
						Source:   report_rule.ObjectSourceDirect,
						ObjectDefine: &cmdb.CmdbObject{
							AttrList: []*cmdb.ObjectAttr{
								{
									Id:    "name",
									Value: &cmdb.ObjectAttrValue{Type: "str"},
								},
							},
						},
					},
				},
				reportTask: &fintech_data.ReportTask{
					ObjectId: "server",
					TaskId:   "fakeId",
				},
			},
			reportList: []*fintech_data.ReportInstance{
				{
					TaskId:     "fakeId",
					InstanceId: "11",
					ReportType: report_center.ReportTypeNew,
					Data: protostruct.ToStruct(map[string]interface{}{
						"name": "one",
					}),
				},
			},

			mockList: []mockInfo{
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    1,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchRes: "innerId1",
					instList: []*fintech_data.ReportInstance{
						{
							TaskId:        "fakeId",
							InstanceId:    "11",
							InnerBranchId: "innerId1",
							ReportType:    report_center.ReportTypeNew,
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "one"}),
						},
					},
				},
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:   "server",
				TaskId:     "fakeId",
				Status:     types.StatusReporting,
				DataTotal:  1,
				BatchTotal: 1,
			},

			reportUpdateTask: &fintech_data.ReportTask{
				ObjectId:   "server",
				TaskId:     "fakeId",
				Status:     types.StatusFail,
				FailType:   types.FailTypeReporting,
				Msg:        "任务上报阶段失败",
				EndTime:    "2021-01-04 15:09:46",
				FailTotal:  1,
				BatchTotal: 1,
				DataTotal:  1,
			},
		},
		{
			name:   "create branch fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
						Source:   report_rule.ObjectSourceDirect,
						ObjectDefine: &cmdb.CmdbObject{
							AttrList: []*cmdb.ObjectAttr{
								{
									Id:    "name",
									Value: &cmdb.ObjectAttrValue{Type: "str"},
								},
							},
						},
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId"},
			},
			reportList: []*fintech_data.ReportInstance{
				{
					TaskId:     "fakeId",
					InstanceId: "11",
					ReportType: report_center.ReportTypeNew,
					Data:       protostruct.ToStruct(map[string]interface{}{"name": "one"}),
				},
			},

			mockList: []mockInfo{
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    1,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchErr: fmt.Errorf("mock fail"),
				},
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				Status:    types.StatusFail,
				FailType:  types.FailTypeInitial,
				Msg:       "创建上报批次失败，mock fail",
				EndTime:   "2021-01-04 15:09:46",
				DataTotal: 1,
			},
		},
		{
			name:   "search retry fail and no report data",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{ObjectId: "server"},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId"},
			},
			retryErr: fmt.Errorf("mock fail"),
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				Status:    types.StatusNoReport,
				Msg:       "无需要上报实例",
				DataTotal: 0,
				EndTime:   "2021-01-04 15:09:46",
			},
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{ObjectId: "server"},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId"},
			},
			searchErr: fmt.Errorf("mock fail"),
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				Status:    types.StatusFail,
				FailType:  types.FailTypeInitial,
				Msg:       "查询上报实例失败：mock fail",
				DataTotal: 0,
				EndTime:   "2021-01-04 15:09:46",
			},
			updateErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			reportInstMock := report_instance2.NewMockService(ctrl)
			reportInstMock.EXPECT().SearchReportInstance(gomock.Any(), tt.args.request, tt.args.reportTask).
				Return(tt.reportList, tt.searchErr).Times(1)

			historyMock := history2.NewMockTaskHistory(ctrl)
			for _, item := range tt.mockList {
				historyMock.EXPECT().CreateBranch(gomock.Any(), item.branch).Return(item.branchRes, item.branchErr).Times(1)
				if item.branchErr == nil {
					historyMock.EXPECT().BatchCreateInstance(gomock.Any(), item.instList).Return(nil, item.instErr).Times(1)
				}
			}

			historyMock.EXPECT().UpdateTask(gomock.Any(), tt.args.reportTask.TaskId, tt.updateTask).
				Return(tt.updateErr).Times(1)

			// 上报阶段
			centerMock := report_center2.NewMockService(ctrl)
			centerMock.EXPECT().ReportData(ctx, gomock.Any(), tt.args.request.GlobalConfig).Return(nil, fmt.Errorf("request fail")).MaxTimes(1)

			branchUpdateFields := []string{"branchId", "totalStatus", "reportStatus", "requestCheckStatus", "code", "msg", "failTotal"}
			historyMock.EXPECT().UpdateBranch(ctx, "innerId1", gomock.Any(), branchUpdateFields).Return(nil).MaxTimes(1)

			updateQuery := []*monthly_collection_service.QueryItem{
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("innerId1"),
				},
			}
			instUpdateFields := []string{"branchId", "code", "msg", "isFail", "status", "retryable"}
			historyMock.EXPECT().UpdateInstanceByFilter(ctx, updateQuery, gomock.Any(), instUpdateFields, gomock.Any(), gomock.Any()).Return(nil).MaxTimes(1)

			historyMock.EXPECT().UpdateTask(ctx, tt.args.reportTask.TaskId, tt.reportUpdateTask).
				Return(nil).MaxTimes(1)
			s := &reportService{
				reportCenter:      centerMock,
				taskHistory:       historyMock,
				reportInstService: reportInstMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				uidFunc:    tt.fields.uidFunc,
				reportConf: config.ReportConf{SearchBatch: 10, TimeLimit: 90},
			}
			s.preReportTask(tt.args.ctx, tt.args.request, tt.args.reportTask)
		})
	}
}

func Test_reportService_handleReportBatch(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		reportCenter      report_center.Service
		taskHistory       history.TaskHistory
		reportInstService report_instance.Service
		timeNowFunc       timeutil.NowTimeFunc
		uidFunc           func() string
		reportConf        config.ReportConf
	}
	type args struct {
		ctx        context.Context
		request    types.CreateTaskRequest
		reportTask *fintech_data.ReportTask
		reportList []*fintech_data.ReportInstance
	}

	type mockInfo struct {
		branch    *fintech_data.ReportBranch
		branchRes string
		branchErr error

		instList []*fintech_data.ReportInstance
		instErr  error
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []report_center.ReportRequest
		wantErr bool

		mockList []mockInfo
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{BatchNum: 2, ObjectId: "server"},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:   "fakeId",
					ObjectId: "server",
				},
				reportList: []*fintech_data.ReportInstance{
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeDelete,
						InstanceId: "one",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "one"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeUpdate,
						InstanceId: "two",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "two"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeNew,
						InstanceId: "three",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "three"}),
					},
				},
			},
			mockList: []mockInfo{
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    2,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchRes: "innerId1",
					instList: []*fintech_data.ReportInstance{
						{
							InnerBranchId: "innerId1",
							ReportType:    report_center.ReportTypeDelete,
							TaskId:        "fakeId",
							ObjectId:      "server",
							InstanceId:    "one",
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "one"}),
						},
						{
							InnerBranchId: "innerId1",
							ReportType:    report_center.ReportTypeUpdate,
							TaskId:        "fakeId",
							ObjectId:      "server",
							InstanceId:    "two",
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "two"}),
						},
					},
				},
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    1,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchRes: "innerId2",
					instList: []*fintech_data.ReportInstance{
						{
							InnerBranchId: "innerId2",
							TaskId:        "fakeId",
							ObjectId:      "server",
							InstanceId:    "three",
							ReportType:    report_center.ReportTypeNew,
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "three"}),
						},
					},
				},
			},
			want: []report_center.ReportRequest{
				{
					DataTotal:           2,
					InnerBranchId:       "innerId1",
					FacilityOwnerAgency: "",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "one", report_center.KeyReportDataType: report_center.ReportTypeDelete},
								map[string]interface{}{"name": "two", report_center.KeyReportDataType: report_center.ReportTypeUpdate},
							},
						},
					},
				},
				{
					DataTotal:           1,
					InnerBranchId:       "innerId2",
					FacilityOwnerAgency: "",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name:   "create instance fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{BatchNum: 2, ObjectId: "server"},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:   "fakeId",
					ObjectId: "server",
				},
				reportList: []*fintech_data.ReportInstance{
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeDelete,
						InstanceId: "one",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "one"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeUpdate,
						InstanceId: "two",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "two"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeNew,
						InstanceId: "three",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "three"}),
					},
				},
			},
			mockList: []mockInfo{
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    2,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchRes: "innerId1",
					instList: []*fintech_data.ReportInstance{
						{
							InnerBranchId: "innerId1",
							ReportType:    report_center.ReportTypeDelete,
							TaskId:        "fakeId",
							ObjectId:      "server",
							InstanceId:    "one",
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "one"}),
						},
						{
							InnerBranchId: "innerId1",
							ReportType:    report_center.ReportTypeUpdate,
							TaskId:        "fakeId",
							ObjectId:      "server",
							InstanceId:    "two",
							Data:          protostruct.ToStruct(map[string]interface{}{"name": "two"}),
						},
					},
					instErr: fmt.Errorf("mock fail"),
				},
			},
			wantErr: true,
		},
		{
			name:   "create branch fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{BatchNum: 3, ObjectId: "server"},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:   "fakeId",
					ObjectId: "server",
				},
				reportList: []*fintech_data.ReportInstance{
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeDelete,
						InstanceId: "one",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "one"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeUpdate,
						InstanceId: "two",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "two"}),
					},
					{
						TaskId:     "fakeId",
						ObjectId:   "server",
						ReportType: report_center.ReportTypeNew,
						InstanceId: "three",
						Data:       protostruct.ToStruct(map[string]interface{}{"name": "three"}),
					},
				},
			},
			mockList: []mockInfo{
				{
					branch: &fintech_data.ReportBranch{
						TaskId:       "fakeId",
						ObjectId:     "server",
						DataTotal:    3,
						TotalStatus:  types.StatusReporting,
						ReportStatus: types.StatusReporting,
					},
					branchErr: fmt.Errorf("mock fail"),
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			for _, item := range tt.mockList {
				historyMock.EXPECT().CreateBranch(ctx, item.branch).Return(item.branchRes, item.branchErr).Times(1)
				if item.branchErr == nil {
					historyMock.EXPECT().BatchCreateInstance(ctx, item.instList).Return(nil, item.instErr).Times(1)
				}
			}

			s := &reportService{
				reportCenter:      tt.fields.reportCenter,
				taskHistory:       historyMock,
				reportInstService: tt.fields.reportInstService,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				uidFunc:    tt.fields.uidFunc,
				reportConf: config.ReportConf{SearchBatch: 10, TimeLimit: 90},
			}
			got, err := s.handleReportBatch(tt.args.ctx, tt.args.request, tt.args.reportTask, tt.args.reportList)
			if (err != nil) != tt.wantErr {
				t.Errorf("handleReportBatch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("handleReportBatch() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_getReportDataType(t *testing.T) {
	type args struct {
		objectId string
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				objectId: "gap@FINTECHDATA",
			},
			want: "gap",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := getReportDataType(tt.args.objectId); got != tt.want {
				t.Errorf("getReportDataType() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_reportService_doReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		reportCenter      report_center.Service
		taskHistory       history.TaskHistory
		reportInstService report_instance.Service
		timeNowFunc       timeutil.NowTimeFunc
		uidFunc           func() string
		reportConf        config.ReportConf
	}
	type args struct {
		ctx               context.Context
		request           types.CreateTaskRequest
		reportTask        *fintech_data.ReportTask
		reportRequestList []report_center.ReportRequest
		isZhongXin        bool
	}
	tests := []struct {
		name   string
		fields fields
		args   args

		reportRes *report_center.ReportResponse
		reportErr error

		updateBranch *fintech_data.ReportBranch
		branchErr    error

		updateInst *fintech_data.ReportInstance
		instErr    error

		updateTask *fintech_data.ReportTask

		searchBranchErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportRes: &report_center.ReportResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeReportSuccess,
				Msg:      "上报成功",
			},
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				TotalStatus:        types.StatusPendingCheck,
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusPendingCheck,
				Code:               report_center.CodeReportSuccess,
				Msg:                "上报成功",
			},
			updateInst: &fintech_data.ReportInstance{
				Status:    types.StatusPendingCheck,
				Code:      report_center.CodeReportSuccess,
				Msg:       "上报成功",
				BranchId:  "branchId1",
				Retryable: false,
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusPendingCheck,
				BranchIds: []string{"branchId1"},
			},
		},
		{
			name:   "report request fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52", DataTotal: 1},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportErr: fmt.Errorf("request fail"),
			updateBranch: &fintech_data.ReportBranch{
				BranchId:     "",
				FailTotal:    1,
				TotalStatus:  types.StatusFail,
				ReportStatus: types.StatusFail,
				Msg:          "调用上报接口失败：request fail",
			},
			updateInst: &fintech_data.ReportInstance{
				IsFail:    true,
				Status:    types.FailTypeReporting,
				Msg:       "调用上报接口失败：request fail",
				BranchId:  "",
				Retryable: true,
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusFail,
				FailType:  types.FailTypeReporting,
				DataTotal: 1,
				BranchIds: nil,
				Msg:       "任务上报阶段失败",
				EndTime:   "2021-01-04 15:09:46",
				FailTotal: 1,
			},
		},
		{
			name:   "update branch fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportRes: &report_center.ReportResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeReportSuccess,
				Msg:      "上报成功",
			},
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				TotalStatus:        types.StatusPendingCheck,
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusPendingCheck,
				Code:               report_center.CodeReportSuccess,
				Msg:                "上报成功",
			},
			branchErr: fmt.Errorf("mock fail"),
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusPendingCheck,
				BranchIds: []string{"branchId1"},
			},
		},
		{
			name:   "report fail and update instance fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52", DataTotal: 1},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportRes: &report_center.ReportResponse{
				BranchId: "branchId1",
				Code:     report_center.CodeAgencyIsEmpty,
				Msg:      "机构编号不能为空",
			},
			updateBranch: &fintech_data.ReportBranch{
				BranchId:     "branchId1",
				FailTotal:    1,
				TotalStatus:  types.StatusFail,
				ReportStatus: types.StatusFail,
				Code:         report_center.CodeAgencyIsEmpty,
				Msg:          "机构编号不能为空",
			},
			updateInst: &fintech_data.ReportInstance{
				IsFail:    true,
				Status:    types.FailTypeReporting,
				Code:      report_center.CodeAgencyIsEmpty,
				Msg:       "机构编号不能为空",
				BranchId:  "branchId1",
				Retryable: true,
			},
			instErr: fmt.Errorf("mock fail"),
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusFail,
				FailType:  types.FailTypeReporting,
				DataTotal: 1,
				BranchIds: []string{"branchId1"},
				Msg:       "任务上报阶段失败",
				EndTime:   "2021-01-04 15:09:46",
				FailTotal: 1,
			},
		},

		{
			name:   "zhongxin report request fail",
			fields: fields{},
			args: args{
				ctx:        ctx,
				isZhongXin: true,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52", DataTotal: 1},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportErr: fmt.Errorf("request fail"),
			updateBranch: &fintech_data.ReportBranch{
				FailTotal:    1,
				TotalStatus:  types.StatusFail,
				ReportStatus: types.StatusFail,
				Msg:          "调用上报接口失败：request fail",
			},
			updateInst: &fintech_data.ReportInstance{
				IsFail:    true,
				Status:    types.FailTypeReporting,
				Msg:       "调用上报接口失败：request fail",
				Retryable: true,
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusFail,
				FailType:  types.FailTypeReporting,
				DataTotal: 1,
				BranchIds: []string{"inner1"},
				Msg:       "任务上报阶段失败",
				EndTime:   "2021-01-04 15:09:46",
				FailTotal: 1,
			},
		},

		{
			name:   "zhongxin report success",
			fields: fields{},
			args: args{
				ctx:        ctx,
				isZhongXin: true,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportRes: &report_center.ReportResponse{
				Code: report_center.ZhongXinCodeReportSuccess,
				Msg:  "接收成功",
				Data: "",
			},
			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusSuccess,
				TotalStatus:  types.StatusResulting,
				CheckStatus:  types.StatusResulting,
				Code:         report_center.ZhongXinCodeReportSuccess,
				Msg:          "接收成功",
			},
			updateInst: &fintech_data.ReportInstance{
				Status: types.StatusResulting,
				Code:   report_center.ZhongXinCodeReportSuccess,
				Msg:    "接收成功",
			},
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				BranchIds: []string{"inner1"},
				Status:    types.StatusResulting,
			},
		},

		{
			name:   "zhongxin report fail",
			fields: fields{},
			args: args{
				ctx:        ctx,
				isZhongXin: true,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				reportRequestList: []report_center.ReportRequest{
					{
						DataTotal:     1,
						InnerBranchId: "inner1",
						Data: []report_center.ReportData{
							{
								DataType: "server",
								DataList: []interface{}{
									map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
								},
							},
						},
					},
				},
			},
			reportRes: &report_center.ReportResponse{
				Code: report_center.ZhongXinCodeReportFail,
				Msg:  "接收失败",
				Data: []*report_center.ReportResponseInstance{
					{
						Msg:                "[facilityName]不能为空",
						FacilityCategory:   "FAITSERPCS",
						FacilityDescriptor: "5f11db861e33ff0ec08ba546",
					},
				},
			},
			updateBranch:    &fintech_data.ReportBranch{},
			searchBranchErr: fmt.Errorf("search error fail"),
			updateTask: &fintech_data.ReportTask{
				ObjectId:  "server",
				TaskId:    "fakeId",
				StartTime: "2020-12-23 21:11:52",
				Status:    types.StatusFail,
				FailType:  types.FailTypeReporting,
				BranchIds: []string{"inner1"},
				Msg:       "任务上报阶段失败",
				EndTime:   "2021-01-04 15:09:46",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerMock := report_center2.NewMockService(ctrl)
			for _, req := range tt.args.reportRequestList {
				centerMock.EXPECT().ReportData(ctx, req, tt.args.request.GlobalConfig).Return(tt.reportRes, tt.reportErr).Times(1)
			}

			historyMock := history2.NewMockTaskHistory(ctrl)
			branchUpdateFields := []string{"branchId", "totalStatus", "reportStatus", "requestCheckStatus", "code", "msg", "failTotal"}
			if tt.args.isZhongXin && tt.updateBranch.CheckStatus != "" {
				branchUpdateFields = append(branchUpdateFields, "checkStatus")
			}
			historyMock.EXPECT().UpdateBranch(ctx, "inner1", tt.updateBranch, branchUpdateFields).Return(tt.branchErr).MaxTimes(1)

			historyMock.EXPECT().SearchBranch(ctx, gomock.Any(), gomock.Any(), gomock.Any(), gomock.Any(), gomock.Any(), gomock.Any()).Return(nil, 0, tt.searchBranchErr).MaxTimes(1)

			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("inner1"),
				},
			}
			instUpdateFields := []string{"branchId", "code", "msg", "isFail", "status", "retryable"}
			historyMock.EXPECT().UpdateInstanceByFilter(ctx, query, tt.updateInst, instUpdateFields, 1608729112, 1609772986).Return(tt.instErr).MaxTimes(1)

			historyMock.EXPECT().UpdateTask(ctx, tt.args.reportTask.TaskId, tt.updateTask).
				Return(nil).MaxTimes(1)
			s := &reportService{
				reportCenter:      centerMock,
				taskHistory:       historyMock,
				reportInstService: nil,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				uidFunc:    tt.fields.uidFunc,
				reportConf: config.ReportConf{SearchBatch: 10, TimeLimit: 90},
			}

			if tt.args.isZhongXin {
				customer_settings.IsZhongXin = true
			}
			s.doReportTask(tt.args.ctx, tt.args.request, tt.args.reportTask, tt.args.reportRequestList)
			customer_settings.IsZhongXin = false
		})
	}
}

func Test_reportService_getBatchNum(t *testing.T) {
	type fields struct {
		reportCenter      report_center.Service
		taskHistory       history.TaskHistory
		reportInstService report_instance.Service
		nowTimeFunc       timeutil.NowTimeFunc
		uidFunc           func() string
		reportConf        config.ReportConf
	}
	type args struct {
		conf *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   int
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				conf: &fintech_data.ReportObjectConf{},
			},
			want: 100,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &reportService{
				reportCenter:      tt.fields.reportCenter,
				taskHistory:       tt.fields.taskHistory,
				reportInstService: tt.fields.reportInstService,
				nowTimeFunc:       tt.fields.nowTimeFunc,
				uidFunc:           tt.fields.uidFunc,
				reportConf:        tt.fields.reportConf,
			}
			if got := s.getBatchNum(tt.args.conf); got != tt.want {
				t.Errorf("getBatchNum() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_CreateAuditTask(t *testing.T) {

	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type args struct {
		autoRequestCheck bool
		branches         []*fintech_data.ReportBranch
		globalConf       *fintech_data.ReportGlobalConfig
		st               int64
		et               int64
		objectId         string
		taskId           string
	}
	tests := []struct {
		name             string
		args             args
		updateTask       *fintech_data.ReportTask
		updateBranch     *fintech_data.ReportBranch
		reportInstance   *fintech_data.ReportInstance
		isPendingCheck   bool
		respReturnFailed bool
		auditErr         error
		searchtaskErr    error
		searchBranchErr  error
		wantErr          bool
	}{
		{
			name:           "request ok and return success",
			isPendingCheck: true,
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				CheckStatus:        types.StatusResulting,
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusSuccess,
				TotalStatus:        types.StatusResulting,
				Code:               report_center.CodeRequestCheckSuccess,
				Msg:                "HH",
			},
			reportInstance: &fintech_data.ReportInstance{
				Code:   report_center.CodeRequestCheckSuccess,
				Msg:    "HH",
				Status: types.StatusResulting,
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				SuccessTotal: 1,
				Status:       types.StatusPendingCheck,
			},
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
		},
		{
			name:             "request ok but return failed,仍然存在待审核",
			isPendingCheck:   true,
			respReturnFailed: true,
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusFail,
				TotalStatus:        types.StatusFail,
				FailTotal:          2,
				Code:               report_center.CodeRequestCheckFailed,
				Msg:                "HH",
			},
			reportInstance: &fintech_data.ReportInstance{
				Code:      report_center.CodeRequestCheckFailed,
				Msg:       "HH",
				Retryable: true,
				IsFail:    true,
				Status:    types.FailTypeRequestCheck,
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				FailTotal:    2,
				SuccessTotal: 1,
				Msg:          fmt.Sprintf("请求审核失败:%s", "HH"),
				EndTime:      "2021-01-04 15:09:46",
				FailType:     types.FailTypeRequestCheck,
				Status:       types.StatusPendingCheck,
			},
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
			wantErr: true,
		},
		{
			name:             "request ok but return failed,最终状态为部分成功",
			respReturnFailed: true,
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusFail,
				TotalStatus:        types.StatusFail,
				FailTotal:          2,
				Code:               report_center.CodeRequestCheckFailed,
				Msg:                "HH",
			},
			reportInstance: &fintech_data.ReportInstance{
				Code:      report_center.CodeRequestCheckFailed,
				Msg:       "HH",
				Retryable: true,
				IsFail:    true,
				Status:    types.FailTypeRequestCheck,
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				FailTotal:    2,
				SuccessTotal: 1,
				Msg:          fmt.Sprintf("请求审核失败:%s", "HH"),
				EndTime:      "2021-01-04 15:09:46",
				FailType:     types.FailTypeRequestCheck,
				Status:       types.StatusPartialSuccess,
			},
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
			wantErr: true,
		},
		{
			name: "audit err",
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusFail,
				TotalStatus:        types.StatusFail,
				Msg:                fmt.Sprintf("调用请求审核接口失败：%s", "err"),
			},
			reportInstance: &fintech_data.ReportInstance{
				Retryable: true,
				IsFail:    true,
				Status:    types.FailTypeRequestCheck,
				Msg:       fmt.Sprintf("调用请求审核接口失败：%s", "err"),
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				SuccessTotal: 1,
				FailTotal:    1,
				FailType:     types.FailTypeRequestCheck,
				Msg:          fmt.Sprintf("审核失败,%s", "err"),
				Status:       types.StatusPartialSuccess,
				EndTime:      "2021-01-04 15:09:46",
			},
			auditErr: fmt.Errorf("err"),
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
			wantErr: true,
		},
		{
			name: "search task err",
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				CheckStatus:        types.StatusResulting,
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusSuccess,
				TotalStatus:        types.StatusResulting,
				Code:               report_center.CodeRequestCheckSuccess,
				Msg:                "HH",
			},
			reportInstance: &fintech_data.ReportInstance{
				Code:   report_center.CodeRequestCheckSuccess,
				Msg:    "HH",
				Status: types.StatusResulting,
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				SuccessTotal: 1,
				Status:       types.StatusResulting,
				EndTime:      "2021-01-04 15:09:46",
			},
			searchtaskErr: fmt.Errorf("err"),
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
		},
		{
			name: "search branches err",
			updateBranch: &fintech_data.ReportBranch{
				InnerId:            "inner1",
				BranchId:           "branchId1",
				CheckStatus:        types.StatusResulting,
				ReportStatus:       types.StatusSuccess,
				RequestCheckStatus: types.StatusSuccess,
				TotalStatus:        types.StatusResulting,
				Code:               report_center.CodeRequestCheckSuccess,
				Msg:                "HH",
			},
			reportInstance: &fintech_data.ReportInstance{
				Code:   report_center.CodeRequestCheckSuccess,
				Msg:    "HH",
				Status: types.StatusResulting,
			},
			updateTask: &fintech_data.ReportTask{
				TaskId:       "taskId001",
				SuccessTotal: 1,
				Status:       types.StatusResulting,
				EndTime:      "2021-01-04 15:09:46",
			},
			searchBranchErr: fmt.Errorf("err"),
			args: args{
				autoRequestCheck: true,
				branches: []*fintech_data.ReportBranch{
					{
						BranchId: "branchId1",
						InnerId:  "inner1",
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{},
				st:         1608729112,
				et:         1608729222,
				objectId:   "HOST",
				taskId:     "taskId001",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerMock := report_center2.NewMockService(ctrl)
			req := report_center.AuditRequest{
				FacilityOwnerAgency: "",
				BranchNumber:        len(tt.args.branches),
				BranchIdList:        []string{"branchId1"},
			}

			code := report_center.CodeRequestCheckSuccess
			if tt.respReturnFailed {
				code = report_center.CodeRequestCheckFailed
			}
			centerMock.EXPECT().Audit(gomock.Any(), req, tt.args.globalConf).Return(&report_center.AuditResponse{
				Code: code,
				Msg:  "HH",
			}, tt.auditErr).AnyTimes()

			historyMock := history2.NewMockTaskHistory(ctrl)
			branchUpdateFields := []string{"branchId", "totalStatus", "reportStatus", "requestCheckStatus", "code", "msg", "failTotal"}
			if tt.updateBranch.CheckStatus != "" {
				branchUpdateFields = append(branchUpdateFields, "checkStatus")
			}
			historyMock.EXPECT().UpdateBranch(ctx, "inner1", tt.updateBranch, branchUpdateFields).Return(nil).MaxTimes(1)

			historyMock.EXPECT().SearchInstance(ctx, gomock.Any(), nil, int(tt.args.st), int(tt.args.et), 1, 3000).AnyTimes().Return([]*fintech_data.ReportInstance{{
				InnerBranchId: "inner1",
				InstanceId:    "001",
			}, {InnerBranchId: "inner1", InstanceId: "002"}}, 2, fmt.Errorf("err"))

			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("inner1"),
				},
			}
			instUpdateFields := []string{"branchId", "code", "msg", "isFail", "status", "retryable"}
			historyMock.EXPECT().UpdateInstanceByFilter(ctx, query, tt.reportInstance, instUpdateFields, int(tt.args.st), int(tt.args.et)).Return(nil).MaxTimes(1)

			historyMock.EXPECT().GetTask(ctx, tt.args.taskId).AnyTimes().Return(&fintech_data.ReportTask{
				TaskId:       tt.args.taskId,
				SuccessTotal: 1,
			}, tt.searchtaskErr)

			query1 := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.taskId),
				},
			}
			fields := map[string]interface{}{
				"branchId":    true,
				"innerId":     true,
				"totalStatus": true,
			}
			totalStatus := types.StatusSuccess
			if tt.isPendingCheck {
				totalStatus = types.StatusPendingCheck
			}
			historyMock.EXPECT().SearchAllBranch(ctx, query1, fields, 1000, int(tt.args.st), gomock.Any()).AnyTimes().Return([]*fintech_data.ReportBranch{
				{
					InnerId:     "inner003",
					TotalStatus: totalStatus,
				},
				{
					InnerId:     "inner1",
					TotalStatus: types.StatusPendingCheck,
				},
			}, tt.searchBranchErr)

			historyMock.EXPECT().UpdateTask(ctx, tt.args.taskId, tt.updateTask).AnyTimes()

			test := &testRedisMock{t: t}

			s := &reportService{
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				newLockFunc:  test.testNewLockFunc,
				reportCenter: centerMock,
				taskHistory:  historyMock,
			}
			err := s.CreateAuditTask(ctx, tt.args.autoRequestCheck, tt.args.branches, tt.args.globalConf, tt.args.st, tt.args.et, tt.args.objectId, tt.args.taskId)
			if (err != nil) != tt.wantErr {
				t.Errorf("CreateAuditTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}

}

func Test_reportService_dealWithZhongXinFailReportResult(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		reportCenter      report_center.Service
		taskHistory       history.TaskHistory
		reportInstService report_instance.Service
		timeNowFunc       timeutil.NowTimeFunc
		uidFunc           func() string
		reportConf        config.ReportConf
	}
	type args struct {
		ctx         context.Context
		request     types.CreateTaskRequest
		reportTask  *fintech_data.ReportTask
		st          int64
		et          int64
		req         *report_center.ReportRequest
		resp        *report_center.ReportResponse
		batchReport *batchReportStatistics
	}
	tests := []struct {
		name      string
		fields    fields
		args      args
		reportRes *report_center.ReportResponse
		reportErr error

		branchList      []*fintech_data.ReportBranch
		searchBranchErr error

		updateBranch    *fintech_data.ReportBranch
		updateBranchErr error

		updateAllInstanceErr error

		instanceList      []*fintech_data.ReportInstance
		searchInstanceErr error

		updateSuccessInst    *fintech_data.ReportInstance
		updateSuccessInstErr error

		updateFailInst    *fintech_data.ReportInstance
		updateFailInstErr error
	}{
		{
			name:   "search branch error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     1,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
			},
			searchBranchErr: fmt.Errorf("search branch error"),
		},

		{
			name:   "resp data error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     1,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: "",
				},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 1,
				},
			},
		},

		{
			name:   "update branch error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     1,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: []interface{}{
						map[string]interface{}{
							"msg":                "[facilityName]不能为空",
							"facilityCategory":   "FAITSERPCS",
							"facilityDescriptor": "5f11db861e33ff0ec08ba546",
						},
					},
				},
				batchReport: &batchReportStatistics{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 1,
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusFail,
				TotalStatus:  types.StatusFail,
				Code:         report_center.ZhongXinCodeReportFail,
				Msg:          "接收失败",
				FailTotal:    1,
			},
			updateBranchErr: fmt.Errorf("update branch error"),
		},

		{
			name:   "all fail update instance error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     1,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: []interface{}{
						map[string]interface{}{
							"msg":                "[facilityOwnerAgency]不能为空",
							"facilityCategory":   "",
							"facilityDescriptor": "",
						},
					},
				},
				batchReport: &batchReportStatistics{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 1,
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusFail,
				TotalStatus:  types.StatusFail,
				Code:         report_center.ZhongXinCodeReportFail,
				Msg:          "接收失败",
				FailTotal:    1,
			},
			updateAllInstanceErr: fmt.Errorf("all fail update instance error"),
		},

		{
			name:   "search instance error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     1,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: []interface{}{
						map[string]interface{}{
							"msg":                "[facilityName]不能为空",
							"facilityCategory":   "FAITSERPCS",
							"facilityDescriptor": "5f11db861e33ff0ec08ba546",
						},
					},
				},
				batchReport: &batchReportStatistics{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 1,
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusFail,
				TotalStatus:  types.StatusFail,
				Code:         report_center.ZhongXinCodeReportFail,
				Msg:          "接收失败",
				FailTotal:    1,
			},
			searchInstanceErr: fmt.Errorf("search instance error"),
		},

		{
			name:   "update instance by filter error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     2,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew, report_center.KeyFacilityDescriptor: "5f11db861e33ff0ec08ba546"},
							},
						},
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "four", report_center.KeyReportDataType: report_center.ReportTypeNew, report_center.KeyFacilityDescriptor: "6ac1db861e33ff0ec08ba698"},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: []interface{}{
						map[string]interface{}{
							"msg":                "[facilityName]不能为空",
							"facilityCategory":   "FAITSERPCS",
							"facilityDescriptor": "5f11db861e33ff0ec08ba546",
						},
					},
				},
				batchReport: &batchReportStatistics{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 2,
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusPartialSuccess,
				TotalStatus:  types.StatusResulting,
				CheckStatus:  types.StatusResulting,
				Code:         report_center.ZhongXinCodeReportFail,
				FailTotal:    1,
			},

			instanceList: []*fintech_data.ReportInstance{
				{
					DataId:             "111",
					InnerBranchId:      "inner1",
					FacilityDescriptor: "5f11db861e33ff0ec08ba546",
				},
				{
					DataId:             "222",
					InnerBranchId:      "inner1",
					FacilityDescriptor: "6ac1db861e33ff0ec08ba698",
				},
			},
			updateSuccessInst: &fintech_data.ReportInstance{
				Status: types.StatusResulting,
			},
			updateSuccessInstErr: fmt.Errorf("update instance by filter error"),
		},

		{
			name:   "update report fail instance error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						ObjectId: "server",
						BatchNum: 2,
					},
				},
				reportTask: &fintech_data.ReportTask{ObjectId: "server", TaskId: "fakeId", StartTime: "2020-12-23 21:11:52"},
				req: &report_center.ReportRequest{
					DataTotal:     2,
					InnerBranchId: "inner1",
					Data: []report_center.ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "three", report_center.KeyReportDataType: report_center.ReportTypeNew, report_center.KeyFacilityDescriptor: "5f11db861e33ff0ec08ba546"},
							},
						},
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{"name": "four", report_center.KeyReportDataType: report_center.ReportTypeNew, report_center.KeyFacilityDescriptor: "6ac1db861e33ff0ec08ba698"},
							},
						},
					},
				},
				resp: &report_center.ReportResponse{
					Code: report_center.ZhongXinCodeReportFail,
					Msg:  "接收失败",
					Data: []interface{}{
						map[string]interface{}{
							"msg":                "[facilityName]不能为空",
							"facilityCategory":   "FAITSERPCS",
							"facilityDescriptor": "5f11db861e33ff0ec08ba546",
						},
					},
				},
				batchReport: &batchReportStatistics{},
			},
			branchList: []*fintech_data.ReportBranch{
				{
					InnerId:   "inner1",
					DataTotal: 2,
				},
			},

			updateBranch: &fintech_data.ReportBranch{
				ReportStatus: types.StatusPartialSuccess,
				TotalStatus:  types.StatusResulting,
				CheckStatus:  types.StatusResulting,
				Code:         report_center.ZhongXinCodeReportFail,
				FailTotal:    1,
			},

			instanceList: []*fintech_data.ReportInstance{
				{
					DataId:             "111",
					InnerBranchId:      "inner1",
					FacilityDescriptor: "5f11db861e33ff0ec08ba546",
				},
				{
					DataId:             "222",
					InnerBranchId:      "inner1",
					FacilityDescriptor: "6ac1db861e33ff0ec08ba698",
				},
			},
			updateSuccessInst: &fintech_data.ReportInstance{
				Status: types.StatusResulting,
			},

			updateFailInst: &fintech_data.ReportInstance{
				Status:    types.FailTypeReporting,
				IsFail:    true,
				Retryable: true,
				Code:      report_center.ZhongXinCodeReportFail,
				Msg:       "[facilityName]不能为空",
			},
			updateFailInstErr: fmt.Errorf("update report fail instance error"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			branchQuery := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.TaskId),
				},
				{
					Name:     "_id",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.req.InnerBranchId),
				},
			}
			branchFields := map[string]interface{}{
				"_id":       true,
				"dataTotal": true,
			}
			historyMock.EXPECT().SearchBranch(ctx, branchQuery, branchFields, gomock.Any(), gomock.Any(), 1, 20).Return(tt.branchList, len(tt.branchList), tt.searchBranchErr).MaxTimes(1)
			historyMock.EXPECT().UpdateBranch(ctx, "inner1", tt.updateBranch, gomock.Any()).Return(tt.updateBranchErr).MaxTimes(1)

			failInstanceQuery := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.TaskId),
				},
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.req.InnerBranchId),
				},
			}
			updateFailInst := &fintech_data.ReportInstance{
				Status:    types.FailTypeReporting,
				IsFail:    true,
				Retryable: true,
				Code:      report_center.ZhongXinCodeReportFail,
				Msg:       "[facilityOwnerAgency]不能为空",
			}
			instUpdateFields := []string{"code", "msg", "isFail", "status", "retryable"}
			historyMock.EXPECT().UpdateInstanceByFilter(ctx, failInstanceQuery, updateFailInst, instUpdateFields, gomock.Any(), gomock.Any()).Return(tt.updateAllInstanceErr).MaxTimes(1)

			instanceQuery := []*monthly_collection_service.QueryItem{
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
			instanceFields := map[string]interface{}{
				"_id":                true,
				"innerBranchId":      true,
				"facilityDescriptor": true,
			}
			historyMock.EXPECT().SearchInstance(ctx, instanceQuery, instanceFields, gomock.Any(), gomock.Any(), 1, 2).Return(tt.instanceList, len(tt.instanceList), tt.searchInstanceErr).MaxTimes(1)

			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "_id",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"222"}),
				},
			}
			historyMock.EXPECT().UpdateInstanceByFilter(ctx, query, tt.updateSuccessInst, gomock.Any(), gomock.Any(), gomock.Any()).Return(tt.updateSuccessInstErr).MaxTimes(1)

			historyMock.EXPECT().UpdateInstance(ctx, "111", tt.updateFailInst, gomock.Any()).Return(tt.updateFailInstErr).MaxTimes(1)

			s := &reportService{
				taskHistory: historyMock,
			}
			s.dealWithZhongXinFailReportResult(tt.args.ctx, tt.args.request, tt.args.reportTask, tt.args.st, tt.args.et, tt.args.req, tt.args.resp, tt.args.batchReport)
		})
	}
}

func Test_reportService_Convert(t *testing.T) {
	type args struct {
		resp interface{}
	}
	tests := []struct {
		name    string
		args    args
		want    []*report_center.ReportResponseInstance
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
						"msg":                1,
						"facility":           "FAITSERPCS",
						"facilityDescriptor": "5f11db861e33ff0ec08ba546",
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
						"msg":                "[facilityName]不能为空",
						"facilityCategory":   "FAITSERPCS",
						"facilityDescriptor": "5f11db861e33ff0ec08ba546",
					},
				},
			},
			want: []*report_center.ReportResponseInstance{
				{
					Msg:                "[facilityName]不能为空",
					FacilityCategory:   "FAITSERPCS",
					FacilityDescriptor: "5f11db861e33ff0ec08ba546",
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := Convert(tt.args.resp)
			if (err != nil) != tt.wantErr {
				t.Errorf("Convert() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Convert() got = %v, want %v", got, tt.want)
			}
		})
	}
}
