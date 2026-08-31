package fill_instance

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/gogo/protobuf/proto"
	"github.com/gogo/protobuf/types"
	funk "github.com/thoas/go-funk"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/notify"
	"go.easyops.local/contracts/protorepo-notify/subscriber"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/fintech_data/internal/extends/cmdbutil"
	"go.easyops.local/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

type Service interface {
	RegisterSubscribers() error
	HasEffectedRule(ctx context.Context, objectId string, item ProcessItem, updateData *types.Struct) bool
	FillInstance(ctx context.Context, objectId string, instList []ProcessItem) error
}

type Result struct {
	UploadInstList []*types.Struct
	FailList       []FailData
}

type ProcessItem struct {
	InstanceId   string   `json:"instanceId"`
	ChangeFields []string `json:"changeFields"`
	PushTime     int64    `json:"pushTime"`
	Error        []string `json:"-"`
	Code         int      `json:"-"`
	instanceData *types.Struct
	updateData   *types.Struct
}

func (i ProcessItem) ToString() string {
	v, _ := json.Marshal(i)
	return string(v)
}

type FailData struct {
	ObjectId   string
	AttrId     string
	InstanceId string
	Msg        string
}

func NewService(instanceRules []InstanceRule, relationRules []RelationRule, instanceClient instance.Client, subscriberClient subscriber.Client, subscriberProcNum int) Service {
	return &serviceImp{
		instanceRules:     instanceRules,
		relationRules:     relationRules,
		instanceClient:    instanceClient,
		subscriberClient:  subscriberClient,
		subscriberProcNum: subscriberProcNum,
	}
}

type serviceImp struct {
	relationRules     []RelationRule
	instanceRules     []InstanceRule
	instanceClient    instance.Client
	subscriberClient  subscriber.Client
	subscriberProcNum int
}

const (
	subscriberName = "fintech_data.instance.listener"
)

func (s *serviceImp) RegisterSubscribers() error {
	subscriberInfo := s.analysisRulesSubscribers()
	procNum := 0
	if len(subscriberInfo.Event) > 0 {
		procNum = s.subscriberProcNum
	}
	in := &notify.Subscriber{
		Name:          subscriberName,
		Callback:      "http://logic.fintech_data.local/api/fill/instance/callback",
		EnsName:       "logic.fintech_data",
		ProcNum:       int32(procNum),
		MsgType:       1,
		Retry:         1,
		SubscribeInfo: []*notify.SubscribeInfo{subscriberInfo},
	}
	_, err := s.subscriberClient.CreateSubscriber(context.Background(), in)
	return err
}

func (s *serviceImp) analysisRulesSubscribers() *notify.SubscribeInfo {
	objectMap := make(map[string]struct{})
	for _, rule := range s.instanceRules {
		if rule.ObjectId != "" {
			objectMap[rule.ObjectId] = struct{}{}
		}
		for _, objId := range rule.ObjectIdList {
			objectMap[objId] = struct{}{}
		}
	}
	for _, rule := range s.relationRules {
		if rule.ObjectId != "" {
			objectMap[rule.ObjectId] = struct{}{}
		}
		for _, objId := range rule.ObjectIdList {
			objectMap[objId] = struct{}{}
		}
	}
	event := make([]string, 0, 2*len(objectMap))
	for objId := range objectMap {
		event = append(event, fmt.Sprintf("event_v2.instance.create.%s", objId))
		event = append(event, fmt.Sprintf("event_v2.instance.modify.%s", objId))
	}
	return &notify.SubscribeInfo{
		Channel: "cmdb",
		Event:   event,
	}
}

func (s *serviceImp) HasEffectedRule(ctx context.Context, objectId string, item ProcessItem, updateData *types.Struct) bool {
	for _, rule := range s.relationRules {
		if rule.EffectedObject(objectId) && rule.Effected(item.ChangeFields, updateData) {
			return true
		}
	}
	for _, rule := range s.instanceRules {
		if rule.EffectedObject(objectId) && rule.Effected(item.ChangeFields) {
			return true
		}
	}
	return false
}

