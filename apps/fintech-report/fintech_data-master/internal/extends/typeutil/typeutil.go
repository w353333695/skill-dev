package typeutil

import (
	"encoding/json"

	pb "github.com/gogo/protobuf/proto"
	"github.com/gogo/protobuf/types"

	"go.easyops.local/kit/gogoprotobuf/jsonpb"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func PbMessageToStruct(data pb.Message) *types.Struct {
	m := jsonpb.Marshaler{}
	jsonStr, err := m.MarshalToString(data)
	if err != nil {
		return nil
	}
	result := make(map[string]interface{})
	_ = json.Unmarshal([]byte(jsonStr), &result)
	return protostruct.ToStruct(result)
}

func StructToPbMessage(data *types.Struct, pbData pb.Message) error {
	dataMap := protostruct.DecodeToMap(data)
	dataBytes, _ := json.Marshal(dataMap)
	um := jsonpb.Unmarshaler{}
	err := um.UnmarshalFromString(string(dataBytes), pbData)
	if err != nil {
		return err
	}
	return nil
}

func PbValueToString(val *types.Value) string {
	if val == nil {
		return "null"
	}
	if x, ok := val.GetKind().(*types.Value_StringValue); ok {
		return x.StringValue
	}
	mar := jsonpb.Marshaler{}
	str, _ := mar.MarshalToString(val)
	return str
}

func IsNullValue(value *types.Value) bool {
	if value == nil {
		return true
	}
	if _, ok := value.GetKind().(*types.Value_NullValue); ok {
		return true
	}
	return false
}
