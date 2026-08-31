package report_rule

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/gogo/protobuf/types"
	funk "github.com/thoas/go-funk"

	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/giraffe-micro/pkg/gerr"
	"go.easyops.local/kit/gogoprotobuf/jsonpb"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

const (
	ruleObjId           = "FINTECH_REPORT_OBJ@EASYOPS"
	ObjectSourceMapping = "mapping"
	ObjectSourceDirect  = "direct"
	NextExecTime        = "nextExecTime"
)

type Service interface {
	UpdateRule(ctx context.Context, instanceId string, rule *fintech_data.ReportObjectConf, updateFields []string) error
	SearchRule(ctx context.Context, query map[string]interface{}, fields []string) ([]*fintech_data.ReportObjectConf, error)
	GetRule(ctx context.Context, objectId string) (*fintech_data.ReportObjectConf, error)
	UpdateRuleByQuery(ctx context.Context, query map[string]interface{}, rule *fintech_data.ReportObjectConf, updateFields []string) (int, error)
}

func NewService(objectClient cmdb_object.Client, instanceClient instance.Client) Service {
	return &serviceImp{
		objectClient:   objectClient,
		instanceClient: instanceClient,
	}
}

type serviceImp struct {
	objectClient   cmdb_object.Client
	instanceClient instance.Client
}

func ruleToStruct(rule *fintech_data.ReportObjectConf) *types.Struct {
	m := jsonpb.Marshaler{}
	jsonStr, err := m.MarshalToString(rule)
	if err != nil {
		return nil
	}
	result := make(map[string]interface{})
	_ = json.Unmarshal([]byte(jsonStr), &result)
	return protostruct.ToStruct(result)
}

func (i *serviceImp) UpdateRule(ctx context.Context, instanceId string, rule *fintech_data.ReportObjectConf, updateFields []string) error {
	logger := logctx.MustGetLogger(ctx)
	if rule.Source == ObjectSourceMapping && funk.InStrings(updateFields, "mappingRule") {
		// 如果映射则可能需要同步上报模型的属性到被映射模型上
		if err := i.syncReportObjectAtt(ctx, rule); err != nil {
			logger.Errorf("sync mapping object %s fail, error: %s", rule.MappingObjectId, err.Error())
			return err
		}
	}
	updateData := ruleToStruct(rule)
	data := make(map[string]*types.Value)
	for _, field := range updateFields {
		data[field] = updateData.Fields[field]
	}
	updateReq := &instance.UpdateInstanceV2Request{
		ObjectId:       ruleObjId,
		InstanceId:     instanceId,
		Instance:       &types.Struct{Fields: data},
		OnlyInstanceId: true,
	}
	_, err := i.instanceClient.UpdateInstanceV2(ctx, updateReq)
	if err != nil {
		logger.Errorf("update object %s mapping rule fail, error: %s", rule.ObjectId, err.Error())
		return formatErr(err)
	}
	logger.Infof("update object %s mapping rule success", rule.ObjectId)
	return nil
}

func (i *serviceImp) syncReportObjectAtt(ctx context.Context, rule *fintech_data.ReportObjectConf) error {
	logger := logctx.MustGetLogger(ctx)
	reportObject, mappingObject, err := i.getRuleObjects(ctx, rule)
	if err != nil {
		logger.Errorf("get mapping rule objects fail, error: %s", err.Error())
		return err
	}

	createAttrIds := make(map[string]struct{})
	for _, attrConf := range rule.MappingRule.AttrMapping {
		if err := checkAttrMapping(reportObject, mappingObject, attrConf); err != nil {
			logger.Errorf("object %s mapping rule invalid, error:%s", rule.ObjectId, err.Error())
			return err
		}
		if attrConf.ReportAttrId != "" && attrConf.MappingAttrId == "" {
			// 当指定没有映射属性时，则
			createAttrIds[attrConf.ReportAttrId] = struct{}{}
		}
	}

	if len(createAttrIds) > 0 {
		logger.Infof("report object %s sync attr %v to mapping object %s", rule.ObjectId, createAttrIds, rule.MappingObjectId)

		createAttrs := make([]*cmdb.ObjectAttr, 0, len(createAttrIds))
		for _, attr := range reportObject.AttrList {
			if _, ok := createAttrIds[attr.Id]; ok {
				createAttrs = append(createAttrs, attr)
			}
		}
		mappingObject.AttrList = append(mappingObject.AttrList, createAttrs...)

		// 更新映射模型
		if err := i.updateMappingObject(ctx, mappingObject); err != nil {
			logger.Errorf("update mapping object %s fail, error: %s", rule.MappingObjectId, err.Error())
			return err
		}

	}
	return nil
}

// 获取上报模型和映射模型的定义
func (i *serviceImp) getRuleObjects(ctx context.Context, rule *fintech_data.ReportObjectConf) (*cmdb.CmdbObject, *cmdb.CmdbObject, error) {
	req := &cmdb_object.GetObjectAllRequest{
		ObjectIds: strings.Join([]string{rule.ObjectId, rule.MappingObjectId}, ","),
	}
	objList, err := i.objectClient.GetObjectAll(ctx, req)
	if err != nil {
		return nil, nil, err
	}
	var reportObject, mappingObject *cmdb.CmdbObject
	for _, obj := range objList.Data {
		if obj.ObjectId == rule.ObjectId {
			reportObject = obj
			continue
		}
		if obj.ObjectId == rule.MappingObjectId {
			mappingObject = obj
			continue
		}
	}
	if reportObject == nil || mappingObject == nil {
		return nil, nil, apierrors.NotFoundErrorf("模型%s或%s不存在", rule.ObjectId, rule.MappingObjectId)
	}
	return reportObject, mappingObject, nil
}