func (s *serviceImp) FillInstance(ctx context.Context, objectId string, instList []ProcessItem) error {
	logger := logctx.MustGetLogger(ctx)
	// fetch instance
	processInstMap, err := s.fetchInstance(ctx, objectId, instList)
	if err != nil {
		logger.Errorf("object %s fetch instance fail, error: %s", objectId, err.Error())
		return err
	}

	// relation rule fill
	for _, rule := range s.relationRules {
		if rule.EffectedObject(objectId) {
			err = s.fillRelationRule(ctx, objectId, rule, processInstMap)
			if err != nil {
				logger.Errorf("object %s fill relation rule fail, rule: %+v, error: %s", objectId, rule, err.Error())
				return err
			}
		}
	}

	// instance rule fill
	for _, rule := range s.instanceRules {
		if rule.EffectedObject(objectId) {
			s.fillInstanceRule(ctx, objectId, rule, processInstMap)
		}
	}

	// update to cmdb
	err = s.updateInstance(ctx, objectId, processInstMap)
	if err != nil {
		logger.Errorf("object %s update instance fail, error: %s", objectId, err.Error())
		return err
	}

	// record to mongodb
	return nil

}

func (s *serviceImp) fetchInstance(ctx context.Context, objectId string, instList []ProcessItem) (map[string]*ProcessItem, error) {
	instIds := make([]string, 0, len(instList))
	processInstMap := make(map[string]*ProcessItem)
	for i := 0; i < len(instList); i++ {
		inst := instList[i]
		if item, ok := processInstMap[inst.InstanceId]; !ok {
			processInstMap[inst.InstanceId] = &inst
			instIds = append(instIds, inst.InstanceId)
		} else {
			if len(item.ChangeFields) == 0 || len(inst.ChangeFields) == 0 {
				item.ChangeFields = []string{}
			} else {
				for _, field := range inst.ChangeFields {
					if !funk.ContainsString(item.ChangeFields, field) {
						item.ChangeFields = append(item.ChangeFields, field)
					}
				}
			}
		}
	}

	in := &instance.PostSearchV3Request{
		ObjectId: objectId,
		Query:    protostruct.ToStruct(map[string]interface{}{cmdbutil.InstanceIdLabel: map[string][]string{"$in": instIds}}),
		Fields:   []string{"*"}, // todo 从规则获取出所有要要用到的字段
		Page:     1,
		PageSize: int32(len(instIds)),
	}
	result, err := s.searchInstAll(ctx, in)
	if err != nil {
		return nil, err
	}
	for _, inst := range result {
		instanceId := cmdbutil.GetInstanceId(inst)
		processInstMap[instanceId].instanceData = inst
	}
	for _, item := range processInstMap {
		if item.instanceData == nil {
			item.Error = append(item.Error, fmt.Sprintf("不存在实例: %s", item.InstanceId))
			item.Code = apierrors.ErrNotFound.Code()
		}
	}
	return processInstMap, nil
}

func (s *serviceImp) searchInstAll(ctx context.Context, req *instance.PostSearchV3Request) ([]*types.Struct, error) {
	req.Page = 0
	instList := make([]*types.Struct, 0, int(req.PageSize))
	for req.Page < 100 { //只拿前100页
		req.Page += 1
		resp, err := s.instanceClient.PostSearchV3(ctx, req)
		if err != nil {
			return nil, err
		}
		instList = append(instList, resp.List...)
		if resp.Total <= req.Page*req.PageSize {
			break
		}
	}
	return instList, nil
}

