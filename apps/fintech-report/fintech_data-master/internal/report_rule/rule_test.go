package report_rule

import (
	"reflect"
	"testing"

	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func TestGetSearchObjectId(t *testing.T) {
	type args struct {
		conf *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				conf: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
				},
			},
			want: "HOST",
		},
		{
			name: "",
			args: args{
				conf: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceDirect,
				},
			},
			want: "server",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetSearchObjectId(tt.args.conf); got != tt.want {
				t.Errorf("GetSearchObjectId() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConvertReportInst(t *testing.T) {
	type args struct {
		reportObj     *cmdb.CmdbObject
		conf          *fintech_data.ReportObjectConf
		reportInst    *fintech_data.ReportInstance
		reportConf    config.ReportConf
		relationRules []fill_instance.RelationRule
	}
	tests := []struct {
		name string
		args args
		want *fintech_data.ReportInstance
	}{
		{
			name: "normal",
			args: args{
				reportObj: &cmdb.CmdbObject{
					AttrList: []*cmdb.ObjectAttr{
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityCategory,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityDescriptor,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "name",
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "relId",
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "inner_attr",
							Tag:   []string{"inner_data"},
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "ignore",
						},
					},
				},
				relationRules: []fill_instance.RelationRule{
					{
						RuleObjectConf: fill_instance.RuleObjectConf{
							ObjectId: "host",
						},
						SourceField: "rel_id",
						Mapping: []fill_instance.RelatedMapping{
							{
								AttrId:     "rel_id",
								MappingKey: "rr",
							},
						},
					},
					{
						RuleObjectConf: fill_instance.RuleObjectConf{
							ObjectId: "app",
						},
						SourceField: "rel_id",
						Mapping: []fill_instance.RelatedMapping{
							{
								AttrId:     "rel_id",
								MappingKey: "rr",
							},
						},
					},
				},
				conf: &fintech_data.ReportObjectConf{
					Source:          ObjectSourceMapping,
					MappingObjectId: "host",
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  report_center.KeyFacilityDescriptor,
								MappingAttrId: "desc",
							},
							{
								ReportAttrId:  report_center.KeyFacilityCategory,
								MappingAttrId: "cate",
							},
							{
								ReportAttrId:  "relId",
								MappingAttrId: "rel_id",
							},
							{
								ReportAttrId: "name",
							},
						},
					},
				},
				reportInst: &fintech_data.ReportInstance{
					ReportType: report_center.ReportTypeNew,
					Data: protostruct.ToStruct(map[string]interface{}{
						"desc":   "desc1",
						"cate":   "cate1",
						"name":   "wc",
						"rel_id": "sha[e4ad034b62c68fd40f5a696ea0b64528]",
					}),
				},
				reportConf: config.ReportConf{
					IgnoreConf: config.IgnoreConf{
						InstanceIgnoreAttr: "ignore",
						AttrIgnoreCategory: []string{"inner_data"},
					},
					PKTranslate: []config.KeyTranslate{
						{
							ObjectId:           "application",
							FacilityDescriptor: "applySystemIdentifiers",
							FacilityCategory:   "softwareCategory",
						},
					},
				},
			},
			want: &fintech_data.ReportInstance{
				ReportType:         report_center.ReportTypeNew,
				FacilityDescriptor: "desc1",
				FacilityCategory:   "cate1",
				Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "desc1",
					report_center.KeyFacilityCategory:   "cate1",
					"name":                              "wc",
					"relId":                             "e4ad034b62c68fd40f5a696ea0b64528",
				}),
			},
		},
		{
			name: "ignore instance",
			args: args{
				reportObj: &cmdb.CmdbObject{
					AttrList: []*cmdb.ObjectAttr{
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityCategory,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityDescriptor,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "name",
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "relId",
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "inner_attr",
							Tag:   []string{"inner_data"},
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "ignore",
						},
					},
				},
				relationRules: []fill_instance.RelationRule{
					{
						RuleObjectConf: fill_instance.RuleObjectConf{
							ObjectId: "host",
						},
						SourceField: "rel_id",
						Mapping: []fill_instance.RelatedMapping{
							{
								AttrId:     "rel_id",
								MappingKey: "rr",
							},
						},
					},
					{
						RuleObjectConf: fill_instance.RuleObjectConf{
							ObjectId: "app",
						},
						SourceField: "rel_id",
						Mapping: []fill_instance.RelatedMapping{
							{
								AttrId:     "rel_id",
								MappingKey: "rr",
							},
						},
					},
				},
				conf: &fintech_data.ReportObjectConf{
					Source:          ObjectSourceMapping,
					ObjectId:        "HOST",
					MappingObjectId: "host",
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  report_center.KeyFacilityDescriptor,
								MappingAttrId: "desc",
							},
							{
								ReportAttrId:  report_center.KeyFacilityCategory,
								MappingAttrId: "cate",
							},
							{
								ReportAttrId:  "relId",
								MappingAttrId: "rel_id",
							},
							{
								ReportAttrId: "name",
							},
						},
					},
				},
				reportInst: &fintech_data.ReportInstance{
					ReportType: report_center.ReportTypeNew,
					Data: protostruct.ToStruct(map[string]interface{}{
						"desc":   "desc1",
						"cate":   "cate1",
						"name":   "wc",
						"rel_id": "sha[e4ad034b62c68fd40f5a696ea0b64528]",
						"ignore": true,
					}),
				},
				reportConf: config.ReportConf{
					IgnoreConf: config.IgnoreConf{
						InstanceIgnoreAttr: "ignore",
						AttrIgnoreCategory: []string{"inner_data"},
					},
					PKTranslate: []config.KeyTranslate{
						{
							ObjectId:           "application",
							FacilityDescriptor: "applySystemIdentifiers",
							FacilityCategory:   "softwareCategory",
						},
					},
					FloatPrecRule: []config.PrecRule{
						{
							ObjectId: "HOST",
							Rule:     map[string]int{"value": 3},
						},
					},
				},
			},
			want: &fintech_data.ReportInstance{
				ReportType:         report_center.ReportTypeNew,
				FacilityDescriptor: "desc1",
				FacilityCategory:   "cate1",
				Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "desc1",
					report_center.KeyFacilityCategory:   "cate1",
					"name":                              "wc",
					"relId":                             "e4ad034b62c68fd40f5a696ea0b64528",
					"ignore":                            true,
				}),
			},
		},
		{
			name: "direct",
			args: args{
				reportObj: &cmdb.CmdbObject{
					AttrList: []*cmdb.ObjectAttr{
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityCategory,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityDescriptor,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "name",
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "enum"},
							Id:    "enum",
						},
						{
							Value: &cmdb.ObjectAttrValue{
								Type: "struct",
								StructDefine: []*cmdb.ObjectAttrValueStruct{{
									Id:   "id",
									Type: "str",
								}}},
							Id: "struct",
						},
					},
				},
				relationRules: []fill_instance.RelationRule{
					{
						RuleObjectConf: fill_instance.RuleObjectConf{
							ObjectId: "server",
						},
						SourceField: "struct.id",
						Mapping: []fill_instance.RelatedMapping{
							{
								AttrId:     "id",
								MappingKey: "relId",
							},
						},
					},
				},
				conf: &fintech_data.ReportObjectConf{
					Source:   ObjectSourceDirect,
					ObjectId: "server",
				},
				reportInst: &fintech_data.ReportInstance{
					ReportType: report_center.ReportTypeNew,
					Data: protostruct.ToStruct(map[string]interface{}{
						report_center.KeyFacilityCategory:   "cate1",
						report_center.KeyFacilityDescriptor: "desc1",
						"name":                              "wc",
						"enum":                              "01-帅哥",
						"struct": map[string]interface{}{
							"id": "sha[e4ad034b62c68fd40f5a696ea0b64528]",
						},
					}),
				},
			},
			want: &fintech_data.ReportInstance{
				ReportType:         report_center.ReportTypeNew,
				FacilityDescriptor: "desc1",
				FacilityCategory:   "cate1",
				Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "desc1",
					report_center.KeyFacilityCategory:   "cate1",
					"name":                              "wc",
					"enum":                              "01",
					"struct": map[string]interface{}{
						"id": "e4ad034b62c68fd40f5a696ea0b64528",
					},
				}),
			},
		},
		{
			name: "inst delete",
			args: args{
				reportObj: &cmdb.CmdbObject{
					AttrList: []*cmdb.ObjectAttr{
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityCategory,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    report_center.KeyFacilityDescriptor,
						},
						{
							Value: &cmdb.ObjectAttrValue{Type: "str"},
							Id:    "name",
						},
					},
				},
				conf: &fintech_data.ReportObjectConf{
					Source: ObjectSourceMapping,
					MappingRule: &fintech_data.MappingRule{
						AttrMapping: []*fintech_data.AttrMapping{
							{
								ReportAttrId:  report_center.KeyFacilityDescriptor,
								MappingAttrId: "desc",
							},
							{
								ReportAttrId:  report_center.KeyFacilityCategory,
								MappingAttrId: "cate",
							},
							{
								ReportAttrId: "name",
							},
						},
					},
				},
				reportInst: &fintech_data.ReportInstance{
					ReportType: report_center.ReportTypeDelete,
					Data: protostruct.ToStruct(map[string]interface{}{
						report_center.KeyFacilityDescriptor: "desc1",
						report_center.KeyFacilityCategory:   "cate1",
						"name":                              "wc",
					}),
				},
			},
			want: &fintech_data.ReportInstance{
				ReportType: report_center.ReportTypeDelete,
				Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "desc1",
					report_center.KeyFacilityCategory:   "cate1",
					"name":                              "wc",
				}),
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := NewConverter(tt.args.reportObj, tt.args.conf, tt.args.reportConf, tt.args.relationRules)
			s.ConvertReportInst(tt.args.reportInst)
			if !reflect.DeepEqual(tt.args.reportInst, tt.want) {
				t.Errorf("report instance not equal, got:%v, want:%v", tt.args.reportInst, tt.want)
			}
		})
	}
}

