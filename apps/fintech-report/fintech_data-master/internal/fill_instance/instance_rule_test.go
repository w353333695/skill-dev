package fill_instance

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"

	"github.com/gogo/protobuf/types"
	"github.com/smartystreets/goconvey/convey"

	"go.easyops.local/kit/gogoprotobuf/protostruct"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func jsonToMap(jsonStr string) map[string]interface{} {
	result := make(map[string]interface{})
	err := json.Unmarshal([]byte(jsonStr), &result)
	if err != nil {
		panic(err)
	}
	return result
}

func TestAttrDefine_GetValue(t *testing.T) {
	type fields struct {
		Key       string
		ValuePath ValuePath
	}
	type args struct {
		fillCtx fillCtx
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    interface{}
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				Key: "",
				ValuePath: ValuePath{
					Path:   `$.phoneNumbers[?(@.type=="home")].number`,
					Source: SourceTypeInstance,
				},
			},
			args: args{
				fillCtx: fillCtx{instData: jsonToMap(`{
  "firstName": "John",
  "lastName" : "doe",
  "age"      : 26,
  "address"  : {
    "streetAddress": "naist street",
    "city"         : "Nara",
    "postalCode"   : "630-0192"
  },
  "phoneNumbers": [
    {
      "type"  : "iPhone",
      "number": "0123-4567-8888"
    },
    {
      "type"  : "home",
      "number": "0123-4567-8910"
    }
  ]
}`)},
			},
			want:    []interface{}{"0123-4567-8910"},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := AttrDefine{
				Key:       tt.fields.Key,
				ValuePath: tt.fields.ValuePath,
			}
			got, err := d.GetValue(tt.args.fillCtx)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetValue() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetValue() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestCase_Compare(t *testing.T) {
	type fields struct {
		Rel       CaseRelation
		Condition []Condition
		Value     Value
	}
	type args struct {
		cmpCtx fillCtx
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "and match",
			fields: fields{
				Rel: RelAnd,
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 20,
					},
					{
						Key:   "addr",
						Opr:   "!=",
						Value: "GZ",
					},
				},
				Value: Value{},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 20, "addr": "SZ"},
					instData:   nil,
				},
			},
			want: true,
		},
		{
			name: "and not match",
			fields: fields{
				Rel: RelAnd,
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 20,
					},
					{
						Key:   "addr",
						Opr:   "!=",
						Value: "GZ",
					},
				},
				Value: Value{},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 20, "addr": "GZ"},
					instData:   nil,
				},
			},
			want: false,
		},
		{
			name: "or not match",
			fields: fields{
				Rel: RelOr,
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 20,
					},
					{
						Key:   "addr",
						Opr:   "!=",
						Value: "GZ",
					},
				},
				Value: Value{},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 30, "addr": "GZ"},
					instData:   nil,
				},
			},
			want: false,
		},
		{
			name: "or match",
			fields: fields{
				Rel: RelOr,
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 20,
					},
					{
						Key:   "addr",
						Opr:   "!=",
						Value: "GZ",
					},
				},
				Value: Value{},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 20, "addr": "GZ"},
					instData:   nil,
				},
			},
			want: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Case{
				Rel:       tt.fields.Rel,
				Condition: tt.fields.Condition,
				Value:     tt.fields.Value,
			}
			if got := c.Compare(tt.args.cmpCtx); got != tt.want {
				t.Errorf("Compare() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestCase_Match(t *testing.T) {
	type fields struct {
		Rel       CaseRelation
		Condition []Condition
		Value     Value
	}
	type args struct {
		cmpCtx fillCtx
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    bool
		want1   interface{}
		wantErr bool
	}{
		{
			name: "match",
			fields: fields{
				Rel: "",
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 18,
					},
				},
				Value: Value{
					Type:  "const",
					Const: "young",
				},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 18},
					instData:   nil,
				},
			},
			want:    true,
			want1:   "young",
			wantErr: false,
		},
		{
			name: "no match",
			fields: fields{
				Rel: "",
				Condition: []Condition{
					{
						Key:   "age",
						Opr:   "==",
						Value: 18,
					},
				},
				Value: Value{
					Type:  "const",
					Const: "young",
				},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 20},
					instData:   nil,
				},
			},
			want:    false,
			want1:   nil,
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Case{
				Rel:       tt.fields.Rel,
				Condition: tt.fields.Condition,
				Value:     tt.fields.Value,
			}
			got, got1, err := c.Match(tt.args.cmpCtx)
			if (err != nil) != tt.wantErr {
				t.Errorf("Match() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if got != tt.want {
				t.Errorf("Match() got = %v, want %v", got, tt.want)
			}
			if !reflect.DeepEqual(got1, tt.want1) {
				t.Errorf("Match() got1 = %v, want %v", got1, tt.want1)
			}
		})
	}
}

