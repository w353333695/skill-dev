package history

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	monthly_collection_service "go.easyops.local/contracts/protorepo-monthly_collection_service"
	"go.easyops.local/contracts/protorepo-monthly_collection_service/document"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/mock/remote/monthly"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewTaskHistory(t *testing.T) {
	type args struct {
		monthlyClient *monthly_collection_service.Client
	}
	tests := []struct {
		name string
		args args
		want TaskHistory
	}{
		{
			name: "",
			args: args{
				monthlyClient: nil,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewTaskHistory(tt.args.monthlyClient)
		})
	}
}

func Test_historyService_CreateTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
	}
	type args struct {
		ctx  context.Context
		task *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    string
		wantErr bool

		createErr error
	}{
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				task: &fintech_data.ReportTask{
					ObjectId: "server",
				},
			},
			want:    "fakeId",
			wantErr: false,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				task: &fintech_data.ReportTask{
					ObjectId: "server",
				},
			},
			createErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Create(tt.args.ctx, &document.CreateRequest{
				CollectionName: collNameTask,
				Timestamp:      int32(1575472186),
				Document:       taskToData(tt.args.task),
			}).Return(&document.CreateResponse{Id: "fakeId"}, tt.createErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			taskId, err := s.CreateTask(tt.args.ctx, tt.args.task)
			if (err != nil) != tt.wantErr {
				t.Errorf("CreateTask() error = %v, wantErr %v", err, tt.wantErr)
			}
			if taskId != tt.want {
				t.Errorf("CreateTask() taskId = %v, want %v", err, tt.want)
			}
		})
	}
}

func Test_historyService_SearchOneTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		monthlyClient *monthly_collection_service.Client
	}
	type args struct {
		ctx    context.Context
		query  []*monthly_model.QueryItem
		fields map[string]interface{}
		st     int
		et     int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportTask
		wantErr bool

		limitResp *document.LimitResponse
		limitErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  []*monthly_model.QueryItem{},
				fields: map[string]interface{}{"taskId": true},
				st:     0,
				et:     0,
			},
			want:    &fintech_data.ReportTask{TaskId: "haha"},
			wantErr: false,

			limitResp: &document.LimitResponse{List: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{"_id": "haha"}),
			}},
		},
		{
			name:   "data empty",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  []*monthly_model.QueryItem{},
				fields: map[string]interface{}{"taskId": true},
				st:     0,
				et:     0,
			},
			want:      nil,
			wantErr:   false,
			limitResp: &document.LimitResponse{List: nil},
		},
		{
			name:   "resp fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  []*monthly_model.QueryItem{},
				fields: map[string]interface{}{"taskId": true},
				st:     0,
				et:     0,
			},
			want:     nil,
			wantErr:  true,
			limitErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "convert fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  []*monthly_model.QueryItem{},
				fields: map[string]interface{}{"objectId": true},
				st:     0,
				et:     0,
			},
			wantErr: true,

			limitResp: &document.LimitResponse{List: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{"objectId": []string{"haha"}}),
			}},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Limit(tt.args.ctx, &document.LimitRequest{
				CollectionName: collNameTask,
				Fields:         protostruct.ToStruct(tt.args.fields),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
				Limit:          1,
			}).Return(tt.limitResp, tt.limitErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchOneTask(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.st, tt.args.et)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchOneTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchOneTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_SearchTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx      context.Context
		query    []*monthly_model.QueryItem
		fields   map[string]interface{}
		st       int
		et       int
		page     int
		pageSize int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportTask
		want1   int
		wantErr bool

		searchResp *document.SearchResponse
		searchErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "name",
						Operator: "eq",
						Value:    protostruct.ToValue("one"),
					},
				},
				fields:   nil,
				st:       0,
				et:       0,
				page:     1,
				pageSize: 10,
			},
			want: []*fintech_data.ReportTask{
				{
					TaskId:   "fakeId",
					ObjectId: "HOST",
				},
			},
			want1:   10,
			wantErr: false,

			searchResp: &document.SearchResponse{
				Total: 10,
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"objectId": "HOST",
						"_id":      "fakeId",
					}),
				},
			},
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "name",
						Operator: "eq",
						Value:    protostruct.ToValue("one"),
					},
				},
				fields:   nil,
				st:       0,
				et:       0,
				page:     1,
				pageSize: 10,
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "convert fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "name",
						Operator: "eq",
						Value:    protostruct.ToValue("one"),
					},
				},
				fields:   nil,
				st:       0,
				et:       0,
				page:     1,
				pageSize: 10,
			},
			searchResp: &document.SearchResponse{
				Total: 10,
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"objectId": []string{"HOST"},
						"_id":      "fakeId",
					}),
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Search(ctx, &document.SearchRequest{
				CollectionName: collNameTask,
				Page:           int32(tt.args.page),
				PageSize:       int32(tt.args.pageSize),
				Fields:         protostruct.ToStruct(tt.args.fields),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
			}).Return(tt.searchResp, tt.searchErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			got, got1, err := s.SearchTask(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.st, tt.args.et, tt.args.page, tt.args.pageSize)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchTask() got = %v, want %v", got, tt.want)
			}
			if got1 != tt.want1 {
				t.Errorf("SearchTask() got1 = %v, want %v", got1, tt.want1)
			}
		})
	}
}

