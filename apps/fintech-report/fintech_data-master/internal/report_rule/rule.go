package report_rule

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/gogo/protobuf/types"
	"github.com/spf13/cast"

	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/stringutil"
	"go.easyops.local/fintech_data/internal/extends/typeutil"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func GetSearchObjectId(conf *fintech_data.ReportObjectConf) string {
	if conf.Source == ObjectSourceMapping {
		return conf.MappingObjectId
	}
	return conf.ObjectId
}

func GetMappingObjectId(conf *fintech_data.ReportObjectConf) string {
	if conf.Source == ObjectSourceMapping {
		return conf.MappingObjectId
	}
	return ""
}

type Converter struct {
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

func NewConverter(reportObj *cmdb.CmdbObject, objectConf *fintech_data.ReportObjectConf, innerConf config.ReportConf, relationRules []fill_instance.RelationRule) Converter {
	selfEffectedIds := genSelfEffectedIds(objectConf, relationRules)
	mappingRule := make(map[string]*fintech_data.AttrMapping)
	if objectConf.Source == ObjectSourceMapping {
		for _, rule := range objectConf.MappingRule.GetAttrMapping() {
			mappingRule[rule.ReportAttrId] = rule
		}
	}
	pkTranslate := make(map[string]config.KeyTranslate)
	for _, item := range innerConf.PKTranslate {
		pkTranslate[item.ObjectId] = item
	}
	ignoreAttrCate := make(map[string]struct{})
	for _, cate := range innerConf.IgnoreConf.AttrIgnoreCategory {
		ignoreAttrCate[cate] = struct{}{}
	}
	floatPrecMap := map[string]int{}
	for _, item := range innerConf.FloatPrecRule {
		if item.ObjectId == objectConf.ObjectId {
			floatPrecMap = item.Rule
			break
		}
	}
	return Converter{
		ReportConf:      objectConf,
		mappingRule:     mappingRule,
		pkTranslate:     pkTranslate,
		ignoreInstAttr:  innerConf.IgnoreConf.InstanceIgnoreAttr,
		ignoreAttrCate:  ignoreAttrCate,
		selfEffectedIds: selfEffectedIds,
		reportObj:       reportObj,
		omitemptyFields: innerConf.OmitemptyFields,
		floatPrecMap:    floatPrecMap,
	}
}

// 获取所有关系填充规则中会变更自身sourceField的字段映射
func genSelfEffectedIds(objectConf *fintech_data.ReportObjectConf, relationRules []fill_instance.RelationRule) map[string]struct{} {
	selfEffectedIds := make(map[string]struct{})
	objectId := GetSearchObjectId(objectConf)
	mappingAttrs := make(map[string]string)
	if objectConf.Source == ObjectSourceMapping {
		for _, rule := range objectConf.MappingRule.GetAttrMapping() {
			mappingAttrs[rule.MappingAttrId] = rule.ReportAttrId
		}
	}
	for _, rule := range relationRules {
		if !rule.EffectedObject(objectId) {
			continue
		}
		if attrId := rule.GetSelfEffectedAttr(); attrId != "" {
			field := attrId
			if strings.Contains(attrId, ".") {
				field = strings.SplitN(attrId, ".", 2)[0]
			}
			if reportId, ok := mappingAttrs[field]; ok {
				attrId = strings.ReplaceAll(attrId, field, reportId)
			}
			selfEffectedIds[attrId] = struct{}{}
		}
	}
	return selfEffectedIds
}

// 判断属性是否应该上报
func (c Converter) attrShouldReport(attr *cmdb.ObjectAttr) bool {
	for _, t := range attr.Tag {
		if _, ok := c.ignoreAttrCate[t]; ok {
			return false
		}
	}
	return true
}

// 根据配置转换上报数据
func (c Converter) ConvertReportInst(reportInst *fintech_data.ReportInstance) {
	if reportInst.ReportType == report_center.ReportTypeDelete {
		return
	}

	reportData := make(map[string]interface{})
	for _, attr := range c.reportObj.AttrList {
		if !c.attrShouldReport(attr) {
			continue
		}
		if attr.Id == c.ignoreInstAttr {
			if reportInst.Data.Fields[attr.Id].GetBoolValue() {
				reportData[attr.Id] = reportInst.Data.Fields[attr.Id].GetBoolValue()
			}
			continue
		}
		var value *types.Value
		// 模型属性映射
		if c.ReportConf.Source == ObjectSourceMapping {
			value = c.convertMappingValue(c.mappingRule, attr.Id, reportInst.Data)
		} else {
			value = reportInst.Data.Fields[attr.Id]
		}

		// 如果数据为空，且设置为omitempty则忽略
		if value != nil || !c.IsOmitEmptyAttr(attr.Id) {
			// 统一属性值转换
			reportData[attr.Id] = protostruct.DecodeValue(c.transformAttrValue(attr, value, ""))
		}
	}
	reportInst.Data = protostruct.ToStruct(reportData)
	c.fillReportInstPk(reportInst)
}

func (c Converter) IsOmitEmptyAttr(attrId string) bool {
	for _, field := range c.omitemptyFields {
		if stringutil.FuzzyMatch(field, attrId) {
			return true
		}
	}
	return false
}

// 复原上报数据
func (c Converter) RecoverReportInst(instData history.ReportMetaData) map[string]interface{} {
	keyCategory, keyDescriptor := c.getPkKeys(instData.ObjectId)
	return map[string]interface{}{
		keyCategory:   instData.FacilityCategory,
		keyDescriptor: instData.FacilityDescriptor,
	}
}

// 复原上报数据
func (c Converter) GetFacilityDescriptor(reportInst *fintech_data.ReportInstance) string {
	_, keyDescriptor := c.getPkKeys(reportInst.ObjectId)
	return cast.ToString(protostruct.DecodeValue(reportInst.Data.Fields[keyDescriptor]))
}

func (c Converter) fillReportInstPk(reportInst *fintech_data.ReportInstance) {
	keyCategory, keyDescriptor := c.getPkKeys(reportInst.ObjectId)
	reportInst.FacilityCategory = cast.ToString(protostruct.DecodeValue(reportInst.Data.Fields[keyCategory]))
	reportInst.FacilityDescriptor = cast.ToString(protostruct.DecodeValue(reportInst.Data.Fields[keyDescriptor]))
}

func (c Converter) getPkKeys(objectId string) (string, string) {
	var keyCategory, keyDescriptor string
	if conf, ok := c.pkTranslate[objectId]; ok {
		keyCategory = conf.FacilityCategory
		keyDescriptor = conf.FacilityDescriptor
	} else {
		keyCategory = report_center.KeyFacilityCategory
		keyDescriptor = report_center.KeyFacilityDescriptor
	}
	return keyCategory, keyDescriptor
}

func (c Converter) convertMappingValue(mappingRule map[string]*fintech_data.AttrMapping, attrId string, instData *types.Struct) *types.Value {
	if attrMap, ok := mappingRule[attrId]; ok {
		if attrMap.MappingAttrId != "" {
			return instData.Fields[attrMap.MappingAttrId]
		}
	}
	return instData.Fields[attrId]
}

func (c Converter) transformAttrValue(attr *cmdb.ObjectAttr, value *types.Value, source string) *types.Value {
	// 人行要求空值传空字符串: ""
	if !attrTypeIsCombine(attr.Value.Type) && typeutil.IsNullValue(value) {
		return emptyStr
	}
	sourceId := attr.Id
	if source != "" {
		sourceId = fmt.Sprintf("%s.%s", source, attr.Id)
	}
	switch attr.Value.Type {
	case "str":
		return c.transformStringValue(value, sourceId)
	case "datetime":
		return c.transformTimeValue(value)
	case "date":
		return c.transformDateValue(value)
	case "bool":
		return c.transformBoolValue(value)
	case "enum":
		return c.transformEnumValue(value)
	case "enums":
		return c.transformEnumsValue(value)
	case "int":
		return c.transformIntValue(value)
	case "float":
		return c.transformFloatValue(value, sourceId)
	case "struct":
		attrList := convertStructAttrs(attr.Value.StructDefine)
		return c.transformStructValue(attrList, value, sourceId)
	case "structs":
		attrList := convertStructAttrs(attr.Value.StructDefine)
		return c.transformStructs(attrList, value, sourceId)
	}
	return value
}

var emptyStr = protostruct.ToValue("")

// 字符转换 为空时上报空字符串
func (c Converter) transformStringValue(value *types.Value, attrId string) *types.Value {
	if value.GetStringValue() == "" {
		return emptyStr
	}
	if _, ok := c.selfEffectedIds[attrId]; ok {
		return protostruct.ToValue(fill_instance.RecoverValueChange(value.GetStringValue()))
	}
	return value
}

// 枚举列表 [00, 01] -> "00,01"
func (c Converter) transformEnumsValue(value *types.Value) *types.Value {
	valueList := value.GetListValue()
	if valueList == nil {
		return value
	}
	convertList := make([]string, 0, len(valueList.Values))
	for _, item := range valueList.Values {
		v := c.transformEnumValue(item)
		if v.GetStringValue() != "" {
			convertList = append(convertList, v.GetStringValue())
		}
	}
	return &types.Value{Kind: &types.Value_StringValue{StringValue: strings.Join(convertList, ",")}}
}

// 枚举
func (c Converter) transformEnumValue(value *types.Value) *types.Value {
	valueStr := value.GetStringValue()
	if valueStr == "" {
		return emptyStr
	}
	regexFormat := "^\\d+%s.*$"
	for _, p := range []string{"-", ":", "："} {
		r := regexp.MustCompile(fmt.Sprintf(regexFormat, p))
		if r.MatchString(valueStr) {
			valueStr = strings.SplitN(valueStr, p, 2)[0]
			break
		}
	}
	return protostruct.ToValue(valueStr)
}

// 布尔
func (c Converter) transformBoolValue(value *types.Value) *types.Value {
	if typeutil.IsNullValue(value) {
		return nil
	}
	valueBool := value.GetBoolValue()
	if valueBool {
		return protostruct.ToValue("True")
	} else {
		return protostruct.ToValue("False")
	}
}

// 时间
func (c Converter) transformTimeValue(value *types.Value) *types.Value {
	valueStr := value.GetStringValue()
	if valueStr == "" {
		return emptyStr
	}
	strList := strings.Split(valueStr, ":")
	strLen := len(strList)
	reportStr := strings.Join(strList[:strLen-1], ":")
	return protostruct.ToValue(reportStr)
}

// 日期
func (c Converter) transformDateValue(value *types.Value) *types.Value {
	valueStr := value.GetStringValue()
	if valueStr == "" {
		return emptyStr
	}
	return value
}

// 整型
func (c Converter) transformIntValue(value *types.Value) *types.Value {
	number := value.GetNumberValue()
	numberStr := strconv.FormatFloat(number, 'f', 0, 64)
	return &types.Value{Kind: &types.Value_StringValue{StringValue: numberStr}}
}

// 浮点
func (c Converter) transformFloatValue(value *types.Value, source string) *types.Value {
	prec := 2
	if p, ok := c.floatPrecMap[source]; ok {
		prec = p
	}
	number := value.GetNumberValue()
	numberStr := strconv.FormatFloat(number, 'f', prec, 64)
	return &types.Value{Kind: &types.Value_StringValue{StringValue: numberStr}}
}

// 结构体
func (c Converter) transformStructValue(attrList []*cmdb.ObjectAttr, value *types.Value, source string) *types.Value {
	valueStruct := value.GetStructValue()
	if valueStruct == nil {
		convertValue := make(map[string]*types.Value)
		for _, subAttr := range attrList {
			convertValue[subAttr.Id] = emptyStr
		}
		return &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}}
	}
	convertValue := make(map[string]*types.Value)
	for _, subAttr := range attrList {
		originValue := valueStruct.Fields[subAttr.Id]
		convertValue[subAttr.Id] = c.transformAttrValue(subAttr, originValue, source)
	}
	return &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}}
}

