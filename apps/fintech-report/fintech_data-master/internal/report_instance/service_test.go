package report_instance

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	pbtypes "github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	"go.easyops.local/contracts/protorepo-cmdb/instance"
	cmdbmodel "go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/contracts/protorepo-models/easyops/model/notify"
	"go.easyops.local/contracts/protorepo-notify/oplog"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/cmdbutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/types"
	history2 "go.easyops.local/fintech_data/mock/history"
	"go.easyops.local/fintech_data/mock/remote/cmdb"
	notify2 "go.easyops.local/fintech_data/mock/remote/notify"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewService(t *testing.T) {
	type args struct {
		instanceClient    instance.Client
		opLogClient       oplog.Client
		centerData        history.CenterData
		taskHistory       history.TaskHistory
		reportConf        config.ReportConf
		relationFillRules []fill_instance.RelationRule
	}
	tests := []struct {
		name string
		args args
		want Service
	}{
		{
			name: "normal",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewService(tt.args.instanceClient, nil, tt.args.opLogClient, tt.args.centerData, tt.args.taskHistory, tt.args.reportConf, tt.args.relationFillRules)
		})
	}
}

func Test_createBeforeSt(t *testing.T) {
	type args struct {
		inst *pbtypes.Struct
		st   int64
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			name: "",
			args: args{
				inst: protostruct.ToStruct(map[string]interface{}{"ctime": "2020-12-23 23:21:22"}),
				st:   1611823907,
			},
			want: true,
		},
		{
			name: "",
			args: args{
				inst: protostruct.ToStruct(map[string]interface{}{"ctime": "2022-12-23 23:21:22"}),
				st:   1611823907,
			},
			want: false,
		},
		{
			name: "",
			args: args{
				inst: protostruct.ToStruct(map[string]interface{}{"ctime": "2022-12-23 23:21:22"}),
				st:   0,
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := createBeforeSt(tt.args.inst, tt.args.st); got != tt.want {
				t.Errorf("createBeforeSt() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_SearchReportInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		batch          int
	}
	type args struct {
		ctx        context.Context
		request    types.CreateTaskRequest
		reportTask *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		wantErr bool

		listErr   error
		list2Err  error
		getObjErr error
		loadErr   error
		searchErr error
		retryErr  error
	}{
		{
			name: "normal",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			want: []*fintech_data.ReportInstance{
				{
					InstanceId:         "11",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeNew,
					ObjectId:           "server",
					ShowKey:            "aa",
					FacilityDescriptor: "desc1",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":         "11",
						"ctime":              "2020-12-22 22:31",
						"facilityCategory":   "",
						"facilityDescriptor": "desc1",
					}),
				},
				{
					InstanceId:         "22",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeUpdate,
					ObjectId:           "server",
					ShowKey:            "bb",
					FacilityDescriptor: "desc2",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":         "22",
						"ctime":              "2020-12-20 22:31",
						"facilityCategory":   "",
						"facilityDescriptor": "desc2",
					}),
				},
				{
					InstanceId:         "33",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					ShowKey:            "dd",
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":   "cate3",
						"facilityDescriptor": "desc3",
						"required":           "three",
					}),
				},
				{
					InstanceId:         "55",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "server",
					FacilityCategory:   "cate5",
					FacilityDescriptor: "desc5",
					ShowKey:            "ff",
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":   "cate3",
						"facilityDescriptor": "desc3",
						"required":           "three",
					}),
				},
			},
		},
		{
			name: "search retry",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
						ObjectDefine: &cmdbmodel.CmdbObject{
							AttrList: []*cmdbmodel.ObjectAttr{
								{
									Id:    "instanceId",
									Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
								},
								{
									Id:    "ctime",
									Value: &cmdbmodel.ObjectAttrValue{Type: "datetime"},
								},
								{
									Id:    "facilityCategory",
									Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
								},
								{
									Id:    "facilityDescriptor",
									Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
								},
							},
						},
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			retryErr: fmt.Errorf("mock fail"),
			wantErr:  true,
		},
		{
			name: "search delete fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			listErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name: "search archive fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			list2Err: fmt.Errorf("mock fail"),
			wantErr:  true,
		},
		{
			name: "get report obj fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			getObjErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name: "load delete fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			loadErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name: "search upsert fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opLogMock := notify2.NewMockOpLogClient(ctrl)
			centerDataMock := history2.NewMockCenterData(ctrl)
			instMock := cmdb.NewMockInstanceClient(ctrl)

			// searchDeleteInstance
			opLogMock.EXPECT().ListOperationLog(ctx, &notify.ListOperationLogRequest{
				Page:         1,
				PageSize:     10,
				System:       "cmdb",
				TargetId:     "server",
				Event:        EventTypeDelete,
				WithoutTotal: "false",
				StartTime:    tt.args.reportTask.LastReportTime,
				EndTime:      tt.args.reportTask.StartTime,
			}).Return(&oplog.ListOperationLogResponse{List: []*notify.OperationLog{
				{
					TargetId: "33",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "dd"}),
					Ctime:    1608211871,
				},
				{
					TargetId: "44",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "ee"}),
					Ctime:    1608631871,
				},
			}, Total: 1}, tt.listErr).MaxTimes(1)

			fields := []string{"instanceId", "facilityCategory", "facilityDescriptor", "objectId", "dataId"}
			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{"instanceId": map[string][]string{"$in": {"33", "44"}}}, fields).
				Return([]*history.ReportMetaData{
					{
						InstanceId:         "33",
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
						DataId:             "dataId33",
					},
				}, nil).MaxTimes(1)

			// searchDeleteInstance
			opLogMock.EXPECT().ListOperationLog(ctx, &notify.ListOperationLogRequest{
				Page:         1,
				PageSize:     10,
				System:       "cmdb",
				TargetId:     "server",
				Event:        EventTypeArchive,
				WithoutTotal: "false",
				StartTime:    tt.args.reportTask.LastReportTime,
				EndTime:      tt.args.reportTask.StartTime,
			}).Return(&oplog.ListOperationLogResponse{List: []*notify.OperationLog{
				{
					TargetId: "55",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "ff"}),
					Ctime:    1608211871,
				},
				{
					TargetId: "66",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "gg"}),
					Ctime:    1608631871,
				},
			}, Total: 1}, tt.list2Err).MaxTimes(1)

			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{"instanceId": map[string][]string{"$in": {"55", "66"}}}, fields).
				Return([]*history.ReportMetaData{
					{
						InstanceId:         "55",
						FacilityCategory:   "cate5",
						FacilityDescriptor: "desc5",
						DataId:             "dataId55",
					},
				}, nil).MaxTimes(1)

			// searchUpsertInstance
			instMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: "server",
				Query: protostruct.ToStruct(map[string]interface{}{"$and": []interface{}{
					map[string]interface{}{
						"_ts": map[string]interface{}{
							"$lt": 1608733871,
						},
					},
					map[string]interface{}{
						"_ts": map[string]interface{}{
							"$gte": 1608561071,
						},
					},
				}}),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*":                   true,
					cmdbutil.ShowKeyLabel: true,
				}),
				PageSize: int32(10),
				Page:     1,
			}).Return(&instance.PostSearchV2Response{
				Total: 4,
				List: []*pbtypes.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "11",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"aa"},
						report_center.KeyFacilityDescriptor: "desc1",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "22",
						"ctime":                             "2020-12-20 22:31:11",
						"#showKey":                          []string{"bb"},
						report_center.KeyFacilityDescriptor: "desc2",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "33",
						"ctime":                             "2020-12-19 22:31:11",
						"#showKey":                          []string{"dd"},
						report_center.KeyFacilityDescriptor: "desc3",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "44",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"ee"},
						report_center.KeyFacilityDescriptor: "desc4",
					}),
				},
			}, tt.searchErr).MaxTimes(1)

			// compareWithExisted
			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{report_center.KeyFacilityDescriptor: map[string][]string{"$in": {"desc2"}}}, fields).
				Return([]*history.ReportMetaData{
					{
						InstanceId:         "22",
						ObjectId:           "server",
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
				}, tt.loadErr).MaxTimes(1)

			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.LastTaskId),
				},
				{
					Name:     "retryable",
					Operator: "eq",
					Value:    protostruct.ToValue(true),
				},
			}
			taskHistoryMock := history2.NewMockTaskHistory(ctrl)
			taskHistoryMock.EXPECT().SearchInstanceAll(ctx, query, nil, 10, 1601996986, 1609772986).
				Return(nil, tt.retryErr).MaxTimes(1)

			objectMock := cmdb.NewMockObjectClient(ctrl)
			objectMock.EXPECT().GetDetail(ctx, &cmdb_object.GetDetailRequest{ObjectId: tt.args.request.ObjectConf.ObjectId}).Return(
				&cmdbmodel.CmdbObject{
					AttrList: []*cmdbmodel.ObjectAttr{
						{
							Id:    "instanceId",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "ctime",
							Value: &cmdbmodel.ObjectAttrValue{Type: "datetime"},
						},
						{
							Id:    "facilityCategory",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "facilityDescriptor",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
					},
				}, tt.getObjErr).MaxTimes(1)

			taskHistoryMock.EXPECT().GetInstance(ctx, "dataId33").Return(&fintech_data.ReportInstance{
				Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "cate3", "facilityDescriptor": "desc3", "required": "three"})}, nil).MaxTimes(1)
			taskHistoryMock.EXPECT().GetInstance(ctx, "dataId55").Return(&fintech_data.ReportInstance{
				Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "cate3", "facilityDescriptor": "desc3", "required": "three"})}, nil).MaxTimes(1)
			s := &instanceService{
				objectClient:   objectMock,
				instanceClient: instMock,
				opLogClient:    opLogMock,
				centerData:     centerDataMock,
				taskHistory:    taskHistoryMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				reportConf: config.ReportConf{SearchBatch: tt.fields.batch, TimeLimit: 90},
			}
			got, err := s.SearchReportInstance(tt.args.ctx, tt.args.request, tt.args.reportTask)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchReportInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchReportInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_SearchReportInstance_Relation(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		batch          int
	}
	type args struct {
		ctx        context.Context
		request    types.CreateTaskRequest
		reportTask *fintech_data.ReportTask
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		wantErr bool

		listErr   error
		getObjErr error
		loadErr   error
		searchErr error
		retryErr  error
	}{
		{
			name: "normal",
			fields: fields{

				batch: 10,
			},
			args: args{
				ctx: ctx,
				request: types.CreateTaskRequest{
					ObjectConf: &fintech_data.ReportObjectConf{
						InstanceId: "instId1",
						ObjectId:   "server",
						Source:     report_rule.ObjectSourceDirect,
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
			},
			want: []*fintech_data.ReportInstance{
				{
					InstanceId:         "11",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeNew,
					ObjectId:           "server",
					ShowKey:            "aa",
					FacilityDescriptor: "desc1",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "11",
						"ctime":                "2020-12-22 22:31",
						"facilityCategory":     "",
						"relationalIdentifier": "desc1",
					}),
				},
				{
					InstanceId:         "22",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeUpdate,
					ObjectId:           "server",
					ShowKey:            "bb",
					FacilityDescriptor: "desc2",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "22",
						"ctime":                "2020-12-20 22:31",
						"facilityCategory":     "",
						"relationalIdentifier": "desc2",
					}),
				},
				{
					InstanceId:         "33",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "server",
					FacilityCategory:   "cate3",
					FacilityDescriptor: "desc3",
					ShowKey:            "dd",
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":     "cate3",
						"relationalIdentifier": "desc3",
						"required":             "three",
					}),
				},
				{
					InstanceId:         "failId1",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "server",
					FacilityDescriptor: "desc6",
					FacilityCategory:   "cate6",
					RetryTimes:         1,
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":     "cate6",
						"relationalIdentifier": "desc6",
					}),
				},
				{
					InstanceId:         "failId2",
					TaskId:             "fakeId",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "server",
					FacilityDescriptor: "desc7",
					FacilityCategory:   "cate7",
					RetryTimes:         1,
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":     "cate7",
						"relationalIdentifier": "desc7",
					}),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opLogMock := notify2.NewMockOpLogClient(ctrl)
			centerDataMock := history2.NewMockCenterData(ctrl)
			instMock := cmdb.NewMockInstanceClient(ctrl)

			// searchDeleteInstance
			opLogMock.EXPECT().ListOperationLog(ctx, &notify.ListOperationLogRequest{
				Page:         1,
				PageSize:     10,
				System:       "cmdb",
				TargetId:     "server",
				Event:        "event.instance.delete",
				WithoutTotal: "false",
				StartTime:    tt.args.reportTask.LastReportTime,
				EndTime:      tt.args.reportTask.StartTime,
			}).Return(&oplog.ListOperationLogResponse{List: []*notify.OperationLog{
				{
					TargetId: "33",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "dd"}),
					Ctime:    1608211871,
				},
				{
					TargetId: "44",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "ee"}),
					Ctime:    1608631871,
				},
			}, Total: 1}, tt.listErr).Times(1)

			fields := []string{"instanceId", "facilityCategory", "facilityDescriptor", "objectId", "dataId"}
			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{"instanceId": map[string][]string{"$in": {"33", "44"}}}, fields).
				Return([]*history.ReportMetaData{
					{
						InstanceId:         "33",
						FacilityCategory:   "cate3",
						FacilityDescriptor: "desc3",
						ObjectId:           "server",
						DataId:             "dataId333",
					},
				}, nil).MaxTimes(1)
			// searchDeleteInstance
			opLogMock.EXPECT().ListOperationLog(ctx, &notify.ListOperationLogRequest{
				Page:         1,
				PageSize:     10,
				System:       "cmdb",
				TargetId:     "server",
				Event:        EventTypeArchive,
				WithoutTotal: "false",
				StartTime:    tt.args.reportTask.LastReportTime,
				EndTime:      tt.args.reportTask.StartTime,
			}).Return(&oplog.ListOperationLogResponse{List: []*notify.OperationLog{}, Total: 0}, tt.listErr).MaxTimes(1)

			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{"instanceId": map[string][]string{"$in": {}}}, fields).
				Return([]*history.ReportMetaData{}, nil).MaxTimes(1)
			// searchUpsertInstance
			instMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: "server",
				Query: protostruct.ToStruct(map[string]interface{}{"$and": []interface{}{
					map[string]interface{}{
						"_ts": map[string]interface{}{
							"$lt": 1608733871,
						},
					},
					map[string]interface{}{
						"_ts": map[string]interface{}{
							"$gte": 1608561071,
						},
					},
				}}),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*":                   true,
					cmdbutil.ShowKeyLabel: true,
				}),
				PageSize: int32(10),
				Page:     1,
			}).Return(&instance.PostSearchV2Response{
				Total: 4,
				List: []*pbtypes.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "11",
						"ctime":                "2020-12-22 22:31:11",
						"#showKey":             []string{"aa"},
						"relationalIdentifier": "desc1",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "22",
						"ctime":                "2020-12-20 22:31:11",
						"#showKey":             []string{"bb"},
						"relationalIdentifier": "desc2",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "33",
						"ctime":                "2020-12-19 22:31:11",
						"#showKey":             []string{"dd"},
						"relationalIdentifier": "desc3",
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":           "44",
						"ctime":                "2020-12-22 22:31:11",
						"#showKey":             []string{"ee"},
						"relationalIdentifier": "desc4",
					}),
				},
			}, tt.searchErr).MaxTimes(1)

			// compareWithExisted
			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{report_center.KeyFacilityDescriptor: map[string][]string{"$in": {"desc2"}}}, fields).
				Return([]*history.ReportMetaData{
					{
						InstanceId:         "22",
						ObjectId:           "server",
						FacilityCategory:   "cate2",
						FacilityDescriptor: "desc2",
					},
				}, tt.loadErr).MaxTimes(1)

			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.LastTaskId),
				},
				{
					Name:     "retryable",
					Operator: "eq",
					Value:    protostruct.ToValue(true),
				},
			}
			taskHistoryMock := history2.NewMockTaskHistory(ctrl)
			taskHistoryMock.EXPECT().SearchInstanceAll(ctx, query, nil, 10, 1601996986, 1609772986).
				Return([]*fintech_data.ReportInstance{
					{
						TaskId:             "oldId",
						BranchId:           "oldBranchId",
						InstanceId:         "failId1",
						ObjectId:           "server",
						FacilityDescriptor: "desc6",
						FacilityCategory:   "cate6",
						ReportType:         report_center.ReportTypeDelete,
						Data: protostruct.ToStruct(map[string]interface{}{
							"facilityCategory":     "cate6",
							"relationalIdentifier": "desc6",
						}),
					},
					{
						TaskId:             "oldId",
						BranchId:           "oldBranchId",
						InstanceId:         "failId2",
						ObjectId:           "server",
						FacilityDescriptor: "desc7",
						FacilityCategory:   "cate7",
						ReportType:         report_center.ReportTypeDelete,
						Data: protostruct.ToStruct(map[string]interface{}{
							"facilityCategory":     "cate7",
							"relationalIdentifier": "desc7",
						}),
					},
				}, tt.retryErr).MaxTimes(1)

			objectMock := cmdb.NewMockObjectClient(ctrl)
			objectMock.EXPECT().GetDetail(ctx, &cmdb_object.GetDetailRequest{ObjectId: tt.args.request.ObjectConf.ObjectId}).Return(
				&cmdbmodel.CmdbObject{
					AttrList: []*cmdbmodel.ObjectAttr{
						{
							Id:    "instanceId",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "ctime",
							Value: &cmdbmodel.ObjectAttrValue{Type: "datetime"},
						},
						{
							Id:    "facilityCategory",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "relationalIdentifier",
							Value: &cmdbmodel.ObjectAttrValue{Type: "str"},
						},
					},
				}, tt.getObjErr).MaxTimes(1)
			taskHistoryMock.EXPECT().GetInstance(ctx, "dataId333").Return(&fintech_data.ReportInstance{
				Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "cate3", "relationalIdentifier": "desc3", "required": "three"})}, nil).MaxTimes(1)
			taskHistoryMock.EXPECT().GetInstance(ctx, "dataId55").Return(&fintech_data.ReportInstance{
				Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "cate3", "facilityDescriptor": "desc3", "required": "three"})}, nil).MaxTimes(1)

			s := &instanceService{
				objectClient:   objectMock,
				instanceClient: instMock,
				opLogClient:    opLogMock,
				centerData:     centerDataMock,
				taskHistory:    taskHistoryMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				reportConf: config.ReportConf{
					SearchBatch: tt.fields.batch,
					TimeLimit:   90,
					PKTranslate: []config.KeyTranslate{
						{
							ObjectId:           "server",
							FacilityDescriptor: "relationalIdentifier",
							FacilityCategory:   "facilityCategory",
						},
					},
				},
			}
			got, err := s.SearchReportInstance(tt.args.ctx, tt.args.request, tt.args.reportTask)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchReportInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				for i, reportInstance := range got {
					if !reflect.DeepEqual(reportInstance, tt.want[i]) {
						t.Errorf("SearchReportInstance() got = %v, want %v", got, tt.want)
					}
				}
				//t.Errorf("SearchReportInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_searchDeleteInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		batch          int
	}
	type args struct {
		ctx        context.Context
		objectConf *fintech_data.ReportObjectConf
		reportTask *fintech_data.ReportTask
		EventType  string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    map[string]*deleteInfo
		want1   map[string]struct{}
		wantErr bool

		listErr error
		loadErr error
	}{
		{
			name: "normal",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				objectConf: &fintech_data.ReportObjectConf{
					InstanceId: "instId1",
					ObjectId:   "server",
					Source:     report_rule.ObjectSourceDirect,
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
				EventType: EventTypeDelete,
			},
			want: map[string]*deleteInfo{"descDD": {
				deleteTime: 1608561030,
				data: &history.ReportMetaData{
					InstanceId:         "33",
					FacilityCategory:   "gg",
					FacilityDescriptor: "descDD",
				},
				name: "dd",
			}},
			want1:   map[string]struct{}{"44": {}},
			wantErr: false,
		},
		{
			name: "load exist fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				objectConf: &fintech_data.ReportObjectConf{
					InstanceId: "instId1",
					ObjectId:   "server",
					Source:     report_rule.ObjectSourceDirect,
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
				EventType: EventTypeDelete,
			},
			loadErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name: "fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				objectConf: &fintech_data.ReportObjectConf{
					InstanceId: "instId1",
					ObjectId:   "server",
					Source:     report_rule.ObjectSourceDirect,
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
				EventType: EventTypeDelete,
			},
			listErr: fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opLogMock := notify2.NewMockOpLogClient(ctrl)
			opLogMock.EXPECT().ListOperationLog(ctx, &notify.ListOperationLogRequest{
				Page:         1,
				PageSize:     10,
				System:       "cmdb",
				TargetId:     "server",
				Event:        "event.instance.delete",
				StartTime:    tt.args.reportTask.LastReportTime,
				EndTime:      tt.args.reportTask.StartTime,
				WithoutTotal: "false",
			}).Return(&oplog.ListOperationLogResponse{List: []*notify.OperationLog{
				{
					TargetId: "33",
					Ctime:    1608561030,
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "dd"}),
				},
				{
					TargetId: "44",
					ExtInfo:  protostruct.ToStruct(map[string]interface{}{"instance_name": "ee"}),
				},
			}, Total: 2}, tt.listErr).Times(1)

			centerDataMock := history2.NewMockCenterData(ctrl)
			centerDataMock.EXPECT().SearchAll(ctx, map[string]interface{}{
				"instanceId": map[string][]string{"$in": {"33", "44"}},
			}, gomock.Any()).Return(
				[]*history.ReportMetaData{{
					InstanceId:         "33",
					FacilityCategory:   "gg",
					FacilityDescriptor: "descDD",
				}}, tt.loadErr).MaxTimes(1)
			s := &instanceService{
				instanceClient: tt.fields.instanceClient,
				opLogClient:    opLogMock,
				centerData:     centerDataMock,
				reportConf:     config.ReportConf{SearchBatch: tt.fields.batch},
			}
			got, got1, err := s.searchDeleteInstance(tt.args.ctx, tt.args.EventType, tt.args.objectConf, tt.args.reportTask)
			if (err != nil) != tt.wantErr {
				t.Errorf("searchDeleteInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("searchDeleteInstance() got = %v, want %v", got, tt.want)
			}
			if !reflect.DeepEqual(got1, tt.want1) {
				t.Errorf("searchDeleteInstance() got1 = %v, want1 %v", got1, tt.want1)
			}
		})
	}
}

