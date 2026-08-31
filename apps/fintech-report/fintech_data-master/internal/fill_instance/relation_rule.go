package fill_instance

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/gogo/protobuf/proto"
	"github.com/gogo/protobuf/types"
	funk "github.com/thoas/go-funk"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

var IDRegex = regexp.MustCompile("^[0-9a-zA-Z_-]{32}$")
var IDFormatRegex = regexp.MustCompile(".+?\\[[0-9a-zA-Z_-]{32}\\]")

// 通过变更字段 判断规则是否对其实例有影响
func (r RelationRule) Effected(changeFields []string, updateData *types.Struct) bool {
	if len(changeFields) == 0 {
		return true
	}
	sourceId := r.SourceField
	if strings.Contains(r.SourceField, ".") {
		sourceId = strings.Split(sourceId, ".")[0]
	}
	if !funk.ContainsString(changeFields, sourceId) {
		return false
	}
	if updateData == nil {
		return true
	}
	values := r.GetSourceValue(updateData)
	return len(values) > 0
}

// 获取来源字段对应的值，用于查询
func (r RelationRule) GetSourceValue(instanceData *types.Struct) []interface{} {
	var valueList []interface{}
	if strings.Contains(r.SourceField, ".") {
		attrStr := strings.SplitN(r.SourceField, ".", 2)
		value := instanceData.Fields[attrStr[0]]
		if value.GetListValue() != nil {
			for _, subData := range value.GetListValue().Values {
				if value := r.getValueFromStruct(subData.GetStructValue(), attrStr[1]); value != nil {
					valueList = append(valueList, value)
				}
			}
		} else if value.GetStructValue() != nil {
			if value := r.getValueFromStruct(value.GetStructValue(), attrStr[1]); value != nil {
				valueList = append(valueList, value)
			}
		}
	} else {
		if value := r.getValueFromStruct(instanceData, r.SourceField); value != nil {
			valueList = append(valueList, value)
		}
	}
	return valueList
}

// 如果引起变更的id(SourceField)和需要变更的id(Mapping.AttrId)有相同，则返回这个id
func (r RelationRule) GetSelfEffectedAttr() string {
	field := r.SourceField
	if strings.Contains(field, ".") {
		field = strings.SplitN(r.SourceField, ".", 2)[1]
	}
	for _, item := range r.Mapping {
		if field == item.AttrId {
			return r.SourceField
		}
	}
	return ""
}

func (r RelationRule) getValueFromStruct(data *types.Struct, field string) interface{} {
	if data == nil {
		return nil
	}
	// 潜规则
	if IsIdValue(data.Fields[field].GetStringValue()) {
		return nil
	}
	return protostruct.DecodeValue(data.Fields[field])
}

func IsIdValue(str string) bool {
	if IDRegex.MatchString(str) {
		return true
	}
	if IDFormatRegex.MatchString(str) {
		return true
	}
	return false
}

func (r RelationRule) GetRelationRequest(values []interface{}) *instance.PostSearchV3Request {
	query := map[string]interface{}{r.RelatedInstance.RelatedField: map[string]interface{}{"$in": values}}
	fields := []string{r.RelatedInstance.RelatedField}
	for _, item := range r.Mapping {
		fields = append(fields, item.MappingKey)
	}
	return &instance.PostSearchV3Request{
		ObjectId: r.RelatedInstance.ObjectId,
		Query:    protostruct.ToStruct(query),
		Fields:   fields,
		Page:     1,
		PageSize: int32(len(values)),
	}
}

