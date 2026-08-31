package report_center

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"go.easyops.local/agollo"
	"io"
	"io/ioutil"
	"net/http"
	"sync"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	logctx "go.easyops.local/slog/context"
)

type compressFunc func(data interface{}) (string, error)

func NewService(reportCenter config.ReportCenter, httpClient httpClient, compressFunc compressFunc, confClient agollo.Client) Service {
	return &serviceImp{
		reportCenter: reportCenter,
		newRequest:   http.NewRequest,
		httpClient:   httpClient,
		ioReadFunc:   ioutil.ReadAll,
		compressFunc: compressFunc,
		tokenManage: &tokenManage{
			mu:          &sync.Mutex{},
			tokenCache:  map[string]*TokenInfo{},
			nowTimeFunc: timeutil.NowTime,
		},
		confClient: confClient,
	}
}

type httpClient interface {
	Do(req *http.Request) (*http.Response, error)
}

type Service interface {
	GetToken(ctx context.Context, tokenRequest TokenRequest, globalConf *fintech_data.ReportGlobalConfig) (*TokenInfo, error)
	ReportData(ctx context.Context, request ReportRequest, globalConf *fintech_data.ReportGlobalConfig) (*ReportResponse, error)
	Audit(ctx context.Context, request AuditRequest, globalConf *fintech_data.ReportGlobalConfig) (*AuditResponse, error)
	CheckReportResult(ctx context.Context, request CheckRequest, globalConf *fintech_data.ReportGlobalConfig) (*CheckResponse, error)
	SelectBranchId(ctx context.Context, request BranchIdRequest, globalConf *fintech_data.ReportGlobalConfig) (*BranchIdResponse, error)
}

func (i *TokenInfo) isValid(nowTs int64) bool {
	// 提前10s
	if nowTs-10 < i.ExpiresTs {
		return true
	}
	return false
}

func getTokenKey(tokenRequest TokenRequest) string {
	return fmt.Sprintf("%s:%s", tokenRequest.ClientId, tokenRequest.ClientSecret)
}

type tokenManage struct {
	mu          *sync.Mutex
	tokenCache  map[string]*TokenInfo
	nowTimeFunc timeutil.NowTimeFunc
}

func (tm *tokenManage) getToken(key string, tokenCreator func() (*TokenInfo, error)) (*TokenInfo, error) {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	token, exist := tm.tokenCache[key]
	nt := tm.nowTimeFunc().Unix()
	if exist && token.isValid(nt) {
		return token, nil
	}
	newToken, err := tokenCreator()
	if err != nil {
		return nil, err
	}
	newToken.ExpiresTs = tm.nowTimeFunc().Unix() + int64(newToken.ExpiresIn)
	tm.tokenCache[key] = newToken
	return newToken, nil
}

type serviceImp struct {
	reportCenter config.ReportCenter
	newRequest   func(method, url string, body io.Reader) (*http.Request, error) // http.NewRequest
	httpClient   httpClient
	ioReadFunc   func(r io.Reader) ([]byte, error)
	compressFunc func(data interface{}) (string, error)
	tokenManage  *tokenManage
	confClient   agollo.Client
}

