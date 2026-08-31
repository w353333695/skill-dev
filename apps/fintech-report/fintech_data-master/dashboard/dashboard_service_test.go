package dashboard

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-collector_center/collection_config"
	message "go.easyops.local/contracts/protorepo-fintech_data/dashboard"
	cmdbmodel "go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/excelutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_rule"
	excelutil2 "go.easyops.local/fintech_data/mock/excelutil"
	history2 "go.easyops.local/fintech_data/mock/history"
	"go.easyops.local/fintech_data/mock/remote/cmdb"
	"go.easyops.local/fintech_data/mock/remote/collector_center"
	report_rule2 "go.easyops.local/fintech_data/mock/report_rule"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewDashboardService(t *testing.T) {
	type args struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
		centerData       history.CenterData
		taskHistory      history.TaskHistory
		objectStat       history.ObjectStat
	}
	tests := []struct {
		name string
		args args
		want *dashboardService
	}{
		{
			name: "",
			args: args{
				ruleService:      nil,
				collectionClient: nil,
				instanceClient:   nil,
			},
			want: &dashboardService{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewDashboardService(tt.args.ruleService, tt.args.collectionClient, tt.args.instanceClient, tt.args.centerData, tt.args.taskHistory, tt.args.objectStat)
		})
	}
}