func TestCondition_Compare(t *testing.T) {
	type fields struct {
		Key   string
		Opr   ConditionOpr
		Value interface{}
	}
	type args struct {
		cmpCtx fillCtx
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
				Key:   "age",
				Opr:   OprNoEqual,
				Value: 20,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 21},
				},
			},
			want: true,
		},
		{
			name: "in",
			fields: fields{
				Key:   "key",
				Opr:   OprIn,
				Value: []interface{}{"one", "two"},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"key": "one"},
				},
			},
			want: true,
		},
		{
			name: "nin",
			fields: fields{
				Key:   "key",
				Opr:   OprNin,
				Value: []interface{}{"one", "two"},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"key": "one"},
				},
			},
			want: false,
		},
		{
			name: "is null",
			fields: fields{
				Key: "other",
				Opr: OprIsNull,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"key": "one"},
				},
			},
			want: true,
		},
		{
			name: "not null",
			fields: fields{
				Key: "other",
				Opr: OprNotNull,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"key": "one"},
				},
			},
			want: false,
		},
		{
			name: "unknown",
			fields: fields{
				Key:   "age",
				Opr:   "other",
				Value: 20,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: map[string]interface{}{"age": 21},
				},
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Condition{
				Key:   tt.fields.Key,
				Opr:   tt.fields.Opr,
				Value: tt.fields.Value,
			}
			if got := c.Compare(tt.args.cmpCtx); got != tt.want {
				t.Errorf("Compare() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRule_Do_Err(t *testing.T) {
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	instData := protostruct.ToStruct(jsonToMap(`{
  "firstName": "John",
  "lastName" : "doe",
  "age"      : 26,
  "address"  : {
    "streetAddress": "naist street",
    "city"         : "Nara",
    "postalCode"   : "630-0192"
  },
  "phoneNumbers": [
    {
      "type"  : "iPhone",
      "number": "0123-4567-8888"
    },
    {
      "type"  : "home",
      "number": "0123-4567-8910"
    }
  ]
}`))
	type fields struct {
		ObjectId   string
		AttrId     string
		AttrSource []AttrDefine
		FillCmdb   bool
		Case       []Case
		Default    *Value
	}
	type args struct {
		ctx  context.Context
		data *types.Struct
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *types.Struct
		wantErr bool
	}{
		{
			name: "get value fail",
			fields: fields{
				ObjectId: "",
				AttrId:   "",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path: "$.unknown",
						},
					},
				},
				FillCmdb: false,
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "==",
								Value: float64(27),
							},
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeMapping,
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
				},
				Default: &Value{},
			},
			args: args{
				ctx:  ctx,
				data: instData,
			},
			wantErr: true,
		},
		{
			name: "get default fail",
			fields: fields{
				ObjectId: "",
				AttrId:   "",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "age",
						ValuePath: ValuePath{
							Path:   "$.age",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "city",
						ValuePath: ValuePath{
							Path:   "$.address.city",
							Source: SourceTypeInstance,
						},
					},
				},
				FillCmdb: false,
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "==",
								Value: float64(27),
							},
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeMapping,
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
					{
						Rel: "or",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "==",
								Value: float64(27),
							},
							{
								Key:   "city",
								Opr:   "==",
								Value: "GZ",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "82204012",
						},
					},
				},
				Default: &Value{
					Type: ValueTypeMapping,
					ValuePath: ValuePath{
						Path:   "$.unknown",
						Source: SourceTypeInstance,
					},
				},
			},
			args: args{
				ctx:  ctx,
				data: instData,
			},
			wantErr: true,
		},
		{
			name: "match fail",
			fields: fields{
				ObjectId: "",
				AttrId:   "",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
				},
				FillCmdb: false,
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  "other",
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
				},
			},
			args: args{
				ctx:  ctx,
				data: instData,
			},
			wantErr: true,
		},
		{
			name: "not struct field",
			fields: fields{
				ObjectId: "",
				AttrId:   "firstName.me",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
				},
				FillCmdb: false,
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  "other",
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
				},
			},
			args: args{
				ctx:  ctx,
				data: instData,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := InstanceRule{
				RuleObjectConf: RuleObjectConf{
					ObjectId: tt.fields.ObjectId,
				},
				AttrId:     tt.fields.AttrId,
				AttrSource: tt.fields.AttrSource,
				Case:       tt.fields.Case,
				Default:    tt.fields.Default,
			}
			got, err := r.Do(tt.args.ctx, tt.args.data)
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

func TestRule_Do(t *testing.T) {
	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	instData := protostruct.ToStruct(jsonToMap(`{
  "firstName": "John",
  "lastName" : "doe",
  "age"      : 26,
  "address"  : {
    "streetAddress": "naist street",
    "city"         : "Nara",
    "postalCode"   : "630-0192"
  },
  "phoneNumbers": [
    {
      "type"  : "iPhone",
      "number": "0123-4567-8888"
    },
    {
      "type"  : "home",
      "number": "0123-4567-8910"
    }
  ]
}`))

	convey.Convey("instance compare", t, func() {
		convey.Convey("match first", func() {
			rule := InstanceRule{
				AttrId: "number",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "age",
						ValuePath: ValuePath{
							Path:   "$.age",
							Source: SourceTypeInstance,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "==",
								Value: float64(26),
							},
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeMapping,
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			convey.So(got.Equal(&types.Struct{Fields: map[string]*types.Value{"number": protostruct.ToValue("0123-4567-8888")}}), convey.ShouldBeTrue)
		},
		)
		convey.Convey("match second", func() {
			rule := InstanceRule{
				AttrId: "number",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "age",
						ValuePath: ValuePath{
							Path:   "$.age",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "city",
						ValuePath: ValuePath{
							Path:   "$.address.city",
							Source: SourceTypeInstance,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "!=",
								Value: float64(26),
							},
						},
						Value: Value{
							Type:  ValueTypeMapping,
							Const: nil,
							ValuePath: ValuePath{
								Path:   "$.phoneNumbers[0].number",
								Source: SourceTypeInstance,
							},
						},
					},
					{
						Rel: "or",
						Condition: []Condition{
							{
								Key:   "age",
								Opr:   "==",
								Value: float64(27),
							},
							{
								Key:   "city",
								Opr:   "==",
								Value: "Nara",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "82204012",
						},
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			convey.So(got.Equal(&types.Struct{Fields: map[string]*types.Value{"number": protostruct.ToValue("82204012")}}), convey.ShouldBeTrue)
		},
		)
		convey.Convey("get default", func() {
			rule := InstanceRule{
				AttrId: "number",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
				},
				Case: []Case{
					{
						Rel: "or",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "==",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "82204012",
						},
					},
				},
				Default: &Value{
					Type:  ValueTypeConst,
					Const: "020-110",
				},
			}
			got, _ := rule.Do(ctx, instData)
			convey.So(got.Equal(&types.Struct{Fields: map[string]*types.Value{"number": protostruct.ToValue("020-110")}}), convey.ShouldBeTrue)
		},
		)
		convey.Convey("not match", func() {
			rule := InstanceRule{
				AttrId: "number",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
				},
				Case: []Case{
					{
						Rel: "or",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "==",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "82204012",
						},
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			convey.So(got, convey.ShouldBeNil)
		},
		)
		convey.Convey("not different", func() {
			rule := InstanceRule{
				AttrId: "lastName",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
				},
				Case: []Case{
					{
						Rel: "or",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "doe",
						},
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			convey.So(got, convey.ShouldBeNil)
		},
		)
	})

	convey.Convey("structs compare", t, func() {
		convey.Convey("match", func() {
			rule := InstanceRule{
				AttrId: "phoneNumbers.level",
				AttrSource: []AttrDefine{
					{
						Key: "name",
						ValuePath: ValuePath{
							Path:   "$.firstName",
							Source: SourceTypeInstance,
						},
					},
					{
						Key: "type",
						ValuePath: ValuePath{
							Path:   "$.type",
							Source: SourceTypeStruct,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
							{
								Key:   "type",
								Opr:   "==",
								Value: "iPhone",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "good",
						},
					},
				},
				Default: &Value{
					Type: ValueTypeMapping,
					ValuePath: ValuePath{
						Path:   "$.type",
						Source: SourceTypeStruct,
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			result := make([]interface{}, 0)
			jsonStr := `[{"type": "iPhone","number": "0123-4567-8888", "level": "good"},{"type"  : "home","number": "0123-4567-8910", "level": "home"}]`
			_ = json.Unmarshal([]byte(jsonStr), &result)
			convey.So(got.Equal(&types.Struct{Fields: map[string]*types.Value{"phoneNumbers": protostruct.ToValue(result)}}), convey.ShouldBeTrue)
		},
		)
		convey.Convey("fail", func() {
			rule := InstanceRule{
				AttrId: "phoneNumbers.level",
				AttrSource: []AttrDefine{
					{
						Key: "type",
						ValuePath: ValuePath{
							Path:   "$.now",
							Source: SourceTypeStruct,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
							{
								Key:   "type",
								Opr:   "==",
								Value: "iPhone",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "good",
						},
					},
				},
			}
			_, err := rule.Do(ctx, instData)
			convey.So(err, convey.ShouldBeError)
		},
		)
	})

	convey.Convey("struct compare", t, func() {
		convey.Convey("match", func() {
			rule := InstanceRule{
				AttrId: "address.level",
				AttrSource: []AttrDefine{
					{
						Key: "city",
						ValuePath: ValuePath{
							Path:   "$.city",
							Source: SourceTypeStruct,
						},
					},
					{
						Key: "postalCode",
						ValuePath: ValuePath{
							Path:   "$.postalCode",
							Source: SourceTypeStruct,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "city",
								Opr:   "!=",
								Value: "other",
							},
							{
								Key:   "postalCode",
								Opr:   "==",
								Value: "630-0192",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "good",
						},
					},
				},
			}
			got, _ := rule.Do(ctx, instData)
			result := jsonToMap(`{"streetAddress": "naist street","city": "Nara","postalCode": "630-0192", "level": "good"}`)
			convey.So(got.Equal(&types.Struct{Fields: map[string]*types.Value{"address": protostruct.ToValue(result)}}), convey.ShouldBeTrue)
		},
		)
		convey.Convey("fail", func() {
			rule := InstanceRule{
				AttrId: "address.level",
				AttrSource: []AttrDefine{
					{
						Key: "type",
						ValuePath: ValuePath{
							Path:   "$.now",
							Source: SourceTypeStruct,
						},
					},
				},
				Case: []Case{
					{
						Rel: "and",
						Condition: []Condition{
							{
								Key:   "name",
								Opr:   "!=",
								Value: "other",
							},
						},
						Value: Value{
							Type:  ValueTypeConst,
							Const: "good",
						},
					},
				},
			}
			_, err := rule.Do(ctx, instData)
			convey.So(err, convey.ShouldBeError)
		},
		)
	})
}

func TestValue_GetValue(t *testing.T) {
	type fields struct {
		Type      ValueType
		Const     interface{}
		ValuePath ValuePath
	}
	type args struct {
		cmpCtx fillCtx
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    interface{}
		wantErr bool
	}{
		{
			name: "mapping",
			fields: fields{
				Type:  ValueTypeMapping,
				Const: nil,
				ValuePath: ValuePath{
					Path:   `$.age`,
					Source: SourceTypeInstance,
				},
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: nil,
					instData:   jsonToMap(`{"age":30}`),
				},
			},
			want:    float64(30),
			wantErr: false,
		},
		{
			name: "const",
			fields: fields{
				Type:  ValueTypeConst,
				Const: 30,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: nil,
					instData:   jsonToMap(`{"age":30}`),
				},
			},
			want:    30,
			wantErr: false,
		},
		{
			name: "invalid",
			fields: fields{
				Type:  "invalid",
				Const: 30,
			},
			args: args{
				cmpCtx: fillCtx{
					attrSource: nil,
					instData:   jsonToMap(`{"age":30}`),
				},
			},
			want:    nil,
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			v := Value{
				Type:      tt.fields.Type,
				Const:     tt.fields.Const,
				ValuePath: tt.fields.ValuePath,
			}
			got, err := v.GetValue(tt.args.cmpCtx)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetValue() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetValue() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestRule_GetAttrId(t *testing.T) {
	type fields struct {
		ObjectId   string
		AttrId     string
		AttrSource []AttrDefine
		FillCmdb   bool
		Case       []Case
		Default    *Value
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name: "",
			fields: fields{
				AttrId: "address.name",
			},
			want: "address",
		},
		{
			name: "",
			fields: fields{
				AttrId: "name",
			},
			want: "name",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := InstanceRule{
				RuleObjectConf: RuleObjectConf{
					ObjectId: tt.fields.ObjectId,
				},
				AttrId:     tt.fields.AttrId,
				AttrSource: tt.fields.AttrSource,
				Case:       tt.fields.Case,
				Default:    tt.fields.Default,
			}
			if got := r.GetAttrId(); got != tt.want {
				t.Errorf("GetPathAttr() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestInstanceRule_Effected(t *testing.T) {
	type fields struct {
		ObjectId   string
		AttrId     string
		AttrSource []AttrDefine
		Case       []Case
		Default    *Value
	}
	type args struct {
		changeFields []string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "effected",
			fields: fields{
				AttrId: "struct.name",
				AttrSource: []AttrDefine{
					{
						Key: "one",
						ValuePath: ValuePath{
							Path:   "$.id",
							Source: SourceTypeStruct,
						},
					},
					{
						Key: "two",
						ValuePath: ValuePath{
							Path:   "$.name",
							Source: SourceTypeInstance,
						},
					},
				},
			},
			args: args{
				changeFields: []string{"name"},
			},
			want: true,
		},
		{
			name: "no effected",
			fields: fields{
				AttrId: "name",
				AttrSource: []AttrDefine{
					{
						Key: "one",
						ValuePath: ValuePath{
							Path:   "$.struct.name",
							Source: SourceTypeInstance,
						},
					},
				},
			},
			args: args{
				changeFields: []string{"name"},
			},
			want: false,
		},
		{
			name: "no change field",
			fields: fields{
				AttrId: "name",
				AttrSource: []AttrDefine{
					{
						Key: "one",
						ValuePath: ValuePath{
							Path:   "$.struct.name",
							Source: SourceTypeInstance,
						},
					},
				},
			},
			args: args{
				changeFields: []string{},
			},
			want: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := InstanceRule{
				RuleObjectConf: RuleObjectConf{
					ObjectId: tt.fields.ObjectId,
				},
				AttrId:     tt.fields.AttrId,
				AttrSource: tt.fields.AttrSource,
				Case:       tt.fields.Case,
				Default:    tt.fields.Default,
			}
			if got := r.Effected(tt.args.changeFields); got != tt.want {
				t.Errorf("Effected() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestValuePath_GetPathAttr(t *testing.T) {
	type fields struct {
		Path   string
		Source SourceType
	}
	type args struct {
		attrId string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   string
	}{
		{
			name: "attr",
			fields: fields{
				Path:   "$.fakeId",
				Source: SourceTypeInstance,
			},
			args: args{
				attrId: "name",
			},
			want: "fakeId",
		},
		{
			name: "attr",
			fields: fields{
				Path:   "$.struct.name",
				Source: SourceTypeInstance,
			},
			args: args{
				attrId: "name",
			},
			want: "struct",
		},
		{
			name: "double .",
			fields: fields{
				Path:   "$..name",
				Source: SourceTypeInstance,
			},
			args: args{
				attrId: "name",
			},
			want: "",
		},
		{
			name: "has []",
			fields: fields{
				Path:   "$.struct[0].name",
				Source: SourceTypeInstance,
			},
			args: args{
				attrId: "name",
			},
			want: "struct",
		},
		{
			name: "struct",
			fields: fields{
				Path:   "$.id",
				Source: SourceTypeStruct,
			},
			args: args{
				attrId: "struct.name",
			},
			want: "struct",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := ValuePath{
				Path:   tt.fields.Path,
				Source: tt.fields.Source,
			}
			if got := p.GetPathAttr(tt.args.attrId); got != tt.want {
				t.Errorf("GetPathAttr() = %v, want %v", got, tt.want)
			}
		})
	}
}