func (i *serviceImp) getReqUrl(uri string, globalConf *fintech_data.ReportGlobalConfig) string {
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

func (i *serviceImp) GetToken(ctx context.Context, tokenRequest TokenRequest, globalConf *fintech_data.ReportGlobalConfig) (*TokenInfo, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := i.confClient.GetString("token_uri", "webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token")
	if tokenRequest.GrantType == "" {
		tokenRequest.GrantType = "client_credentials"
	}
	req, err := i.newRequest(http.MethodPost, i.getReqUrl(uri, globalConf), nil)
	if err != nil {
		logger.Errorf("client %s get token info new request fail, error: %s", tokenRequest.ClientId, err.Error())
		return nil, err
	}

	// append query
	q := req.URL.Query()
	q.Add("client_id", tokenRequest.ClientId)
	q.Add("client_secret", tokenRequest.ClientSecret)
	q.Add("grant_type", tokenRequest.GrantType)
	req.URL.RawQuery = q.Encode()

	req = req.WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	resp, err := i.httpClient.Do(req)
	if err != nil {
		logger.Errorf("client %s get token info request fail, error: %s", tokenRequest.ClientId, err.Error())
		return nil, err
	}
	tokenInfo := &TokenInfo{}
	err = i.parseResponse(resp, tokenInfo)
	if err != nil {
		return nil, err
	}
	if tokenInfo.AccessToken == "" {
		logger.Errorf("client %s get token empty", tokenRequest.ClientId)
		return nil, fmt.Errorf("token is empty")
	}
	logger.Infof("client %s get token info success", tokenRequest.ClientId)
	return tokenInfo, nil
}

func (i *serviceImp) parseResponse(resp *http.Response, data interface{}) error {
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

func (i *serviceImp) getTokenByCache(ctx context.Context, tokenRequest TokenRequest, globalConf *fintech_data.ReportGlobalConfig) (*TokenInfo, error) {
	tokenKey := getTokenKey(tokenRequest)
	tokenCreator := func() (*TokenInfo, error) {
		return i.GetToken(ctx, tokenRequest, globalConf)
	}
	return i.tokenManage.getToken(tokenKey, tokenCreator)
}

func (i *serviceImp) ReportData(ctx context.Context, request ReportRequest, globalConf *fintech_data.ReportGlobalConfig) (*ReportResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := i.confClient.GetString("report_data_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/reportData")
	compressStr, err := i.compressFunc(request.Data)
	if err != nil {
		logger.Errorf("gzip compress data fail, error: %s", err.Error())
		return nil, err
	}
	type reqData struct {
		BranchId            string `json:"branchId"`
		FacilityOwnerAgency string `json:"facilityOwnerAgency"`
		Data                string `json:"data"`
	}
	if globalConf.FacilityOwnerAgency == "" {
		request.FacilityOwnerAgency = i.confClient.GetString("report_center.facilityOwnerAgency", "", agollo.WithNamespace("application"))
	} else {
		request.FacilityOwnerAgency = globalConf.FacilityOwnerAgency
	}
	data := reqData{
		BranchId:            request.BranchId,
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

// Audit 审核接口
func (s *serviceImp) Audit(ctx context.Context, request AuditRequest, globalConf *fintech_data.ReportGlobalConfig) (*AuditResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := s.confClient.GetString("request_check_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/requestCheck")
	compressBranchIdList, err := s.compressFunc(request.BranchIdList)
	if err != nil {
		logger.Errorf("gzip compress branchIdList fail, error: %s", err.Error())
		return nil, err
	}
	type reqData struct {
		FacilityOwnerAgency string `json:"facilityOwnerAgency"`
		BranchNumber        int    `json:"branchNumber"`
		BranchIdList        string `json:"branchIdList"`
	}
	if globalConf.FacilityOwnerAgency == "" {
		request.FacilityOwnerAgency = s.confClient.GetString("report_center.facilityOwnerAgency", "", agollo.WithNamespace("application"))
	} else {
		request.FacilityOwnerAgency = globalConf.FacilityOwnerAgency
	}
	data := reqData{
		FacilityOwnerAgency: request.FacilityOwnerAgency,
		BranchNumber:        request.BranchNumber,
		BranchIdList:        compressBranchIdList,
	}
	resp, err := s.doRequest(ctx, uri, data, globalConf)
	if err != nil {
		logger.Errorf("audit data request fail, error: %s", err.Error())
		return nil, err
	}
	auditResp := &AuditResponse{}
	err = s.parseResponse(resp, auditResp)
	if err != nil {
		logger.Errorf("audit data parse result fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("audit data success, groupId %s", auditResp.GroupId)
	return auditResp, nil
}

func (i *serviceImp) doRequest(ctx context.Context, uri string, request interface{}, globalConf *fintech_data.ReportGlobalConfig) (*http.Response, error) {
	logger := logctx.MustGetLogger(ctx)
	tokenRequest := TokenRequest{ClientId: globalConf.ClientId, ClientSecret: globalConf.ClientSecret}
	tokenInfo, err := i.getTokenByCache(ctx, tokenRequest, globalConf)
	if err != nil {
		logger.Errorf("get token by cache fail, id: %s error: %s", tokenRequest.ClientId, err.Error())
		return nil, err
	}
	dataBytes, _ := json.Marshal(request)
	req, err := i.newRequest(http.MethodPost, i.getReqUrl(uri, globalConf), bytes.NewReader(dataBytes))
	if err != nil {
		logger.Errorf("new request fail, error: %s", err.Error())
		return nil, err
	}
	req = req.WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Access-Token", tokenInfo.AccessToken)
	req.Header.Set("Charset", "UTF-8")
	return i.httpClient.Do(req)
}

func (i *serviceImp) CheckReportResult(ctx context.Context, request CheckRequest, globalConf *fintech_data.ReportGlobalConfig) (*CheckResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	uri := i.confClient.GetString("report_result_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData")
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

func (i *serviceImp) SelectBranchId(ctx context.Context, request BranchIdRequest, globalConf *fintech_data.ReportGlobalConfig) (*BranchIdResponse, error) {
	return nil, nil
}
