package fill_instance

import (
	"context"
	"fmt"
	"reflect"
	"sort"
	"testing"

	"github.com/gogo/protobuf/types"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	notifymodel "go.easyops.local/contracts/protorepo-models/easyops/model/notify"
	"go.easyops.local/contracts/protorepo-notify/subscriber"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/fintech_data/internal/extends/cmdbutil"
	"go.easyops.local/fintech_data/mock/remote/cmdb"
	"go.easyops.local/fintech_data/mock/remote/notify"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewProcessor(t *testing.T) {
	type args struct {
		instanceRules     []InstanceRule
		relationRules     []RelationRule
		instanceClient    instance.Client
		subscriberClient  subscriber.Client
		subscriberProcNum int
	}
	tests := []struct {
		name string
		args args
		want Service
	}{
		{
			name: "",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewService(tt.args.instanceRules, tt.args.relationRules, tt.args.instanceClient, tt.args.subscriberClient, tt.args.subscriberProcNum)
		})
	}
}

func Test_serviceImp_FillInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx      context.Context
		objectId string
		instList []ProcessItem
	}
	type relatedInst struct {
		resp *instance.PostSearchV3Response
		err  error
	}
	relatedRules := []RelationRule{
		{
			RuleObjectConf: RuleObjectConf{
				ObjectId: "server",
			},
			SourceField: "cateId",
			RelatedInstance: RelatedInstance{
				ObjectId:     "idc",
				RelatedField: "idcName",
			},
			Mapping: []RelatedMapping{
				{
					AttrId:     "cateId",
					MappingKey: "idcCate",
				},
			},
		},
		{
			RuleObjectConf: RuleObjectConf{
				ObjectIdList: []string{"server"},
			},
			SourceField: "structs.relId",
			RelatedInstance: RelatedInstance{
				ObjectId:     "deployDb",
				RelatedField: "dbName",
			},
			Mapping: []RelatedMapping{
				{
					AttrId:     "relId",
					MappingKey: "deployId",
				},
				{
					AttrId:     "relCate",
					MappingKey: "deployCate",
				},
			},
		},
	}
	instanceRules := []InstanceRule{
		{
			RuleObjectConf: RuleObjectConf{
				ObjectId: "server",
			},
			AttrId: "memo",
			AttrSource: []AttrDefine{
				{
					Key:        "name",
					IgnoreFail: true,
					ValuePath: ValuePath{
						Path:   "$.name",
						Source: SourceTypeInstance,
					},
				},
			},
			Case: []Case{
				{
					Rel: "",
					Condition: []Condition{
						{
							Key:   "name",
							Opr:   OprEqual,
							Value: "name1",
						},
					},
					Value: Value{
						Type:  ValueTypeConst,
						Const: "one",
					},
				},
			},
		},
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		fetchResp *instance.PostSearchV3Response
		fetchErr  error

		relatedList []relatedInst

		importList []*types.Struct
		importResp *instance.ImportInstanceResponse
		importErr  error
	}{
		{
			name: "update instance fail",
			fields: fields{
				relationRules: relatedRules,
				instanceRules: instanceRules,
			},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{"name"},
					},
				},
			},
			wantErr: true,
			fetchResp: &instance.PostSearchV3Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId": "id1",
						"name":       "name1",
						"cateId":     "cate1",
					}),
				},
			},
			importList: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{
					"instanceId": "id1",
					"memo":       "one",
				}),
			},
			importErr: fmt.Errorf("mock fail"),
		},
		{
			name: "happy path",
			fields: fields{
				relationRules: relatedRules,
				instanceRules: instanceRules,
			},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{"name", "cateId", "structs"},
					},
					{
						InstanceId:   "id2",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{},
					},
				},
			},
			wantErr: false,
			fetchResp: &instance.PostSearchV3Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId": "id1",
						"name":       "name1",
						"cateId":     "cate1",
						"structs": []map[string]interface{}{
							{
								"relId": "R1",
								"other": "haha",
							},
							{
								"relId": "R2",
							},
						},
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId": "id2",
						"name":       "name2",
						"cateId":     "cate2",
					}),
				},
			},
			relatedList: []relatedInst{
				{
					resp: &instance.PostSearchV3Response{
						List: []*types.Struct{
							protostruct.ToStruct(map[string]interface{}{
								"idcName": "cate1",
								"idcCate": "idcCate1",
							}),
							protostruct.ToStruct(map[string]interface{}{
								"idcName": "cate2",
								"idcCate": "idcCate2",
							}),
						},
					},
				},
				{
					resp: &instance.PostSearchV3Response{
						List: []*types.Struct{
							protostruct.ToStruct(map[string]interface{}{
								"dbName":     "R1",
								"deployId":   "deployId1",
								"deployCate": "idcCate1",
							}),
							protostruct.ToStruct(map[string]interface{}{
								"dbName":     "R2",
								"deployId":   "deployId2",
								"deployCate": "idcCate2",
							}),
						},
					},
				},
			},
			importList: []*types.Struct{
				protostruct.ToStruct(map[string]interface{}{
					"instanceId": "id1",
					"cateId":     "cate1[idcCate1]",
					"memo":       "one",
					"structs": []map[string]interface{}{
						{
							"relId":   "R1[deployId1]",
							"other":   "haha",
							"relCate": "idcCate1",
						},
						{
							"relId":   "R2[deployId2]",
							"relCate": "idcCate2",
						},
					},
				}),
				protostruct.ToStruct(map[string]interface{}{
					"instanceId": "id2",
					"cateId":     "cate2[idcCate2]",
				}),
			},
			importResp: &instance.ImportInstanceResponse{
				UpdateCount: 2,
			},
		},
		{
			name: "fetch instance fail",
			fields: fields{
				relationRules: relatedRules,
				instanceRules: instanceRules,
			},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{"name", "cateId", "structs"},
					},
					{
						InstanceId:   "id2",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{},
					},
				},
			},
			wantErr:  true,
			fetchErr: fmt.Errorf("mock fail"),
		},
		{
			name: "search related fail",
			fields: fields{
				relationRules: relatedRules,
				instanceRules: instanceRules,
			},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{"name", "cateId", "structs"},
					},
					{
						InstanceId:   "id2",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{},
					},
				},
			},
			wantErr: true,
			fetchResp: &instance.PostSearchV3Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"instanceId": "id1",
						"name":       "name1",
						"cateId":     "cate1",
						"structs": []map[string]interface{}{
							{
								"relId": "R1",
								"other": "haha",
							},
							{
								"relId": "R2",
							},
						},
					}),
					protostruct.ToStruct(map[string]interface{}{
						"instanceId": "id2",
						"name":       "name2",
						"cateId":     "cate2",
					}),
				},
			},
			relatedList: []relatedInst{
				{
					err: fmt.Errorf("mock fail"),
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceClient := cmdb.NewMockInstanceClient(ctrl)
			instanceClient.EXPECT().PostSearchV3(ctx, gomock.Any()).Return(tt.fetchResp, tt.fetchErr).Times(1)

			for _, item := range tt.relatedList {
				instanceClient.EXPECT().PostSearchV3(ctx, gomock.Any()).Return(item.resp, item.err).Times(1)
			}

			if len(tt.importList) > 0 {
				instanceClient.EXPECT().ImportInstance(ctx, gomock.Any()).DoAndReturn(func(ctx context.Context, in *instance.ImportInstanceRequest) (*instance.ImportInstanceResponse, error) {
					sort.Slice(in.Datas, func(i, j int) bool {
						return in.Datas[i].Fields[cmdbutil.InstanceIdLabel].GetStringValue() < in.Datas[j].Fields[cmdbutil.InstanceIdLabel].GetStringValue()
					})
					sort.Slice(tt.importList, func(i, j int) bool {
						return tt.importList[i].Fields[cmdbutil.InstanceIdLabel].GetStringValue() < tt.importList[j].Fields[cmdbutil.InstanceIdLabel].GetStringValue()
					})
					if !reflect.DeepEqual(in.Datas, tt.importList) {
						t.Errorf("import args not equal")
					}
					return tt.importResp, tt.importErr
				}).Times(1)
			}

			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: instanceClient,
			}
			if err := s.FillInstance(tt.args.ctx, tt.args.objectId, tt.args.instList); (err != nil) != tt.wantErr {
				t.Errorf("FillInstance() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_serviceImp_HasEffectedRule(t *testing.T) {
	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx        context.Context
		objectId   string
		item       ProcessItem
		updateData *types.Struct
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "relation rule effected",
			fields: fields{
				relationRules: []RelationRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
						SourceField: "name",
					},
				},
			},
			args: args{
				ctx:      context.Background(),
				objectId: "server",
				item: ProcessItem{
					InstanceId:   "id1",
					ChangeFields: []string{"name"},
				},
			},
			want: true,
		},
		{
			name: "instance rule effected",
			fields: fields{
				instanceRules: []InstanceRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
						AttrId: "name",
						AttrSource: []AttrDefine{
							{
								Key: "one",
								ValuePath: ValuePath{
									Path: "$.one",
								},
							},
						},
					},
				},
			},
			args: args{
				ctx:      context.Background(),
				objectId: "server",
				item: ProcessItem{
					InstanceId:   "id1",
					ChangeFields: []string{"one"},
				},
			},
			want: true,
		},
		{
			name: "no rule effected",
			fields: fields{
				relationRules: []RelationRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
						SourceField: "name",
					},
				},
				instanceRules: []InstanceRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
						AttrId: "name",
						AttrSource: []AttrDefine{
							{
								Key: "one",
								ValuePath: ValuePath{
									Path: "$.one",
								},
							},
						},
					},
				},
			},
			args: args{
				ctx:      context.Background(),
				objectId: "HOST",
				item: ProcessItem{
					InstanceId:   "id1",
					ChangeFields: []string{"name"},
				},
			},
			want: false,
		},
		{
			name: "relation rule no effected",
			fields: fields{
				relationRules: []RelationRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
						SourceField: "struct.deployDb",
					},
				},
			},
			args: args{
				ctx:      context.Background(),
				objectId: "HOST",
				item: ProcessItem{
					InstanceId:   "id1",
					ChangeFields: []string{"struct"},
					updateData: protostruct.ToStruct(map[string]interface{}{
						"struct": []interface{}{
							map[string]interface{}{
								"deployDb": "woshisb[e4ad034b62c68fd40f5a696ea0b64528]",
							},
						},
					}),
				},
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: tt.fields.instanceClient,
			}
			if got := s.HasEffectedRule(tt.args.ctx, tt.args.objectId, tt.args.item, tt.args.updateData); got != tt.want {
				t.Errorf("HasEffectedRule() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_fetchInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx      context.Context
		objectId string
		instList []ProcessItem
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    map[string]*ProcessItem
		wantErr bool

		resp      *instance.PostSearchV3Response
		searchErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id2",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{"name"},
					},
					{
						InstanceId:   "id1",
						ChangeFields: []string{"name"},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{"name", "abc"},
					},
				},
			},
			resp: &instance.PostSearchV3Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id1",
						"name":                   "11",
					}),
					protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id2",
						"name":                   "22",
					}),
				},
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId:   "id1",
					ChangeFields: []string{},
					instanceData: protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id1",
						"name":                   "11",
					}),
				},
				"id2": {
					InstanceId:   "id2",
					ChangeFields: []string{},
					instanceData: protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id2",
						"name":                   "22",
					}),
				},
				"id3": {
					InstanceId:   "id3",
					ChangeFields: []string{"name", "abc"},
					Error:        []string{"不存在实例: id3"},
					Code:         apierrors.ErrNotFound.Code(),
				},
			},
			wantErr: false,
		},
		{
			name:   "search fail",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				instList: []ProcessItem{
					{
						InstanceId:   "id1",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id2",
						ChangeFields: []string{},
					},
					{
						InstanceId:   "id3",
						ChangeFields: []string{"name"},
					},
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceMock := cmdb.NewMockInstanceClient(ctrl)
			instanceMock.EXPECT().PostSearchV3(ctx, &instance.PostSearchV3Request{
				ObjectId: tt.args.objectId,
				Query:    protostruct.ToStruct(map[string]interface{}{cmdbutil.InstanceIdLabel: map[string][]string{"$in": {"id1", "id2", "id3"}}}),
				Fields:   []string{"*"},
				Page:     1,
				PageSize: 3,
			}).Return(tt.resp, tt.searchErr).Times(1)
			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: instanceMock,
			}
			got, err := s.fetchInstance(tt.args.ctx, tt.args.objectId, tt.args.instList)
			if (err != nil) != tt.wantErr {
				t.Errorf("fetchInstance() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("fetchInstance() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_fillRelationRule(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	rule := RelationRule{
		RuleObjectConf: RuleObjectConf{
			ObjectId: "server",
		},
		SourceField: "descId",
		RelatedInstance: RelatedInstance{
			ObjectId:     "deployDB",
			RelatedField: "name",
		},
		Mapping: []RelatedMapping{
			{
				AttrId:     "descId",
				MappingKey: "relDesc",
			},
			{
				AttrId:     "cateId",
				MappingKey: "relCate",
			},
		},
	}
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx            context.Context
		objectId       string
		relationRule   RelationRule
		processInstMap map[string]*ProcessItem
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		resp      *instance.PostSearchV3Response
		searchErr error

		want map[string]*ProcessItem
	}{
		{
			name:   "happy path",
			fields: fields{},
			args: args{
				ctx:          ctx,
				relationRule: rule,
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId:   "id1",
						ChangeFields: []string{"descId"},
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"descId": "fakeId",
						}),
					},
				},
			},
			resp: &instance.PostSearchV3Response{
				List: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{"name": "fakeId", "relDesc": "fakeDesc", "relCate": "fakeCate"}),
				},
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId:   "id1",
					ChangeFields: []string{"descId"},
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"descId": "fakeId",
					}),
					updateData: protostruct.ToStruct(map[string]interface{}{
						"descId": "fakeId[fakeDesc]",
						"cateId": "fakeCate",
					}),
				},
			},
			wantErr: false,
		},
		{
			name:   "not found related instance",
			fields: fields{},
			args: args{
				ctx:          ctx,
				relationRule: rule,
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId:   "id1",
						ChangeFields: []string{"descId"},
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"descId": "fakeId",
						}),
					},
				},
			},
			resp: &instance.PostSearchV3Response{
				List: nil,
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId:   "id1",
					ChangeFields: []string{"descId"},
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"descId": "fakeId",
					}),
					Error: []string{"关联关系填充失败：模型deployDB不存在name值为fakeId的实例"},
				},
			},
			wantErr: false,
		},
		{
			name:   "no need fill",
			fields: fields{},
			args: args{
				ctx:          ctx,
				relationRule: rule,
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId:   "id1",
						ChangeFields: []string{"fake"},
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"descId": "fakeId",
						}),
					},
				},
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId:   "id1",
					ChangeFields: []string{"fake"},
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"descId": "fakeId",
					}),
				},
			},
		},
		{
			name:   "request fail",
			fields: fields{},
			args: args{
				ctx:          ctx,
				relationRule: rule,
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId:   "id1",
						ChangeFields: []string{"descId"},
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"descId": "fakeId",
						}),
					},
				},
			},
			searchErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceClient := cmdb.NewMockInstanceClient(ctrl)
			instanceClient.EXPECT().PostSearchV3(ctx, rule.GetRelationRequest([]interface{}{"fakeId"})).Return(tt.resp, tt.searchErr).MaxTimes(1)
			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: instanceClient,
			}
			if err := s.fillRelationRule(tt.args.ctx, tt.args.objectId, tt.args.relationRule, tt.args.processInstMap); (err != nil) != tt.wantErr {
				t.Errorf("fillRelationRule() error = %v, wantErr %v", err, tt.wantErr)
			}
			if !tt.wantErr {
				if !reflect.DeepEqual(tt.args.processInstMap, tt.want) {
					t.Errorf("fillRelationRule() got = %v, want %v", tt.args.processInstMap, tt.want)
				}
			}
		})
	}
}

