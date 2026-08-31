package report_rule

import (
	"context"
	"fmt"
	"reflect"
	"testing"

	"github.com/easyops-cn/giraffe-micro/codes"
	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	cmdb2 "go.easyops.local/fintech_data/mock/remote/cmdb"
	giraffe "go.easyops.local/giraffe-micro"
	"go.easyops.local/giraffe-micro/pkg/gerr"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func Test_ruleToStruct(t *testing.T) {
	type args struct {
		rule *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name string
		args args
		want *types.Struct
	}{
		{
			name: "",
			args: args{
				rule: nil,
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ruleToStruct(tt.args.rule); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ruleToStruct() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_UpdateRule(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx          context.Context
		instanceId   string
		rule         *fintech_data.ReportObjectConf
		updateFields []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		getResp *cmdb_object.GetObjectAllResponse
		getErr  error

		updateErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					Enable:          true,
					BatchNum:        0,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
						},
					},
				},
				updateFields: []string{"objectId", "mappingObjectId", "source", "enable", "batchNum", "mappingRule"},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			wantErr: false,
		},
		{
			name:   "rule invalid",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					Enable:          true,
					BatchNum:        0,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
						},
					},
				},
				updateFields: []string{"objectId", "mappingObjectId", "source", "enable", "batchNum", "mappingRule"},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			wantErr: true,
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					Enable:          true,
					BatchNum:        0,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
						},
					},
				},
				updateFields: []string{"objectId", "mappingObjectId", "source", "enable", "batchNum", "mappingRule"},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			updateErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			objectMock := cmdb2.NewMockObjectClient(ctrl)
			objectMock.EXPECT().GetObjectAll(tt.args.ctx, &cmdb_object.GetObjectAllRequest{
				ObjectIds: "server,HOST",
			}).Return(tt.getResp, tt.getErr).MaxTimes(1)
			updateData := map[string]interface{}{
				"objectId":        "server",
				"source":          "mapping",
				"mappingObjectId": "HOST",
				"mappingRule": map[string]interface{}{
					"attrMapping": []interface{}{
						map[string]interface{}{
							"reportAttrId":  "serverIp",
							"mappingAttrId": "ip",
						},
						map[string]interface{}{
							"reportAttrId":  "name",
							"mappingAttrId": "hostname",
						},
					},
				},
				"batchNum": 0,
				"enable":   true,
			}
			instanceMock := cmdb2.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().UpdateInstanceV2(ctx, &instance.UpdateInstanceV2Request{
				ObjectId:       ruleObjId,
				InstanceId:     tt.args.instanceId,
				Instance:       protostruct.ToStruct(updateData),
				OnlyInstanceId: true,
			}).Return(nil, tt.updateErr).MaxTimes(1)

			i := &serviceImp{
				objectClient:   objectMock,
				instanceClient: instanceMock,
			}
			if err := i.UpdateRule(tt.args.ctx, tt.args.instanceId, tt.args.rule, tt.args.updateFields); (err != nil) != tt.wantErr {
				t.Errorf("UpdateRule() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_serviceImp_getRuleObjects(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx  context.Context
		rule *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *cmdb.CmdbObject
		want1   *cmdb.CmdbObject
		wantErr bool

		getResp *cmdb_object.GetObjectAllResponse
		getErr  error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
				},
			},

			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
				},
				{
					ObjectId: "server",
				},
			}},
			want: &cmdb.CmdbObject{
				ObjectId: "server",
			},
			want1: &cmdb.CmdbObject{
				ObjectId: "HOST",
			},
			wantErr: false,
		},
		{
			name:   "object not found",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
				},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
				},
			}},
			wantErr: true,
		},
		{
			name:   "get fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
				},
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			objectMock := cmdb2.NewMockObjectClient(ctrl)
			objectMock.EXPECT().GetObjectAll(tt.args.ctx, &cmdb_object.GetObjectAllRequest{
				ObjectIds: "server,HOST",
			}).Return(tt.getResp, tt.getErr).Times(1)
			i := &serviceImp{
				objectClient:   objectMock,
				instanceClient: tt.fields.instanceClient,
			}
			got, got1, err := i.getRuleObjects(tt.args.ctx, tt.args.rule)
			if (err != nil) != tt.wantErr {
				t.Errorf("getRuleObjects() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("getRuleObjects() got = %v, want %v", got, tt.want)
			}
			if !reflect.DeepEqual(got1, tt.want1) {
				t.Errorf("getRuleObjects() got1 = %v, want %v", got1, tt.want1)
			}
		})
	}
}

