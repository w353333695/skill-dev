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

func Test_historyService_SearchBranch(t *testing.T) {
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
		want    []*fintech_data.ReportBranch
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
			want: []*fintech_data.ReportBranch{
				{
					InnerId:  "innerId",
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
						"_id":      "innerId",
						"objectId": "HOST",
						"taskId":   "fakeId",
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
						"_id":      "innerId",
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
				CollectionName: collNameBranch,
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
			got, got1, err := s.SearchBranch(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.st, tt.args.et, tt.args.page, tt.args.pageSize)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchBranch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchBranch() got = %v, want %v", got, tt.want)
			}
			if got1 != tt.want1 {
				t.Errorf("SearchBranch() got1 = %v, want %v", got1, tt.want1)
			}
		})
	}
}

func Test_historyService_BatchCreateBranch(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx        context.Context
		branchList []*fintech_data.ReportBranch
	}
	tests := []struct {
		name      string
		fields    fields
		args      args
		want      []string
		wantErr   bool
		createErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				branchList: []*fintech_data.ReportBranch{
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
				branchList: []*fintech_data.ReportBranch{
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
				CollectionName: collNameBranch,
				Timestamp:      int32(1575472186),
				Documents: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"taskId":             "",
						"branchId":           "",
						"objectId":           "server",
						"dataTotal":          0,
						"successTotal":       0,
						"failTotal":          0,
						"inserted":           0,
						"updated":            0,
						"removed":            0,
						"totalStatus":        "",
						"reportStatus":       "",
						"requestCheckStatus": "",
						"checkStatus":        "",
						"code":               "",
						"msg":                "",
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
			got, err := s.BatchCreateBranch(tt.args.ctx, tt.args.branchList)
			if (err != nil) != tt.wantErr {
				t.Errorf("BatchCreateBranch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("BatchCreateBranch() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_CreateBranch(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx    context.Context
		branch *fintech_data.ReportBranch
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
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				branch: &fintech_data.ReportBranch{
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
				branch: &fintech_data.ReportBranch{
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
			docMock.EXPECT().Create(ctx, &document.CreateRequest{
				CollectionName: collNameBranch,
				Timestamp:      int32(1575472186),
				Document: protostruct.ToStruct(map[string]interface{}{
					"taskId":             "",
					"branchId":           "",
					"objectId":           "server",
					"dataTotal":          0,
					"successTotal":       0,
					"failTotal":          0,
					"inserted":           0,
					"updated":            0,
					"removed":            0,
					"totalStatus":        "",
					"reportStatus":       "",
					"checkStatus":        "",
					"requestCheckStatus": "",
					"code":               "",
					"msg":                "",
				}),
			}).Return(&document.CreateResponse{Id: "fakeId"}, tt.createErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.CreateBranch(tt.args.ctx, tt.args.branch)
			if (err != nil) != tt.wantErr {
				t.Errorf("CreateBranch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("CreateBranch() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_historyService_UpdateBranch(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		monthlyClient *monthly_collection_service.Client
		nowTimeFunc   timeutil.NowTimeFunc
	}
	type args struct {
		ctx          context.Context
		innerId      string
		branch       *fintech_data.ReportBranch
		updateFields []string
	}
	tests := []struct {
		name      string
		fields    fields
		args      args
		wantErr   bool
		updateErr error

		updateData *types.Struct
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				innerId: "fakeId",
				branch: &fintech_data.ReportBranch{
					BranchId: "branchId1",
				},
				updateFields: []string{"branchId"},
			},
			wantErr:    false,
			updateErr:  nil,
			updateData: protostruct.ToStruct(map[string]interface{}{"branchId": "branchId1"}),
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				innerId: "fakeId",
				branch: &fintech_data.ReportBranch{
					BranchId: "branchId1",
				},
				updateFields: []string{},
			},
			wantErr:    false,
			updateErr:  nil,
			updateData: branchToData(&fintech_data.ReportBranch{BranchId: "branchId1"}),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			docMock := monthly.NewMockCollectionClient(ctrl)
			docMock.EXPECT().Update(ctx, &document.UpdateRequest{
				CollectionName: collNameBranch,
				Id:             tt.args.innerId,
				Update:         tt.updateData,
			}).Return(nil, tt.updateErr).Times(1)
			s := &historyService{
				monthlyClient: &monthly_collection_service.Client{Document: docMock},
				nowTimeFunc:   tt.fields.nowTimeFunc,
			}
			if err := s.UpdateBranch(tt.args.ctx, tt.args.innerId, tt.args.branch, tt.args.updateFields); (err != nil) != tt.wantErr {
				t.Errorf("UpdateBranch() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_historyService_SearchAllBranch(t *testing.T) {
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
		want    []*fintech_data.ReportBranch
		wantErr bool

		limitResp *document.LimitResponse
		limitErr  error
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
			want: []*fintech_data.ReportBranch{
				{
					InnerId:  "dataId",
					ObjectId: "server",
					TaskId:   "fakeId",
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
						"objectId": []string{"server"},
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
				CollectionName: collNameBranch,
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
			got, err := s.SearchAllBranch(tt.args.ctx, tt.args.query, tt.args.fields, tt.args.limit, tt.args.st, tt.args.et)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchAllBranch() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchAllBranch() got = %v, want %v", got, tt.want)
			}
		})
	}
}
