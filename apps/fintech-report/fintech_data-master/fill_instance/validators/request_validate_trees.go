package validators

import (
	"bytes"
	"encoding/json"

	"go.easyops.local/giraffe/pkg/validators"
)

var _ = bytes.Split
var _ = json.Unmarshal

var EmptyTree validators.ValidateTree

const InstanceCallbackValidateTreeStr = `{"roots":[{"field":"data","field_type":"","children":[{"field":"ext_info","field_type":"","children":[{"field":"instance_id","field_type":"string","children":null,"validate_method":{"pattern":"^[0-9a-z]{13}$"},"required":false},{"field":"object_id","field_type":"string","children":null,"validate_method":{"pattern":"^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$"},"required":false}],"validate_method":null,"required":false}],"validate_method":null,"required":false}]}`

var InstanceCallbackValidateTree *validators.ValidateTree

func init() {
	var err error
	_ = err

	InstanceCallbackValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(InstanceCallbackValidateTreeStr), InstanceCallbackValidateTree)
	panicIfErr(err)

}

func panicIfErr(err error) {
	if err != nil {
		panic(err)
	}
}