func Test_serviceImp_updateInstance(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := logctx.WithLogger(context.Background(), slog.Noop())

	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx            context.Context
		objectId       string
		processInstMap map[string]*ProcessItem
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    map[string]*ProcessItem
		wantErr bool

		resp      *instance.ImportInstanceResponse
		importErr error
	}{
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId: "id1",
						updateData: protostruct.ToStruct(map[string]interface{}{
							"cate": "nba",
						}),
					},
					"id2": {
						InstanceId: "id2",
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"other": "one",
						}),
						Error: []string{"实例填充失败: unknown key name"},
					},
				},
			},
			resp: &instance.ImportInstanceResponse{
				UpdateCount: 0,
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId: "id1",
					updateData: protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id1",
						"cate":                   "nba",
					}),
				},
				"id2": {
					InstanceId: "id2",
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"other": "one",
					}),
					Error: []string{"实例填充失败: unknown key name"},
				},
			},
			wantErr: false,
		},
		{
			name:   "no update",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				processInstMap: map[string]*ProcessItem{
					"id2": {
						InstanceId: "id2",
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"other": "one",
						}),
						Error: []string{"实例填充失败: unknown key name"},
					},
				},
			},
			want: map[string]*ProcessItem{
				"id2": {
					InstanceId: "id2",
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"other": "one",
					}),
					Error: []string{"实例填充失败: unknown key name"},
				},
			},
			wantErr: false,
		},
		{
			name:   "import fail",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId: "id1",
						updateData: protostruct.ToStruct(map[string]interface{}{
							"cate": "nba",
						}),
					},
					"id2": {
						InstanceId: "id2",
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"other": "one",
						}),
						Error: []string{"实例填充失败: unknown key name"},
					},
				},
			},
			importErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
		{
			name:   "data fail",
			fields: fields{},
			args: args{
				ctx:      ctx,
				objectId: "server",
				processInstMap: map[string]*ProcessItem{
					"id1": {
						InstanceId: "id1",
						updateData: protostruct.ToStruct(map[string]interface{}{
							"cate": "nba",
						}),
					},
					"id2": {
						InstanceId: "id2",
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"other": "one",
						}),
						Error: []string{"实例填充失败: unknown key name"},
					},
				},
			},
			resp: &instance.ImportInstanceResponse{
				FailedCount: 1,
				Data: []*instance.ImportInstanceResponse_Data{
					{
						Code:  130114,
						Error: "导入失败",
						Data:  []*types.Struct{protostruct.ToStruct(map[string]interface{}{cmdbutil.InstanceIdLabel: "id1"})},
					},
				},
			},
			want: map[string]*ProcessItem{
				"id1": {
					InstanceId: "id1",
					updateData: protostruct.ToStruct(map[string]interface{}{
						cmdbutil.InstanceIdLabel: "id1",
						"cate":                   "nba",
					}),
					Error: []string{"实例更新失败: 导入失败"},
					Code:  apierrors.ErrInternal.Code(),
				},
				"id2": {
					InstanceId: "id2",
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"other": "one",
					}),
					Error: []string{"实例填充失败: unknown key name"},
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			instanceClient := cmdb.NewMockInstanceClient(ctrl)
			instanceClient.EXPECT().ImportInstance(ctx, &instance.ImportInstanceRequest{
				ObjectId: tt.args.objectId,
				Keys:     []string{cmdbutil.InstanceIdLabel},
				Datas: []*types.Struct{
					protostruct.ToStruct(map[string]interface{}{
						"cate":                   "nba",
						cmdbutil.InstanceIdLabel: "id1",
					}),
				},
			}).Return(tt.resp, tt.importErr).MaxTimes(1)
			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: instanceClient,
			}
			if err := s.updateInstance(tt.args.ctx, tt.args.objectId, tt.args.processInstMap); (err != nil) != tt.wantErr {
				t.Errorf("updateInstance() error = %v, wantErr %v", err, tt.wantErr)
			}
			if !tt.wantErr {
				if !reflect.DeepEqual(tt.args.processInstMap, tt.want) {
					t.Errorf("updateInstance() got = %v, want %v", tt.args.processInstMap, tt.want)
				}
			}
		})
	}
}