func Test_instanceService_searchUpsertInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		batch          int
	}
	type args struct {
		ctx           context.Context
		converter     report_rule.Converter
		objectConf    *fintech_data.ReportObjectConf
		reportTask    *fintech_data.ReportTask
		deleteInstMap map[string]*deleteInfo
		newDeleteIds  map[string]struct{}
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		want1   []*fintech_data.ReportInstance
		wantErr bool

		searchErr error
	}{
		{
			name: "normal",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				objectConf: &fintech_data.ReportObjectConf{
					InstanceId: "instId1",
					ObjectId:   "server",
					Source:     report_rule.ObjectSourceDirect,
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
				deleteInstMap: map[string]*deleteInfo{
					"descDD": {
						deleteTime: 1608631871,
						data: &history.ReportMetaData{
							InstanceId:         "dd",
							FacilityCategory:   "gg",
							FacilityDescriptor: "descDD",
						},
						name: "dd",
					},
					"descEE": {
						deleteTime: 1608739871,
						data: &history.ReportMetaData{
							InstanceId:         "ee",
							FacilityCategory:   "gg",
							FacilityDescriptor: "descEE",
						},
						name: "ee",
					},
				},
				newDeleteIds: map[string]struct{}{"55": {}},
			},
			want: []*fintech_data.ReportInstance{
				{
					InstanceId:         "11",
					TaskId:             "fakeId",
					ReportType:         "new",
					ObjectId:           "server",
					FacilityDescriptor: "descAA",
					ShowKey:            "aa",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "11",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"aa"},
						report_center.KeyFacilityDescriptor: "descAA",
						"_ts":                               1608647471,
					}),
				},
			},
			want1: []*fintech_data.ReportInstance{
				{
					InstanceId:         "22",
					TaskId:             "fakeId",
					ReportType:         "update",
					ObjectId:           "server",
					FacilityDescriptor: "descBB",
					ShowKey:            "bb",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "22",
						"ctime":                             "2020-12-20 22:31:11",
						"#showKey":                          []string{"bb"},
						report_center.KeyFacilityDescriptor: "descBB",
						"_ts":                               1608647471,
					}),
				},
				{
					InstanceId:         "33",
					TaskId:             "fakeId",
					ReportType:         "update",
					ObjectId:           "server",
					FacilityDescriptor: "descDD",
					ShowKey:            "dd",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "33",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"dd"},
						report_center.KeyFacilityDescriptor: "descDD",
						"_ts":                               1608647471,
					}),
				},
			},
			wantErr: false,
		},
		{
			name: "search fail",
			fields: fields{
				batch: 10,
			},
			args: args{
				ctx: ctx,
				objectConf: &fintech_data.ReportObjectConf{
					InstanceId: "instId1",
					ObjectId:   "server",
					Source:     report_rule.ObjectSourceDirect,
				},
				reportTask: &fintech_data.ReportTask{
					TaskId:         "fakeId",
					ObjectId:       "server",
					LastReportTime: "2020-12-21 22:31:11",
					StartTime:      "2020-12-23 22:31:11",
				},
				deleteInstMap: map[string]*deleteInfo{
					"descDD": {
						deleteTime: 1608561030,
						data: &history.ReportMetaData{
							InstanceId:         "dd",
							FacilityCategory:   "gg",
							FacilityDescriptor: "descDD",
						},
						name: "dd",
					}},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instMock := cmdb.NewMockInstanceClient(ctrl)
			instMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: "server",
				Query: protostruct.ToStruct(map[string]interface{}{
					"$and": []interface{}{
						map[string]interface{}{
							"_ts": map[string]interface{}{
								"$lt": 1608733871,
							},
						},
						map[string]interface{}{
							"_ts": map[string]interface{}{
								"$gte": 1608561071,
							},
						},
					},
				}),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*":                   true,
					cmdbutil.ShowKeyLabel: true,
				}),
				PageSize: int32(10),
				Page:     1,
			}).Return(&instance.PostSearchV2Response{
				Total: 5,
				List: []*pbtypes.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "11",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"aa"},
						report_center.KeyFacilityDescriptor: "descAA",
						"_ts":                               1608647471,
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "22",
						"ctime":                             "2020-12-20 22:31:11",
						"#showKey":                          []string{"bb"},
						report_center.KeyFacilityDescriptor: "descBB",
						"_ts":                               1608647471,
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "33",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"dd"},
						report_center.KeyFacilityDescriptor: "descDD",
						"_ts":                               1608647471,
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "44",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"ee"},
						report_center.KeyFacilityDescriptor: "descEE",
						"_ts":                               1608647471,
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "55",
						"ctime":                             "2020-12-22 22:31:11",
						"#showKey":                          []string{"ff"},
						report_center.KeyFacilityDescriptor: "descFF",
						"_ts":                               1608647471,
					}),
				},
			}, tt.searchErr).Times(1)
			s := &instanceService{
				instanceClient: instMock,
				opLogClient:    tt.fields.opLogClient,
				centerData:     tt.fields.centerData,
				reportConf: config.ReportConf{
					SearchBatch: tt.fields.batch,
					IgnoreConf: config.IgnoreConf{
						InstanceIgnoreAttr: "ignore",
					},
				},
			}
			got, got1, err := s.searchUpsertInstance(tt.args.ctx, report_rule.Converter{}, tt.args.objectConf, tt.args.reportTask, tt.args.deleteInstMap, tt.args.newDeleteIds)
			if (err != nil) != tt.wantErr {
				t.Errorf("searchUpsertInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("searchUpsertInstance() got = %v, want %v", got, tt.want)
			}
			if !reflect.DeepEqual(got1, tt.want1) {
				t.Errorf("searchUpsertInstance() got1 = %v, want1 %v", got1, tt.want1)
			}
		})
	}
}

