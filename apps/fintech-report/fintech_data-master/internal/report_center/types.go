package report_center

type TokenRequest struct {
	ClientId     string `json:"client_id"`
	ClientSecret string `json:"client_secret"`
	GrantType    string `json:"grant_type"`
}

type TokenInfo struct {
	AccessToken string `json:"access_token"`
	ExpiresIn   int    `json:"expires_in"`
	ExpiresTs   int64
}

type ReportRequest struct {
	DataTotal           int          `json:"-"`
	InnerBranchId       string       `json:"-"`
	BranchId            string       `json:"branchId"`
	FacilityOwnerAgency string       `json:"facilityOwnerAgency"`
	Data                []ReportData `json:"data"`
}

// AuditRequest 审核请求
type AuditRequest struct {
	// 金融编号
	FacilityOwnerAgency string `json:"facilityOwnerAgency"`
	// 批次数量
	BranchNumber int `json:"branchNumber"`
	// 批次ID数组
	BranchIdList []string `json:"branchIdList"`
}

type ReportData struct {
	DataType string        `json:"dataType"`
	DataList []interface{} `json:"dataList"`
}

type ReportResponse struct {
	BranchId string      `json:"branchId"`
	Code     string      `json:"code"`
	Msg      string      `json:"msg"`
	Data     interface{} `json:"data"`
}

type ReportResponseInstance struct {
	Msg                string `json:"msg"`
	FacilityCategory   string `json:"facilityCategory"`
	FacilityDescriptor string `json:"facilityDescriptor"`
}

// AuditResponse 审核响应
type AuditResponse struct {
	GroupId string `json:"groupId"`
	Code    string `json:"code"`
	Msg     string `json:"msg"`
}

type CheckRequest struct {
	BranchId            string `json:"branchId"`
	FacilityOwnerAgency string `json:"facilityOwnerAgency"`
}

type CheckResponse struct {
	BranchId string      `json:"branchId"`
	Code     string      `json:"code"`
	Msg      string      `json:"msg"`
	Data     []CheckData `json:"data"`
}

type BranchIdRequest struct {
	FacilityOwnerAgency string   `json:"facilityOwnerAgency"`
	DataType            string   `json:"dataType"`
	DataList            []string `json:"dataList"`
}

type BranchIdResponse struct {
	Code string      `json:"code"`
	Msg  string      `json:"msg"`
	Data interface{} `json:"data"`
}

type BranchIdData struct {
	BranchId           string `json:"branchId"`
	GroupId            string `json:"groupId"`
	FacilityDescriptor string `json:"facilityDescriptor"`
}

func (c *CheckResponse) IsEffected() bool {
	if c.BranchId == "" || c.Code == "" {
		return false
	}
	return true
}

type CheckData struct {
	Code               string `json:"code"`
	Msg                string `json:"msg"`
	FacilityCategory   string `json:"facilityCategory"`
	FacilityDescriptor string `json:"facilityDescriptor"`
}

const (
	ReportTypeNew    = "new"
	ReportTypeUpdate = "update"
	ReportTypeDelete = "delete"

	KeyReportDataType     = "reportDataType"
	KeyFacilityCategory   = "facilityCategory"
	KeyFacilityDescriptor = "facilityDescriptor"
)

// 上报状态码
const (
	// 数据采集状态
	CodeReportSuccess   = "WL-10000" // 采集成功
	CodeAgencyIsEmpty   = "WL-10001" // 金融机构编号不能为空
	CodeDataIsEmpty     = "WL-10002" // 上报数据不能为空
	CodeBranchIdIsEmpty = "WL-10003" // 批次编号不能为空
	CodeBranchIdNoExist = "WL-10004" // 批次编号不存在
	CodeCompressFail    = "WL-10010" // 数据格式错误（解压数据异常）
	CodeAgencyIsDiff    = "WL-10020" // 报送机构号与报文中机构号不匹配

	// 本批次数据处理状态
	CodeSaveSuccess    = "WL-10005" // 已保存
	CodeHandling       = "WL-10006" // 处理中
	CodeHandleFail     = "WL-10007" // 处理失败
	CodeDataHasFail    = "WL-10008" // 部分数据异常
	CodeHandleSuccess  = "WL-10009" // 处理成功
	CodeHandleWithWarn = "WL-10013" // 处理成功

	// 单条数据数据处理状态
	CodeDataValid            = "WL-20000" // 数据检核通过
	CodeDataInValid          = "WL-20001" // 数据检核未通过
	CodeDataHandleFail       = "WL-20002" // 数据处理失败
	CodeDataValidWithWarning = "WL-20003" // 数据检核通过但存在警告

	//数据请求审核状态
	CodeRequestCheckSuccess          = "WL-30000" //审核请求接收成功
	CodeRequestCheckFailed           = "WL-30001" //检核请求校验失败，请检查批次数量和批次列表是否正确
	CodeRequestCheckBranchIdNotExist = "WL-30002" // 检核请求中的批次ID不存在或检核请求已完成

	ZhongXinCodeReportSuccess = "1"
	ZhongXinCodeReportFail    = "0"
)

// 异常实例处理状态
const (
	HandleStatusPending   = "pending"
	HandleStatusProcessed = "processed"
)

func ConvertReportType(reportType string) string {
	switch reportType {
	case ReportTypeNew:
		return "新建"
	case ReportTypeDelete:
		return "删除"
	case ReportTypeUpdate:
		return "更新"
	default:
		return ""
	}
}
