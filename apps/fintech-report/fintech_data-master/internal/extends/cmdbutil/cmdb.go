package cmdbutil

import (
	"fmt"
	pbtypes "github.com/gogo/protobuf/types"
	"github.com/spf13/cast"

	"go.easyops.local/fintech_data/internal/extends/typeutil"
)

const (
	ShowKeyLabel    = "#showKey"
	InstanceIdLabel = "instanceId"
)

func GetInstanceIdByMap(instanceData map[string]interface{}) string {
	return cast.ToString(instanceData[InstanceIdLabel])
}

func GetInstanceId(instanceData *pbtypes.Struct) string {
	return instanceData.Fields[InstanceIdLabel].GetStringValue()
}

func GetShowName(instanceData *pbtypes.Struct) string {
	showKeyValue, ok := instanceData.Fields[ShowKeyLabel]
	var showKey string
	if !ok {
		showKey = GetInstanceId(instanceData)
	} else {
		var valueList []string
		for _, val := range showKeyValue.GetListValue().GetValues() {
			valueList = append(valueList, typeutil.PbValueToString(val))
		}
		showKey = formatShowKey(valueList)
	}
	return showKey
}

func formatShowKey(vals []string) string {
	if len(vals) == 1 {
		return vals[0]
	}
	if len(vals) != 0 {
		return fmt.Sprintf("%s(%s)", vals[0], vals[1])
	}
	return ""
}

func GetCreator(instanceData *pbtypes.Struct) string {
	if creatorValue, ok := instanceData.Fields["creator"]; ok && creatorValue != nil {
		return typeutil.PbValueToString(creatorValue)
	}
	return ""
}
