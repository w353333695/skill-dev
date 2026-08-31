package history

import (
	"context"
	"errors"
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

func Test_historyService_SearchInstanceAll(t *testing.T) {
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
		limit  int
		st     int
		et     int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		wantErr bool

		limitResp *document.LimitResponse
		limitErr  error

		ids         []string
		findIdsResp *document.FindIDsResponse
		findIdError error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				fields: nil,
			},
			want: []*fintech_data.ReportInstance{
				{
					DataId:          "dataId",
					ObjectId:        "server",
					TaskId:          "fakeId",
					MappingObjectId: "fakeMappingObjectId",
				},
			},
			wantErr: false,
			limitResp: &document.LimitResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":      "dataId",
						"objectId": "server",
						"taskId":   "fakeId",
					}),
				},
				HaveMore: false,
				NextId:   "",
			},
			ids: []string{"fakeId"},
			findIdsResp: &document.FindIDsResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":             "fakeId",
						"mappingObjectId": "fakeMappingObjectId",
					}),
				},
			},
		},
		{
			name:   "convert fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				fields: nil,
			},
			wantErr: true,
			limitResp: &document.LimitResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":      "dataId",
						"objectId": []string{"server", "server"},
						"taskId":   "fakeId",
					}),
				},
				HaveMore: false,
				NextId:   "",
			},
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				fields: nil,
			},
			wantErr:  true,
			limitErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Limit(tt.args.ctx, &document.LimitRequest{
				CollectionName: collNameInstance,
				Fields:         protostruct.ToStruct(tt.args.fields),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
				Limit:          int32(tt.args.limit),
			}).Return(tt.limitResp, tt.limitErr).Times(1)
			docMock.EXPECT().FindIDs(ctx, &document.FindIDsRequest{
				CollectionName: collNameTask,
				Ids:            tt.ids,
			}).Return(tt.findIdsResp, tt.findIdError).AnyTimes()
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.SearchInstanceAll(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.limit, tt.args.st, tt.args.et)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchInstanceAll() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchInstanceAll() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_SearchInstance(t *testing.T) {
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
		want    []*fintech_data.ReportInstance
		want1   int
		wantErr bool

		searchResp *document.SearchResponse
		searchErr  error

		ids         []string
		findIdsResp *document.FindIDsResponse
		findIdError error
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
			want: []*fintech_data.ReportInstance{
				{
					DataId:          "dataId",
					TaskId:          "fakeId",
					ObjectId:        "HOST",
					MappingObjectId: "TEST",
				},
			},
			want1:   10,
			wantErr: false,

			searchResp: &document.SearchResponse{
				Total: 10,
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":      "dataId",
						"objectId": "HOST",
						"taskId":   "fakeId",
					}),
				},
			},
			ids: []string{
				"fakeId",
			},
			findIdsResp: &document.FindIDsResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":             "fakeId",
						"mappingObjectId": "TEST",
					}),
				},
			},
			findIdError: nil,
		},
		{
			name:   "find ids fail",
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
			want:    nil,
			want1:   0,
			wantErr: true,

			searchResp: &document.SearchResponse{
				Total: 10,
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id":      "dataId",
						"objectId": "HOST",
						"taskId":   "fakeId",
					}),
				},
			},
			ids: []string{
				"fakeId",
			},
			findIdsResp: nil,
			findIdError: errors.New(""),
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
						"_id":      "dataId",
						"objectId": []string{"HOST"},
						"taskId":   "fakeId",
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
				CollectionName: collNameInstance,
				Page:           int32(tt.args.page),
				PageSize:       int32(tt.args.pageSize),
				Fields:         protostruct.ToStruct(tt.args.fields),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
			}).Return(tt.searchResp, tt.searchErr).Times(1)
			docMock.EXPECT().FindIDs(ctx, &document.FindIDsRequest{
				CollectionName: collNameTask,
				Ids:            tt.ids,
			}).Return(tt.findIdsResp, tt.findIdError).AnyTimes()
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			got, got1, err := s.SearchInstance(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.st, tt.args.et, tt.args.page, tt.args.pageSize)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchInstance() got = %v, want %v", got, tt.want)
			}
			if got1 != tt.want1 {
				t.Errorf("SearchInstance() got1 = %v, want %v", got1, tt.want1)
			}
		})
	}
}

