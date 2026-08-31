package validators

import (
	"bytes"
	"encoding/json"

	"go.easyops.local/giraffe/pkg/validators"
)

var _ = bytes.Split
var _ = json.Unmarshal

var EmptyTree validators.ValidateTree

const DebugTokenValidateTreeStr = `{"roots":[{"field":"grantType","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"clientId","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"clientSecret","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"ip","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"port","field_type":"int","children":null,"validate_method":null,"required":true},{"field":"facilityOwnerAgency","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"memo","field_type":"string","children":null,"validate_method":null,"required":true}]}`

var DebugTokenValidateTree *validators.ValidateTree

const GetGlobalConfigValidateTreeStr = `{"roots":null}`

var GetGlobalConfigValidateTree *validators.ValidateTree

const ReportDataValidateTreeStr = `{"roots":[{"field":"objectId","field_type":"string","children":null,"validate_method":{"pattern":"^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$"},"required":true}]}`

var ReportDataValidateTree *validators.ValidateTree

const RequestAuditValidateTreeStr = `{"roots":[{"field":"branchList","field_type":"ReportBranch[]","children":[{"field":"objectId","field_type":"string","children":null,"validate_method":{"pattern":"^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$"},"required":false}],"validate_method":null,"required":true},{"field":"st","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"taskId","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"objectId","field_type":"string","children":null,"validate_method":null,"required":true}]}`

var RequestAuditValidateTree *validators.ValidateTree

const UpdateGlobalConfigValidateTreeStr = `{"roots":[{"field":"clientId","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"clientSecret","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"ip","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"port","field_type":"int","children":null,"validate_method":null,"required":true},{"field":"facilityOwnerAgency","field_type":"string","children":null,"validate_method":null,"required":true},{"field":"memo","field_type":"string","children":null,"validate_method":null,"required":true}]}`

var UpdateGlobalConfigValidateTree *validators.ValidateTree

func init() {
	var err error
	_ = err

	DebugTokenValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(DebugTokenValidateTreeStr), DebugTokenValidateTree)
	panicIfErr(err)

	GetGlobalConfigValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(GetGlobalConfigValidateTreeStr), GetGlobalConfigValidateTree)
	panicIfErr(err)

	ReportDataValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ReportDataValidateTreeStr), ReportDataValidateTree)
	panicIfErr(err)

	RequestAuditValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(RequestAuditValidateTreeStr), RequestAuditValidateTree)
	panicIfErr(err)

	UpdateGlobalConfigValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(UpdateGlobalConfigValidateTreeStr), UpdateGlobalConfigValidateTree)
	panicIfErr(err)

}

func panicIfErr(err error) {
	if err != nil {
		panic(err)
	}
}
