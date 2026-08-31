package history

import (
	"context"
	"errors"
	"fmt"
	"github.com/stretchr/testify/assert"
	"go.easyops.local/fintech_data/internal/report_center"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	message "go.easyops.local/contracts/protorepo-fintech_data/history"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/excelutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/types"
	excelutil2 "go.easyops.local/fintech_data/mock/excelutil"
	history2 "go.easyops.local/fintech_data/mock/history"
	"go.easyops.local/fintech_data/mock/remote/cmdb"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewHistoryService(t *testing.T) {
	type args struct {
		taskHistory history.TaskHistory
		centerData  history.CenterData
		objClient   cmdb_object.Client
	}
	tests := []struct {
		name string
		args args
		want *historyService
	}{
		{
			name: "",
			args: args{},
			want: &historyService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewHistoryService(tt.args.taskHistory, tt.args.centerData, tt.args.objClient)
		})
	}
}

func Test_historyService_GetReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		taskHistory history.TaskHistory
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.GetReportTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportTask
		wantErr bool
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.GetReportTaskRequest{
					TaskId: "fakeId",
				},
			},
			want:    &fintech_data.ReportTask{TaskId: "fakeId"},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().GetTask(ctx, "fakeId").Return(&fintech_data.ReportTask{TaskId: "fakeId"}, nil).Times(1)
			s := &historyService{
				taskHistory: historyMock,
				nowTimeFunc: tt.fields.nowTimeFunc,
			}
			got, err := s.GetReportTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetReportTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetReportTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_LastReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		taskHistory history.TaskHistory
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.LastReportTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportTask
		wantErr bool
		query   []*monthly_collection_service.QueryItem
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.LastReportTaskRequest{
					Status:    strings.Join([]string{types.StatusSuccess, types.StatusPartialSuccess, types.StatusFail}, ","),
					Days:      10,
					ObjectId:  "HOST",
					HasReport: true,
				},
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusSuccess, types.StatusPartialSuccess, types.StatusFail}),
				},
				{
					Name:     "dataTotal",
					Operator: "ne",
					Value:    protostruct.ToValue(0),
				},
			},
			want:    &fintech_data.ReportTask{TaskId: "fakeId"},
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.LastReportTaskRequest{
					Status:   strings.Join([]string{types.StatusSuccess, types.StatusPartialSuccess, "!fail"}, ","),
					Days:     10,
					ObjectId: "HOST",
				},
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusSuccess, types.StatusPartialSuccess}),
				},
				{
					Name:     "status",
					Operator: "nin",
					Value:    protostruct.ToValue([]string{types.StatusFail}),
				},
			},
			want:    &fintech_data.ReportTask{TaskId: "fakeId"},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)

			historyMock.EXPECT().SearchOneTask(ctx, tt.query, nil, 1608908986, 1609772986).Return(&fintech_data.ReportTask{TaskId: "fakeId"}, nil).Times(1)
			s := &historyService{
				taskHistory: historyMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			got, err := s.LastReportTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("LastReportTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("LastReportTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_SearchReportBranch(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		taskHistory history.TaskHistory
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.SearchReportBranchRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.SearchReportBranchResponse
		wantErr bool

		searchErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportBranchRequest{
					Fields:   protostruct.ToStruct(map[string]interface{}{"taskId": 1}),
					St:       1608908786,
					Et:       1608908986,
					Page:     1,
					PageSize: 1,
					TaskId:   "fakeId",
					InnerId:  "innerId",
					Status:   "success",
				},
			},
			want: &message.SearchReportBranchResponse{
				List: []*fintech_data.ReportBranch{
					{
						TaskId: "fakeId",
					},
				},
				Total:    2,
				Page:     1,
				PageSize: 1,
			},
			wantErr: false,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportBranchRequest{
					Fields:   protostruct.ToStruct(map[string]interface{}{"taskId": 1}),
					St:       1608908786,
					Et:       1608908986,
					Page:     1,
					PageSize: 1,
					TaskId:   "fakeId",
					InnerId:  "innerId",
					Status:   "success",
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.request.TaskId),
				},
				{
					Name:     "innerId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.request.InnerId),
				},
				{
					Name:     "totalStatus",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusSuccess}),
				},
			}
			historyMock.EXPECT().SearchBranch(ctx, query, protostruct.DecodeToMap(tt.args.request.Fields), int(tt.args.request.St), 1608908986, int(tt.args.request.Page), int(tt.args.request.PageSize)).
				Return([]*fintech_data.ReportBranch{
					{
						TaskId: "fakeId",
					},
				}, 2, tt.searchErr).Times(1)
			s := &historyService{
				taskHistory: historyMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchReportBranch(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchReportBranch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchReportBranch() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_SearchReportInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		taskHistory history.TaskHistory
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.SearchReportInstanceRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.SearchReportInstanceResponse
		wantErr bool

		taskList      []*fintech_data.ReportTask
		searchTaskErr error

		query     []*monthly_collection_service.QueryItem
		searchErr error
	}{
		{
			name:   "search all task error",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:          nil,
					Status:          "fail",
					St:              1608908786,
					Page:            1,
					PageSize:        1,
					BranchId:        "fakeBranch",
					InnerBranchId:   "innerId",
					Search:          "aaa",
					ObjectId:        "fakeObjectId",
					MappingObjectId: "fakeMappingObjectId",
				},
			},
			searchTaskErr: errors.New("search all task error"),
			wantErr:       true,
		},

		{
			name:   "taskList len is equal 0",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:          nil,
					St:              1608908786,
					Page:            1,
					PageSize:        1,
					Search:          "aaa",
					ObjectId:        "fakeObjectId",
					MappingObjectId: "fakeMappingObjectId",
					ReportType:      "new",
					Status:          "fail",
				},
			},
			taskList: []*fintech_data.ReportTask{},
			want: &message.SearchReportInstanceResponse{
				Total:    0,
				Page:     1,
				PageSize: 1,
				List:     nil,
			},
		},

		{
			name:   "taskIdList len is more than 0",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:          nil,
					St:              1608908786,
					Page:            1,
					PageSize:        1,
					Search:          "aaa",
					ObjectId:        "fakeObjectId",
					MappingObjectId: "fakeMappingObjectId",
					ReportType:      "new",
					Status:          "fail",
				},
			},
			taskList: []*fintech_data.ReportTask{
				{
					TaskId: "taskId1",
				},
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "showKey",
					Operator: "regex",
					Value:    protostruct.ToValue("aaa"),
				},
				{
					Name:     "showKey",
					Operator: "options",
					Value:    protostruct.ToValue("$i"),
				},
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("fakeObjectId"),
				},
				{
					Name:     "reportType",
					Operator: "eq",
					Value:    protostruct.ToValue("new"),
				},
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.FailTypeReporting, types.FailTypeRequestCheck, types.FailTypeResult}),
				},
				{
					Name:     "taskId",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"taskId1"}),
				},
			},
			searchErr: errors.New("search instance error"),
			wantErr:   true,
		},

		{
			name:   "status is success",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:        nil,
					Status:        "success",
					St:            1608908786,
					Page:          1,
					PageSize:      1,
					TaskId:        "fakeId",
					BranchId:      "fakeBranch",
					InnerBranchId: "innerId",
					Username:      "admin",
					HandleStatus:  "success",
				},
			},
			want: &message.SearchReportInstanceResponse{
				List: []*fintech_data.ReportInstance{
					{
						TaskId: "fakeId",
					},
				},
				Total:    2,
				Page:     1,
				PageSize: 1,
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"success"}),
				},
				{
					Name:     "branchId",
					Operator: "eq",
					Value:    protostruct.ToValue("fakeBranch"),
				},
				{
					Name:     "creator",
					Operator: "eq",
					Value:    protostruct.ToValue("admin"),
				},
				{
					Name:     "handleStatus",
					Operator: "eq",
					Value:    protostruct.ToValue("success"),
				},
				{
					Name:     "innerBranchId",
					Operator: "eq",
					Value:    protostruct.ToValue("innerId"),
				},
				{
					Name:     "taskId",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"fakeId"}),
				},
			},
			searchErr: nil,
		},

		{
			name:   "status is nil",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:   nil,
					St:       1608908786,
					Page:     1,
					PageSize: 1,
					TaskId:   "fakeId",
				},
			},
			want: &message.SearchReportInstanceResponse{
				List: []*fintech_data.ReportInstance{
					{
						TaskId: "fakeId",
					},
				},
				Total:    2,
				Page:     1,
				PageSize: 1,
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"fakeId"}),
				},
			},
			searchErr: nil,
		},

		{
			name:   "status is running",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportInstanceRequest{
					Fields:   nil,
					St:       1608908786,
					Page:     1,
					PageSize: 1,
					TaskId:   "fakeId",
					Status:   "running",
				},
			},
			want: &message.SearchReportInstanceResponse{
				List: []*fintech_data.ReportInstance{
					{
						TaskId: "fakeId",
					},
				},
				Total:    2,
				Page:     1,
				PageSize: 1,
			},
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusPendingCheck, types.StatusResulting}),
				},
				{
					Name:     "taskId",
					Operator: "in",
					Value:    protostruct.ToValue([]string{"fakeId"}),
				},
			},
			searchErr: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			if tt.args.request.MappingObjectId != "" {
				var queryTask []*monthly_collection_service.QueryItem
				queryTask = append(queryTask, &monthly_collection_service.QueryItem{
					Name:     "mappingObjectId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.request.MappingObjectId),
				})
				historyMock.EXPECT().SearchAllTask(ctx, queryTask, map[string]interface{}{
					"_id": true,
				}, 10000, int(tt.args.request.St), 1609772986).Return(tt.taskList, tt.searchTaskErr).AnyTimes()
			}
			historyMock.EXPECT().SearchInstance(ctx, tt.query, protostruct.DecodeToMap(tt.args.request.Fields), int(tt.args.request.St), 1609772986, int(tt.args.request.Page), int(tt.args.request.PageSize)).
				Return([]*fintech_data.ReportInstance{
					{
						TaskId: "fakeId",
					},
				}, 2, tt.searchErr).AnyTimes()
			s := &historyService{
				taskHistory: historyMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchReportInstance(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchReportInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchReportInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_SearchReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		taskHistory history.TaskHistory
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.SearchReportTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.SearchReportTaskResponse
		wantErr bool

		query     []*monthly_collection_service.QueryItem
		searchErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       1609686586,
					Et:       0,
					Page:     1,
					PageSize: 1,
				},
			},
			want: &message.SearchReportTaskResponse{
				List: []*fintech_data.ReportTask{
					{
						TaskId:       "fakeId",
						DataTotal:    10,
						SuccessTotal: 5,
					},
				},
				Total:    2,
				Page:     1,
				PageSize: 1,
			},
			wantErr: false,
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
			},
			searchErr: nil,
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.SearchReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					Status:   types.StatusSuccess,
					St:       0,
					Et:       0,
					Page:     1,
					PageSize: 1,
				},
			},
			wantErr: true,
			query: []*monthly_collection_service.QueryItem{
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusSuccess}),
				},
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
			},
			searchErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchTask(ctx, tt.query, protostruct.DecodeToMap(tt.args.request.Fields), 1609686586, 1609772986, int(tt.args.request.Page), int(tt.args.request.PageSize)).
				Return([]*fintech_data.ReportTask{
					{
						TaskId:       "fakeId",
						DataTotal:    10,
						SuccessTotal: 5,
					},
				}, 2, tt.searchErr).Times(1)
			s := &historyService{
				taskHistory: historyMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchReportTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchReportTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchReportTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_parseQuery(t *testing.T) {
	type args struct {
		objectId        string
		mappingObjectId string
		status          string
		method          string
	}
	tests := []struct {
		name string
		args args
		want []*monthly_collection_service.QueryItem
	}{
		{
			name: "",
			args: args{
				objectId:        "server",
				mappingObjectId: "HOST",
				method:          string(types.TimerCreate),
				status:          types.StatusSuccess,
			},
			want: []*monthly_collection_service.QueryItem{
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue([]string{types.StatusSuccess}),
				},
				{
					Name:     "method",
					Operator: "eq",
					Value:    protostruct.ToValue(types.TimerCreate),
				},
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("server"),
				},
				{
					Name:     "mappingObjectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := parseQuery(tt.args.objectId, tt.args.mappingObjectId, tt.args.status, tt.args.method); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("parseQuery() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_GetReportInstanceTotal(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	type fields struct {
		taskHistory history.TaskHistory
		centerData  history.CenterData
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.GetReportInstanceTotalRequest
	}
	tests := []struct {
		name     string
		fields   fields
		args     args
		want     *message.GetReportInstanceTotalResponse
		wantErr  bool
		countErr error
	}{
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &message.GetReportInstanceTotalRequest{
					ObjectIds: "server,switch",
				},
			},
			wantErr: true,

			countErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &message.GetReportInstanceTotalRequest{
					ObjectIds: "server,switch",
				},
			},
			want: &message.GetReportInstanceTotalResponse{
				Total: 3,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerMock := history2.NewMockCenterData(ctrl)
			query := map[string]interface{}{
				"objectId": map[string]interface{}{
					"$in": []string{"server", "switch"},
				},
			}
			centerMock.EXPECT().Count(tt.args.ctx, query).Return(3, tt.countErr).Times(1)
			s := &historyService{
				taskHistory: tt.fields.taskHistory,
				centerData:  centerMock,
				nowTimeFunc: tt.fields.nowTimeFunc,
			}
			got, err := s.GetReportInstanceTotal(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetReportInstanceTotal() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetReportInstanceTotal() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_ExportReportTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		taskHistory history.TaskHistory
		centerData  history.CenterData
		nowTimeFunc func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.ExportReportTaskRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		searchErr  error
		objNameErr error
		headerErr  error
		rowErr     error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.ExportReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       1609686586,
					Et:       0,
				},
			},
			wantErr: false,
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.ExportReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       1609686586,
					Et:       0,
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "obj mapping",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.ExportReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       1609686586,
					Et:       0,
				},
			},
			objNameErr: fmt.Errorf("mock fail"),
			wantErr:    true,
		},
		{
			name:   "header fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.ExportReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       1609686586,
					Et:       0,
				},
			},
			headerErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "row fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.ExportReportTaskRequest{
					ObjectId: "HOST",
					Fields:   nil,
					St:       0,
					Et:       0,
				},
			},
			rowErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("HOST"),
				},
			}
			historyMock.EXPECT().SearchAllTask(ctx, query, protostruct.DecodeToMap(tt.args.request.Fields), 10000, 1609686586, 1609772986).
				Return([]*fintech_data.ReportTask{
					{
						TaskId:          "fakeId",
						ObjectId:        "HOST",
						MappingObjectId: "host",
						Sponsor:         "easyops",
						Status:          types.StatusPartialSuccess,
						Method:          "manual",
						StartTime:       "2021-06-21 23:12:21",
						BatchTotal:      1,
						DataTotal:       10,
						SuccessTotal:    2,
						Inserted:        2,
						SuccessRate:     0.2,
						BranchIds:       []string{"bbb"},
					},
					{
						TaskId:          "fakeId",
						ObjectId:        "HOST",
						MappingObjectId: "not-found",
						Sponsor:         "easyops",
						Status:          types.StatusPartialSuccess,
						Method:          "timer",
						StartTime:       "2021-06-21 22:12:21",
						BatchTotal:      1,
						DataTotal:       10,
						SuccessTotal:    2,
						Updated:         2,
						SuccessRate:     0.2,
						BranchIds:       []string{"ggg"},
					},
				}, tt.searchErr).Times(1)

			objClient := cmdb.NewMockObjectClient(ctrl)
			objClient.EXPECT().GetIdMapName(ctx, gomock.Any()).Return(
				protostruct.ToStruct(map[string]interface{}{
					"HOST": "主机",
					"host": "映射主机",
				}), tt.objNameErr).MaxTimes(1)

			excelMock := excelutil2.NewMockExporter(ctrl)
			excelMock.EXPECT().WriteExcelHeader(getTaskExcelHeader()).Return(tt.headerErr).MaxTimes(1)
			value := map[string]interface{}{
				"time":              "2021-06-21 23:12:21",
				"objectName":        "主机",
				"mappingObjectName": "映射主机",
				"total":             int32(10),
				"successTotal":      int32(2),
				"inserted":          int32(2),
				"updated":           int32(0),
				"removed":           int32(0),
				"successRate":       "20%",
				"batchTotal":        int32(1),
				"branchIds":         "bbb",
				"trigger":           "手动执行",
				"execUser":          "easyops",
				"status":            "部分成功",
			}
			excelMock.EXPECT().WriteRow(value).Return(nil).MaxTimes(1)
			value2 := map[string]interface{}{
				"time":              "2021-06-21 22:12:21",
				"objectName":        "主机",
				"mappingObjectName": "已删除模型",
				"total":             int32(10),
				"successTotal":      int32(2),
				"inserted":          int32(0),
				"updated":           int32(2),
				"removed":           int32(0),
				"successRate":       "20%",
				"batchTotal":        int32(1),
				"branchIds":         "ggg",
				"trigger":           "定时执行",
				"execUser":          "easyops",
				"status":            "部分成功",
			}
			excelMock.EXPECT().WriteRow(value2).Return(tt.rowErr).MaxTimes(1)
			s := &historyService{
				taskHistory: historyMock,
				objClient:   objClient,
				newExcelExporter: func(filename string) excelutil.Exporter {
					return excelMock
				},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			_, err := s.ExportReportTask(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ExportReportTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}

func Test_parseInstanceQuery(t *testing.T) {
	type args struct {
		search     string
		objectId   string
		reportType string
		status     string
	}
	tests := []struct {
		name string
		args args
		want []*monthly_collection_service.QueryItem
	}{
		{
			name: "normal",
			args: args{
				search:     "xxx",
				objectId:   "obj",
				reportType: "new",
				status:     "fail",
			},
			want: []*monthly_collection_service.QueryItem{
				{
					Name:     "showKey",
					Operator: "regex",
					Value:    protostruct.ToValue("xxx"),
				},
				{
					Name:     "showKey",
					Operator: "options",
					Value:    protostruct.ToValue("$i"),
				},
				{
					Name:     "objectId",
					Operator: "eq",
					Value:    protostruct.ToValue("obj"),
				},
				{
					Name:     "reportType",
					Operator: "eq",
					Value:    protostruct.ToValue("new"),
				},
				{
					Name:     "status",
					Operator: "in",
					Value:    protostruct.ToValue(getStatus("fail")),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := parseInstanceQuery(tt.args.search, tt.args.objectId, tt.args.reportType, tt.args.status); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("parseInstanceQuery() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_ExportReportInstance(t *testing.T) {
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	mockNowTimeFunc := func() time.Time {
		t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
		return t
	}
	mockErr := fmt.Errorf("mock failed")
	req := &message.ExportReportInstanceRequest{
		MappingObjectId: "mappingObj1",
	}
	anotherReq := &message.ExportReportInstanceRequest{
		St:              1,
		MappingObjectId: "mappingObj1",
	}
	queryTask := []*monthly_collection_service.QueryItem{
		{
			Name:     "mappingObjectId",
			Operator: "eq",
			Value:    protostruct.ToValue("mappingObj1"),
		},
	}
	taskList := []*fintech_data.ReportTask{
		{
			TaskId: "t1",
		},
	}
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "in",
			Value:    protostruct.ToValue([]string{"t1"}),
		},
	}
	instanceList := []*fintech_data.ReportInstance{
		{
			ObjectId:        "obj1",
			MappingObjectId: "mappingObj1",
		},
		{
			ObjectId:        "obj2",
			MappingObjectId: "mappingObj2",
		},
	}
	objIdName := protostruct.ToStruct(map[string]interface{}{
		"obj1":        "obj1的名字",
		"mappingObj1": "mappingObj1的名字",
	})
	value1 := map[string]interface{}{
		"showKey":            "",
		"objectName":         "obj1的名字",
		"mappingObjectName":  "mappingObj1的名字",
		"facilityCategory":   "",
		"facilityDescriptor": "",
		"reportType":         "",
		"status":             "",
		"msg":                "",
	}
	value2 := map[string]interface{}{
		"showKey":            "",
		"objectName":         "",
		"mappingObjectName":  "已删除模型",
		"facilityCategory":   "",
		"facilityDescriptor": "",
		"reportType":         "",
		"status":             "",
		"msg":                "",
	}
	type fields struct {
		taskHistory      history.TaskHistory
		centerData       history.CenterData
		objClient        cmdb_object.Client
		newExcelExporter excelutil.NewExporterFunc
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.ExportReportInstanceRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		mockNewExcelExporter func(ctrl *gomock.Controller) excelutil.Exporter
		mockTaskHistory      func(ctrl *gomock.Controller) history.TaskHistory
		mockObjClient        func(ctrl *gomock.Controller) cmdb_object.Client
	}{
		{
			name:    "newExcelExporter failed",
			wantErr: true,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(mockErr).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				return nil
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				return nil
			},
		},
		{
			name:    "GetTaskIdList failed",
			wantErr: true,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(nil, mockErr).
					Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				return nil
			},
		},
		{
			name: "GetTaskIdList returns empty list",
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(nil, nil).
					Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				return nil
			},
		},
		{
			name:    "SearchInstanceAll failed",
			wantErr: true,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000, int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(nil, mockErr).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				return nil
			},
		},
		{
			name:    "GetIdMapName failed",
			wantErr: true,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(nil, nil).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(nil, mockErr).Times(1)
				return client
			},
		},
		{
			name:    "WriteRow failed",
			wantErr: true,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value1).Return(mockErr).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000, int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(instanceList, nil).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(objIdName, nil).Times(1)
				return client
			},
		},
		{
			name: "normal",
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value1).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value2).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(instanceList, nil).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(objIdName, nil).Times(1)
				return client
			},
		},
		{
			name: "normal with another request",
			args: args{
				request: anotherReq,
			},
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value1).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value2).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000, 1, int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000, 1, int(mockNowTimeFunc().Unix())).
					Return(instanceList, nil).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(objIdName, nil).Times(1)
				return client
			},
		},
		{
			name: "request with dataId and username",
			args: args{
				request: &message.ExportReportInstanceRequest{
					MappingObjectId: "mappingObj1",
					DataId:          []string{"data1", "data2"},
					Username:        "testUser",
				},
			},
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value1).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(value2).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, append([]*monthly_collection_service.QueryItem{
						&monthly_collection_service.QueryItem{
							Name:     "_id",
							Operator: "in",
							Value:    protostruct.ToValue([]string{"data1", "data2"}),
						},
						&monthly_collection_service.QueryItem{
							Name:     "creator",
							Operator: "eq",
							Value:    protostruct.ToValue("testUser"),
						},
					}, query...), nil, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return(instanceList, nil).Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(objIdName, nil).Times(1)
				return client
			},
		},
		{
			name: "empty task list for MappingObjectId",
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				exporter.EXPECT().WriteExcelHeader(getInstanceExcelHeader(false)).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000,
						int(mockNowTimeFunc().Unix()-24*3600), int(mockNowTimeFunc().Unix())).
					Return([]*fintech_data.ReportTask{}, nil).
					Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				return nil
			},
			args: args{
				request: &message.ExportReportInstanceRequest{
					MappingObjectId: "mappingObj1",
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			s := &historyService{
				taskHistory: tt.mockTaskHistory(ctrl),
				centerData:  tt.fields.centerData,
				objClient:   tt.mockObjClient(ctrl),
				newExcelExporter: func(filename string) excelutil.Exporter {
					return tt.mockNewExcelExporter(ctrl)
				},
				nowTimeFunc: mockNowTimeFunc,
			}
			if tt.args.request == nil {
				tt.args.request = req
			}
			_, err := s.ExportReportInstance(ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ExportReportInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}

func Test_historyService_ExportReportInstance_HandlePendingStatus(t *testing.T) {
	ctrl := gomock.NewController(t)
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	mockNowTimeFunc := func() time.Time {
		t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
		return t
	}
	handleStatusReq := &message.ExportReportInstanceRequest{
		HandleStatus:    "pending",
		MappingObjectId: "mappingObj1",
	}
	queryTask := []*monthly_collection_service.QueryItem{
		{
			Name:     "mappingObjectId",
			Operator: "eq",
			Value:    protostruct.ToValue("mappingObj1"),
		},
	}
	taskList := []*fintech_data.ReportTask{
		{
			TaskId: "t1",
		},
	}
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "handleStatus",
			Operator: "eq",
			Value:    protostruct.ToValue("pending"),
		},
		{
			Name:     "taskId",
			Operator: "in",
			Value:    protostruct.ToValue([]string{"t1"}),
		},
	}
	instanceList := []*fintech_data.ReportInstance{
		{
			ObjectId:        "obj1",
			MappingObjectId: "mappingObj1",
			Creator:         "creator1",
			ReportType:      "new",
			HandleTime:      1610000000,
		},
	}
	objIdName := protostruct.ToStruct(map[string]interface{}{
		"obj1":        "obj1的名字",
		"mappingObj1": "mappingObj1的名字",
	})
	type fields struct {
		taskHistory      history.TaskHistory
		centerData       history.CenterData
		objClient        cmdb_object.Client
		newExcelExporter excelutil.NewExporterFunc
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *message.ExportReportInstanceRequest
	}

	tests := []struct {
		name                 string
		fields               fields
		args                 args
		wantErr              bool
		mockNewExcelExporter func(ctrl *gomock.Controller) excelutil.Exporter
		mockTaskHistory      func(ctrl *gomock.Controller) history.TaskHistory
		mockObjClient        func(ctrl *gomock.Controller) cmdb_object.Client
	}{
		{
			name: "normal with HandleStatus",
			args: args{
				request: handleStatusReq,
			},
			wantErr: false,
			mockNewExcelExporter: func(ctrl *gomock.Controller) excelutil.Exporter {
				exporter := excelutil2.NewMockExporter(ctrl)
				expectedHeaders := getInstanceExcelHeader(true)
				exporter.EXPECT().WriteExcelHeader(expectedHeaders).Return(nil).Times(1)
				exporter.EXPECT().WriteRow(gomock.Any()).Return(nil).Times(1)
				return exporter
			},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				taskHistory := history2.NewMockTaskHistory(ctrl)
				et := int(mockNowTimeFunc().Unix())
				st := et - 86400
				taskHistory.EXPECT().
					SearchAllTask(ctx, queryTask, map[string]interface{}{"_id": true}, 10000, st, et).
					Return(taskList, nil).
					Times(1)
				taskHistory.EXPECT().
					SearchInstanceAll(ctx, query, nil, 10000, st, et).
					Return(instanceList, nil).
					Times(1)
				return taskHistory
			},
			mockObjClient: func(ctrl *gomock.Controller) cmdb_object.Client {
				client := cmdb.NewMockObjectClient(ctrl)
				client.EXPECT().
					GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{}).
					Return(objIdName, nil).
					Times(1)
				return client
			},

			fields: fields{
				centerData: history2.NewMockCenterData(ctrl),
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()

			mockTaskHistory := tt.mockTaskHistory(ctrl)
			mockObjClient := tt.mockObjClient(ctrl)
			mockExcelExporter := tt.mockNewExcelExporter(ctrl)
			var mockCenterData history.CenterData
			if tt.fields.centerData != nil {
				mockCenterData = tt.fields.centerData
			} else {
				mockCenterData = nil
			}

			s := &historyService{
				taskHistory:      mockTaskHistory,
				centerData:       mockCenterData,
				objClient:        mockObjClient,
				newExcelExporter: func(filename string) excelutil.Exporter { return mockExcelExporter },
				nowTimeFunc:      mockNowTimeFunc,
			}
			if tt.args.request == nil {
				tt.args.request = handleStatusReq
			}
			_, err := s.ExportReportInstance(ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ExportReportInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
		})
	}
}

