package fill_instance

import (
	"context"
	"reflect"
	"testing"

	"github.com/gogo/protobuf/types"
	"github.com/smartystreets/goconvey/convey"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestRelatedMapping_diffValue(t *testing.T) {
	convey.Convey("instance compare", t, func() {
		m := RelatedMapping{
			AttrId:     "idc",
			MappingKey: "idcId",
		}
		convey.Convey("set id", func() {
			got := m.diffValue("idc", protostruct.ToStruct(map[string]interface{}{"idc": "GD"}), protostruct.ToStruct(map[string]interface{}{"idcId": "ABC-001"}))
			convey.So(got.Equal(protostruct.ToValue("GD[ABC-001]")), convey.ShouldBeTrue)
		})
		convey.Convey("set other", func() {
			got := m.diffValue("name", protostruct.ToStruct(map[string]interface{}{"idc": "GD"}), protostruct.ToStruct(map[string]interface{}{"idcId": "ABC-001"}))
			convey.So(got.Equal(protostruct.ToValue("ABC-001")), convey.ShouldBeTrue)
		})
		convey.Convey("no diff", func() {
			got := m.diffValue("name", protostruct.ToStruct(map[string]interface{}{"idc": "GD"}), protostruct.ToStruct(map[string]interface{}{"idcId": "GD"}))
			convey.So(got, convey.ShouldBeNil)
		})
	})
}

func TestRelationRule_Do(t *testing.T) {
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	relatedInstMap := map[string]*types.Struct{
		"GZ": protostruct.ToStruct(map[string]interface{}{
			"relId":   "ABC001",
			"relCate": "FLKBL01",
		}),
		"SZ": protostruct.ToStruct(map[string]interface{}{
			"relId":   "ABC002",
			"relCate": "FLKBL02",
		}),
	}
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	type args struct {
		ctx            context.Context
		objectId       string
		instanceData   *types.Struct
		relatedInstMap map[string]*types.Struct
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *types.Struct
		wantErr bool
	}{
		{
			name: "instance",
			fields: fields{
				SourceField: "id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"id": "GZ",
				}),
				relatedInstMap: relatedInstMap,
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"id":   "GZ[ABC001]",
				"cate": "FLKBL01",
			}),
			wantErr: false,
		},
		{
			name: "instance relation not found",
			fields: fields{
				SourceField: "id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"id": "FS",
				}),
				relatedInstMap: relatedInstMap,
			},
			wantErr: true,
		},
		{
			name: "struct",
			fields: fields{
				SourceField: "struct.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"struct": map[string]interface{}{
						"id":  "GZ",
						"age": 10,
					},
				}),
				relatedInstMap: relatedInstMap,
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"struct": map[string]interface{}{
					"id":   "GZ[ABC001]",
					"cate": "FLKBL01",
					"age":  10,
				},
			}),
			wantErr: false,
		},
		{
			name: "struct related inst not found",
			fields: fields{
				SourceField: "struct.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"struct": map[string]interface{}{
						"id":  "FS",
						"age": 10,
					},
				}),
				relatedInstMap: relatedInstMap,
			},
			wantErr: true,
		},
		{
			name: "structs",
			fields: fields{
				SourceField: "structs.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"structs": []map[string]interface{}{
						{
							"id":  "GZ",
							"age": 10,
						},
						{
							"age": 15,
						},
						{
							"id":  "SZ",
							"age": 20,
						},
					},
				}),
				relatedInstMap: relatedInstMap,
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"structs": []map[string]interface{}{
					{
						"id":   "GZ[ABC001]",
						"cate": "FLKBL01",
						"age":  10,
					},
					{
						"age": 15,
					},
					{
						"id":   "SZ[ABC002]",
						"cate": "FLKBL02",
						"age":  20,
					},
				},
			}),
			wantErr: false,
		},
		{
			name: "structs related one inst not found",
			fields: fields{
				SourceField: "structs.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"structs": []map[string]interface{}{
						{
							"id":  "FS",
							"age": 10,
						},
						{
							"age": 15,
						},
						{
							"id":  "SZ",
							"age": 20,
						},
					},
				}),
				relatedInstMap: relatedInstMap,
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"structs": []map[string]interface{}{
					{
						"id":  "FS",
						"age": 10,
					},
					{
						"age": 15,
					},
					{
						"id":   "SZ[ABC002]",
						"cate": "FLKBL02",
						"age":  20,
					},
				},
			}),
			wantErr: true,
		},
		{
			name: "structs related all inst not found",
			fields: fields{
				SourceField: "structs.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
					{
						AttrId:     "cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"structs": []map[string]interface{}{
						{
							"id":  "FS",
							"age": 10,
						},
						{
							"age": 15,
						},
						{
							"id":  "ZH",
							"age": 20,
						},
					},
				}),
				relatedInstMap: relatedInstMap,
			},
			wantErr: true,
		},
		{
			name: "name",
			fields: fields{
				SourceField: "name.id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
			},
			args: args{
				ctx: ctx,
				instanceData: protostruct.ToStruct(map[string]interface{}{
					"name": "fake",
				}),
				relatedInstMap: relatedInstMap,
			},
			want:    nil,
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			got, err := r.Do(tt.args.ctx, tt.args.objectId, tt.args.instanceData, tt.args.relatedInstMap)
			if (err != nil) != tt.wantErr {
				t.Errorf("Do() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Do() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRelationRule_Effected(t *testing.T) {
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	type args struct {
		changeFields []string
		updateData   *types.Struct
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name:   "fields empty",
			fields: fields{},
			args: args{
				changeFields: []string{},
			},
			want: true,
		},
		{
			name:   "true",
			fields: fields{SourceField: "struct.Id"},
			args: args{
				changeFields: []string{"struct"},
			},
			want: true,
		},
		{
			name:   "false",
			fields: fields{SourceField: "struct.Id"},
			args: args{
				changeFields: []string{"name"},
			},
			want: false,
		},
		{
			name:   "false",
			fields: fields{SourceField: "struct.Id"},
			args: args{
				changeFields: []string{"struct"},
				updateData: protostruct.ToStruct(map[string]interface{}{
					"struct": []map[string]interface{}{
						{
							"Id": "e4ad034b62c68fd40f5a696ea0b64528",
						},
						{
							"Id": "sha[e4ad034b62c68fd40f5a696ea0b64528]",
						},
					},
				}),
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			if got := r.Effected(tt.args.changeFields, tt.args.updateData); got != tt.want {
				t.Errorf("Effected() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRelationRule_GetRelationRequest(t *testing.T) {
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	type args struct {
		values []interface{}
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *instance.PostSearchV3Request
	}{
		{
			name: "",
			fields: fields{
				RuleObjectConf: RuleObjectConf{
					ObjectId: "my",
				},
				SourceField: "struct.Id",
				RelatedInstance: RelatedInstance{
					ObjectId:     "server",
					RelatedField: "relName",
				},
				Mapping: []RelatedMapping{
					{
						AttrId:     "struct.Id",
						MappingKey: "relId",
					},
					{
						AttrId:     "struct.Cate",
						MappingKey: "relCate",
					},
				},
			},
			args: args{
				values: []interface{}{"a", "b", "c"},
			},
			want: &instance.PostSearchV3Request{
				ObjectId: "server",
				Query: protostruct.ToStruct(map[string]interface{}{
					"relName": map[string]interface{}{"$in": []interface{}{"a", "b", "c"}},
				}),
				Fields:   []string{"relName", "relId", "relCate"},
				Page:     1,
				PageSize: 3,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			if got := r.GetRelationRequest(tt.args.values); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetRelationRequest() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRelationRule_GetSourceValue(t *testing.T) {
	instanceData := protostruct.ToStruct(map[string]interface{}{
		"name": "james",
		"struct": map[string]interface{}{
			"name": "wade",
		},
		"structs": []map[string]interface{}{
			{"name": "paul"},
			{"age": 32},
			{"name": "bosh"},
		},
	})
	convey.Convey("normal", t, func() {
		convey.Convey("inst value", func() {
			rule := RelationRule{
				SourceField: "name",
			}
			got := rule.GetSourceValue(instanceData)
			convey.So(reflect.DeepEqual(got, []interface{}{"james"}), convey.ShouldBeTrue)
		})
		convey.Convey("struct", func() {
			rule := RelationRule{
				SourceField: "struct.name",
			}
			got := rule.GetSourceValue(instanceData)
			convey.So(reflect.DeepEqual(got, []interface{}{"wade"}), convey.ShouldBeTrue)
		})
		convey.Convey("structs", func() {
			rule := RelationRule{
				SourceField: "structs.name",
			}
			got := rule.GetSourceValue(instanceData)
			convey.So(reflect.DeepEqual(got, []interface{}{"paul", "bosh"}), convey.ShouldBeTrue)
		})
	})
}

func TestRelationRule_fillRelationValue(t *testing.T) {
	relatedInstMap := map[string]*types.Struct{
		"GZ": protostruct.ToStruct(map[string]interface{}{
			"relId":   "ABC001",
			"relCate": "FLKBL01",
		}),
	}
	convey.Convey("normal", t, func() {
		rule := RelationRule{
			SourceField: "deployDb.id",
			Mapping: []RelatedMapping{
				{
					AttrId:     "id",
					MappingKey: "relId",
				},
				{
					AttrId:     "cate",
					MappingKey: "relCate",
				},
			},
		}
		convey.Convey("set value", func() {
			data := protostruct.ToStruct(map[string]interface{}{
				"id": "GZ",
			})
			got, _ := rule.fillRelationValue("id", data, relatedInstMap)
			want := protostruct.ToStruct(map[string]interface{}{
				"id":   "GZ[ABC001]",
				"cate": "FLKBL01",
			})
			convey.So(got.Equal(want), convey.ShouldBeTrue)
		})
		convey.Convey("set value cate not diff", func() {
			data := protostruct.ToStruct(map[string]interface{}{
				"id":   "GZ",
				"cate": "FLKBL01",
			})
			got, _ := rule.fillRelationValue("id", data, relatedInstMap)
			want := protostruct.ToStruct(map[string]interface{}{
				"id": "GZ[ABC001]",
			})
			convey.So(got.Equal(want), convey.ShouldBeTrue)
		})
		convey.Convey("all not diff", func() {
			data := protostruct.ToStruct(map[string]interface{}{
				"abc":  "GZ",
				"id":   "ABC001",
				"cate": "FLKBL01",
			})
			got, _ := rule.fillRelationValue("abc", data, relatedInstMap)
			convey.So(got, convey.ShouldBeNil)
		})
		convey.Convey("related inst not found", func() {
			data := protostruct.ToStruct(map[string]interface{}{
				"abc":  "GZA",
				"id":   "ABC001",
				"cate": "FLKBL01",
			})
			_, err := rule.fillRelationValue("abc", data, relatedInstMap)
			convey.So(err, convey.ShouldBeError)
		})
		convey.Convey("is id value", func() {
			data := protostruct.ToStruct(map[string]interface{}{
				"abc":  "sha[e4ad034b62c68fd40f5a696ea0b64528]",
				"id":   "ABC001",
				"cate": "FLKBL01",
			})
			got, err := rule.fillRelationValue("abc", data, relatedInstMap)
			convey.So(got, convey.ShouldBeNil)
			convey.So(err, convey.ShouldBeNil)
		})
	})
}

func TestRelationRule_getValueFromStruct(t *testing.T) {
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	type args struct {
		data  *types.Struct
		field string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   interface{}
	}{
		{
			name:   "value is id format",
			fields: fields{},
			args: args{
				data:  protostruct.ToStruct(map[string]interface{}{"fakeId": "yes[e4ad034b62c68fd40f5a696ea0b64528]"}),
				field: "fakeId",
			},
			want: nil,
		},
		{
			name:   "data nil",
			fields: fields{},
			args: args{
				data:  nil,
				field: "",
			},
			want: nil,
		},
		{
			name:   "value is id",
			fields: fields{},
			args: args{
				data:  protostruct.ToStruct(map[string]interface{}{"fakeId": "e4ad034b62c68fd40f5a696ea0b64528"}),
				field: "fakeId",
			},
			want: nil,
		},
		{
			name:   "value is id",
			fields: fields{},
			args: args{
				data:  protostruct.ToStruct(map[string]interface{}{"fakeId": "yes"}),
				field: "fakeId",
			},
			want: "yes",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			if got := r.getValueFromStruct(tt.args.data, tt.args.field); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("getValueFromStruct() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRelationRule_GetSelfEffectedAttr(t *testing.T) {
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name: "",
			fields: fields{
				RuleObjectConf: RuleObjectConf{
					ObjectId: "server",
				},
				SourceField: "struct.id",
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
				},
			},
			want: "struct.id",
		},
		{
			name: "",
			fields: fields{
				RuleObjectConf: RuleObjectConf{
					ObjectId: "server",
				},
				SourceField: "id",
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
				},
			},
			want: "id",
		},
		{
			name: "",
			fields: fields{
				RuleObjectConf: RuleObjectConf{
					ObjectId: "server",
				},
				SourceField: "struct.name",
				Mapping: []RelatedMapping{
					{
						AttrId:     "id",
						MappingKey: "relId",
					},
				},
			},
			want: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			if got := r.GetSelfEffectedAttr(); got != tt.want {
				t.Errorf("GetSelfEffectedAttr() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRecoverValueChange(t *testing.T) {
	type args struct {
		value string
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				value: "sha[e4ad034b62c68fd40f5a696ea0b64528]",
			},
			want: "e4ad034b62c68fd40f5a696ea0b64528",
		},
		{
			name: "",
			args: args{
				value: "e4ad034b62c68fd40f5a696ea0b64528",
			},
			want: "e4ad034b62c68fd40f5a696ea0b64528",
		},
		{
			name: "",
			args: args{
				value: "XYGJ00[90c730f5beed03ff4e2e76a8c-XYGJ00]",
			},
			want: "90c730f5beed03ff4e2e76a8c-XYGJ00",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := RecoverValueChange(tt.args.value); got != tt.want {
				t.Errorf("RecoverValueChange() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRelationRule_doStructData(t *testing.T) {
	type fields struct {
		RuleObjectConf  RuleObjectConf
		SourceField     string
		RelatedInstance RelatedInstance
		Mapping         []RelatedMapping
	}
	type args struct {
		subAttrId      string
		structData     *types.Struct
		relatedInstMap map[string]*types.Struct
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    bool
		wantErr bool
	}{
		{
			name:   "struct is nil",
			fields: fields{},
			args: args{
				subAttrId:  "name",
				structData: nil,
			},
			want:    false,
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := RelationRule{
				RuleObjectConf:  tt.fields.RuleObjectConf,
				SourceField:     tt.fields.SourceField,
				RelatedInstance: tt.fields.RelatedInstance,
				Mapping:         tt.fields.Mapping,
			}
			got, err := r.doStructData(tt.args.subAttrId, tt.args.structData, tt.args.relatedInstMap)
			if (err != nil) != tt.wantErr {
				t.Errorf("doStructData() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("doStructData() got = %v, want %v", got, tt.want)
			}
		})
	}
}
