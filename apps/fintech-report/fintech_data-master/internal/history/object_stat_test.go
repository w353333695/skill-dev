package history

import (
	"context"
	"errors"
	"fmt"
	"go.easyops.local/fintech_data/internal/mongo"
	"reflect"
	"testing"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/easyops-cn/mongo-driver-helper/pmongo/mock_pmongo"
	"github.com/golang/mock/gomock"
	"go.mongodb.org/mongo-driver/bson"
	mongoModel "go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

func TestNewObjectStat(t *testing.T) {
	type args struct {
		client pmongo.ClientInterface
	}
	tests := []struct {
		name string
		arg  args
		want ObjectStat
	}{
		{
			name: "",
			arg: args{
				client: nil,
			},
			want: &objectStatService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewObjectStat(tt.arg.client)
		})
	}
}

func Test_objectStatService_getCollection(t *testing.T) {
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
			s := &objectStatService{
				collectionFactory: func(ctx context.Context, tableName string) mongo.CollectionHelper {
					return nil
				},
			}
			s.getCollection(tt.arg.ctx)
		})
	}
}

func TestStatData_ToMap(t *testing.T) {
	type fields struct {
		ObjectId    string
		Total       int
		ReportTotal int
		FailTotal   int
		TS          int32
		LastTaskId  string
	}
	tests := []struct {
		name   string
		fields fields
		want   map[string]interface{}
	}{
		{
			name: "",
			fields: fields{
				ObjectId:    "objectId",
				Total:       1,
				ReportTotal: 10,
				FailTotal:   5,
				TS:          int32(1),
				LastTaskId:  "111",
			},
			want: map[string]interface{}{
				"objectId":    "objectId",
				"total":       1,
				"reportTotal": 10,
				"failTotal":   5,
				"ts":          int32(1),
				"lastTaskId":  "111",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := &StatData{
				ObjectId:    tt.fields.ObjectId,
				Total:       tt.fields.Total,
				ReportTotal: tt.fields.ReportTotal,
				FailTotal:   tt.fields.FailTotal,
				TS:          tt.fields.TS,
				LastTaskId:  tt.fields.LastTaskId,
			}
			if got := d.ToMap(); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ToMap() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_objectStatService_Get(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx      context.Context
		objectId string
	}
	tests := []struct {
		name    string
		args    args
		want    *StatData
		wantErr bool

		getErr error
	}{
		{
			name: "decode error",
			args: args{
				ctx:      context.Background(),
				objectId: "HOST",
			},
			getErr:  errors.New("decode error"),
			wantErr: true,
		},
		{
			name: "normal",
			args: args{
				ctx:      context.Background(),
				objectId: "HOST",
			},
			want: &StatData{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockSingle := mock_pmongo.NewMockSingleResultInterface(ctrl)
			mockColl.EXPECT().FindOne(tt.args.ctx, bson.M{"objectId": tt.args.objectId}, options.FindOne()).Return(mockSingle).AnyTimes()
			mockSingle.EXPECT().Decode(gomock.Any()).Return(tt.getErr).AnyTimes()

			s := &objectStatService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			got, err := s.Get(tt.args.ctx, tt.args.objectId)
			if (err != nil) != tt.wantErr {
				t.Errorf("Get() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Get() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_objectStatService_SearchAll(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx   context.Context
		query map[string]interface{}
	}
	tests := []struct {
		name    string
		args    args
		want    []*StatData
		wantErr bool

		total    int64
		countErr error

		findErr error
		allErr  error
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
			name: "total is 0",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},
			total: 0,
		},
		{
			name: "find error",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},
			total:   1,
			findErr: errors.New("find error"),
			wantErr: true,
		},
		{
			name: "all error",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},
			total:   1,
			allErr:  errors.New("all error"),
			wantErr: true,
		},

		{
			name: "normal",
			args: args{
				ctx:   context.Background(),
				query: map[string]interface{}{"instanceId": "xxx"},
			},
			total: 1,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)
			mockCursor := mock_pmongo.NewMockCursorInterface(ctrl)

			mockColl.EXPECT().CountDocuments(tt.args.ctx, tt.args.query).Return(tt.total, tt.countErr).AnyTimes()

			opts := findOptions(nil, nil, 1, tt.total)
			mockColl.EXPECT().Find(tt.args.ctx, tt.args.query, opts).Return(mockCursor, tt.findErr).AnyTimes()

			mockCursor.EXPECT().All(tt.args.ctx, gomock.Any()).Return(tt.allErr).AnyTimes()

			s := &objectStatService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			got, err := s.SearchAll(tt.args.ctx, tt.args.query)
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

func Test_objectStatService_Update(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type args struct {
		ctx      context.Context
		dataList []*StatData
	}
	tests := []struct {
		name    string
		args    args
		want    *ChangeInfo
		wantErr bool

		ret       *mongoModel.BulkWriteResult
		upsertErr error
	}{
		{
			name: "normal",
			args: args{
				ctx: context.Background(),
				dataList: []*StatData{
					{
						ObjectId: "11",
						Total:    10,
					},
				},
			},
			ret: &mongoModel.BulkWriteResult{
				ModifiedCount: 0,
			},
			want: &ChangeInfo{
				Updated:  0,
				Inserted: 1,
			},
			wantErr: false,
		},
		{
			name: "fail",
			args: args{
				ctx: context.Background(),
				dataList: []*StatData{
					{
						ObjectId: "11",
						Total:    10,
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

			s := &objectStatService{
				collectionFactoryV2: func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
					return mockColl
				},
			}
			got, err := s.Upsert(tt.args.ctx, tt.args.dataList...)
			if (err != nil) != tt.wantErr {
				t.Errorf("Update() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Update() got = %v, want %v", got, tt.want)
			}
		})
	}
}