func Test_serviceImp_fillInstanceRule(t *testing.T) {
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		relationRules  []RelationRule
		instanceRules  []InstanceRule
		instanceClient instance.Client
	}
	type args struct {
		ctx            context.Context
		objectId       string
		instanceRule   InstanceRule
		processInstMap map[string]*ProcessItem
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   map[string]*ProcessItem
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				ctx: ctx,
				instanceRule: InstanceRule{
					RuleObjectConf: RuleObjectConf{
						ObjectId: "server",
					},
					AttrId: "cate",
					AttrSource: []AttrDefine{
						{
							Key: "name",
							ValuePath: ValuePath{
								Path: "$.name",
							},
						},
					},
					Case: []Case{
						{
							Condition: []Condition{
								{
									Key:   "name",
									Opr:   OprEqual,
									Value: "james",
								},
							},
							Value: Value{
								Type:  "const",
								Const: "nba",
							},
						},
					},
					Default: nil,
				},
				processInstMap: map[string]*ProcessItem{
					"id1": {
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"name": "james",
						}),
						updateData: protostruct.ToStruct(map[string]interface{}{
							"title": "goat",
						}),
					},
					"id2": {
						instanceData: protostruct.ToStruct(map[string]interface{}{
							"other": "one",
						}),
					},
				},
			},
			want: map[string]*ProcessItem{
				"id1": {
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"name": "james",
					}),
					updateData: protostruct.ToStruct(map[string]interface{}{
						"cate":  "nba",
						"title": "goat",
					}),
				},
				"id2": {
					instanceData: protostruct.ToStruct(map[string]interface{}{
						"other": "one",
					}),
					Error: []string{"实例填充失败: unknown key name"},
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &serviceImp{
				relationRules:  tt.fields.relationRules,
				instanceRules:  tt.fields.instanceRules,
				instanceClient: tt.fields.instanceClient,
			}
			s.fillInstanceRule(tt.args.ctx, tt.args.objectId, tt.args.instanceRule, tt.args.processInstMap)
			if !reflect.DeepEqual(tt.args.processInstMap, tt.want) {
				t.Errorf("fillInstanceRule() got = %v, want %v", tt.args.processInstMap, tt.want)
			}
		})
	}
}

