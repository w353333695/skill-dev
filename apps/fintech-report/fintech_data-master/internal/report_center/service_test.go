package report_center

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/golang/mock/gomock"
	"go.easyops.local/fintech_data/mock/agollo_client"
	"io"
	"io/ioutil"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

type fakeClient struct {
}

func (c *fakeClient) Do(req *http.Request) (*http.Response, error) {
	return nil, fmt.Errorf("mock fail")
}

func Test_serviceImp_GetToken(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		var buf []byte
		clientId := q.Get("client_id")
		if clientId == "invalid_id" {
			buf, _ = json.Marshal(map[string]interface{}{
				"access_token": []string{"error"},
			})
		} else if clientId == "empty_token" {
			resp := TokenInfo{AccessToken: "", ExpiresIn: 3000}
			buf, _ = json.Marshal(resp)
		} else {
			resp := TokenInfo{AccessToken: "fake_token", ExpiresIn: 3600}
			buf, _ = json.Marshal(resp)
		}
		w.Write(buf)
	}))
	defer ts.Close()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	host := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[0]
	port := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[1]
	p, _ := strconv.ParseInt(port, 10, 64)

	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error) // http.NewRequest
		httpClient   httpClient
	}
	type args struct {
		ctx          context.Context
		tokenRequest TokenRequest
		globalConf   *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *TokenInfo
		wantErr bool
	}{
		{
			name: "normal",
			fields: fields{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
			},
			args: args{
				ctx: ctx,
				tokenRequest: TokenRequest{
					ClientId:     "fakeId",
					ClientSecret: "fakeSecret",
					GrantType:    "client_credentials",
				},
			},
			want: &TokenInfo{
				AccessToken: "fake_token",
				ExpiresIn:   3600,
			},
			wantErr: false,
		},
		{
			name: "token empty",
			fields: fields{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
			},
			args: args{
				ctx: ctx,
				tokenRequest: TokenRequest{
					ClientId:     "empty_token",
					ClientSecret: "fakeSecret",
					GrantType:    "client_credentials",
				},
			},
			wantErr: true,
		},
		{
			name: "invalid client id",
			fields: fields{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
			},
			args: args{
				ctx: ctx,
				tokenRequest: TokenRequest{
					ClientId:     "invalid_id",
					ClientSecret: "fakeSecret",
					GrantType:    "client_credentials",
				},
			},
			wantErr: true,
		},
		{
			name: "new request fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest: func(method, url string, body io.Reader) (*http.Request, error) {
					return nil, fmt.Errorf("mock fail")
				},
				httpClient: ts.Client(),
			},
			args: args{
				ctx: ctx,
				tokenRequest: TokenRequest{
					ClientId:     "invalid_id",
					ClientSecret: "fakeSecret",
					GrantType:    "client_credentials",
				},
			},
			wantErr: true,
		},
		{
			name: "request fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: &fakeClient{},
			},
			args: args{
				ctx: ctx,
				tokenRequest: TokenRequest{
					ClientId:     "invalid_id",
					ClientSecret: "fakeSecret",
					GrantType:    "client_credentials",
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			mockAgolloClient.EXPECT().GetString("report_center.host", "127.0.0.1", gomock.Any()).Return(host).AnyTimes()
			mockAgolloClient.EXPECT().GetInt("report_center.port", 18002, gomock.Any()).Return(int(p)).AnyTimes()
			mockAgolloClient.EXPECT().GetBool("report_center.with_ssl", true, gomock.Any()).Return(true).AnyTimes()
			mockAgolloClient.EXPECT().GetString("token_uri", "webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token", gomock.Any()).Return("webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token").AnyTimes()
			i := &serviceImp{
				reportCenter: tt.fields.reportCenter,
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   ioutil.ReadAll,
			}
			i.confClient = mockAgolloClient
			got, err := i.GetToken(tt.args.ctx, tt.args.tokenRequest, tt.args.globalConf)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetToken() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetToken() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_parseResponse(t *testing.T) {
	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error)
		httpClient   httpClient
		ioReadFunc   func(r io.Reader) ([]byte, error)
	}
	type args struct {
		resp *http.Response
		data interface{}
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				ioReadFunc: func(r io.Reader) ([]byte, error) {
					return nil, fmt.Errorf("mock fail")
				},
			},
			args: args{
				resp: &http.Response{
					Body: ioutil.NopCloser(strings.NewReader("abcdef")),
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &serviceImp{
				reportCenter: tt.fields.reportCenter,
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
			}
			if err := i.parseResponse(tt.args.resp, tt.args.data); (err != nil) != tt.wantErr {
				t.Errorf("parseResponse() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestNewService(t *testing.T) {
	type args struct {
		reportCenter config.ReportCenter
		httpClient   httpClient
	}
	tests := []struct {
		name string
		args args
		want Service
	}{
		{
			name: "",
			args: args{},
			want: &serviceImp{
				newRequest: http.NewRequest,
				ioReadFunc: ioutil.ReadAll,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			NewService(tt.args.reportCenter, tt.args.httpClient, nil, mockAgolloClient)
		})
	}
}

func Test_serviceImp_ReportData(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := r.Header.Get("X-Access-Token")
		var buf []byte
		if token == "" {
			panic("invalid token")
		} else if token == "error_id" {
			buf, _ = json.Marshal(map[string]interface{}{
				"branchId": []string{"error"},
			})
		} else {
			resp := ReportResponse{
				BranchId: "branchId",
				Code:     "WL-10000",
				Msg:      "采集成功",
			}
			buf, _ = json.Marshal(resp)
		}
		w.Write(buf)
	}))
	defer ts.Close()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	host := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[0]
	port := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[1]
	p, _ := strconv.ParseInt(port, 10, 64)

	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error)
		httpClient   httpClient
		ioReadFunc   func(r io.Reader) ([]byte, error)
		compressFunc func(data interface{}) (string, error)
	}
	type args struct {
		ctx        context.Context
		request    ReportRequest
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *ReportResponse
		wantErr bool
	}{
		{
			name: "normal",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "center",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "secret",
					Ip:           host,
					Port:         int32(p),
				},
			},
			want: &ReportResponse{
				BranchId: "branchId",
				Code:     "WL-10000",
				Msg:      "采集成功",
			},
			wantErr: false,
		},
		{
			name: "get token fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "--",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "compress fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "", fmt.Errorf("mock fail")
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "invalid token",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "new request fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: func(method, url string, body io.Reader) (*http.Request, error) {
					return nil, fmt.Errorf("mock fail")
				},
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "do http client fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: &fakeClient{},
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: ReportRequest{
					BranchId:            "",
					FacilityOwnerAgency: "center",
					Data: []ReportData{
						{
							DataType: "server",
							DataList: []interface{}{
								map[string]interface{}{
									"name": "host",
								},
							},
						},
					},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:            "error",
					ClientSecret:        "secret",
					Ip:                  "127.0.0.1",
					Port:                int32(p),
					FacilityOwnerAgency: "WC001",
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &serviceImp{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
				tokenManage: &tokenManage{
					tokenCache: map[string]*TokenInfo{
						"error:secret": {
							AccessToken: "error_id",
							ExpiresTs:   1611996986,
						},
						"normal:secret": {
							AccessToken: "normal-token",
							ExpiresTs:   1611996986,
						},
					}, mu: &sync.Mutex{},
					nowTimeFunc: func() time.Time {
						t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
						return t
					},
				},
			}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			i.confClient = mockAgolloClient
			mockAgolloClient.EXPECT().GetString("report_center.host", "127.0.0.1", gomock.Any()).Return(host).AnyTimes()
			mockAgolloClient.EXPECT().GetInt("report_center.port", 18002, gomock.Any()).Return(int(p)).AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_center.facilityOwnerAgency", "", gomock.Any()).Return("").AnyTimes()
			mockAgolloClient.EXPECT().GetBool("report_center.with_ssl", true, gomock.Any()).Return(true).AnyTimes()
			mockAgolloClient.EXPECT().GetString("token_uri", "webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token", gomock.Any()).Return("webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token").AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_data_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/reportData", gomock.Any()).Return("webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/reportData").AnyTimes()
			got, err := i.ReportData(tt.args.ctx, tt.args.request, tt.args.globalConf)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportData() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportData() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_Audit(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := r.Header.Get("X-Access-Token")
		var buf []byte
		if token == "" {
			panic("invalid token")
		} else if token == "error_id" {
			buf, _ = json.Marshal(map[string]interface{}{
				"groupId": []string{"error"},
			})
		} else {
			resp := AuditResponse{
				GroupId: "groupId",
				Code:    "WL-30000",
				Msg:     "接收成功",
			}
			buf, _ = json.Marshal(resp)
		}
		w.Write(buf)
	}))
	defer ts.Close()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	host := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[0]
	port := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[1]
	p, _ := strconv.ParseInt(port, 10, 64)

	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error)
		httpClient   httpClient
		ioReadFunc   func(r io.Reader) ([]byte, error)
		compressFunc func(data interface{}) (string, error)
	}
	type args struct {
		ctx        context.Context
		request    AuditRequest
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *AuditResponse
		wantErr bool
	}{
		{
			name: "normal",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "center",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "secret",
					Ip:           host,
					Port:         int32(p),
				},
			},
			want: &AuditResponse{
				GroupId: "groupId",
				Code:    "WL-30000",
				Msg:     "接收成功",
			},
			wantErr: false,
		},
		{
			name: "get token fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "--",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "compress fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "", fmt.Errorf("mock fail")
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "invalid token",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "new request fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: func(method, url string, body io.Reader) (*http.Request, error) {
					return nil, fmt.Errorf("mock fail")
				},
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
					Ip:           "127.0.0.1",
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "do http client fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: &fakeClient{},
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: AuditRequest{
					FacilityOwnerAgency: "center",
					BranchNumber:        1,
					BranchIdList:        []string{"111"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:            "error",
					ClientSecret:        "secret",
					Ip:                  "127.0.0.1",
					Port:                int32(p),
					FacilityOwnerAgency: "WC001",
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &serviceImp{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
				tokenManage: &tokenManage{
					tokenCache: map[string]*TokenInfo{
						"error:secret": {
							AccessToken: "error_id",
							ExpiresTs:   1611996986,
						},
						"normal:secret": {
							AccessToken: "normal-token",
							ExpiresTs:   1611996986,
						},
					}, mu: &sync.Mutex{},
					nowTimeFunc: func() time.Time {
						t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
						return t
					},
				},
			}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			i.confClient = mockAgolloClient
			mockAgolloClient.EXPECT().GetString("report_center.host", "127.0.0.1", gomock.Any()).Return(host).AnyTimes()
			mockAgolloClient.EXPECT().GetInt("report_center.port", 18002, gomock.Any()).Return(int(p)).AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_center.facilityOwnerAgency", "", gomock.Any()).Return("").AnyTimes()
			mockAgolloClient.EXPECT().GetBool("report_center.with_ssl", true, gomock.Any()).Return(true).AnyTimes()
			mockAgolloClient.EXPECT().GetString("token_uri", "webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token", gomock.Any()).Return("webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token").AnyTimes()
			mockAgolloClient.EXPECT().GetString("request_check_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/requestCheck", gomock.Any()).Return("webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/requestCheck").AnyTimes()
			got, err := i.Audit(tt.args.ctx, tt.args.request, tt.args.globalConf)
			if (err != nil) != tt.wantErr {
				t.Errorf("ReportData() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ReportData() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestTokenInfo_isValid(t *testing.T) {
	type fields struct {
		AccessToken string
		ExpiresIn   int
		ExpiresTs   int64
	}
	type args struct {
		nowTs int64
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "",
			fields: fields{
				ExpiresTs: 1600000,
			},
			args: args{
				nowTs: 1500000,
			},
			want: true,
		},
		{
			name: "",
			fields: fields{
				ExpiresTs: 1500000,
			},
			args: args{
				nowTs: 1600000,
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &TokenInfo{
				AccessToken: tt.fields.AccessToken,
				ExpiresIn:   tt.fields.ExpiresIn,
				ExpiresTs:   tt.fields.ExpiresTs,
			}
			if got := i.isValid(tt.args.nowTs); got != tt.want {
				t.Errorf("isValid() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_tokenManage_getToken(t *testing.T) {
	now := time.Now()
	type fields struct {
		mu          *sync.Mutex
		tokenCache  map[string]*TokenInfo
		nowTimeFunc timeutil.NowTimeFunc
	}
	type args struct {
		key          string
		tokenCreator func() (*TokenInfo, error)
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *TokenInfo
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				mu:         &sync.Mutex{},
				tokenCache: map[string]*TokenInfo{},
				nowTimeFunc: func() time.Time {
					return now
				},
			},
			args: args{
				key: "one:cc",
				tokenCreator: func() (*TokenInfo, error) {
					return &TokenInfo{
						AccessToken: "haha",
						ExpiresIn:   300,
					}, nil
				},
			},
			want: &TokenInfo{
				AccessToken: "haha",
				ExpiresIn:   300,
				ExpiresTs:   now.Unix() + 300,
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tm := &tokenManage{
				mu:          tt.fields.mu,
				tokenCache:  tt.fields.tokenCache,
				nowTimeFunc: tt.fields.nowTimeFunc,
			}
			got, err := tm.getToken(tt.args.key, tt.args.tokenCreator)
			if (err != nil) != tt.wantErr {
				t.Errorf("getToken() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("getToken() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_CheckReportResult(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := r.Header.Get("X-Access-Token")
		var buf []byte
		if token == "" {
			panic("invalid token")
		} else if token == "error_id" {
			buf, _ = json.Marshal(map[string]interface{}{
				"branchId": []string{"error"},
			})
		} else if token == "resp_error" {
			resp := CheckResponse{}
			buf, _ = json.Marshal(resp)
		} else {
			resp := CheckResponse{
				BranchId: "branchId",
				Code:     "WL-10008",
				Msg:      "部分失败",
				Data: []CheckData{
					{
						Code:               "WL-20001",
						Msg:                "[facilityUsedState]不在填报范围",
						FacilityCategory:   "FAITSERPCS",
						FacilityDescriptor: "5f11db861e33ff0ec08ba546",
					},
				},
			}
			buf, _ = json.Marshal(resp)
		}
		w.Write(buf)
	}))
	defer ts.Close()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	host := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[0]
	port := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[1]
	p, _ := strconv.ParseInt(port, 10, 64)

	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error)
		httpClient   httpClient
		ioReadFunc   func(r io.Reader) ([]byte, error)
		compressFunc func(data interface{}) (string, error)
		tokenManage  *tokenManage
	}
	type args struct {
		ctx        context.Context
		request    CheckRequest
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *CheckResponse
		wantErr bool
	}{
		{
			name: "normal",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "normal",
					ClientSecret: "secret",
					Ip:           host,
					Port:         int32(p),
				},
			},
			want: &CheckResponse{
				BranchId: "branchId",
				Code:     "WL-10008",
				Msg:      "部分失败",
				Data: []CheckData{
					{
						Code:               "WL-20001",
						Msg:                "[facilityUsedState]不在填报范围",
						FacilityCategory:   "FAITSERPCS",
						FacilityDescriptor: "5f11db861e33ff0ec08ba546",
					},
				},
			},
			wantErr: false,
		},
		{
			name: "resp not effected",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "resp-error",
					ClientSecret: "secret",
					Ip:           host,
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
		{
			name: "fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:            "error",
					ClientSecret:        "secret",
					Ip:                  host,
					Port:                int32(p),
					FacilityOwnerAgency: "WC001",
				},
			},
			wantErr: true,
		},
		{
			name: "request fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: func(method, url string, body io.Reader) (*http.Request, error) {
					return nil, fmt.Errorf("mock fail")
				},
				httpClient: ts.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "center",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
					Ip:           host,
					Port:         int32(p),
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &serviceImp{
				reportCenter: tt.fields.reportCenter,
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
				tokenManage: &tokenManage{
					tokenCache: map[string]*TokenInfo{
						"error:secret": {
							AccessToken: "error_id",
							ExpiresTs:   1611996986,
						},
						"normal:secret": {
							AccessToken: "normal-token",
							ExpiresTs:   1611996986,
						},
						"resp-error:secret": {
							AccessToken: "resp_error",
							ExpiresTs:   1611996986,
						},
					}, mu: &sync.Mutex{},
					nowTimeFunc: func() time.Time {
						t, _ := time.Parse("2006-01-02 15:04:05", "2021-01-04 15:09:46")
						return t
					},
				},
			}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			i.confClient = mockAgolloClient
			mockAgolloClient.EXPECT().GetString("report_center.host", "127.0.0.1", gomock.Any()).Return(host).AnyTimes()
			mockAgolloClient.EXPECT().GetInt("report_center.port", 18002, gomock.Any()).Return(int(p)).AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_center.facilityOwnerAgency", "", gomock.Any()).Return("").AnyTimes()
			mockAgolloClient.EXPECT().GetBool("report_center.with_ssl", true, gomock.Any()).Return(true).AnyTimes()
			mockAgolloClient.EXPECT().GetString("token_uri", "webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token", gomock.Any()).Return("webproxy/fig2fics/conn/oauth2/v1/pshare/oauth/token").AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_result_uri", "webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData", gomock.Any()).Return("webproxy/fig2fics/conn/pshare/api/prod/FICS/api/fics/dataElementInstance/selectUploadData").AnyTimes()
			got, err := i.CheckReportResult(tt.args.ctx, tt.args.request, tt.args.globalConf)
			if (err != nil) != tt.wantErr {
				t.Errorf("CheckReportResult() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("CheckReportResult() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_serviceImp_SelectBranchId(t *testing.T) {

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		reportCenter config.ReportCenter
		newRequest   func(method, url string, body io.Reader) (*http.Request, error)
		httpClient   httpClient
		ioReadFunc   func(r io.Reader) ([]byte, error)
		compressFunc func(data interface{}) (string, error)
		tokenManage  *tokenManage
	}
	type args struct {
		ctx        context.Context
		request    BranchIdRequest
		globalConf *fintech_data.ReportGlobalConfig
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    *BranchIdResponse
		wantErr bool
	}{
		{
			name:   "normal",
			fields: fields{},
			args:   args{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &serviceImp{}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()

			got, err := i.SelectBranchId(tt.args.ctx, tt.args.request, tt.args.globalConf)
			if (err != nil) != tt.wantErr {
				t.Errorf("CheckReportResult() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("CheckReportResult() got = %v, want %v", got, tt.want)
			}
		})
	}
}
