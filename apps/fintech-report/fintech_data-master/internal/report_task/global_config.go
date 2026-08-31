package report_task

import (
	"context"
	"encoding/json"
	"time"

	"github.com/gogo/protobuf/types"
	"github.com/gorhill/cronexpr"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/kit/gogoprotobuf/jsonpb"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

const (
	configObjId        = "FINTECH_REPORT_CONFIG@EASYOPS"
	internalConfigName = "internal_config"
)

type ConfigService interface {
	GetConfig(ctx context.Context) (*fintech_data.ReportGlobalConfig, error)
	UpdateConfig(ctx context.Context, data *fintech_data.ReportGlobalConfig) error
}

func NewConfigService(instanceClient instance.Client) ConfigService {
	return &serviceImp{
		instanceClient: instanceClient,
	}
}

type serviceImp struct {
	instanceClient instance.Client
}

func getConfigQuery() map[string]interface{} {
	query := map[string]interface{}{
		"name": internalConfigName,
	}
	return query
}

func (i *serviceImp) GetConfig(ctx context.Context) (*fintech_data.ReportGlobalConfig, error) {
	logger := logctx.MustGetLogger(ctx)
	confList, err := i.SearchConfig(ctx, getConfigQuery())
	if err != nil {
		logger.Errorf("search task config fail, error: %s", err.Error())
		return nil, err
	}
	if len(confList) == 0 {
		logger.Infof("has no task config, return empty data")
		return &fintech_data.ReportGlobalConfig{}, nil
	}
	return confList[0], nil
}

func (i *serviceImp) UpdateConfig(ctx context.Context, data *fintech_data.ReportGlobalConfig) error {
	logger := logctx.MustGetLogger(ctx)
	updateData := configToStruct(data)
	updateData.Fields["name"] = protostruct.ToValue(internalConfigName)
	resp, err := i.instanceClient.ImportInstance(ctx, &instance.ImportInstanceRequest{
		ObjectId: configObjId,
		Keys:     []string{"name"},
		Datas:    []*types.Struct{updateData},
	})
	if err != nil {
		logger.Errorf("update task config fail, error: %s", err.Error())
		return err
	}
	if len(resp.Data) > 0 {
		logger.Errorf("update task config fail, error: %s", resp.Data[0].Error)
		if resp.Data[0].Code == 130600 {
			return apierrors.PermissionDeniedErrorf("无上报配置编辑权限")
		}
		return apierrors.InternalErrorf(resp.Data[0].Error)
	}
	logger.Infof("update task config success")
	return nil
}

func configToStruct(data *fintech_data.ReportGlobalConfig) *types.Struct {
	m := jsonpb.Marshaler{}
	jsonStr, err := m.MarshalToString(data)
	if err != nil {
		return nil
	}
	result := make(map[string]interface{})
	_ = json.Unmarshal([]byte(jsonStr), &result)
	return protostruct.ToStruct(result)
}

func structToConf(data *types.Struct) (*fintech_data.ReportGlobalConfig, error) {
	dataMap := protostruct.DecodeToMap(data)
	dataBytes, _ := json.Marshal(dataMap)
	um := jsonpb.Unmarshaler{}
	config := &fintech_data.ReportGlobalConfig{}
	err := um.UnmarshalFromString(string(dataBytes), config)
	if err != nil {
		return nil, err
	}
	return config, nil
}

func NextExecTime(crontab string, now time.Time) (string, error) {
	exp, err := cronexpr.Parse(crontab)
	if err != nil {
		return "", apierrors.InvalidArgumentErrorf("crontab格式不合法: %s", err.Error())
	}
	nextExecTime := exp.Next(now).Format(timeutil.TimeFormat)
	return nextExecTime, nil
}

func (i *serviceImp) SearchConfig(ctx context.Context, query map[string]interface{}) ([]*fintech_data.ReportGlobalConfig, error) {
	req := &instance.PostSearchV2Request{
		ObjectId: configObjId,
		Query:    protostruct.ToStruct(query),
		Fields:   protostruct.ToStruct(map[string]interface{}{"*": true}),
		Page:     1,
		PageSize: 3000,
	}
	resp, err := i.instanceClient.PostSearchV2(ctx, req)
	if err != nil {
		return nil, err
	}
	configList := make([]*fintech_data.ReportGlobalConfig, 0, len(resp.List))
	for _, item := range resp.List {
		conf, err := structToConf(item)
		if err != nil {
			return nil, err
		}
		configList = append(configList, conf)
	}
	return configList, nil
}
