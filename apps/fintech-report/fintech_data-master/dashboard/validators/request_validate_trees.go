package validators

import (
	"bytes"
	"encoding/json"

	"go.easyops.local/giraffe/pkg/validators"
)

var _ = bytes.Split
var _ = json.Unmarshal

var EmptyTree validators.ValidateTree

const ExportReportObjectStatValidateTreeStr = `{"roots":null}`

var ExportReportObjectStatValidateTree *validators.ValidateTree

const ReportInstanceCountValidateTreeStr = `{"roots":null}`

var ReportInstanceCountValidateTree *validators.ValidateTree

const ReportObjectCountValidateTreeStr = `{"roots":null}`

var ReportObjectCountValidateTree *validators.ValidateTree

const ReportObjectStatValidateTreeStr = `{"roots":null}`

var ReportObjectStatValidateTree *validators.ValidateTree

func init() {
	var err error
	_ = err

	ExportReportObjectStatValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ExportReportObjectStatValidateTreeStr), ExportReportObjectStatValidateTree)
	panicIfErr(err)

	ReportInstanceCountValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ReportInstanceCountValidateTreeStr), ReportInstanceCountValidateTree)
	panicIfErr(err)

	ReportObjectCountValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ReportObjectCountValidateTreeStr), ReportObjectCountValidateTree)
	panicIfErr(err)

	ReportObjectStatValidateTree = &validators.ValidateTree{}
	err = json.Unmarshal([]byte(ReportObjectStatValidateTreeStr), ReportObjectStatValidateTree)
	panicIfErr(err)

}

func panicIfErr(err error) {
	if err != nil {
		panic(err)
	}
}
