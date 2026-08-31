package report_task

import (
	"context"
	"fmt"
	"time"

	"go.easyops.local/fintech_data/internal/extends/timeutil"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/fintech_data/mock/remote/cmdb"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"

	"reflect"
	"testing"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func TestNewService(t *testing.T) {
	type args struct {
		instanceClient instance.Client
	}
	tests := []struct {
		name string
		args args
		want ConfigService
	}{
		{
			name: "",
			args: args{},
			want: &serviceImp{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := NewConfigService(tt.args.instanceClient); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("NewConfigService() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_configToStruct(t *testing.T) {
	type args struct {
		data *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name string
		args args
		want *types.Struct
	}{
		{
			name: "",
			args: args{
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "C100WC",
					Memo:                "haha",
				},
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"clientId":            "fakeId",
				"clientSecret":        "fakeSecret",
				"ip":                  "192.168.100.162",
				"port":                int64(8079),
				"facilityOwnerAgency": "C100WC",
				"memo":                "haha",
			}),
		},
		{
			name: "",
			args: args{
				data: nil,
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := configToStruct(tt.args.data); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("configToStruct() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_GetConfig(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		instanceClient instance.Client
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportGlobalConfig
		wantErr bool

		searchResp *instance.PostSearchV2Response
		searchErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			want: &fintech_data.ReportGlobalConfig{
				ClientId:     "fakeId",
				ClientSecret: "fakeSecret",
			},
			wantErr: false,
			searchResp: &instance.PostSearchV2Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"clientId":     "fakeId",
						"clientSecret": "fakeSecret",
					}),
				},
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
			searchErr: nil,
		},
		{
			name:   "convert fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr: true,
			searchResp: &instance.PostSearchV2Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"clientId":     "fakeId",
						"clientSecret": []string{"fakeSecret"},
					}),
				},
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
			searchErr: nil,
		},
		{
			name:   "data empty",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			searchResp: &instance.PostSearchV2Response{
				List: []*types.Struct{},
			},
			want:      &fintech_data.ReportGlobalConfig{},
			searchErr: nil,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: configObjId,
				Query:    protostruct.ToStruct(getConfigQuery()),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*": true,
				}),
				Page:     1,
				PageSize: 3000,
			}).Return(tt.searchResp, tt.searchErr).Times(1)
			i := &serviceImp{
				instanceClient: instanceMock,
			}
			got, err := i.GetConfig(tt.args.ctx)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetConfig() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetConfig() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_UpdateConfig(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		instanceClient instance.Client
	}
	type args struct {
		ctx  context.Context
		data *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		importResp *instance.ImportInstanceResponse
		importErr  error
	}{
		{
			name: "normal",
			args: args{
				ctx: ctx,
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "C100WC",
					Memo:                "haha",
				},
			},
			importResp: &instance.ImportInstanceResponse{
				InsertCount: 1,
				FailedCount: 0,
				Data:        nil,
			},
			wantErr: false,
		},
		{
			name: "fail",
			args: args{
				ctx: ctx,
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "C100WC",
					Memo:                "haha",
				},
			},
			importResp: &instance.ImportInstanceResponse{
				InsertCount: 0,
				FailedCount: 1,
				Data: []*instance.ImportInstanceResponse_Data{
					{
						Code:  130010,
						Error: "fail",
					},
				},
			},
			wantErr: true,
		},
		{
			name: "fail",
			args: args{
				ctx: ctx,
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "C100WC",
					Memo:                "haha",
				},
			},
			importResp: &instance.ImportInstanceResponse{
				InsertCount: 0,
				FailedCount: 1,
				Data: []*instance.ImportInstanceResponse_Data{
					{
						Code:  130600,
						Error: "fail",
					},
				},
			},
			wantErr: true,
		},
		{
			name: "fail",
			args: args{
				ctx: ctx,
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "C100WC",
					Memo:                "haha",
				},
			},
			importErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().ImportInstance(ctx, &instance.ImportInstanceRequest{
				ObjectId: configObjId,
				Keys:     []string{"name"},
				Datas: []*types.Struct{protostruct.ToStruct(map[string]interface{}{
					"name":                internalConfigName,
					"clientId":            "fakeId",
					"clientSecret":        "fakeSecret",
					"ip":                  "192.168.100.162",
					"port":                8079,
					"facilityOwnerAgency": "C100WC",
					"memo":                "haha",
				})},
			}).Return(tt.importResp, tt.importErr).Times(1)

			i := &serviceImp{
				instanceClient: instanceMock,
			}
			if err := i.UpdateConfig(tt.args.ctx, tt.args.data); (err != nil) != tt.wantErr {
				t.Errorf("UpdateConfig() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestNextExecTime(t *testing.T) {
	now, _ := time.ParseInLocation(timeutil.TimeFormat, "2019-11-11 12:00:00", timeutil.TimeZone)
	type args struct {
		crontab string
		now     time.Time
	}
	tests := []struct {
		name    string
		args    args
		want    string
		wantErr bool
	}{
		{
			name: "normal",
			args: args{
				crontab: "*/5 * * * *",
				now:     now,
			},
			want:    "2019-11-11 12:05:00",
			wantErr: false,
		},
		{
			name: "fail",
			args: args{
				crontab: "* * * *",
			},
			want:    "",
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := NextExecTime(tt.args.crontab, tt.args.now)
			if (err != nil) != tt.wantErr {
				t.Errorf("NextExecTime() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("NextExecTime() got = %v, want %v", got, tt.want)
			}
		})
	}
}