func TestProcessItem_ToString(t *testing.T) {
	type fields struct {
		InstanceId   string
		ChangeFields []string
		PushTime     int64
		Error        []string
		Code         int
		instanceData *types.Struct
		updateData   *types.Struct
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name: "",
			fields: fields{
				InstanceId:   "id1",
				ChangeFields: []string{"name"},
				PushTime:     520,
			},
			want: `{"instanceId":"id1","changeFields":["name"],"pushTime":520}`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := ProcessItem{
				InstanceId:   tt.fields.InstanceId,
				ChangeFields: tt.fields.ChangeFields,
				PushTime:     tt.fields.PushTime,
				Error:        tt.fields.Error,
				Code:         tt.fields.Code,
				instanceData: tt.fields.instanceData,
				updateData:   tt.fields.updateData,
			}
			if got := i.ToString(); got != tt.want {
				t.Errorf("ToString() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_RegisterSubscribers(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	type fields struct {
		relationRules    []RelationRule
		instanceRules    []InstanceRule
		instanceClient   instance.Client
		subscriberClient subscriber.Client
	}
	tests := []struct {
		name    string
		fields  fields
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				relationRules: []RelationRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectIdList: []string{"server"},
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "",
			fields: fields{
				instanceRules: []InstanceRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "",
			fields: fields{
				instanceRules: []InstanceRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectIdList: []string{"server"},
						},
					},
				},
			},
			wantErr: false,
		},
		{
			name: "",
			fields: fields{
				relationRules: []RelationRule{
					{
						RuleObjectConf: RuleObjectConf{
							ObjectId: "server",
						},
					},
				},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			subscriberMock := notify.NewMockSubscriberClient(ctrl)
			subscriberMock.EXPECT().CreateSubscriber(context.Background(), &notifymodel.Subscriber{
				Name:     subscriberName,
				Callback: "http://logic.fintech_data.local/api/fill/instance/callback",
				EnsName:  "logic.fintech_data",
				MsgType:  1,
				Retry:    1,
				SubscribeInfo: []*notifymodel.SubscribeInfo{{
					Channel: "cmdb",
					Event: []string{
						"event_v2.instance.create.server",
						"event_v2.instance.modify.server",
					},
				}},
			}).Return(nil, nil).Times(1)
			s := &serviceImp{
				relationRules:    tt.fields.relationRules,
				instanceRules:    tt.fields.instanceRules,
				instanceClient:   tt.fields.instanceClient,
				subscriberClient: subscriberMock,
			}
			if err := s.RegisterSubscribers(); (err != nil) != tt.wantErr {
				t.Errorf("RegisterSubscribers() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