func TestGetMappingObjectId(t *testing.T) {
	type args struct {
		conf *fintech_data.ReportObjectConf
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				conf: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceMapping,
				},
			},
			want: "HOST",
		},
		{
			name: "",
			args: args{
				conf: &fintech_data.ReportObjectConf{
					ObjectId:        "server",
					MappingObjectId: "HOST",
					Source:          ObjectSourceDirect,
				},
			},
			want: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetMappingObjectId(tt.args.conf); got != tt.want {
				t.Errorf("GetMappingObjectId() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformAttrValue(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		selfEffectedIds map[string]struct{}
		floatPrecMap    map[string]int
	}
	type args struct {
		attr  *cmdb.ObjectAttr
		value *types.Value
	}
	attrList := []string{"f1", "f2"}
	convertValue := make(map[string]*types.Value)
	for _, subAttr := range attrList {
		convertValue[subAttr] = emptyStr
	}
	var convertList []*types.Value
	s := &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}}
	convertList = append(convertList, s)
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "enum null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "enum",
					Value: &cmdb.ObjectAttrValue{
						Type: "enum",
					},
				},
				value: protostruct.ToValue(123),
			},
			want: emptyStr,
		},
		{
			name:   "struct null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "struct",
					Value: &cmdb.ObjectAttrValue{
						Type: "struct",
						StructDefine: []*cmdb.ObjectAttrValueStruct{
							{
								Id:   "f1",
								Name: "f1",
								Type: "string",
							},
							{
								Id:   "f2",
								Name: "f2",
								Type: "string",
							},
						},
					},
				},
				value: nil,
			},
			want: &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}},
		},
		{
			name:   "struct other null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "struct",
					Value: &cmdb.ObjectAttrValue{
						Type: "struct",
						StructDefine: []*cmdb.ObjectAttrValueStruct{
							{
								Id:   "f1",
								Name: "f1",
								Type: "string",
							},
							{
								Id:   "f2",
								Name: "f2",
								Type: "string",
							},
						},
					},
				},
				value: protostruct.ToValue("13"),
			},
			want: &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}},
		},
		{
			name:   "struct",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "struct",
					Value: &cmdb.ObjectAttrValue{
						Type: "struct",
						StructDefine: []*cmdb.ObjectAttrValueStruct{
							{
								Id:   "enum",
								Name: "enum",
								Type: "enum",
							},
							{
								Id:   "str",
								Name: "str",
								Type: "str",
							},
						},
					},
				},
				value: protostruct.ToValue(map[string]interface{}{
					"enum": "99-你好-帅",
					"str":  "01-你不帅",
				}),
			},
			want: protostruct.ToValue(map[string]interface{}{
				"enum": "99",
				"str":  "01-你不帅",
			}),
		},
		{
			name: "struct list",
			fields: fields{
				selfEffectedIds: map[string]struct{}{"structs.id": {}},
				floatPrecMap: map[string]int{
					"structs.float": 3,
				},
			},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "structs",
					Value: &cmdb.ObjectAttrValue{
						Type: "structs",
						StructDefine: []*cmdb.ObjectAttrValueStruct{
							{
								Id:   "enum",
								Name: "enum",
								Type: "enum",
							},
							{
								Id:   "str",
								Name: "str",
								Type: "str",
							},
							{
								Id:   "bool",
								Name: "bool",
								Type: "bool",
							},
							{
								Id:   "datetime",
								Name: "datetime",
								Type: "datetime",
							},
							{
								Id:   "date",
								Name: "date",
								Type: "date",
							},
							{
								Id:   "id",
								Name: "id",
								Type: "str",
							},
							{
								Id:   "float",
								Name: "float",
								Type: "float",
							},
						},
					},
				},
				value: protostruct.ToValue([]map[string]interface{}{
					{
						"enum":     "99：你好-帅",
						"str":      "01-你不帅",
						"bool":     false,
						"datetime": "2021-10-29 17:21:53",
						"id":       "xxx[e4ad034b62c68fd40f5a696ea0b64528]",
						"float":    2.3331,
					},
				}),
			},
			want: protostruct.ToValue([]map[string]interface{}{
				{
					"enum":     "99",
					"str":      "01-你不帅",
					"bool":     "False",
					"datetime": "2021-10-29 17:21",
					"id":       "e4ad034b62c68fd40f5a696ea0b64528",
					"date":     "",
					"float":    "2.333",
				},
			}),
		},
		{
			name:   "enums",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "enums",
					Value: &cmdb.ObjectAttrValue{
						Type: "enums",
					},
				},
				value: protostruct.ToValue([]string{"99-你好-帅", "01-你不帅"}),
			},
			want: protostruct.ToValue("99,01"),
		},
		{
			name:   "enums empty",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "enums",
					Value: &cmdb.ObjectAttrValue{
						Type: "enums",
					},
				},
				value: protostruct.ToValue(""),
			},
			want: protostruct.ToValue(""),
		},
		{
			name:   "structs null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "structs",
					Value: &cmdb.ObjectAttrValue{
						Type: "structs",
						StructDefine: []*cmdb.ObjectAttrValueStruct{
							{
								Id:   "f1",
								Name: "f1",
								Type: "string",
							},
							{
								Id:   "f2",
								Name: "f2",
								Type: "string",
							},
						},
					},
				},
				value: protostruct.ToValue([]interface{}{}),
			},
			want: &types.Value{Kind: &types.Value_ListValue{ListValue: &types.ListValue{Values: convertList}}},
		},
		{
			name:   "string null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "str",
					Value: &cmdb.ObjectAttrValue{
						Type: "str",
					},
				},
				value: protostruct.ToValue(20),
			},
			want: emptyStr,
		},
		{
			name:   "int",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "int",
					Value: &cmdb.ObjectAttrValue{
						Type: "int",
					},
				},
				value: protostruct.ToValue(20),
			},
			want: protostruct.ToValue("20"),
		},
		{
			name:   "string no null",
			fields: fields{},
			args: args{
				attr: &cmdb.ObjectAttr{
					Id: "str",
					Value: &cmdb.ObjectAttrValue{
						Type: "str",
					},
				},
				value: protostruct.ToValue("str"),
			},
			want: protostruct.ToValue("str"),
		},
		{
			name:   "date",
			fields: fields{},
			args: args{
				attr:  &cmdb.ObjectAttr{Value: &cmdb.ObjectAttrValue{Type: "date"}},
				value: protostruct.ToValue("2021-12-11"),
			},
			want: protostruct.ToValue("2021-12-11"),
		},
		{
			name:   "other",
			fields: fields{},
			args: args{
				attr:  &cmdb.ObjectAttr{Value: &cmdb.ObjectAttrValue{Type: "other"}},
				value: protostruct.ToValue(2),
			},
			want: protostruct.ToValue(2),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				selfEffectedIds: tt.fields.selfEffectedIds,
				floatPrecMap:    tt.fields.floatPrecMap,
			}
			if got := c.transformAttrValue(tt.args.attr, tt.args.value, ""); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformAttrValue() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformTimeValue(t *testing.T) {
	type fields struct {
		ReportConf  *fintech_data.ReportObjectConf
		mappingRule map[string]*fintech_data.AttrMapping
	}
	type args struct {
		value *types.Value
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				value: protostruct.ToValue("2020-12-05 23:42:23"),
			},
			want: protostruct.ToValue("2020-12-05 23:42"),
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				value: nil,
			},
			want: emptyStr,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:  tt.fields.ReportConf,
				mappingRule: tt.fields.mappingRule,
			}
			if got := c.transformTimeValue(tt.args.value); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformTimeValue() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformBoolValue(t *testing.T) {
	type fields struct {
		ReportConf  *fintech_data.ReportObjectConf
		mappingRule map[string]*fintech_data.AttrMapping
	}
	type args struct {
		value *types.Value
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				value: protostruct.ToValue(true),
			},
			want: protostruct.ToValue("True"),
		},
		{
			name:   "",
			fields: fields{},
			args: args{
				value: nil,
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:  tt.fields.ReportConf,
				mappingRule: tt.fields.mappingRule,
			}
			if got := c.transformBoolValue(tt.args.value); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformBoolValue() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_fillReportInstPk(t *testing.T) {
	type fields struct {
		ReportConf  *fintech_data.ReportObjectConf
		mappingRule map[string]*fintech_data.AttrMapping
		pkTranslate map[string]config.KeyTranslate
	}
	type args struct {
		reportInst *fintech_data.ReportInstance
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *fintech_data.ReportInstance
	}{
		{
			name: "",
			fields: fields{
				pkTranslate: map[string]config.KeyTranslate{
					"app": {
						ObjectId:           "app",
						FacilityDescriptor: "descriptor",
						FacilityCategory:   "category",
					},
				},
			},
			args: args{
				reportInst: &fintech_data.ReportInstance{
					ObjectId: "app",
					Data: protostruct.ToStruct(map[string]interface{}{
						"descriptor": "desc",
						"category":   "cate",
					}),
				},
			},
			want: &fintech_data.ReportInstance{
				ObjectId: "app",
				Data: protostruct.ToStruct(map[string]interface{}{
					"descriptor": "desc",
					"category":   "cate",
				}),
				FacilityDescriptor: "desc",
				FacilityCategory:   "cate",
			},
		},
		{
			name: "",
			fields: fields{
				pkTranslate: map[string]config.KeyTranslate{
					"app": {
						ObjectId:           "app",
						FacilityDescriptor: "descriptor",
						FacilityCategory:   "category",
					},
				},
			},
			args: args{
				reportInst: &fintech_data.ReportInstance{
					ObjectId: "host",
					Data: protostruct.ToStruct(map[string]interface{}{
						report_center.KeyFacilityDescriptor: "desc",
						report_center.KeyFacilityCategory:   "cate",
					}),
				},
			},
			want: &fintech_data.ReportInstance{
				ObjectId: "host",
				Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "desc",
					report_center.KeyFacilityCategory:   "cate",
				}),
				FacilityDescriptor: "desc",
				FacilityCategory:   "cate",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:  tt.fields.ReportConf,
				mappingRule: tt.fields.mappingRule,
				pkTranslate: tt.fields.pkTranslate,
			}
			c.fillReportInstPk(tt.args.reportInst)
			if !reflect.DeepEqual(tt.args.reportInst, tt.want) {
				t.Errorf("report instance not equal, got:%v, want:%v", tt.args.reportInst, tt.want)
			}
		})
	}
}

