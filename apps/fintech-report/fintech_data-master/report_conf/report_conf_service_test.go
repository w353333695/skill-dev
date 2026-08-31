package report_conf

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/golang/mock/gomock"

	message "go.easyops.local/contracts/protorepo-fintech_data/report_conf"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/report_rule"
	report_rule2 "go.easyops.local/fintech_data/mock/report_rule"
	"go.easyops.local/gin-giraffe/pkg/orguser"
)

func TestNewReportConfService(t *testing.T) {
	type args struct {
		reportRuleService report_rule.Service
	}
	tests := []struct {
		name string
		args args
		want *reportConfService
	}{
		{
			name: "",
			args: args{
				reportRuleService: nil,
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewReportConfService(tt.args.reportRuleService)
		})
	}
}

func Test_reportConfService_UpdateMappingRule(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{User: "easyops", Org: 8888})
	type fields struct {
		reportRuleService report_rule.Service
		nowTimeFunc       func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.UpdateMappingRuleResponse
		wantErr bool

		updateErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &fintech_data.ReportObjectConf{
					InstanceId:     "fakeId",
					ObjectId:       "server",
					ConfigModifier: "easyops",
				},
			},
			want: &message.UpdateMappingRuleResponse{
				InstanceId: "fakeId",
			},
			wantErr: false,
		},
		{
			name:   "ctx fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &fintech_data.ReportObjectConf{
					InstanceId: "fakeId",
					ObjectId:   "server",
				},
			},
			wantErr: true,
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &fintech_data.ReportObjectConf{
					InstanceId:     "fakeId",
					ObjectId:       "server",
					ConfigModifier: "easyops",
				},
			},
			updateErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_rule2.NewMockService(ctrl)
			updateFields := []string{"source", "mappingObjectId", "mappingObjectName", "mappingRule", "configModifier"}
			serviceMock.EXPECT().UpdateRule(tt.args.ctx, tt.args.request.InstanceId, tt.args.request, updateFields).Return(tt.updateErr).MaxTimes(1)
			s := &reportConfService{
				reportRuleService: serviceMock,
				nowTimeFunc:       tt.fields.nowTimeFunc,
			}
			got, err := s.UpdateMappingRule(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("UpdateMappingRule() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("UpdateMappingRule() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_reportConfService_UpdateReportConf(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{User: "easyops", Org: 8888})
	type fields struct {
		reportRuleService report_rule.Service
		nowTimeFunc       func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.UpdateReportConfResponse
		wantErr bool

		updateErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &fintech_data.ReportObjectConf{
					InstanceId: "fakeId",
					ObjectId:   "server",
					Crontab:    "1 * * * *",
				},
			},
			want: &message.UpdateReportConfResponse{
				InstanceId: "fakeId",
			},
			wantErr: false,
		},
		{
			name:   "ctx fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				request: &fintech_data.ReportObjectConf{
					InstanceId: "fakeId",
					ObjectId:   "server",
					Crontab:    "1 * * * *",
				},
			},
			wantErr: true,
		},
		{
			name:   "crontab invalid",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &fintech_data.ReportObjectConf{
					InstanceId: "fakeId",
					ObjectId:   "server",
					Crontab:    "1 ---",
				},
			},
			wantErr: true,
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				request: &fintech_data.ReportObjectConf{
					InstanceId: "fakeId",
					ObjectId:   "server",
					Crontab:    "1 * * * *",
				},
			},
			updateErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			serviceMock := report_rule2.NewMockService(ctrl)
			updateFields := []string{"enable", "autoRequestCheck","crontab", "batchNum", "nextExecTime", "configModifier"}
			serviceMock.EXPECT().UpdateRule(tt.args.ctx, tt.args.request.InstanceId, &fintech_data.ReportObjectConf{
				InstanceId:     "fakeId",
				ObjectId:       "server",
				Crontab:        "1 * * * *",
				NextExecTime:   "2019-12-04 16:01:00",
				ConfigModifier: "easyops",
			}, updateFields).Return(tt.updateErr).MaxTimes(1)
			s := &reportConfService{
				reportRuleService: serviceMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			got, err := s.UpdateReportConf(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("UpdateReportConf() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("UpdateReportConf() got = %v, want %v", got, tt.want)
			}
		})
	}
}
