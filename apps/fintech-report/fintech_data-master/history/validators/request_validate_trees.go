package validators

import (
	"bytes"
	"encoding/json"
	"go.easyops.local/giraffe/pkg/validators"
)

var _ = bytes.Split
var _ = json.Unmarshal

var EmptyTree validators.ValidateTree

const ExportReportInstanceValidateTreeStr = `{"roots":null}`

var ExportReportInstanceValidateTree *validators.ValidateTree

const ExportReportTaskValidateTreeStr = `{"roots":null}`

var ExportReportTaskValidateTree *validators.ValidateTree

const GetReportInstanceTotalValidateTreeStr = `{"roots":null}`

var GetReportInstanceTotalValidateTree *validators.ValidateTree

const GetReportTaskValidateTreeStr = `{"roots":[{"field":"taskId","field_type":"string","children":null,"validate_method":null,"required":true}]}`

var GetReportTaskValidateTree *validators.ValidateTree

const HandleReportInstanceValidateTreeStr = `{"roots":[{"field":"dataId","field_type":"string[]","children":null,"validate_method":null,"required":true}]}`

var HandleReportInstanceValidateTree *validators.ValidateTree

const LastReportTaskValidateTreeStr = `{"roots":[{"field":"objectId","field_type":"string","children":null,"validate_method":{"pattern":"^[a-zA-Z_][0-9a-zA-Z_]{0,46}(@[A-Z]{1,16})?$"},"required":false}]}`

var LastReportTaskValidateTree *validators.ValidateTree

const SearchReportBranchValidateTreeStr = `{"roots":[{"field":"st","field_type":"int","children":null,"validate_method":null,"required":true},{"field":"page","field_type":"int","children":null,"validate_method":{"gte":1},"required":false},{"field":"page_size","field_type":"int","children":null,"validate_method":{"gte":1},"required":false},{"field":"taskId","field_type":"string","children":null,"validate_method":null,"required":true}]}`

var SearchReportBranchValidateTree *validators.ValidateTree

const SearchReportInstanceValidateTreeStr = `{"roots":[{"field":"st","field_type":"int","children":null,"validate_method":null,"required":true},{"field":"page","field_type":"int","children":null,"validate_method":{"gte":1},"required":false},{"field":"page_size","field_type":"int","children":null,"validate_method":{"gte":1},"required":false}]}`

var SearchReportInstanceValidateTree *validators.ValidateTree

const SearchReportTaskValidateTreeStr = `{"roots":[{"field":"page","field_type":"int","children":null,"validate_method":{"gte":1},"required":false},{"field":"page_size","field_type":"int","children":null,"validate_method":{"gte":1},"required":false}]}`

var SearchReportTaskValidateTree *validators.ValidateTree

func init() {
	var err error
	_ = err

	ExportReportInstanceValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ExportReportInstanceValidateTreeStr), ExportReportInstanceValidateTree)
	panicIfErr(err)

	ExportReportTaskValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ExportReportTaskValidateTreeStr), ExportReportTaskValidateTree)
	panicIfErr(err)

	GetReportInstanceTotalValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(GetReportInstanceTotalValidateTreeStr), GetReportInstanceTotalValidateTree)
	panicIfErr(err)

	GetReportTaskValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(GetReportTaskValidateTreeStr), GetReportTaskValidateTree)
	panicIfErr(err)

	HandleReportInstanceValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(HandleReportInstanceValidateTreeStr), HandleReportInstanceValidateTree)
	panicIfErr(err)

	LastReportTaskValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(LastReportTaskValidateTreeStr), LastReportTaskValidateTree)
	panicIfErr(err)

	SearchReportBranchValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(SearchReportBranchValidateTreeStr), SearchReportBranchValidateTree)
	panicIfErr(err)

	SearchReportInstanceValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(SearchReportInstanceValidateTreeStr), SearchReportInstanceValidateTree)
	panicIfErr(err)

	SearchReportTaskValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(SearchReportTaskValidateTreeStr), SearchReportTaskValidateTree)
	panicIfErr(err)

}

func panicIfErr(err error) {
	if err != nil {
		panic(err)
	}
}