func Test_historyService_BatchCreateInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx        context.Context
		branchList []*fintech_data.ReportInstance
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []string
		wantErr bool

		createErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				branchList: []*fintech_data.ReportInstance{
					{
						ObjectId: "server",
					},
				},
			},
			want:    []string{"fakeId"},
			wantErr: false,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				branchList: []*fintech_data.ReportInstance{
					{
						ObjectId: "server",
					},
				},
			},
			createErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().BatchCreate(ctx, &document.BatchCreateRequest{
				CollectionName: collNameInstance,
				Timestamp:      int32(1575472186),
				Documents: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":         "",
						"taskId":             "",
						"innerBranchId":      "",
						"branchId":           "",
						"reportType":         "",
						"objectId":           "server",
						"version":            0,
						"isFail":             false,
						"status":             "",
						"code":               "",
						"msg":                "",
						"retryable":          false,
						"retryTimes":         0,
						"facilityCategory":   "",
						"facilityDescriptor": "",
						"showKey":            "",
						"data":               nil,
						"ts":                 0,
						"mappingObjectId":    "",
						"creator":            "",
						"handleStatus":       "",
						"handleTime":         0,
					}),
				},
			}).Return(&document.BatchCreateResponse{Ids: []string{"fakeId"}}, tt.createErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.BatchCreateInstance(tt.args.ctx, tt.args.branchList)
			if (err != nil) != tt.wantErr {
				t.Errorf("BatchCreateInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("BatchCreateInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_UpdateInstanceByFilter(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx          context.Context
		query        []*monthly_model.QueryItem
		instance     *fintech_data.ReportInstance
		updateFields []string
		st           int
		et           int
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		limitResp *document.LimitResponse
		limitErr  error

		updateErr error

		ids         []string
		findIdsResp *document.FindIDsResponse
		findIdError error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				instance:     &fintech_data.ReportInstance{BranchId: "branchId1"},
				updateFields: []string{"branchId"},
			},
			wantErr: false,
			limitResp: &document.LimitResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id": "dataId",
					}),
				},
				HaveMore: false,
				NextId:   "",
			},
			ids:         []string{""},
			findIdsResp: &document.FindIDsResponse{},
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				instance:     &fintech_data.ReportInstance{BranchId: "branchId1"},
				updateFields: []string{"branchId"},
			},
			wantErr:   true,
			updateErr: fmt.Errorf("mock fail"),
			limitResp: &document.LimitResponse{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"_id": "dataId",
					}),
				},
				HaveMore: false,
				NextId:   "",
			},
			ids:         []string{""},
			findIdsResp: &document.FindIDsResponse{},
		},
		{
			name:   "limit fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: []*monthly_model.QueryItem{
					{
						Name:     "objectId",
						Operator: "eq",
						Value:    protostruct.ToValue("HOST"),
					},
				},
				instance:     &fintech_data.ReportInstance{BranchId: "branchId1"},
				updateFields: []string{"branchId"},
			},
			wantErr:  true,
			limitErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Limit(tt.args.ctx, &document.LimitRequest{
				CollectionName: collNameInstance,
				Fields:         protostruct.ToStruct(map[string]interface{}{"_id": true}),
				Query:          tt.args.query,
				StartTime:      int32(tt.args.st),
				EndTime:        int32(tt.args.et),
				Limit:          50,
			}).Return(tt.limitResp, tt.limitErr).Times(1)

			docMock.EXPECT().Update(tt.args.ctx, &document.UpdateRequest{
				CollectionName: collNameInstance,
				Id:             "dataId",
				Update:         protostruct.ToStruct(map[string]interface{}{"branchId": "branchId1"}),
			}).Return(nil, tt.updateErr).MaxTimes(1)
			docMock.EXPECT().FindIDs(ctx, &document.FindIDsRequest{
				CollectionName: collNameTask,
				Ids:            tt.ids,
			}).Return(tt.findIdsResp, tt.findIdError).AnyTimes()
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			if err := s.UpdateInstanceByFilter(tt.args.ctx, tt.args.query, tt.args.instance, tt.args.updateFields, tt.args.st, tt.args.et); (err != nil) != tt.wantErr {
				t.Errorf("UpdateInstanceByFilter() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_historyService_UpdateInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx          context.Context
		dataId       string
		instance     *fintech_data.ReportInstance
		updateFields []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:          ctx,
				dataId:       "dataId",
				instance:     &fintech_data.ReportInstance{BranchId: "branchId1"},
				updateFields: []string{"branchId"},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		docMock := monthly.NewMockCollectionClient(ctrl)
		docMock.EXPECT().Update(tt.args.ctx, &document.UpdateRequest{
			CollectionName: collNameInstance,
			Id:             "dataId",
			Update:         protostruct.ToStruct(map[string]interface{}{"branchId": "branchId1"}),
		}).Return(nil, nil).MaxTimes(1)
		t.Run(tt.name, func(t *testing.T) {
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			if err := s.UpdateInstance(tt.args.ctx, tt.args.dataId, tt.args.instance, tt.args.updateFields); (err != nil) != tt.wantErr {
				t.Errorf("UpdateInstance() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_historyService_GetInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx    context.Context
		dataId string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportInstance
		wantErr bool

		taskData *types.Struct
		getErr   error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:    ctx,
				dataId: "fakeId",
			},
			want: &fintech_data.ReportInstance{
				DataId:   "fakeId",
				ObjectId: "HOST",
			},
			wantErr: false,
			taskData: protostruct.ToStruct(map[string]interface{}{
				"objectId": "HOST",
				"_id":      "fakeId",
			}),
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				dataId: "fakeId",
			},
			wantErr: true,
			getErr:  fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().GET(ctx, &document.GETRequest{
				Id:             tt.args.dataId,
				CollectionName: collNameInstance,
			}).Return(tt.taskData, tt.getErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			got, err := s.GetInstance(tt.args.ctx, tt.args.dataId)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}