// 结构体数组
func (c Converter) transformStructs(attrList []*cmdb.ObjectAttr, value *types.Value, source string) *types.Value {
	valueList := value.GetListValue()
	if valueList == nil || len(valueList.Values) == 0 {
		var convertList []*types.Value
		convertValue := make(map[string]*types.Value)
		for _, subAttr := range attrList {
			convertValue[subAttr.Id] = emptyStr
		}
		s := &types.Value{Kind: &types.Value_StructValue{StructValue: &types.Struct{Fields: convertValue}}}
		convertList = append(convertList, s)
		return &types.Value{Kind: &types.Value_ListValue{ListValue: &types.ListValue{Values: convertList}}}
	}
	convertList := make([]*types.Value, len(valueList.Values))
	for idx, item := range valueList.Values {
		convertList[idx] = c.transformStructValue(attrList, item, source)
	}
	return &types.Value{Kind: &types.Value_ListValue{ListValue: &types.ListValue{Values: convertList}}}
}

func convertStructAttrs(structAttrs []*cmdb.ObjectAttrValueStruct) []*cmdb.ObjectAttr {
	attrList := make([]*cmdb.ObjectAttr, len(structAttrs))
	for idx, subAttr := range structAttrs {
		refactorAttr := &cmdb.ObjectAttr{
			Id:   subAttr.Id,
			Name: subAttr.Name,
			Value: &cmdb.ObjectAttrValue{
				Type:  subAttr.Type,
				Regex: subAttr.Regex,
			},
		}
		attrList[idx] = refactorAttr
	}
	return attrList
}

// 是否是复合属性
func attrTypeIsCombine(attrType string) bool {
	if attrType == "struct" || attrType == "structs" {
		return true
	}
	return false
}