func Test_dashboardService_ReportObjectCount(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
	}
	type args struct {
		ctx     context.Context
		request *types.Empty
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.ReportObjectCountResponse
		wantErr bool

		searchErr error
		listErr   error
		groupErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			want: &message.ReportObjectCountResponse{
				Total:           3,
				EnableTotal:     2,
				CollectionTotal: 2,
				CheckTotal:      2,
			},
			wantErr:  false,
			listErr:  nil,
			groupErr: nil,
		},
		{
			name:   "search rule fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
			listErr:   nil,
			groupErr:  nil,
		},
		{
			name:   "collection fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:  true,
			listErr:  fmt.Errorf("mock fail"),
			groupErr: nil,
		},
		{
			name:   "data filter fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:  true,
			listErr:  nil,
			groupErr: fmt.Errorf("mock fail"),
		},
		{
			name:   "all fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr:  true,
			listErr:  fmt.Errorf("mock fail"),
			groupErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ruleMock := report_rule2.NewMockService(ctrl)
			ruleMock.EXPECT().SearchRule(ctx, nil, []string{"enable", "objectId", "source", "mappingObjectId"}).Return(
				[]*fintech_data.ReportObjectConf{
					{
						ObjectId: "app",
						Enable:   true,
					},
					{
						ObjectId: "server",
						Enable:   false,
					},
					{
						ObjectId: "switch",
						Enable:   true,
					},
				}, tt.searchErr).Times(1)

			collectionMock := collector_center.NewMockcollectionClient(ctrl)
			collectionMock.EXPECT().ListCollectionConfig(ctx, &collection_config.ListCollectionConfigRequest{Disabled: 1, IsAll: 0, Page: 1, PageSize: 300, Fields: "labels,targetRange"}).Return(
				&collection_config.ListCollectionConfigResponse{
					List: []*collection_config.ListCollectionConfigResponse_List{
						{
							Labels: []string{"app"},
						},
						{
							Labels: []string{"app"},
						},
						{
							Labels: []string{"server"},
						},
						{
							Labels: []string{"ugly"},
						},
					},
				}, tt.listErr).MaxTimes(1)

			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().GroupInstance(ctx, &instance.GroupInstanceRequest{
				ObjectId: "_DATAFILTER_STRATEGY",
				Query: protostruct.ToStruct(map[string]interface{}{
					"enable":           true,
					"strategyObjectId": map[string]interface{}{"$in": []string{"app", "server", "switch"}},
				}),
				Funcs:      []*cmdbmodel.GroupInstanceFunc{{Op: "count", Field: "name", Alias: "count"}},
				GroupField: "strategyObjectId",
			}).Return(&instance.GroupInstanceResponse{
				List: []*instance.GroupInstanceResponse_List{
					{
						GroupField: "strategyObjectId",
						GroupValue: protostruct.ToValue("app"),
						FuncValues: nil,
					},
					{
						GroupField: "strategyObjectId",
						GroupValue: protostruct.ToValue("server"),
						FuncValues: nil,
					},
				},
			}, tt.groupErr).MaxTimes(1)

			s := &dashboardService{
				ruleService:      ruleMock,
				collectionClient: collectionMock,
				instanceClient:   instanceMock,
			}
			got, err := s.ReportObjectCount(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportObjectCount() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportObjectCount() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_dashboardService_countCollectionObject(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
	}
	type args struct {
		ctx          context.Context
		objectIdList []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    int
		wantErr bool

		listErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:          ctx,
				objectIdList: []string{"app", "server"},
			},
			want:    2,
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:          ctx,
				objectIdList: []string{"app", "server"},
			},
			listErr: fmt.Errorf("mock fail"),
			want:    0,
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			collectionMock := collector_center.NewMockcollectionClient(ctrl)
			collectionMock.EXPECT().ListCollectionConfig(ctx, &collection_config.ListCollectionConfigRequest{Disabled: 1, IsAll: 0, Page: 1, PageSize: 300, Fields: "labels,targetRange"}).Return(
				&collection_config.ListCollectionConfigResponse{
					List: []*collection_config.ListCollectionConfigResponse_List{
						{
							Labels: []string{"app"},
						},
						{
							Labels: []string{"app"},
						},
						{
							Labels: []string{"server"},
						},
						{
							Labels: []string{"ugly"},
						},
					},
				}, tt.listErr).Times(1)
			s := &dashboardService{
				ruleService:      tt.fields.ruleService,
				collectionClient: collectionMock,
				instanceClient:   tt.fields.instanceClient,
			}
			got, err := s.countCollectionObject(tt.args.ctx, tt.args.objectIdList)
			if (err != nil) != tt.wantErr {
				t.Errorf("countCollectionObject() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("countCollectionObject() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_dashboardService_countDataFilterObject(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
	}
	type args struct {
		ctx          context.Context
		objectIdList []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    int
		wantErr bool

		groupErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:          ctx,
				objectIdList: []string{"app", "server"},
			},
			want:    2,
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:          ctx,
				objectIdList: []string{"app", "server"},
			},
			groupErr: fmt.Errorf("mock fail"),
			want:     0,
			wantErr:  true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().GroupInstance(ctx, &instance.GroupInstanceRequest{
				ObjectId: "_DATAFILTER_STRATEGY",
				Query: protostruct.ToStruct(map[string]interface{}{
					"enable":           true,
					"strategyObjectId": map[string]interface{}{"$in": tt.args.objectIdList},
				}),
				Funcs:      []*cmdbmodel.GroupInstanceFunc{{Op: "count", Field: "name", Alias: "count"}},
				GroupField: "strategyObjectId",
			}).Return(&instance.GroupInstanceResponse{
				List: []*instance.GroupInstanceResponse_List{
					{
						GroupField: "strategyObjectId",
						GroupValue: protostruct.ToValue("app"),
						FuncValues: nil,
					},
					{
						GroupField: "strategyObjectId",
						GroupValue: protostruct.ToValue("server"),
						FuncValues: nil,
					},
				},
			}, tt.groupErr).Times(1)
			s := &dashboardService{
				ruleService:      tt.fields.ruleService,
				collectionClient: tt.fields.collectionClient,
				instanceClient:   instanceMock,
			}
			got, err := s.countDataFilterObject(tt.args.ctx, tt.args.objectIdList)
			if (err != nil) != tt.wantErr {
				t.Errorf("countDataFilterObject() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("countDataFilterObject() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_dashboardService_ReportInstanceCount(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
		centerData       history.CenterData
	}
	type args struct {
		ctx     context.Context
		request *types.Empty
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.ReportInstanceCountResponse
		wantErr bool

		allErr   error
		todayErr error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: nil,
			},
			want:    &message.ReportInstanceCountResponse{Total: 10, TodayTotal: 2},
			wantErr: false,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: nil,
			},
			allErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:     ctx,
				request: nil,
			},
			todayErr: fmt.Errorf("mock fail"),
			wantErr:  true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerDataMock := history2.NewMockCenterData(ctrl)
			centerDataMock.EXPECT().Count(ctx, nil).Return(10, tt.allErr).MaxTimes(1)
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().SearchInstanceAll(ctx, gomock.Any(), map[string]interface{}{"_id": 1}, 1000, 1486051200, 1486057371).Return([]*fintech_data.ReportInstance{{}, {}}, tt.todayErr).MaxTimes(1)
			s := &dashboardService{
				ruleService:      tt.fields.ruleService,
				collectionClient: tt.fields.collectionClient,
				instanceClient:   tt.fields.instanceClient,
				centerData:       centerDataMock,
				taskHistory:      historyMock,
				nowTimeFunc: func() time.Time {
					return time.Unix(1486057371, 0)
				},
			}
			got, err := s.ReportInstanceCount(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportInstanceCount() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportInstanceCount() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_dashboardService_ExportReportObjectStat(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
		centerData       history.CenterData
		taskHistory      history.TaskHistory
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *types.Empty
	}
	tests := []struct {
		name       string
		fields     fields
		args       args
		wantErr    bool
		getRuleErr error
		headerErr  error
		rowErr     error
		flushErr   error
	}{
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			wantErr: false,
		},
		{
			name:   "set header fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			headerErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "set row fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			rowErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name:   "get rule fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			getRuleErr: fmt.Errorf("mock fail"),
			wantErr:    true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ruleMock := report_rule2.NewMockService(ctrl)
			ruleMock.EXPECT().SearchRule(ctx, nil, []string{"objectId", "name", "source", "mappingObjectId", "mappingObjectName"}).
				Return([]*fintech_data.ReportObjectConf{
					{
						ObjectId: "server",
						Name:     "服务器",
						Source:   "",
					},
					{
						ObjectId:          "idc",
						Name:              "机房",
						Source:            "mapping",
						MappingObjectId:   "maping_idc",
						MappingObjectName: "机房模型",
					},
				}, tt.getRuleErr).MaxTimes(1)

			objectStatMock := history2.NewMockObjectStat(ctrl)
			objectStatMock.EXPECT().SearchAll(ctx, nil).Return(
				[]*history.StatData{
					{
						ObjectId:    "server",
						Total:       4,
						ReportTotal: 10,
						FailTotal:   3,
					},
					{
						ObjectId:    "idc",
						Total:       4,
						ReportTotal: 9,
						FailTotal:   2,
					},
				}, nil).MaxTimes(1)

			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().CountAll(ctx, &instance.CountAllRequest{}).Return(
				protostruct.ToStruct(map[string]interface{}{
					"server":     8,
					"app":        2,
					"idc":        1,
					"maping_idc": 4,
				}), nil).MaxTimes(1)

			exporterMock := excelutil2.NewMockExporter(ctrl)
			header := []excelutil.HeaderCell{
				{
					Name: "采集接口",
					Id:   "objectName",
				},
				{
					Name: "映射模型",
					Id:   "mappingObjectName",
				},
				{
					Name: "维护实例数量",
					Id:   "instanceTotal",
				},
				{
					Name: "上报成功总数",
					Id:   "successTotal",
				},
				{
					Name: "上报成功率",
					Id:   "successRate",
				},
			}
			exporterMock.EXPECT().WriteExcelHeader(header).Return(tt.headerErr).MaxTimes(1)

			exporterMock.EXPECT().WriteRow(map[string]interface{}{
				"objectName":        "服务器",
				"mappingObjectName": "",
				"instanceTotal":     int32(8),
				"successTotal":      int32(4),
				"successRate":       "70%",
			}).Return(tt.rowErr).MaxTimes(1)
			exporterMock.EXPECT().WriteRow(map[string]interface{}{
				"objectName":        "机房",
				"mappingObjectName": "机房模型",
				"instanceTotal":     int32(4),
				"successTotal":      int32(4),
				"successRate":       "77.78%",
			}).Return(tt.rowErr).MaxTimes(1)
			exporterMock.EXPECT().WriteExcelHeader(header).Return(tt.headerErr).MaxTimes(1)
			s := &dashboardService{
				ruleService:    ruleMock,
				instanceClient: instanceMock,
				objectStat:     objectStatMock,
				newExporterFunc: func(filename string) excelutil.Exporter {
					return exporterMock
				},
			}
			_, err := s.ExportReportObjectStat(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ExportReportObjectStat() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

		})
	}
}

func Test_dashboardService_ReportObjectStat(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
		centerData       history.CenterData
		taskHistory      history.TaskHistory
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx     context.Context
		request *types.Empty
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *message.ReportObjectStatResponse
		wantErr bool

		getRuleErr error
	}{
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			want: &message.ReportObjectStatResponse{
				List: []*message.ReportObjectStatResponse_List{
					{
						ReportObjectId:   "server",
						ReportObjectName: "服务器",
						InstanceTotal:    8,
						SuccessTotal:     4,
						SuccessRate:      0.7,
					},
					{
						ReportObjectId:    "idc",
						ReportObjectName:  "机房",
						MappingObjectId:   "maping_idc",
						MappingObjectName: "机房模型",
						InstanceTotal:     4,
						SuccessTotal:      4,
						SuccessRate:       1,
					},
					{
						ReportObjectId:   "app",
						ReportObjectName: "应用",
						InstanceTotal:    2,
						SuccessTotal:     0,
						SuccessRate:      0,
					},
				},
			},
			wantErr: false,
		},
		{
			name:   "get rule fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			getRuleErr: fmt.Errorf("mock fail"),
			wantErr:    true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ruleMock := report_rule2.NewMockService(ctrl)
			ruleMock.EXPECT().SearchRule(ctx, nil, []string{"objectId", "name", "source", "mappingObjectId", "mappingObjectName"}).
				Return([]*fintech_data.ReportObjectConf{
					{
						ObjectId: "server",
						Name:     "服务器",
						Source:   "",
					},
					{
						ObjectId:          "idc",
						Name:              "机房",
						Source:            "mapping",
						MappingObjectId:   "maping_idc",
						MappingObjectName: "机房模型",
					},
					{
						ObjectId:        "app",
						Name:            "应用",
						MappingObjectId: "fakeApp",
					},
				}, tt.getRuleErr).MaxTimes(1)

			objectStatMock := history2.NewMockObjectStat(ctrl)
			objectStatMock.EXPECT().SearchAll(ctx, nil).Return(
				[]*history.StatData{
					{
						ObjectId:    "server",
						Total:       4,
						ReportTotal: 10,
						FailTotal:   3,
					},
					{
						ObjectId:    "idc",
						Total:       4,
						ReportTotal: 10,
						FailTotal:   0,
					},
				}, nil).MaxTimes(1)

			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().CountAll(ctx, &instance.CountAllRequest{}).Return(
				protostruct.ToStruct(map[string]interface{}{
					"server":     8,
					"app":        2,
					"idc":        1,
					"maping_idc": 4,
				}), nil).MaxTimes(1)
			s := &dashboardService{
				ruleService:    ruleMock,
				instanceClient: instanceMock,
				objectStat:     objectStatMock,
			}
			got, err := s.ReportObjectStat(tt.args.ctx, tt.args.request)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportObjectStat() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportObjectStat() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_dashboardService_getObjectReportStat(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		ruleService      report_rule.Service
		collectionClient collection_config.Client
		instanceClient   instance.Client
		centerData       history.CenterData
		objectStat       history.ObjectStat
		taskHistory      history.TaskHistory
		nowTimeFunc      func() time.Time
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*message.ReportObjectStatResponse_List
		wantErr bool

		getRuleErr error

		statErr error

		countErr error
	}{
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			want: []*message.ReportObjectStatResponse_List{
				{
					ReportObjectId:   "server",
					ReportObjectName: "服务器",
					InstanceTotal:    8,
					SuccessTotal:     4,
					SuccessRate:      0.7,
				},
				{
					ReportObjectId:    "idc",
					ReportObjectName:  "机房",
					MappingObjectId:   "maping_idc",
					MappingObjectName: "机房模型",
					InstanceTotal:     4,
					SuccessTotal:      4,
					SuccessRate:       1,
				},
				{
					ReportObjectId:   "app",
					ReportObjectName: "应用",
					InstanceTotal:    2,
					SuccessTotal:     0,
					SuccessRate:      0,
				},
			},
			wantErr: false,
		},
		{
			name:   "get rule fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			getRuleErr: fmt.Errorf("mock fail"),
			wantErr:    true,
		},
		{
			name:   "object stat fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			statErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name:   "count instance fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			countErr: fmt.Errorf("mock fail"),
			wantErr:  true,
		},
		{
			name:   "2 event fail",
			fields: fields{},
			args: args{
				ctx: ctx,
			},
			getRuleErr: fmt.Errorf("mock fail"),
			countErr:   fmt.Errorf("mock fail"),
			wantErr:    true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ruleMock := report_rule2.NewMockService(ctrl)
			ruleMock.EXPECT().SearchRule(ctx, nil, []string{"objectId", "name", "source", "mappingObjectId", "mappingObjectName"}).
				Return([]*fintech_data.ReportObjectConf{
					{
						ObjectId: "server",
						Name:     "服务器",
						Source:   "",
					},
					{
						ObjectId:          "idc",
						Name:              "机房",
						Source:            "mapping",
						MappingObjectId:   "maping_idc",
						MappingObjectName: "机房模型",
					},
					{
						ObjectId:        "app",
						Name:            "应用",
						MappingObjectId: "fakeApp",
					},
				}, tt.getRuleErr).MaxTimes(1)

			objectStatMock := history2.NewMockObjectStat(ctrl)
			objectStatMock.EXPECT().SearchAll(ctx, nil).Return(
				[]*history.StatData{
					{
						ObjectId:    "server",
						Total:       4,
						ReportTotal: 10,
						FailTotal:   3,
					},
					{
						ObjectId:    "idc",
						Total:       4,
						ReportTotal: 10,
						FailTotal:   0,
					},
				}, tt.statErr).MaxTimes(1)

			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().CountAll(ctx, &instance.CountAllRequest{}).Return(
				protostruct.ToStruct(map[string]interface{}{
					"server":     8,
					"app":        2,
					"idc":        1,
					"maping_idc": 4,
				}), tt.countErr).MaxTimes(1)

			s := &dashboardService{
				ruleService:    ruleMock,
				instanceClient: instanceMock,
				objectStat:     objectStatMock,
			}
			got, err := s.getObjectReportStat(tt.args.ctx)
			if (err != nil) != tt.wantErr {
				t.Errorf("getObjectReportStat() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("getObjectReportStat() got = %v, want %v", got, tt.want)
			}
		})
	}
}