func (i *serviceImp) updateMappingObject(ctx context.Context, obj *cmdb.CmdbObject) error {
	resp, err := i.objectClient.ImportV2(ctx, &cmdb_object.ImportV2Request{ObjectList: []*cmdb.CmdbObject{obj}})
	if err != nil {
		return formatErr(err)
	}
	for _, res := range resp.ImportResult {
		if res.Code != 0 {
			var msg []string
			for _, attr := range res.AttrListResult {
				if attr.Code != 0 {
					msg = append(msg, fmt.Sprintf("属性%s(%s): %s", attr.Name, attr.Id, attr.Message))
				}
			}
			return apierrors.UnknownErrorf("更新映射模型失败, %s", strings.Join(msg, ";"))
		}
	}
	return nil
}

func checkAttrMapping(reportObj *cmdb.CmdbObject, mappingObj *cmdb.CmdbObject, attrConf *fintech_data.AttrMapping) error {
	reportAttr := getObjectAttr(reportObj, attrConf.ReportAttrId)
	if reportAttr == nil {
		return apierrors.NotFoundErrorf("上报模型%s不存在字段%s", reportObj.ObjectId, attrConf.ReportAttrId)
	}
	if attrConf.MappingAttrId != "" {
		mappingAttr := getObjectAttr(mappingObj, attrConf.MappingAttrId)
		if mappingAttr == nil {
			return apierrors.NotFoundErrorf("映射模型%s不存在字段%s", mappingObj.ObjectId, attrConf.MappingAttrId)
		}
		if reportAttr.Value.Type != mappingAttr.Value.Type {
			return apierrors.InvalidArgumentErrorf("%s和%s属性类型不一致，无法映射", reportAttr.Name, mappingAttr.Name)
		}
	}
	return nil
}

func getObjectAttr(obj *cmdb.CmdbObject, attrId string) *cmdb.ObjectAttr {
	for _, attr := range obj.AttrList {
		if attr.Id == attrId {
			return attr
		}
	}
	return nil
}

func structToConf(data *types.Struct) (*fintech_data.ReportObjectConf, error) {
	dataMap := protostruct.DecodeToMap(data)
	dataBytes, _ := json.Marshal(dataMap)
	um := jsonpb.Unmarshaler{}
	config := &fintech_data.ReportObjectConf{}
	err := um.UnmarshalFromString(string(dataBytes), config)
	if err != nil {
		return nil, err
	}
	return config, nil
}

func (i *serviceImp) GetRule(ctx context.Context, objectId string) (*fintech_data.ReportObjectConf, error) {
	query := map[string]interface{}{
		"objectId": objectId,
	}
	ruleList, err := i.SearchRule(ctx, query, nil)
	if err != nil {
		return nil, err
	}
	if len(ruleList) == 0 {
		return nil, apierrors.NotFoundErrorf("找不到模型id为%s的配置", objectId)
	}
	return ruleList[0], nil
}

func (i *serviceImp) SearchRule(ctx context.Context, query map[string]interface{}, fields []string) ([]*fintech_data.ReportObjectConf, error) {
	logger := logctx.MustGetLogger(ctx)
	fieldsMap := make(map[string]interface{})
	if len(fields) == 0 {
		fieldsMap["*"] = true
	} else {
		for _, f := range fields {
			fieldsMap[f] = true
		}
	}
	req := &instance.PostSearchV2Request{
		ObjectId: ruleObjId,
		Query:    protostruct.ToStruct(query),
		Fields:   protostruct.ToStruct(fieldsMap),
		Page:     1,
		PageSize: 3000,
	}
	resp, err := i.instanceClient.PostSearchV2(ctx, req)
	if err != nil {
		logger.Errorf("search object report rule fail, error: %s", err.Error())
		return nil, err
	}
	ruleList := make([]*fintech_data.ReportObjectConf, 0, len(resp.List))
	for _, item := range resp.List {
		rule, err := structToConf(item)
		if err != nil {
			logger.Errorf("data convert fail, error: %s", err.Error())
			return nil, err
		}
		ruleList = append(ruleList, rule)
	}
	return ruleList, nil
}

// 根据查询条件更新规则
func (i *serviceImp) UpdateRuleByQuery(ctx context.Context, query map[string]interface{}, rule *fintech_data.ReportObjectConf, updateFields []string) (int, error) {
	updateData := ruleToStruct(rule)
	data := make(map[string]*types.Value)
	for _, field := range updateFields {
		data[field] = updateData.Fields[field]
	}
	resp, err := i.instanceClient.UpdateByQuery(ctx, &instance.UpdateByQueryRequest{
		ObjectId: ruleObjId,
		Query:    protostruct.ToStruct(query),
		Data:     &types.Struct{Fields: data},
	})
	if err != nil {
		return 0, err
	}
	return int(resp.SuccessTotal), nil
}

func formatErr(err error) error {
	status := gerr.FromError(err)
	if status.Code() == 130600 {
		return apierrors.PermissionDeniedErrorf("无配置编辑权限")
	}
	return err
}