func Test_historyService_GetTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx    context.Context
		taskId string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportTask
		wantErr bool

		taskData *types.Struct
		getErr   error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:    ctx,
				taskId: "fakeId",
			},
			want: &fintech_data.ReportTask{
				TaskId:       "fakeId",
				ObjectId:     "HOST",
				SuccessTotal: 2,
				DataTotal:    7,
				SuccessRate:  float32(2) / float32(7),
			},
			wantErr: false,
			taskData: protostruct.ToStruct(map[string]interface{}{
				"objectId":     "HOST",
				"_id":          "fakeId",
				"successTotal": 2,
				"dataTotal":    7,
			}),
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				taskId: "fakeId",
			},
			wantErr: true,
			getErr:  fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().GET(ctx, &document.GETRequest{
				Id:             tt.args.taskId,
				CollectionName: collNameTask,
			}).Return(tt.taskData, tt.getErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			got, err := s.GetTask(tt.args.ctx, tt.args.taskId)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_UpdateTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx    context.Context
		taskId string
		task   *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:    ctx,
				taskId: "fakeId",
				task: &fintech_data.ReportTask{
					ObjectId: "HOST",
				},
			},
			wantErr:   false,
			updateErr: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Update(ctx, &document.UpdateRequest{
				CollectionName: collNameTask,
				Id:             tt.args.taskId,
				Update:         taskToData(tt.args.task),
			}).Return(nil, tt.updateErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			if err := s.UpdateTask(tt.args.ctx, tt.args.taskId, tt.args.task); (err != nil) != tt.wantErr {
				t.Errorf("UpdateTask() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_historyService_SearchAllTask(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx    context.Context
		query  []*monthly_model.QueryItem
		fields map[string]interface{}
		st     int
		et     int
		limit  int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportTask
		wantErr bool

		limitResp *document.LimitResponse
		limitErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  nil,
				fields: map[string]interface{}{"name": "one"},
				st:     1400000,
				et:     0,
				limit:  50,
			},
			want: []*fintech_data.ReportTask{
				{
					TaskId:   "fakeId",
					ObjectId: "HOST",
				},
			},
			wantErr: false,
			limitResp: &document.LimitResponse{List: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{
					"objectId": "HOST",
					"_id":      "fakeId",
				}),
			}},
			limitErr: nil,
		},
		{
			name:   "convert fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  nil,
				fields: map[string]interface{}{"name": "one"},
				st:     1400000,
				et:     0,
				limit:  50,
			},
			wantErr: true,
			limitResp: &document.LimitResponse{List: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{
					"objectId": []string{"HOST"},
					"_id":      "fakeId",
				}),
			}},
			limitErr: nil,
		},
		{
			name:   "request fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				query:  nil,
				fields: map[string]interface{}{"name": "one"},
				st:     1400000,
				et:     0,
				limit:  50,
			},
			wantErr:  true,
			limitErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Limit(tt.args.ctx, &document.LimitRequest{
				CollectionName: collNameTask,
				Fields:         protostruct.ToStruct(tt.args.fields),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
				Limit:          int32(tt.args.limit),
			}).Return(tt.limitResp, tt.limitErr).Times(1)

			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchAllTask(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.limit, tt.args.st, tt.args.et)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchAllTask() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchAllTask() got = %v, want %v", got, tt.want)
			}
		})
	}
}
