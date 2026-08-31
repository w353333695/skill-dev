package fill_instance

import (
	"context"
	"strings"

	"github.com/PaesslerAG/jsonpath"
	"github.com/gogo/protobuf/types"

	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

// 比较时所需要的上下文
type fillCtx struct {
	attrSource map[string]interface{}
	instData   map[string]interface{}
	structData map[string]interface{}
	attrId     string
}

func (r InstanceRule) Effected(changeFields []string) bool {
	if len(changeFields) == 0 {
		return true
	}
	changeMap := make(map[string]struct{})
	for _, f := range changeFields {
		changeMap[f] = struct{}{}
	}
	for _, attr := range r.AttrSource {
		pathAttr := attr.GetPathAttr(r.AttrId)
		if _, ok := changeMap[pathAttr]; ok {
			return true
		}
	}
	return false
}

func (r InstanceRule) Do(ctx context.Context, instance *types.Struct) (*types.Struct, error) {
	fillCtx := fillCtx{instData: protostruct.DecodeToMap(instance)}
	if strings.Contains(r.AttrId, ".") {
		var result *types.Struct
		attrStr := strings.SplitN(r.AttrId, ".", 2)
		value := instance.Fields[attrStr[0]]
		fillCtx.attrId = attrStr[1]
		if value.GetListValue() != nil {
			valueList := make([]*types.Value, len(value.GetListValue().Values))
			change := false
			for idx, subData := range value.GetListValue().Values {
				if subStruct := subData.GetStructValue(); subStruct != nil {
					fillCtx.structData = protostruct.DecodeToMap(subStruct)
					updateData, err := r.do(ctx, fillCtx, subStruct)
					if err != nil {
						return nil, err
					}
					if updateData != nil {
						change = true
						subStruct.Fields[fillCtx.attrId] = updateData.Fields[fillCtx.attrId]
					}
					valueList[idx] = &types.Value{Kind: &types.Value_StructValue{StructValue: subStruct}}
				}
			}
			if change {
				result = &types.Struct{Fields: map[string]*types.Value{attrStr[0]: {Kind: &types.Value_ListValue{ListValue: &types.ListValue{Values: valueList}}}}}
			}
			return result, nil
		} else if value.GetStructValue() != nil {
			structData := value.GetStructValue()
			fillCtx.structData = protostruct.DecodeToMap(structData)
			updateData, err := r.do(ctx, fillCtx, structData)
			if err != nil {
				return nil, err
			}
			if updateData != nil {
				structData.Fields[fillCtx.attrId] = updateData.Fields[fillCtx.attrId]
				result = &types.Struct{Fields: map[string]*types.Value{attrStr[0]: {Kind: &types.Value_StructValue{StructValue: structData}}}}
			}
			return result, nil
		}
	} else {
		fillCtx.attrId = r.AttrId
		return r.do(ctx, fillCtx, instance)
	}
	return nil, nil
}

func (r InstanceRule) do(ctx context.Context, fillCtx fillCtx, data *types.Struct) (*types.Struct, error) {
	logger := logctx.MustGetLogger(ctx)

	// 遍历attrSource，逐个取比较值
	fillCtx.attrSource = make(map[string]interface{})
	for _, source := range r.AttrSource {
		value, err := source.GetValue(fillCtx)
		if err != nil {
			logger.Errorf("get key %s path %s value fail, error: %s", source.Key, source.Path, err.Error())
			if !source.IgnoreFail {
				return nil, err
			}
		}
		fillCtx.attrSource[source.Key] = value
	}

	// 逐个case比较
	for _, ruleCase := range r.Case {
		matched, value, err := ruleCase.Match(fillCtx)
		if err != nil {
			logger.Errorf("match case fail, case: %v, error: %s", ruleCase, err.Error())
			return nil, err
		}
		if matched {
			return compareValue(value, data, fillCtx.attrId), nil
		}
	}

	// 获取默认值
	if r.Default != nil {
		rawDefault, err := r.Default.GetValue(fillCtx)
		if err != nil {
			logger.Errorf("get default value fail, default: %v, error: %s", r.Default, err)
			return nil, err
		}
		return compareValue(rawDefault, data, fillCtx.attrId), nil
	}
	return nil, nil
}

func (r InstanceRule) GetAttrId() string {
	if strings.Contains(r.AttrId, ".") {
		return strings.Split(r.AttrId, ".")[0]
	}
	return r.AttrId
}

func compareValue(value interface{}, data *types.Struct, attrId string) *types.Struct {
	preValue := data.Fields[attrId]
	newValue := protostruct.ToValue(value)
	if !preValue.Equal(newValue) {
		return &types.Struct{Fields: map[string]*types.Value{attrId: newValue}}
	}
	return nil
}

// 根据路径从实例获取值
func (d AttrDefine) GetValue(fillCtx fillCtx) (interface{}, error) {
	return d.GetByPath(fillCtx)
}

// 与case里每个condition比较
func (c Case) Compare(fillCtx fillCtx) bool {
	result := false
	for _, cdn := range c.Condition {
		match := cdn.Compare(fillCtx)
		if c.Rel == RelOr && match {
			return true
		} else if c.Rel == RelAnd && !match {
			return false
		}
		result = result || match
	}
	return result
}

func (c Case) Match(fillCtx fillCtx) (bool, interface{}, error) {
	if c.Compare(fillCtx) {
		value, err := c.Value.GetValue(fillCtx)
		return true, value, err
	}
	return false, nil, nil
}

// 比较值
func (c Condition) Compare(fillCtx fillCtx) bool {
	srcValue := fillCtx.attrSource[c.Key]
	switch c.Opr {
	case OprEqual:
		return CompareEq(srcValue, c.Value)
	case OprNoEqual:
		return CompareNeq(srcValue, c.Value)
	case OprIn:
		return CompareIn(srcValue, c.Value)
	case OprNin:
		return CompareNin(srcValue, c.Value)
	case OprIsNull:
		return CompareIsNull(srcValue)
	case OprNotNull:
		return CompareNotNull(srcValue)
	}
	return false
}

// 获取设置的值
func (v Value) GetValue(fillCtx fillCtx) (interface{}, error) {
	switch v.Type {
	case ValueTypeConst:
		return v.Const, nil
	case ValueTypeMapping:
		return v.GetByPath(fillCtx)
	}
	return nil, apierrors.InvalidArgumentErrorf("invalid value type %s", v.Type)
}

// 根据path和source获取值
func (p ValuePath) GetByPath(fillCtx fillCtx) (interface{}, error) {
	if p.Source == SourceTypeStruct {
		return jsonpath.Get(p.Path, fillCtx.structData)
	}
	return jsonpath.Get(p.Path, fillCtx.instData)
}

// 获取json path的首位属性 如 path: $.struct.name  return: struct
func (p ValuePath) GetPathAttr(attrId string) string {
	if p.Source == SourceTypeStruct {
		return strings.SplitN(attrId, ".", 2)[0]
	}
	pattern := strings.SplitN(p.Path, ".", 3)[1]
	if strings.Contains(pattern, "[") {
		pattern = strings.Split(pattern, "[")[0]
	}
	return pattern
}
