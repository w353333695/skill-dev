package history

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"testing"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/easyops-cn/mongo-driver-helper/pmongo/mock_pmongo"
	"github.com/golang/mock/gomock"
	"go.mongodb.org/mongo-driver/bson"
	mongoModel "go.mongodb.org/mongo-driver/mongo"

	"go.easyops.local/fintech_data/internal/mongo"
)

func TestNewCenterData(t *testing.T) {
	type args struct {
		client pmongo.ClientInterface
	}
	tests := []struct {
		name string
		arg  args
		want CenterData
	}{
		{
			name: "",
			arg: args{
				client: nil,
			},
			want: &centerDataService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewCenterData(tt.arg.client)
		})
	}
}

func Test_centerDataService_getCollection(t *testing.T) {
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name string
		arg  args
	}{
		{
			name: "",
			arg: args{
				ctx: context.Background(),
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &centerDataService{
				collectionFactory: func(ctx context.Context, tableName string) mongo.CollectionHelper {
					return nil
				},
			}
			s.getCollection(tt.arg.ctx)
		})
	}
}

func TestReportMetaData_ToMap(t *testing.T) {
	type fields struct {
		InstanceId         string
		Version            int
		ObjectId           string
		FacilityCategory   string
		FacilityDescriptor string
		DataId             string
		Ts                 int32
	}
	tests := []struct {
		name   string
		fields fields
		want   map[string]interface{}
	}{
		{
			name: "",
			fields: fields{
				InstanceId:         "instId",
				Version:            1,
				ObjectId:           "HOST",
				FacilityCategory:   "cate",
				FacilityDescriptor: "desc",
				DataId:             "111",
				Ts:                 int32(1),
			},
			want: map[string]interface{}{
				"instanceId":         "instId",
				"objectId":           "HOST",
				"facilityCategory":   "cate",
				"facilityDescriptor": "desc",
				"version":            1,
				"dataId":             "111",
				"ts":                 int32(1),
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := &ReportMetaData{
				InstanceId:         tt.fields.InstanceId,
				Version:            tt.fields.Version,
				ObjectId:           tt.fields.ObjectId,
				FacilityCategory:   tt.fields.FacilityCategory,
				FacilityDescriptor: tt.fields.FacilityDescriptor,
				Ts:                 tt.fields.Ts,
				DataId:             tt.fields.DataId,
			}
			if got := d.ToMap(); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ToMap() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_centerDataService_Remove(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
	type fields struct {
		collectionFactoryV2 mongo.CollectionFactoryV2
	}
	type args struct {
		ctx      context.Context
		dataList []*ReportMetaData
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		deleteErr error
	}{
		{
			name: "normal",
			fields: fields{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			},
			args: args{
				ctx:      context.Background(),
				dataList: []*ReportMetaData{{InstanceId: "aaa"}},
			},
			deleteErr: nil,
			wantErr:   false,
		},
		{
			name: "fail",
			fields: fields{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			},
			args: args{
				ctx:      context.Background(),
				dataList: []*ReportMetaData{{InstanceId: "aaa"}},
			},
			deleteErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl.EXPECT().DeleteMany(tt.args.ctx, bson.M{
				"instanceId": bson.M{
					"$in": []string{"aaa"},
				},
			}).Return(nil, tt.deleteErr).Times(1)
			s := &centerDataService{
				collectionFactoryV2: tt.fields.collectionFactoryV2,
			}
			if err := s.RemoveAll(tt.args.ctx, tt.args.dataList...); (err != nil) != tt.wantErr {
				t.Errorf("Remove() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_centerDataService_SearchAll(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx    context.Context
		query  map[string]interface{}
		fields []string
	}
	tests := []struct {
		name    string
		args    args
		want    []*ReportMetaData
		wantErr bool

		countErr error
		total    int64
		findErr  error
		allErr   error
	}{
		{
			name: "count error",
			args: args{
				ctx:    context.Background(),
				query:  map[string]interface{}{"instanceId": "xxx"},
				fields: []string{"instanceId"},
			},
			countErr: errors.New("count error"),
			wantErr:  true,
		},
		{
			name: "total is 0",
			args: args{
				ctx:    context.Background(),
				query:  map[string]interface{}{"instanceId": "xxx"},
				fields: []string{"instanceId"},
			},
			total: 0,
		},
		{
			name: "find error",
			args: args{
				ctx:    context.Background(),
				query:  map[string]interface{}{"instanceId": "xxx"},
				fields: []string{"instanceId"},
			},
			total:   1,
			findErr: errors.New("find error"),
			wantErr: true,
		},
		{
			name: "all error",
			args: args{
				ctx:    context.Background(),
				query:  map[string]interface{}{"instanceId": "xxx"},
				fields: []string{"instanceId"},
			},
			total:   1,
			allErr:  errors.New("all error"),
			wantErr: true,
		},

		{
			name: "normal",
			args: args{
				ctx:    context.Background(),
				query:  map[string]interface{}{"instanceId": "xxx"},
				fields: []string{"instanceId"},
			},
			total: 1,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockCursor := mock_pmongo.NewMockCursorInterface(ctrl)

			mockColl.EXPECT().CountDocuments(tt.args.ctx, tt.args.query).Return(tt.total, tt.countErr).AnyTimes()

			opts := findOptions(tt.args.fields, nil, 1, tt.total)
			mockColl.EXPECT().Find(tt.args.ctx, tt.args.query, opts).Return(mockCursor, tt.findErr).AnyTimes()

			mockCursor.EXPECT().All(tt.args.ctx, gomock.Any()).Return(tt.allErr).AnyTimes()

			s := &centerDataService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			got, err := s.SearchAll(tt.args.ctx, tt.args.query, tt.args.fields)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchAll() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchAll() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_centerDataService_Upsert(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type fields struct {
		collectionFactory mongo.CollectionFactory
	}
	type args struct {
		ctx      context.Context
		dataList []*ReportMetaData
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		ret       *mongoModel.BulkWriteResult
		upsertErr error
	}{
		{
			name: "normal",
			args: args{
				ctx: context.Background(),
				dataList: []*ReportMetaData{
					{
						InstanceId: "11",
						ObjectId:   "11",
					},
					{
						InstanceId: "22",
						ObjectId:   "22",
					},
				},
			},
			ret: &mongoModel.BulkWriteResult{
				ModifiedCount: 1,
			},
			wantErr: false,
		},
		{
			name: "upsert error",
			args: args{
				ctx: context.Background(),
				dataList: []*ReportMetaData{
					{
						InstanceId: "11",
						ObjectId:   "11",
					},
					{
						InstanceId: "22",
						ObjectId:   "22",
					},
				},
			},
			upsertErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockColl.EXPECT().BulkWrite(tt.args.ctx, gomock.Any()).Return(tt.ret, tt.upsertErr).AnyTimes()

			s := &centerDataService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			if _, err := s.Upsert(tt.args.ctx, tt.args.dataList...); (err != nil) != tt.wantErr {
				t.Errorf("Upsert() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_centerDataService_Count(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx   context.Context
		query map[string]interface{}
	}
	tests := []struct {
		name    string
		args    args
		want    int
		wantErr bool

		total    int64
		countErr error
	}{
		{
			name: "count error",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},

			countErr: errors.New("count error"),
			wantErr:  true,
		},
		{
			name: "normal",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},
			total: 1,
			want:  1,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockColl.EXPECT().CountDocuments(tt.args.ctx, tt.args.query).Return(tt.total, tt.countErr).AnyTimes()

			s := &centerDataService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			got, err := s.Count(tt.args.ctx, tt.args.query)
			if (err != nil) != tt.wantErr {
				t.Errorf("Count() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("Count() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_centerDataService_Aggregate(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx      context.Context
		pipeline interface{}
		result   interface{}
	}
	tests := []struct {
		name         string
		args         args
		aggregateErr error
		wantErr      bool
	}{
		{
			name: "aggregate error",
			args: args{
				ctx:      context.Background(),
				pipeline: nil,
				result:   nil,
			},
			aggregateErr: errors.New("aggregate error"),
			wantErr:      true,
		},
		{
			name: "aggregate error",
			args: args{
				ctx:      context.Background(),
				pipeline: nil,
				result:   nil,
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockCursor := mock_pmongo.NewMockCursorInterface(ctrl)
			mockColl.EXPECT().Aggregate(tt.args.ctx, tt.args.pipeline).Return(mockCursor, tt.aggregateErr).AnyTimes()
			mockCursor.EXPECT().All(tt.args.ctx, gomock.Any()).Return(nil).AnyTimes()

			s := &centerDataService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			if err := s.Aggregate(tt.args.ctx, tt.args.pipeline, tt.args.result); (err != nil) != tt.wantErr {
				t.Errorf("Aggregate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_centerDataService_findOptions(t *testing.T) {
	type args struct {
		fields   []string
		sorts    []string
		page     int64
		pageSize int64
	}
	tests := []struct {
		name string
		arg  args
	}{
		{
			name: "",
			arg: args{
				sorts:    []string{"-_id", "name"},
				page:     1,
				pageSize: 10,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			findOptions(tt.arg.fields, tt.arg.sorts, tt.arg.page, tt.arg.pageSize)
		})
	}
}