func Test_instanceService_searchRetryInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		taskHistory    history.TaskHistory
		reportConf     config.ReportConf
		nowTimeFunc    timeutil.NowTimeFunc
	}
	type args struct {
		ctx           context.Context
		converter     report_rule.Converter
		reportTask    *fintech_data.ReportTask
		reportList    []*fintech_data.ReportInstance
		deleteInstMap map[string]struct{}
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		wantErr bool

		retryList []*fintech_data.ReportInstance
		retryErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportList: []*fintech_data.ReportInstance{
					{
						TaskId:             "newId",
						InstanceId:         "id2",
						FacilityDescriptor: "desc2",
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId: "newId",
				},
				deleteInstMap: map[string]struct{}{
					"desc4": {},
				},
			},
			wantErr: false,
			retryList: []*fintech_data.ReportInstance{
				{
					TaskId:             "oldId",
					BranchId:           "oldBranchId",
					InstanceId:         "failId1",
					FacilityDescriptor: "desc1",
				},
				{
					TaskId:             "oldId",
					BranchId:           "oldBranchId",
					InstanceId:         "id2",
					FacilityDescriptor: "desc2",
				},
				{
					TaskId:             "oldId",
					BranchId:           "oldBranchId",
					InstanceId:         "failId3",
					FacilityDescriptor: "desc3",
				},
				{
					TaskId:             "oldId",
					BranchId:           "oldBranchId",
					InstanceId:         "deleteId",
					FacilityDescriptor: "desc4",
				},
			},
			retryErr: nil,
			want: []*fintech_data.ReportInstance{
				{
					TaskId:             "newId",
					InstanceId:         "failId1",
					RetryTimes:         1,
					FacilityDescriptor: "desc1",
				},
				{
					TaskId:             "newId",
					InstanceId:         "failId3",
					RetryTimes:         1,
					FacilityDescriptor: "desc3",
				},
			},
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				reportList: []*fintech_data.ReportInstance{
					{
						TaskId:     "newId",
						InstanceId: "id2",
					},
				},
				reportTask: &fintech_data.ReportTask{
					TaskId: "newId",
				},
			},
			wantErr:  true,
			retryErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			query := []*monthly_collection_service.QueryItem{
				{
					Name:     "taskId",
					Operator: "eq",
					Value:    protostruct.ToValue(tt.args.reportTask.LastTaskId),
				},
				{
					Name:     "retryable",
					Operator: "eq",
					Value:    protostruct.ToValue(true),
				},
			}
			historyMock.EXPECT().SearchInstanceAll(ctx, query, nil, 10, 1601996986, 1609772986).
				Return(tt.retryList, tt.retryErr).MaxTimes(1)
			s := &instanceService{
				instanceClient: tt.fields.instanceClient,
				opLogClient:    tt.fields.opLogClient,
				centerData:     tt.fields.centerData,
				taskHistory:    historyMock,
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
					return t
				},
				reportConf: config.ReportConf{SearchBatch: 10, TimeLimit: 90},
			}
			got, err := s.searchRetryInstance(tt.args.ctx, tt.args.converter, tt.args.reportTask, tt.args.reportList, tt.args.deleteInstMap)
			if (err != nil) != tt.wantErr {
				t.Errorf("searchRetryInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("searchRetryInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_compareWithExisted(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		instanceClient instance.Client
		opLogClient    oplog.Client
		centerData     history.CenterData
		taskHistory    history.TaskHistory
		reportConf     config.ReportConf
		nowTimeFunc    timeutil.NowTimeFunc
	}
	type args struct {
		ctx           context.Context
		updateList    []*fintech_data.ReportInstance
		deleteInstMap map[string]*deleteInfo
		reportTask    *fintech_data.ReportTask
		converter     report_rule.Converter
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportInstance
		wantErr bool

		dataList []*history.ReportMetaData
		loadErr  error
	}{
		{
			name:   "no search",
			fields: fields{},
			args: args{
				ctx:           ctx,
				updateList:    nil,
				deleteInstMap: nil,
				reportTask:    &fintech_data.ReportTask{},
			},
			want:    nil,
			wantErr: false,
		},
		{
			name:   "success",
			fields: fields{},
			args: args{
				ctx: ctx,
				updateList: []*fintech_data.ReportInstance{
					{
						InstanceId:         "11",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "aa",
						FacilityDescriptor: "aa",
						Data: protostruct.ToStruct(map[string]interface{}{
							"instanceId":                        "11",
							report_center.KeyFacilityDescriptor: "aa",
							"_ts":                               1608647471,
						}),
					},
					{
						InstanceId:         "22",
						ReportType:         report_center.ReportTypeUpdate,
						FacilityCategory:   "bb",
						FacilityDescriptor: "bb",
						Data: protostruct.ToStruct(map[string]interface{}{
							"instanceId":                        "22",
							report_center.KeyFacilityDescriptor: "bb",
							"_ts":                               1608647471,
						}),
					},
				},
				deleteInstMap: nil,
				reportTask:    &fintech_data.ReportTask{},
				converter:     report_rule.Converter{},
			},
			dataList: []*history.ReportMetaData{
				{
					InstanceId:         "22",
					Version:            1,
					ObjectId:           "server",
					FacilityCategory:   "bb",
					FacilityDescriptor: "bb",
				},
				{
					InstanceId:         "33",
					Version:            2,
					ObjectId:           "server",
					FacilityCategory:   "dd",
					FacilityDescriptor: "dd",
				},
			},
			want: []*fintech_data.ReportInstance{
				{
					InstanceId:         "11",
					ReportType:         report_center.ReportTypeNew,
					FacilityCategory:   "aa",
					FacilityDescriptor: "aa",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "11",
						report_center.KeyFacilityDescriptor: "aa",
						"_ts":                               1608647471,
					}),
				},
				{
					InstanceId:         "22",
					ReportType:         report_center.ReportTypeUpdate,
					FacilityCategory:   "bb",
					FacilityDescriptor: "bb",
					Data: protostruct.ToStruct(map[string]interface{}{
						"instanceId":                        "22",
						report_center.KeyFacilityDescriptor: "bb",
						"_ts":                               1608647471,
					}),
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerDataMock := history2.NewMockCenterData(ctrl)
			fields := []string{"instanceId", "facilityCategory", "facilityDescriptor", "objectId", "dataId"}
			centerDataMock.EXPECT().SearchAll(tt.args.ctx, map[string]interface{}{report_center.KeyFacilityDescriptor: map[string][]string{"$in": {"aa", "bb"}}}, fields).
				Return(tt.dataList, tt.loadErr).MaxTimes(1)

			s := &instanceService{
				instanceClient: tt.fields.instanceClient,
				opLogClient:    tt.fields.opLogClient,
				centerData:     centerDataMock,
				taskHistory:    tt.fields.taskHistory,
				reportConf:     tt.fields.reportConf,
				nowTimeFunc:    tt.fields.nowTimeFunc,
			}
			got, err := s.compareWithExisted(tt.args.ctx, tt.args.converter, tt.args.updateList, tt.args.reportTask)
			if (err != nil) != tt.wantErr {
				t.Errorf("compareWithExisted() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("compareWithExisted() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_filterIgnoreInstance(t *testing.T) {
	type fields struct {
		instanceClient    instance.Client
		opLogClient       oplog.Client
		centerData        history.CenterData
		taskHistory       history.TaskHistory
		reportConf        config.ReportConf
		nowTimeFunc       timeutil.NowTimeFunc
		relationFillRules []fill_instance.RelationRule
	}
	type args struct {
		reportList []*fintech_data.ReportInstance
		converter  report_rule.Converter
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   []*fintech_data.ReportInstance
	}{
		{
			name: "",
			fields: fields{
				reportConf: config.ReportConf{
					IgnoreConf: config.IgnoreConf{InstanceIgnoreAttr: "ignore"},
				},
			},
			args: args{
				reportList: []*fintech_data.ReportInstance{
					{
						Data: protostruct.ToStruct(map[string]interface{}{"ignore": true, "facilityCategory": "one"}),
					},
					{
						Data: protostruct.ToStruct(map[string]interface{}{"ignore": false, "facilityCategory": "three"}),
					},
					{
						Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "two"}),
					},
				},
			},
			want: []*fintech_data.ReportInstance{
				{
					Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "three"}),
				},
				{
					Data: protostruct.ToStruct(map[string]interface{}{"facilityCategory": "two"}),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &instanceService{
				instanceClient:    tt.fields.instanceClient,
				opLogClient:       tt.fields.opLogClient,
				centerData:        tt.fields.centerData,
				taskHistory:       tt.fields.taskHistory,
				reportConf:        tt.fields.reportConf,
				nowTimeFunc:       tt.fields.nowTimeFunc,
				relationFillRules: tt.fields.relationFillRules,
			}
			if got := s.filterIgnoreInst(tt.args.reportList); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("filterIgnoreInstance() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_instanceService_convertDeleteData(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		instanceClient    instance.Client
		objectClient      cmdb_object.Client
		opLogClient       oplog.Client
		centerData        history.CenterData
		taskHistory       history.TaskHistory
		reportConf        config.ReportConf
		nowTimeFunc       timeutil.NowTimeFunc
		relationFillRules []fill_instance.RelationRule
	}
	type args struct {
		ctx           context.Context
		converter     report_rule.Converter
		reportTask    *fintech_data.ReportTask
		deleteInstMap map[string]*deleteInfo
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   []*fintech_data.ReportInstance
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:       ctx,
				converter: report_rule.Converter{},
				reportTask: &fintech_data.ReportTask{
					TaskId:   "taskId1",
					ObjectId: "host",
				},
				deleteInstMap: map[string]*deleteInfo{
					"one": {
						data: &history.ReportMetaData{
							InstanceId:         "123",
							Version:            0,
							ObjectId:           "host",
							FacilityCategory:   "abc",
							FacilityDescriptor: "abc",
							Ts:                 0,
							DataId:             "one",
						},
						name: "one",
					},
				},
			},
			want: []*fintech_data.ReportInstance{
				{
					InstanceId:         "123",
					TaskId:             "taskId1",
					ReportType:         report_center.ReportTypeDelete,
					ObjectId:           "host",
					FacilityCategory:   "abc",
					FacilityDescriptor: "abc",
					ShowKey:            "one",
					Data: protostruct.ToStruct(map[string]interface{}{
						"facilityCategory":   "abc",
						"facilityDescriptor": "abc",
					}),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			historyMock := history2.NewMockTaskHistory(ctrl)
			historyMock.EXPECT().GetInstance(tt.args.ctx, "one").Return(nil, fmt.Errorf("mock fail")).Times(1)
			s := &instanceService{
				instanceClient:    tt.fields.instanceClient,
				objectClient:      tt.fields.objectClient,
				opLogClient:       tt.fields.opLogClient,
				centerData:        tt.fields.centerData,
				taskHistory:       historyMock,
				reportConf:        tt.fields.reportConf,
				nowTimeFunc:       tt.fields.nowTimeFunc,
				relationFillRules: tt.fields.relationFillRules,
			}
			if got := s.convertDeleteData(tt.args.ctx, tt.args.converter, tt.args.reportTask, tt.args.deleteInstMap); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("convertDeleteData() = %v, want %v", got, tt.want)
			}
		})
	}
}