func TestConverter_RecoverReportInst(t *testing.T) {
	type fields struct {
		ReportConf  *fintech_data.ReportObjectConf
		mappingRule map[string]*fintech_data.AttrMapping
		pkTranslate map[string]config.KeyTranslate
	}
	type args struct {
		instData history.ReportMetaData
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   map[string]interface{}
	}{
		{
			name: "",
			fields: fields{
				pkTranslate: map[string]config.KeyTranslate{
					"server": {
						ObjectId:           "server",
						FacilityDescriptor: "descKey",
						FacilityCategory:   "cateKey",
					},
				},
			},
			args: args{
				instData: history.ReportMetaData{
					ObjectId:           "server",
					FacilityCategory:   "cate1",
					FacilityDescriptor: "desc1",
				},
			},
			want: map[string]interface{}{
				"descKey": "desc1",
				"cateKey": "cate1",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:  tt.fields.ReportConf,
				mappingRule: tt.fields.mappingRule,
				pkTranslate: tt.fields.pkTranslate,
			}
			if got := c.RecoverReportInst(tt.args.instData); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("RecoverReportInst() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_GetFacilityDescriptor(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		pkTranslate     map[string]config.KeyTranslate
		ignoreInstAttr  string
		ignoreAttrCate  map[string]struct{}
		selfEffectedIds map[string]struct{}
		reportObj       *cmdb.CmdbObject
	}
	type args struct {
		reportInst *fintech_data.ReportInstance
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   string
	}{
		{
			name: "",
			fields: fields{
				pkTranslate: map[string]config.KeyTranslate{},
			},
			args: args{
				reportInst: &fintech_data.ReportInstance{Data: protostruct.ToStruct(map[string]interface{}{
					report_center.KeyFacilityDescriptor: "one",
				})},
			},
			want: "one",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				pkTranslate:     tt.fields.pkTranslate,
				ignoreInstAttr:  tt.fields.ignoreInstAttr,
				ignoreAttrCate:  tt.fields.ignoreAttrCate,
				selfEffectedIds: tt.fields.selfEffectedIds,
				reportObj:       tt.fields.reportObj,
			}
			if got := c.GetFacilityDescriptor(tt.args.reportInst); got != tt.want {
				t.Errorf("GetFacilityDescriptor() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_IsOmitEmptyAttr(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		pkTranslate     map[string]config.KeyTranslate
		ignoreInstAttr  string
		ignoreAttrCate  map[string]struct{}
		selfEffectedIds map[string]struct{}
		reportObj       *cmdb.CmdbObject
		omitemptyFields []string
	}
	type args struct {
		attrId string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "",
			fields: fields{
				omitemptyFields: []string{"%_operationsManagement"},
			},
			args: args{
				attrId: "holeScanner_operationsManagement",
			},
			want: true,
		},
		{
			name: "",
			fields: fields{
				omitemptyFields: []string{"operationsManagement"},
			},
			args: args{
				attrId: "holeScanner_operationsManagement",
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				pkTranslate:     tt.fields.pkTranslate,
				ignoreInstAttr:  tt.fields.ignoreInstAttr,
				ignoreAttrCate:  tt.fields.ignoreAttrCate,
				selfEffectedIds: tt.fields.selfEffectedIds,
				reportObj:       tt.fields.reportObj,
				omitemptyFields: tt.fields.omitemptyFields,
			}
			if got := c.IsOmitEmptyAttr(tt.args.attrId); got != tt.want {
				t.Errorf("IsOmitEmptyAttr() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformFloatValue(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		pkTranslate     map[string]config.KeyTranslate
		ignoreInstAttr  string
		ignoreAttrCate  map[string]struct{}
		selfEffectedIds map[string]struct{}
		reportObj       *cmdb.CmdbObject
		omitemptyFields []string
		floatPrecMap    map[string]int
	}
	type args struct {
		value  *types.Value
		source string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				value:  protostruct.ToValue(1),
				source: "value",
			},
			want: protostruct.ToValue("1.00"),
		},
		{
			name: "",
			fields: fields{
				floatPrecMap: map[string]int{
					"value": 3,
				},
			},
			args: args{
				value:  protostruct.ToValue(2.33),
				source: "value",
			},
			want: protostruct.ToValue("2.330"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				pkTranslate:     tt.fields.pkTranslate,
				ignoreInstAttr:  tt.fields.ignoreInstAttr,
				ignoreAttrCate:  tt.fields.ignoreAttrCate,
				selfEffectedIds: tt.fields.selfEffectedIds,
				reportObj:       tt.fields.reportObj,
				omitemptyFields: tt.fields.omitemptyFields,
				floatPrecMap:    tt.fields.floatPrecMap,
			}
			if got := c.transformFloatValue(tt.args.value, tt.args.source); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformFloatValue() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformDateValue(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		pkTranslate     map[string]config.KeyTranslate
		ignoreInstAttr  string
		ignoreAttrCate  map[string]struct{}
		selfEffectedIds map[string]struct{}
		reportObj       *cmdb.CmdbObject
		omitemptyFields []string
		floatPrecMap    map[string]int
	}
	type args struct {
		value *types.Value
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				value: protostruct.ToValue(""),
			},
			want: emptyStr,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				pkTranslate:     tt.fields.pkTranslate,
				ignoreInstAttr:  tt.fields.ignoreInstAttr,
				ignoreAttrCate:  tt.fields.ignoreAttrCate,
				selfEffectedIds: tt.fields.selfEffectedIds,
				reportObj:       tt.fields.reportObj,
				omitemptyFields: tt.fields.omitemptyFields,
				floatPrecMap:    tt.fields.floatPrecMap,
			}
			if got := c.transformDateValue(tt.args.value); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformDateValue() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestConverter_transformIntValue(t *testing.T) {
	type fields struct {
		ReportConf      *fintech_data.ReportObjectConf
		mappingRule     map[string]*fintech_data.AttrMapping
		pkTranslate     map[string]config.KeyTranslate
		ignoreInstAttr  string
		ignoreAttrCate  map[string]struct{}
		selfEffectedIds map[string]struct{}
		reportObj       *cmdb.CmdbObject
		omitemptyFields []string
		floatPrecMap    map[string]int
	}
	type args struct {
		value *types.Value
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   *types.Value
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				value: protostruct.ToValue(1.2),
			},
			want: protostruct.ToValue("1"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Converter{
				ReportConf:      tt.fields.ReportConf,
				mappingRule:     tt.fields.mappingRule,
				pkTranslate:     tt.fields.pkTranslate,
				ignoreInstAttr:  tt.fields.ignoreInstAttr,
				ignoreAttrCate:  tt.fields.ignoreAttrCate,
				selfEffectedIds: tt.fields.selfEffectedIds,
				reportObj:       tt.fields.reportObj,
				omitemptyFields: tt.fields.omitemptyFields,
				floatPrecMap:    tt.fields.floatPrecMap,
			}
			if got := c.transformIntValue(tt.args.value); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("transformIntValue() = %v, want %v", got, tt.want)
			}
		})
	}
}