func Test_historyService_GetTaskIdList(t *testing.T) {
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	mockNowTimeFunc := func() time.Time {
		t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
		return t
	}
	mockErr := fmt.Errorf("mock failed")
	type fields struct {
		taskHistory      history.TaskHistory
		centerData       history.CenterData
		objClient        cmdb_object.Client
		newExcelExporter excelutil.NewExporterFunc
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx             context.Context
		mappingObjectId string
		st              int
		et              int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []string
		wantErr bool

		mockTaskHistory func(ctrl *gomock.Controller) history.TaskHistory
	}{
		{
			name:    "SearchAllTask failed",
			wantErr: true,
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				queryTask := []*monthly_collection_service.QueryItem{
					{
						Name:     "mappingObjectId",
						Operator: "eq",
						Value:    protostruct.ToValue(""),
					},
				}
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().SearchAllTask(ctx, queryTask, map[string]interface{}{
					"_id": true,
				}, 10000, 0, 0).Return(nil, mockErr).Times(1)
				return taskHistory
			},
		},
		{
			name: "dataList is empty",
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				queryTask := []*monthly_collection_service.QueryItem{
					{
						Name:     "mappingObjectId",
						Operator: "eq",
						Value:    protostruct.ToValue(""),
					},
				}
				taskHistory := history2.NewMockTaskHistory(ctrl)
				taskHistory.EXPECT().SearchAllTask(ctx, queryTask, map[string]interface{}{
					"_id": true,
				}, 10000, 0, 0).Return(nil, nil).Times(1)
				return taskHistory
			},
		},
		{
			name: "normal",
			want: []string{"mockTaskId1"},
			mockTaskHistory: func(ctrl *gomock.Controller) history.TaskHistory {
				queryTask := []*monthly_collection_service.QueryItem{
					{
						Name:     "mappingObjectId",
						Operator: "eq",
						Value:    protostruct.ToValue(""),
					},
				}
				taskHistory := history2.NewMockTaskHistory(ctrl)
				dataList := []*fintech_data.ReportTask{
					{
						TaskId: "mockTaskId1",
					},
				}
				taskHistory.EXPECT().SearchAllTask(ctx, queryTask, map[string]interface{}{
					"_id": true,
				}, 10000, 0, 0).Return(dataList, nil).Times(1)
				return taskHistory
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			s := &historyService{
				taskHistory:      tt.mockTaskHistory(ctrl),
				centerData:       tt.fields.centerData,
				objClient:        tt.fields.objClient,
				newExcelExporter: tt.fields.newExcelExporter,
				nowTimeFunc:      mockNowTimeFunc,
			}
			got, err := s.GetTaskIdList(ctx, tt.args.mappingObjectId, tt.args.st, tt.args.et)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetTaskIdList() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetTaskIdList() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_HandleReportInstance(t *testing.T) {
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	fixedNow := time.Now().Unix()
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	tests := []struct {
		name             string
		request          *message.HandlReportInstanceRequest
		mockTaskHistory  func(mockTH *history2.MockTaskHistory)
		wantErr          bool
		expectedLogError string
	}{
		{
			name: "UpdateInstanceByFilter succeeds with DataId and no Et/St",
			request: &message.HandlReportInstanceRequest{
				DataId: []string{"12345"},
				Et:     0,
				St:     0,
			},
			mockTaskHistory: func(mockTH *history2.MockTaskHistory) {
				currentUnix := int(fixedNow)
				expectedEt := currentUnix
				expectedSt := expectedEt - 86400
				updateData := &fintech_data.ReportInstance{
					HandleStatus: report_center.HandleStatusProcessed,
					HandleTime:   int32(fixedNow),
				}
				updateFields := []string{"handleStatus", "handleTime"}
				expectedDataId := []string{"12345"}
				instanceQuery := []*monthly_collection_service.QueryItem{
					{
						Name:     "_id",
						Operator: "in",
						Value:    protostruct.ToValue(expectedDataId),
					},
				}

				mockTH.EXPECT().UpdateInstanceByFilter(
					gomock.Any(),
					gomock.Eq(instanceQuery),
					gomock.Eq(updateData),
					gomock.Eq(updateFields),
					expectedSt,
					expectedEt,
				).Return(nil)
			},
			wantErr: false,
		},
		{
			name: "UpdateInstanceByFilter fails",
			request: &message.HandlReportInstanceRequest{
				DataId: []string{"12345"},
				Et:     0,
				St:     0,
			},
			mockTaskHistory: func(mockTH *history2.MockTaskHistory) {
				currentUnix := int(fixedNow)
				expectedEt := currentUnix
				expectedSt := expectedEt - 86400
				updateData := &fintech_data.ReportInstance{
					HandleStatus: report_center.HandleStatusProcessed,
					HandleTime:   int32(fixedNow),
				}
				updateFields := []string{"handleStatus", "handleTime"}
				expectedDataId := []string{"12345"}
				instanceQuery := []*monthly_collection_service.QueryItem{
					{
						Name:     "_id",
						Operator: "in",
						Value:    protostruct.ToValue(expectedDataId),
					},
				}

				mockTH.EXPECT().UpdateInstanceByFilter(
					gomock.Any(),
					gomock.Eq(instanceQuery),
					gomock.Eq(updateData),
					gomock.Eq(updateFields),
					expectedSt,
					expectedEt,
				).Return(fmt.Errorf("mock update error"))
			},
			wantErr:          true,
			expectedLogError: "update instance handle status fail, error: mock update error",
		},
		{
			name: "No DataId provided",
			request: &message.HandlReportInstanceRequest{
				DataId: []string{},
				Et:     0,
				St:     0,
			},
			mockTaskHistory: func(mockTH *history2.MockTaskHistory) {

			},
			wantErr: false,
		},
		{
			name: "DataId provided with Et and St set",
			request: &message.HandlReportInstanceRequest{
				DataId: []string{"67890"},
				Et:     1700001000,
				St:     1700000000,
			},
			mockTaskHistory: func(mockTH *history2.MockTaskHistory) {
				expectedEt := 1700001000
				expectedSt := 1700000000
				updateData := &fintech_data.ReportInstance{
					HandleStatus: report_center.HandleStatusProcessed,
					HandleTime:   int32(fixedNow),
				}
				updateFields := []string{"handleStatus", "handleTime"}
				expectedDataId := []string{"67890"}
				instanceQuery := []*monthly_collection_service.QueryItem{
					{
						Name:     "_id",
						Operator: "in",
						Value:    protostruct.ToValue(expectedDataId),
					},
				}

				mockTH.EXPECT().UpdateInstanceByFilter(
					gomock.Any(),
					gomock.Eq(instanceQuery),
					gomock.Eq(updateData),
					gomock.Eq(updateFields),
					expectedSt,
					expectedEt,
				).Return(nil)
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockCtrl := gomock.NewController(t)
			defer mockCtrl.Finish()

			mockTH := history2.NewMockTaskHistory(mockCtrl)
			tt.mockTaskHistory(mockTH)

			s := &historyService{
				taskHistory: mockTH,
			}

			err := s.HandleReportInstance(ctx, tt.request)

			if tt.wantErr {
				assert.Error(t, err)
				if tt.expectedLogError != "" {
				}
			} else {
				assert.NoError(t, err)
			}
		})
	}
}
