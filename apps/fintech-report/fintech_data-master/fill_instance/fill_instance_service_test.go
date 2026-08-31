package fill_instance

import (
	"context"
	"fmt"
	"reflect"
	"testing"

	"go.easyops.local/kit/gogoprotobuf/protostruct"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	message "go.easyops.local/contracts/protorepo-fintech_data/fill_instance"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/fill_instance/dispatch"
	fill_instance2 "go.easyops.local/fintech_data/mock/fill_instance"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewFillInstanceService(t *testing.T) {
	type args struct {
		fillService    fill_instance.Service
		fillController dispatch.Dispatcher
	}
	tests := []struct {
		name string
		args args
		want *fillInstanceService
	}{
		{
			name: "",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewFillInstanceService(tt.args.fillService, tt.args.fillController)
		})
	}
}

func Test_fillInstanceService_InstanceCallback(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		fillService    fill_instance.Service
		fillController dispatch.Dispatcher
	}
	type args struct {
		ctx     context.Context
		request *message.InstanceCallbackRequest
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *types.Empty
		wantErr bool

		updateData *types.Struct
		effected   bool
		pushErr    error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.InstanceCallbackRequest{
					System: "cmdb",
					Topic:  "event.instance.update",
					Data: &message.InstanceCallbackRequest_Data{
						ExtInfo: &message.InstanceCallbackRequest_Data_ExtInfo{
							InstanceId:    "id1",
							ObjectId:      "server",
							XChangeFields: []string{"name"},
							DiffData: protostruct.ToStruct(map[string]interface{}{
								"name": map[string]interface{}{
									"new": "haha",
									"old": "wdnmd",
								},
							}),
						},
					},
				},
			},
			updateData: protostruct.ToStruct(map[string]interface{}{
				"name": "haha",
			}),
			effected: true,
			want:     nil,
			wantErr:  false,
		},
		{
			name:   "push fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.InstanceCallbackRequest{
					System: "cmdb",
					Topic:  "event.instance.update",
					Data: &message.InstanceCallbackRequest_Data{
						ExtInfo: &message.InstanceCallbackRequest_Data_ExtInfo{
							InstanceId:    "id1",
							ObjectId:      "server",
							XChangeFields: []string{"name"},
						},
					},
				},
			},
			effected: true,
			pushErr:  fmt.Errorf("mock fail"),
			wantErr:  true,
		},
		{
			name:   "no effected",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &message.InstanceCallbackRequest{
					System: "cmdb",
					Topic:  "event.instance.update",
					Data: &message.InstanceCallbackRequest_Data{
						ExtInfo: &message.InstanceCallbackRequest_Data_ExtInfo{
							InstanceId:    "id1",
							ObjectId:      "server",
							XChangeFields: []string{"name"},
						},
					},
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := fill_instance2.NewMockService(ctrl)
			item := fill_instance.ProcessItem{
				InstanceId:   "id1",
				ChangeFields: []string{"name"},
			}
			serviceMock.EXPECT().HasEffectedRule(ctx, "server", item, tt.updateData).Return(tt.effected).Times(1)

			dispatcherMock := fill_instance2.NewMockDispatcher(ctrl)
			if tt.effected {
				dispatcherMock.EXPECT().PushJob(ctx, "server", item).Return(tt.pushErr).Times(1)
			}

			f := &fillInstanceService{
				fillService: serviceMock,
				dispatcher:  dispatcherMock,
			}
			got, err := f.InstanceCallback(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("InstanceCallback() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("InstanceCallback() got = %v, want %v", got, tt.want)
			}
		})
	}
}
