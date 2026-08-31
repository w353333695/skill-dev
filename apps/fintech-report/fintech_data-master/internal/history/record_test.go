package history

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-data_exchange/store"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/mock/remote/data_exchange"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewRecorder(t *testing.T) {
	type args struct {
		storeClient store.Client
	}
	tests := []struct {
		name string
		args args
		want Recorder
	}{
		{
			name: "",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewRecorder(tt.args.storeClient)
		})
	}
}

func Test_recorderImp_Save(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888})
	type fields struct {
		storeClient store.Client
		nowTimeFunc timeutil.NowTimeFunc
	}
	type args struct {
		ctx   context.Context
		count []ReportCount
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		saveErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				count: []ReportCount{
					{
						Total:      10,
						Inserted:   2,
						Updated:    3,
						Removed:    1,
						ObjectId:   "server",
						InstanceId: "id",
						TaskId:     "jobId",
					},
				},
			},
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:   ctx,
				count: nil,
			},
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				count: []ReportCount{
					{
						Total:      10,
						Inserted:   2,
						Updated:    3,
						Removed:    1,
						ObjectId:   "server",
						InstanceId: "id",
						TaskId:     "jobId",
					},
				},
			},
			saveErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			storeMock := data_exchange.NewMockStoreClient(ctrl)
			storeMock.EXPECT().ClickHouseInsertData(ctx, &store.ClickHouseInsertDataRequest{
				Model:   historyTable,
				Columns: []string{"org", "time", "objectId", "_ver", "_seriesId", "_job", "instanceId", "total", "inserted", "updated", "removed", "failed"},
				Data: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"org":        8888,
						"time":       1609772986000,
						"objectId":   "server",
						"_ver":       1609772986000000000,
						"_seriesId":  "id",
						"_job":       "jobId",
						"instanceId": "id",
						"total":      10,
						"inserted":   2,
						"updated":    3,
						"removed":    1,
						"failed":     0,
					}),
				},
			}).Return(nil, tt.saveErr).MaxTimes(1)
			i := &recorderImp{
				storeClient: storeMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
			}
			if err := i.Save(tt.args.ctx, tt.args.count...); (err != nil) != tt.wantErr {
				t.Errorf("Save() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestReportCount_IsEffective(t *testing.T) {
	type fields struct {
		Total      int
		Inserted   int
		Updated    int
		Removed    int
		ObjectId   string
		InstanceId string
		TaskId     string
	}
	tests := []struct {
		name   string
		fields fields
		want   bool
	}{
		{
			name:   "",
			fields: fields{},
			want:   false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := ReportCount{
				Total:      tt.fields.Total,
				Inserted:   tt.fields.Inserted,
				Updated:    tt.fields.Updated,
				Removed:    tt.fields.Removed,
				ObjectId:   tt.fields.ObjectId,
				InstanceId: tt.fields.InstanceId,
				TaskId:     tt.fields.TaskId,
			}
			if got := c.IsEffective(); got != tt.want {
				t.Errorf("IsEffective() = %v, want %v", got, tt.want)
			}
		})
	}
}
