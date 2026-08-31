package report_center

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/ioutil"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/mock/agollo_client"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func Test_zhongXinServiceImp_GetToken(t *testing.T) {
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
			name:    "normal",
			fields:  fields{},
			args:    args{},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			i := &zhongXinServiceImp{
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

func Test_zhongXinServiceImp_parseResponse(t *testing.T) {
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
			name: "read fail",
			fields: fields{
				ioReadFunc: func(r io.Reader) ([]byte, error) {
					return nil, fmt.Errorf("read fail")
				},
			},
			args: args{
				resp: &http.Response{
					Body: ioutil.NopCloser(strings.NewReader("abcdef")),
				},
			},
			wantErr: true,
		},

		{
			name: "unmarshal fail",
			fields: fields{
				ioReadFunc: ioutil.ReadAll,
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
			i := &zhongXinServiceImp{
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

func TestNewZhongXinService(t *testing.T) {
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
			want: &zhongXinServiceImp{
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
			NewZhongXinService(tt.args.reportCenter, tt.args.httpClient, nil, mockAgolloClient)
		})
	}
}

func Test_zhongXinServiceImp_ReportData(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var buf []byte
		resp := ReportResponse{
			Code: "1",
			Msg:  "接收成功",
			Data: "",
		}
		buf, _ = json.Marshal(resp)
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
				Code: "1",
				Msg:  "接收成功",
				Data: "",
			},
			wantErr: false,
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
					FacilityOwnerAgency: "WC001",
				},
			},
			wantErr: true,
		},

		{
			name: "parse response fail",
			fields: fields{
				compressFunc: func(data interface{}) (string, error) {
					return "data", nil
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: func(r io.Reader) ([]byte, error) {
					return nil, fmt.Errorf("parse response fail")
				},
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
			i := &zhongXinServiceImp{
				reportCenter: config.ReportCenter{
					Host:    host,
					Port:    int(p),
					WithSSL: true,
				},
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
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

func Test_zhongXinServiceImp_Audit(t *testing.T) {
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
			name:    "normal",
			fields:  fields{},
			args:    args{},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &zhongXinServiceImp{
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
			}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			i.confClient = mockAgolloClient
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

func Test_zhongXinServiceImp_CheckReportResult(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var buf []byte
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
		w.Write(buf)
	}))
	defer ts.Close()

	ts2 := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var buf []byte
		resp := CheckResponse{
			BranchId: "",
		}
		buf, _ = json.Marshal(resp)
		w.Write(buf)
	}))
	defer ts2.Close()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())

	host := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[0]
	port := strings.Split(strings.Replace(ts.URL, "https://", "", 1), ":")[1]
	p, _ := strconv.ParseInt(port, 10, 64)

	host2 := strings.Split(strings.Replace(ts2.URL, "https://", "", 1), ":")[0]
	port2 := strings.Split(strings.Replace(ts2.URL, "https://", "", 1), ":")[1]
	p2, _ := strconv.ParseInt(port2, 10, 64)

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
					BranchId:            "branchId",
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
			name: "new request fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: func(method, url string, body io.Reader) (*http.Request, error) {
					return nil, fmt.Errorf("new request fail")
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
					ClientId:            "error",
					ClientSecret:        "secret",
					Ip:                  host,
					Port:                int32(p),
					FacilityOwnerAgency: "center",
				},
			},
			wantErr: true,
		},

		{
			name: "parse response fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: func(r io.Reader) ([]byte, error) {
					return nil, fmt.Errorf("parse response fail")
				},
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "center",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:            "error",
					ClientSecret:        "secret",
					Ip:                  host,
					Port:                int32(p),
					FacilityOwnerAgency: "center",
				},
			},
			wantErr: true,
		},

		{
			name: "resp not effected",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts2.Client(),
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: CheckRequest{
					BranchId:            "",
					FacilityOwnerAgency: "",
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					Ip:   host2,
					Port: int32(p2),
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &zhongXinServiceImp{
				reportCenter: tt.fields.reportCenter,
				newRequest:   tt.fields.newRequest,
				httpClient:   tt.fields.httpClient,
				ioReadFunc:   tt.fields.ioReadFunc,
				compressFunc: tt.fields.compressFunc,
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

func Test_zhongXinServiceImp_SelectBranchId(t *testing.T) {
	ts := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var buf []byte
		resp := BranchIdResponse{
			Code: "0",
			Msg:  "部分失败",
			Data: "",
		}
		buf, _ = json.Marshal(resp)
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
			name: "do http client fail",
			fields: fields{
				newRequest: http.NewRequest,
				httpClient: &fakeClient{},
				ioReadFunc: ioutil.ReadAll,
			},
			args: args{
				ctx: ctx,
				request: BranchIdRequest{
					DataType: "dataCenter",
					DataList: []string{"0000000000000101-H-HDV-000000010"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					ClientId:     "error",
					ClientSecret: "secret",
				},
			},
			wantErr: true,
		},

		{
			name: "parse response fail",
			fields: fields{
				reportCenter: config.ReportCenter{
					WithSSL: true,
				},
				newRequest: http.NewRequest,
				httpClient: ts.Client(),
				ioReadFunc: func(r io.Reader) ([]byte, error) {
					return nil, fmt.Errorf("parse response fail")
				},
			},
			args: args{
				ctx: ctx,
				request: BranchIdRequest{
					DataType: "dataCenter",
					DataList: []string{"0000000000000101-H-HDV-000000010"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					FacilityOwnerAgency: "center",
				},
			},
			wantErr: true,
		},

		{
			name: "success",
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
				request: BranchIdRequest{
					DataType: "dataCenter",
					DataList: []string{"0000000000000101-H-HDV-000000010"},
				},
				globalConf: &fintech_data.ReportGlobalConfig{
					FacilityOwnerAgency: "center",
				},
			},
			want: &BranchIdResponse{
				Code: "0",
				Msg:  "部分失败",
				Data: "",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			i := &zhongXinServiceImp{
				newRequest: tt.fields.newRequest,
				httpClient: tt.fields.httpClient,
				ioReadFunc: tt.fields.ioReadFunc,
			}
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()
			mockAgolloClient := agollo_client.NewMockAgolloClient(ctrl)
			mockAgolloClient.EXPECT().GetString("report_center.host", "127.0.0.1", gomock.Any()).Return(host).AnyTimes()
			mockAgolloClient.EXPECT().GetInt("report_center.port", 18002, gomock.Any()).Return(int(p)).AnyTimes()
			mockAgolloClient.EXPECT().GetString("report_center.facilityOwnerAgency", "", gomock.Any()).Return("").AnyTimes()
			mockAgolloClient.EXPECT().GetBool("report_center.with_ssl", true, gomock.Any()).Return(true).AnyTimes()
			i.confClient = mockAgolloClient
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