func Test_serviceImp_syncReportObjectAtt(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx  context.Context
		rule *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		updateObj *cmdb.CmdbObject
		getResp   *cmdb_object.GetObjectAllResponse
		getErr    error

		importResp *cmdb_object.ImportV2Response
		importErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
							{
								ReportAttrId:  "other",
								MappingAttrId: "",
							},
						},
					},
				},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			updateObj: &cmdb.CmdbObject{
				ObjectId: "HOST",
				AttrList: []*cmdb.ObjectAttr{
					{
						Id:    "ip",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
					{
						Id:    "hostname",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
					{
						Id:    "other",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
				},
			},
			importResp: &cmdb_object.ImportV2Response{ImportResult: []*cmdb.ImportResult{{ObjectId: "HOST"}}},
			wantErr:    false,
		},
		{
			name:   "get object fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
							{
								ReportAttrId:  "other",
								MappingAttrId: "",
							},
						},
					},
				},
			},
			getErr:  fmt.Errorf("mock fail"),
			wantErr: true,
		},
		{
			name:   "check attr fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
							{
								ReportAttrId:  "other",
								MappingAttrId: "",
							},
						},
					},
				},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "int"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			wantErr: true,
		},
		{
			name:   "import fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				rule: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  "serverIp",
								MappingAttrId: "ip",
							},
							{
								ReportAttrId:  "name",
								MappingAttrId: "hostname",
							},
							{
								ReportAttrId:  "other",
								MappingAttrId: "",
							},
						},
					},
				},
			},
			getResp: &cmdb_object.GetObjectAllResponse{Data: []*cmdb.CmdbObject{
				{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			}},
			updateObj: &cmdb.CmdbObject{
				ObjectId: "HOST",
				AttrList: []*cmdb.ObjectAttr{
					{
						Id:    "ip",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
					{
						Id:    "hostname",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
					{
						Id:    "other",
						Value: &cmdb.ObjectAttrValue{Type: "str"},
					},
				},
			},
			importErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			objectMock := cmdb2.NewMockObjectClient(ctrl)
			objectMock.EXPECT().GetObjectAll(tt.args.ctx, &cmdb_object.GetObjectAllRequest{
				ObjectIds: "server,HOST",
			}).Return(tt.getResp, tt.getErr).MaxTimes(1)
			objectMock.EXPECT().ImportV2(tt.args.ctx,
				&cmdb_object.ImportV2Request{ObjectList: []*cmdb.CmdbObject{tt.updateObj}},
			).Return(tt.importResp, tt.importErr).MaxTimes(1)
			i := &serviceImp{
				objectClient:   objectMock,
				instanceClient: tt.fields.instanceClient,
			}
			if err := i.syncReportObjectAtt(tt.args.ctx, tt.args.rule); (err != nil) != tt.wantErr {
				t.Errorf("syncReportObjectAtt() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_serviceImp_updateMappingObject(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx context.Context
		obj *cmdb.CmdbObject
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		importResp *cmdb_object.ImportV2Response
		importErr  error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				obj: &cmdb.CmdbObject{
					ObjectId: "TEST",
				},
			},
			importResp: &cmdb_object.ImportV2Response{
				ImportResult: []*cmdb.ImportResult{
					{
						ObjectId: "TEST",
					},
				},
			},
			wantErr: false,
		},
		{
			name:   "request fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				obj: &cmdb.CmdbObject{
					ObjectId: "TEST",
				},
			},
			importErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "result fail",
			fields: fields{},
			args: args{
				ctx: context.Background(),
				obj: &cmdb.CmdbObject{
					ObjectId: "TEST",
				},
			},
			importResp: &cmdb_object.ImportV2Response{
				ImportResult: []*cmdb.ImportResult{
					{
						ObjectId: "TEST",
						Code:     130000,
						AttrListResult: []*cmdb.ImportStatus{
							{
								Id:      "test",
								Name:    "test",
								Code:    1300000,
								Message: "fail",
							},
						},
					},
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			objectMock := cmdb2.NewMockObjectClient(ctrl)
			objectMock.EXPECT().ImportV2(tt.args.ctx,
				&cmdb_object.ImportV2Request{ObjectList: []*cmdb.CmdbObject{tt.args.obj}},
			).Return(tt.importResp, tt.importErr).Times(1)

			i := &serviceImp{
				objectClient:   objectMock,
				instanceClient: tt.fields.instanceClient,
			}
			if err := i.updateMappingObject(tt.args.ctx, tt.args.obj); (err != nil) != tt.wantErr {
				t.Errorf("updateMappingObject() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_checkAttrMapping(t *testing.T) {
	type args struct {
		reportObj  *cmdb.CmdbObject
		mappingObj *cmdb.CmdbObject
		attrConf   *fintech_data.AttrMapping
	}
	tests := []struct {
		name    string
		args    args
		wantErr bool
	}{
		{
			name: "normal",
			args: args{
				attrConf: &fintech_data.AttrMapping{
					ReportAttrId:  "serverIp",
					MappingAttrId: "ip",
				},
				mappingObj: &cmdb.CmdbObject{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				reportObj: &cmdb.CmdbObject{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "report attr not found",
			args: args{
				attrConf: &fintech_data.AttrMapping{
					ReportAttrId:  "other",
					MappingAttrId: "ip",
				},
				mappingObj: &cmdb.CmdbObject{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				reportObj: &cmdb.CmdbObject{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			},
			wantErr: true,
		},
		{
			name: "mapping attr not found",
			args: args{
				attrConf: &fintech_data.AttrMapping{
					ReportAttrId:  "serverIp",
					MappingAttrId: "other",
				},
				mappingObj: &cmdb.CmdbObject{
					ObjectId: "HOST",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "ip",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "hostname",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
				reportObj: &cmdb.CmdbObject{
					ObjectId: "server",
					AttrList: []*cmdb.ObjectAttr{
						{
							Id:    "serverIp",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "name",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
						{
							Id:    "other",
							Value: &cmdb.ObjectAttrValue{Type: "str"},
						},
					},
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := checkAttrMapping(tt.args.reportObj, tt.args.mappingObj, tt.args.attrConf); (err != nil) != tt.wantErr {
				t.Errorf("checkAttrMapping() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestNewService(t *testing.T) {
	type args struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	tests := []struct {
		name string
		args args
		want Service
	}{
		{
			name: "",
			args: args{},
			want: &serviceImp{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := NewService(tt.args.objectClient, tt.args.instanceClient); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("NewService() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_SearchRule(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx    context.Context
		query  map[string]interface{}
		fields []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []*fintech_data.ReportObjectConf
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
			want: []*fintech_data.ReportObjectConf{
				{
					InstanceId:      "xxxx",
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
				},
			},
			wantErr: false,
			searchResp: &instance.PostSearchV2Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":      "xxxx",
						"objectId":        "server",
						"source":          "mapping",
						"mappingObjectId": "HOST",
					}),
				},
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
			searchErr: nil,
		},
		{
			name:   "fail",
			fields: fields{},
			args: args{
				ctx:    ctx,
				fields: []string{"*"},
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
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
						"instanceId":      "xxxx",
						"objectId":        []string{"ss"},
						"source":          "mapping",
						"mappingObjectId": "HOST",
					}),
				},
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb2.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: ruleObjId,
				Query:    protostruct.ToStruct(tt.args.query),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*": true,
				}),
				Page:     1,
				PageSize: 3000,
			}).Return(tt.searchResp, tt.searchErr).Times(1)
			i := &serviceImp{
				objectClient:   tt.fields.objectClient,
				instanceClient: instanceMock,
			}
			got, err := i.SearchRule(tt.args.ctx, tt.args.query, tt.args.fields)
			if (err != nil) != tt.wantErr {
				t.Errorf("SearchRule() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("SearchRule() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_GetRule(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx      context.Context
		objectId string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *fintech_data.ReportObjectConf
		wantErr bool

		searchResp *instance.PostSearchV2Response
		searchErr  error
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "HOST",
			},
			want: &fintech_data.ReportObjectConf{
				InstanceId:      "xxxx",
				ObjectId:        "server",
				MappingObjectId: "HOST",
				Source:          ObjectSourceMapping,
			},
			wantErr: false,
			searchResp: &instance.PostSearchV2Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId":      "xxxx",
						"objectId":        "server",
						"source":          "mapping",
						"mappingObjectId": "HOST",
					}),
				},
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
			searchErr: nil,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "HOST",
			},
			wantErr: true,
			searchResp: &instance.PostSearchV2Response{
				List:     nil,
				Total:    1,
				Page:     1,
				PageSize: 1,
			},
			searchErr: nil,
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "HOST",
			},
			wantErr:   true,
			searchErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb2.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().PostSearchV2(tt.args.ctx, &instance.PostSearchV2Request{
				ObjectId: ruleObjId,
				Query:    protostruct.ToStruct(map[string]interface{}{"objectId": tt.args.objectId}),
				Fields: protostruct.ToStruct(map[string]interface{}{
					"*": true,
				}),
				Page:     1,
				PageSize: 3000,
			}).Return(tt.searchResp, tt.searchErr).Times(1)
			i := &serviceImp{
				objectClient:   tt.fields.objectClient,
				instanceClient: instanceMock,
			}
			got, err := i.GetRule(tt.args.ctx, tt.args.objectId)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetRule() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetRule() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_UpdateRuleByQuery(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		objectClient   cmdb_object.Client
		instanceClient instance.Client
	}
	type args struct {
		ctx          context.Context
		query        map[string]interface{}
		rule         *fintech_data.ReportObjectConf
		updateFields []string
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    int
		wantErr bool

		updateErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: map[string]interface{}{
					"instanceId": "abc",
				},
				rule: &fintech_data.ReportObjectConf{
					NextExecTime: "2012-12-21 23:21:40",
				},
				updateFields: []string{"nextExecTime"},
			},
			want:    1,
			wantErr: false,
		},
		{
			name:   "update fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				query: map[string]interface{}{
					"instanceId": "abc",
				},
				rule: &fintech_data.ReportObjectConf{
					NextExecTime: "2012-12-21 23:21:40",
				},
				updateFields: []string{"nextExecTime"},
			},
			updateErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instMock := cmdb2.NewMockInstanceClient(ctrl)
			instMock.EXPECT().UpdateByQuery(ctx, &instance.UpdateByQueryRequest{
				ObjectId: ruleObjId,
				Query: protostruct.ToStruct(map[string]interface{}{
					"instanceId": "abc",
				}),
				Data: protostruct.ToStruct(map[string]interface{}{
					"nextExecTime": "2012-12-21 23:21:40",
				}),
			}).Return(&instance.UpdateByQueryResponse{SuccessTotal: 1}, tt.updateErr).Times(1)
			i := &serviceImp{
				objectClient:   tt.fields.objectClient,
				instanceClient: instMock,
			}
			got, err := i.UpdateRuleByQuery(tt.args.ctx, tt.args.query, tt.args.rule, tt.args.updateFields)
			if (err != nil) != tt.wantErr {
				t.Errorf("UpdateRuleByQuery() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("UpdateRuleByQuery() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_formatErr(t *testing.T) {
	type args struct {
		err error
	}
	tests := []struct {
		name    string
		args    args
		wantErr bool
	}{
		{
			name: "",
			args: args{
				err: gerr.ErrorProto(&giraffe.Status{Code: codes.Code(130600)}),
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := formatErr(tt.args.err); (err != nil) != tt.wantErr {
				t.Errorf("formatErr() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
