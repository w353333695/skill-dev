package report_center

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"go.easyops.local/agollo"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	logctx "go.easyops.local/slog/context"
	"io"
	"io/ioutil"
	"net/http"
)

func NewZhongXinService(reportCenter config.ReportCenter, httpClient httpClient, compressFunc compressFunc, confClient agollo.Client) Service {
	return &zhongXinServiceImp{
		reportCenter: reportCenter,
		newRequest:   http.NewRequest,
		httpClient:   httpClient,
		ioReadFunc:   ioutil.ReadAll,
		compressFunc: compressFunc,
		confClient:   confClient,
	}
}

type zhongXinServiceImp struct {
	reportCenter config.ReportCenter
	newRequest   func(method, url string, body io.Reader) (*http.Request, error) // http.NewRequest
	httpClient   httpClient
	ioReadFunc   func(r io.Reader) ([]byte, error)
	compressFunc func(data interface{}) (string, error)
	tokenManage  *tokenManage
	confClient   agollo.Client
}

func (i *zhongXinServiceImp) GetToken(ctx context.Context, tokenRequest TokenRequest, globalConf *fintech_data.ReportGlobalConfig) (*TokenInfo, error) {
	return nil, nil
}

func (i *zhongXinServiceImp) ReportData(ctx context.Context, request ReportRequest, globalConf *fintech_data.ReportGlobalConfig) (*ReportResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := "itsm/httpclient/reportData.action"
	compressStr, err := i.compressFunc(request.Data)
	if err != nil {
		logger.Errorf("gzip compress data fail, error: %s", err.Error())
		return nil, err
	}
	type reqData struct {
		FacilityOwnerAgency string `json:"facilityOwnerAgency"`
		Data                string `json:"data"`
	}
	if globalConf.FacilityOwnerAgency == "" {
		request.FacilityOwnerAgency = i.confClient.GetString("report_center.facilityOwnerAgency", "", agollo.WithNamespace("application"))
	} else {
		request.FacilityOwnerAgency = globalConf.FacilityOwnerAgency
	}
	data := reqData{
		FacilityOwnerAgency: request.FacilityOwnerAgency,
		Data:                compressStr,
	}
	resp, err := i.doRequest(ctx, uri, data, globalConf)
	if err != nil {
		logger.Errorf("report data request fail, error: %s", err.Error())
		return nil, err
	}
	reportResp := &ReportResponse{}
	err = i.parseResponse(resp, reportResp)
	if err != nil {
		logger.Errorf("report data parse result fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("report data success, branchId %s", reportResp.BranchId)
	return reportResp, nil
}

func (s *zhongXinServiceImp) Audit(ctx context.Context, request AuditRequest, globalConf *fintech_data.ReportGlobalConfig) (*AuditResponse, error) {
	return nil, nil
}

func (i *zhongXinServiceImp) CheckReportResult(ctx context.Context, request CheckRequest, globalConf *fintech_data.ReportGlobalConfig) (*CheckResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := "itsm/cmdbhttp/queryUploadData.action"
	if globalConf.FacilityOwnerAgency == "" {
		request.FacilityOwnerAgency = i.confClient.GetString("report_center.facilityOwnerAgency", "", agollo.WithNamespace("application"))
	} else {
		request.FacilityOwnerAgency = globalConf.FacilityOwnerAgency
	}
	resp, err := i.doRequest(ctx, uri, request, globalConf)
	if err != nil {
		logger.Errorf("check report result request fail, error: %s", err.Error())
		return nil, err
	}
	reportResp := &CheckResponse{}
	err = i.parseResponse(resp, reportResp)
	if err != nil {
		logger.Errorf("check report result parse return fail, error: %s", err.Error())
		return nil, err
	}
	if !reportResp.IsEffected() {
		logger.Errorf("check response not effected, branchId %s", request.BranchId)
		return nil, fmt.Errorf("invalid check response")
	}
	logger.Infof("check report result success, branchId %s, code %s, dataLen: %d", reportResp.BranchId, reportResp.Code, len(reportResp.Data))
	return reportResp, nil
}

func (i *zhongXinServiceImp) SelectBranchId(ctx context.Context, request BranchIdRequest, globalConf *fintech_data.ReportGlobalConfig) (*BranchIdResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := "itsm/cmdbhttp/queryDataBranchId.action"
	if globalConf.FacilityOwnerAgency == "" {
		request.FacilityOwnerAgency = i.confClient.GetString("report_center.facilityOwnerAgency", "", agollo.WithNamespace("application"))
	} else {
		request.FacilityOwnerAgency = globalConf.FacilityOwnerAgency
	}
	resp, err := i.doRequest(ctx, uri, request, globalConf)
	if err != nil {
		logger.Errorf("select branch id request fail, error: %s", err.Error())
		return nil, err
	}
	branchIdResp := &BranchIdResponse{}
	err = i.parseResponse(resp, branchIdResp)
	if err != nil {
		logger.Errorf("select branch id parse return fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("select branch id success, code %s, msg %s", branchIdResp.Code, branchIdResp.Msg)
	return branchIdResp, nil
}

func (i *zhongXinServiceImp) doRequest(ctx context.Context, uri string, request interface{}, globalConf *fintech_data.ReportGlobalConfig) (*http.Response, error) {
	logger := logctx.MustGetLogger(ctx)
	dataBytes, _ := json.Marshal(request)
	req, err := i.newRequest(http.MethodPost, i.getReqUrl(uri, globalConf), bytes.NewReader(dataBytes))
	if err != nil {
		logger.Errorf("new request fail, error: %s", err.Error())
		return nil, err
	}
	req = req.WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Charset", "UTF-8")
	return i.httpClient.Do(req)
}

func (i *zhongXinServiceImp) getReqUrl(uri string, globalConf *fintech_data.ReportGlobalConfig) string {
	var ip string
	var port int
	if globalConf.GetIp() != "" && globalConf.GetPort() != 0 {
		ip = globalConf.GetIp()
		port = int(globalConf.GetPort())
	} else {
		ip = i.confClient.GetString("report_center.host", "127.0.0.1", agollo.WithNamespace("application"))
		port = i.confClient.GetInt("report_center.port", 18002, agollo.WithNamespace("application"))
	}
	schema := "http"
	if i.confClient.GetBool("report_center.with_ssl", true, agollo.WithNamespace("application")) {
		schema = "https"
	}
	return fmt.Sprintf("%s://%s:%d/%s", schema, ip, port, uri)
}

func (i *zhongXinServiceImp) parseResponse(resp *http.Response, data interface{}) error {
	defer resp.Body.Close()
	ret, err := i.ioReadFunc(resp.Body)
	if err != nil {
		return err
	}
	err = json.Unmarshal(ret, data)
	if err != nil {
		return fmt.Errorf("unmarshal response:\n%s \nunmarshal error: %s", string(ret), err.Error())
	}
	return nil
}