func (r RelationRule) Do(ctx context.Context, objectId string, instanceData *types.Struct, relatedInstMap map[string]*types.Struct) (*types.Struct, error) {
	logger := logctx.MustGetLogger(ctx)
	var result *types.Struct
	if strings.Contains(r.SourceField, ".") {
		attrStr := strings.SplitN(r.SourceField, ".", 2)
		value := instanceData.Fields[attrStr[0]]
		var structErr error
		if value.GetListValue() != nil {
			change := false
			valueList := make([]*types.Value, len(value.GetListValue().Values))
			for idx, subData := range value.GetListValue().Values {
				subChange, err := r.doStructData(attrStr[1], subData.GetStructValue(), relatedInstMap)
				if err != nil {
					logger.Errorf("object %s fill %s fail, idx: %d, error: %s", objectId, r.SourceField, idx, err.Error())
					structErr = err
				}
				change = change || subChange
				valueList[idx] = &types.Value{Kind: &types.Value_StructValue{StructValue: subData.GetStructValue()}}
			}
			if change {
				result = &types.Struct{Fields: map[string]*types.Value{attrStr[0]: {Kind: &types.Value_ListValue{ListValue: &types.ListValue{Values: valueList}}}}}
			}
			return result, structErr
		} else if structData := value.GetStructValue(); structData != nil {
			change, err := r.doStructData(attrStr[1], structData, relatedInstMap)
			if err != nil {
				logger.Errorf("object %s fill %s fail, error: %s", objectId, r.SourceField, err.Error())
				return nil, err
			}
			if change {
				result = &types.Struct{Fields: map[string]*types.Value{attrStr[0]: {Kind: &types.Value_StructValue{StructValue: structData}}}}
			}
			return result, nil
		}
	} else {
		updateData, err := r.fillRelationValue(r.SourceField, instanceData, relatedInstMap)
		if err != nil {
			logger.Errorf("object %s fill struct %s fail, error: %s", objectId, r.SourceField, err.Error())
			return nil, err
		}
		return updateData, nil
	}
	return result, nil
}

func (r RelationRule) doStructData(subAttrId string, structData *types.Struct, relatedInstMap map[string]*types.Struct) (bool, error) {
	if structData == nil {
		return false, nil
	}
	updateData, err := r.fillRelationValue(subAttrId, structData, relatedInstMap)
	if err != nil {
		return false, err
	}
	change := false
	if updateData != nil {
		change = true
		proto.Merge(structData, updateData)
	}
	return change, nil
}

// 给实例或结构体里填充关联关系数据
func (r RelationRule) fillRelationValue(sourceId string, data *types.Struct, relatedInstMap map[string]*types.Struct) (*types.Struct, error) {
	if _, ok := data.Fields[sourceId]; !ok {
		return nil, nil
	}
	valueKey := data.Fields[sourceId].GetStringValue()

	// 对唯一id类型的数据不作转换
	if IsIdValue(valueKey) {
		return nil, nil
	}
	if relatedInst, ok := relatedInstMap[valueKey]; ok {
		updateMap := make(map[string]*types.Value)
		for _, item := range r.Mapping {
			if v := item.diffValue(sourceId, data, relatedInst); v != nil {
				updateMap[item.AttrId] = v
			}
		}
		if len(updateMap) > 0 {
			return &types.Struct{Fields: updateMap}, nil
		}
		return nil, nil
	}
	return nil, fmt.Errorf("模型%s不存在%s值为%s的实例", r.RelatedInstance.ObjectId, r.RelatedInstance.RelatedField, valueKey)
}

// 比较映射后的值和原值，有差异则设置变更
func (m RelatedMapping) diffValue(sourceId string, instData *types.Struct, relatedInst *types.Struct) *types.Value {
	instValue := instData.Fields[m.AttrId]
	relatedValue := relatedInst.Fields[m.MappingKey]
	if !instValue.Equal(relatedValue) {
		var newValue *types.Value
		if sourceId == m.AttrId {
			// 更新sourceId的值时，对内容整合
			newValue = protostruct.ToValue(fmt.Sprintf("%s[%s]", instValue.GetStringValue(), relatedValue.GetStringValue()))
		} else {
			newValue = relatedValue
		}
		return newValue
	}
	return nil
}

func RecoverValueChange(value string) string {
	if IDFormatRegex.MatchString(value) {
		tmp := strings.SplitN(value, "[", 2)[1]
		return strings.ReplaceAll(tmp, "]", "")
	}
	return value
}