func (s *serviceImp) fillRelationRule(ctx context.Context, objectId string, relationRule RelationRule, processInstMap map[string]*ProcessItem) error {
	logger := logctx.MustGetLogger(ctx)
	var sourceValue []interface{}
	effectedInstIds := make([]string, 0, len(processInstMap))

	// 筛选调无需变更的实例和整理需要查询的key value
	for _, item := range processInstMap {
		if item.instanceData == nil || !relationRule.Effected(item.ChangeFields, item.instanceData) {
			continue
		}
		values := relationRule.GetSourceValue(item.instanceData)
		if len(values) > 0 {
			effectedInstIds = append(effectedInstIds, item.InstanceId)
			sourceValue = append(sourceValue, values...)
		}
	}

	if len(effectedInstIds) == 0 {
		return nil
	}

	// 查询依赖的实例列表
	in := relationRule.GetRelationRequest(sourceValue)
	instList, err := s.searchInstAll(ctx, in)
	if err != nil {
		return err
	}
	relatedInstMap := make(map[string]*types.Struct)
	for _, inst := range instList {
		key := inst.Fields[relationRule.RelatedInstance.RelatedField].GetStringValue()
		relatedInstMap[key] = inst
	}

	// 实例值填充
	for _, instId := range effectedInstIds {
		item := processInstMap[instId]
		updateInst, err := relationRule.Do(ctx, objectId, item.instanceData, relatedInstMap)
		if err != nil {
			errMsg := fmt.Sprintf("关联关系填充失败：%s", err.Error())
			item.Error = append(item.Error, errMsg)
			logger.Errorf("object %s instance %s fill relation rul fail, error: %s", objectId, item.InstanceId, err.Error())
		}
		if updateInst != nil {
			mergeUpdateData(item, updateInst)
			logger.Infof("object %s instance %s update value: %+v", objectId, item.InstanceId, protostruct.DecodeToMap(updateInst))
		}
	}
	return nil
}

func mergeUpdateData(item *ProcessItem, updateInst *types.Struct) {
	if item.updateData == nil {
		item.updateData = &types.Struct{}
	}
	proto.Merge(item.updateData, updateInst)
}

func (s *serviceImp) fillInstanceRule(ctx context.Context, objectId string, instanceRule InstanceRule, processInstMap map[string]*ProcessItem) {
	logger := logctx.MustGetLogger(ctx)
	for _, item := range processInstMap {
		updateInst, err := instanceRule.Do(ctx, item.instanceData)
		if err != nil {
			item.Error = append(item.Error, fmt.Sprintf("实例填充失败: %s", err.Error()))
			logger.Errorf("object %s instance %s fill instance rul fail, error: %s", objectId, item.InstanceId, err.Error())
		} else if updateInst != nil {
			mergeUpdateData(item, updateInst)
			logger.Infof("object %s instance %s update value: %+v", objectId, item.InstanceId, updateInst.Fields)
		}
	}
	return
}

func (s *serviceImp) updateInstance(ctx context.Context, objectId string, processInstMap map[string]*ProcessItem) error {
	logger := logctx.MustGetLogger(ctx)
	importList := make([]*types.Struct, 0, len(processInstMap))
	for _, item := range processInstMap {
		if item.updateData != nil {
			item.updateData.Fields[cmdbutil.InstanceIdLabel] = protostruct.ToValue(item.InstanceId)
			importList = append(importList, item.updateData)
		}
	}
	if len(importList) == 0 {
		logger.Infof("object %s no instance update", objectId)
		return nil
	}
	in := &instance.ImportInstanceRequest{
		ObjectId: objectId,
		Keys:     []string{cmdbutil.InstanceIdLabel},
		Datas:    importList,
	}
	resp, err := s.instanceClient.ImportInstance(ctx, in)
	if err != nil {
		return err
	}
	if len(resp.Data) > 0 {
		for _, item := range resp.Data {
			for _, data := range item.Data {
				instanceId := cmdbutil.GetInstanceId(data)
				errMsg := fmt.Sprintf("实例更新失败: %s", item.Error)
				processInstMap[instanceId].Error = append(processInstMap[instanceId].Error, errMsg)
				processInstMap[instanceId].Code = apierrors.ErrInternal.Code()
			}
		}
	}
	logger.Infof("object %s instance update done, total: %d, failed: %d", objectId, len(importList), resp.FailedCount)
	return nil
}
