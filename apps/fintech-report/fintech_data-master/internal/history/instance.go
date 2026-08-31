package history

import (
	"context"
	"strings"

	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/contracts/protorepo-monthly_collection_service/document"
	"go.easyops.local/fintech_data/internal/extends/typeutil"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

func convertInstance(data *types.Struct) (*fintech_data.ReportInstance, error) {
	instance := &fintech_data.ReportInstance{}
	err := typeutil.StructToPbMessage(data, instance)
	if err != nil {
		return nil, err
	}
	instance.DataId = data.Fields["_id"].GetStringValue()
	return instance, nil
}

func instanceToData(branch *fintech_data.ReportInstance) *types.Struct {
	data := typeutil.PbMessageToStruct(branch)
	delete(data.Fields, "dataId")
	return data
}

func (s *historyService) GetInstanceList(ctx context.Context, list []*types.Struct) ([]*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	instanceList := make([]*fintech_data.ReportInstance, 0, len(list))
	var (
		taskIdSet          = make(map[string]struct{})
		taskId2ObjectIdMap = make(map[string]string)
		i                  = 0
	)
	for _, data := range list {
		inst, err := convertInstance(data)
		if err != nil {
			logger.Errorf("instance convert fail, data: %v, error: %s", data, err.Error())
			return nil, err
		}
		instanceList = append(instanceList, inst)
		taskIdSet[inst.TaskId] = struct{}{}
	}
	if len(taskIdSet) > 0 {
		taskIdList := make([]string, len(taskIdSet))
		for taskId := range taskIdSet {
			taskIdList[i] = taskId
			i += 1
		}
		taskIdResp, err := s.monthlyClient.Document.FindIDs(ctx, &document.FindIDsRequest{
			CollectionName: collNameTask,
			Ids:            taskIdList,
		})
		if err != nil {
			logger.Errorf("find ids fail:%s;the task id list is [%s]", err, strings.Join(taskIdList, ","))
			return nil, err
		}
		for _, taskStruct := range taskIdResp.List {
			taskId := taskStruct.Fields["_id"].GetStringValue()
			mapObjectId := taskStruct.Fields["mappingObjectId"].GetStringValue()
			taskId2ObjectIdMap[taskId] = mapObjectId
		}
		for _, inst := range instanceList {
			if mapObjectId, exit := taskId2ObjectIdMap[inst.TaskId]; exit {
				inst.MappingObjectId = mapObjectId
			}
		}
	}
	return instanceList, nil
}

func (s *historyService) SearchInstance(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportInstance, int, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.SearchRequest{
		CollectionName: collNameInstance,
		Page:           int32(page),
		PageSize:       int32(pageSize),
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
	}
	resp, err := s.monthlyClient.Document.Search(ctx, req)
	if err != nil {
		logger.Errorf("search instance fail, error: %s", err.Error())
		return nil, 0, err
	}
	instanceList, err := s.GetInstanceList(ctx, resp.List)
	if err != nil {
		logger.Errorf("get instance list fail, error: %s", err.Error())
		return nil, 0, err
	}
	return instanceList, int(resp.Total), nil
}

func (s *historyService) SearchInstanceAll(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	var instList []*fintech_data.ReportInstance
	var nextId string
	for {
		resp, err := s.SearchInstanceLimit(ctx, query, fields, limit, st, et, nextId)
		if err != nil {
			logger.Errorf("search report instance fail, nextId: %s , error: %s", nextId, err.Error())
			return nil, err
		}
		instList = append(instList, resp.InstanceList...)
		nextId = resp.NextId
		if !resp.HasMore {
			break
		}
	}
	return instList, nil
}

func (s *historyService) BatchCreateInstance(ctx context.Context, branchList []*fintech_data.ReportInstance) ([]string, error) {
	logger := logctx.MustGetLogger(ctx)
	dataList := make([]*types.Struct, 0, len(branchList))
	for _, item := range branchList {
		dataList = append(dataList, instanceToData(item))
	}
	req := &document.BatchCreateRequest{
		CollectionName: collNameInstance,
		Timestamp:      int32(s.nowTimeFunc().Unix()),
		Documents:      dataList,
	}
	resp, err := s.monthlyClient.Document.BatchCreate(ctx, req)
	if err != nil {
		logger.Errorf("batch create instance fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("batch create instance success, total: %d", len(resp.Ids))
	return resp.Ids, nil
}

func (s *historyService) updateInstance(ctx context.Context, dataId string, updateData *types.Struct) error {
	_, err := s.monthlyClient.Document.Update(ctx, &document.UpdateRequest{
		CollectionName: collNameInstance,
		Id:             dataId,
		Update:         updateData,
	})
	return err
}

func (s *historyService) UpdateInstanceByFilter(ctx context.Context, query []*monthly_model.QueryItem, instance *fintech_data.ReportInstance, updateFields []string, st int, et int) error {
	logger := logctx.MustGetLogger(ctx)
	updateData := convertUpdateData(instance, updateFields)
	fields := map[string]interface{}{"_id": true}
	limit := 50
	var nextId string
	updateTotal := 0
	for {
		resp, err := s.SearchInstanceLimit(ctx, query, fields, limit, st, et, nextId)
		if err != nil {
			logger.Errorf("search report instance fail, nextId: %s , error: %s", nextId, err.Error())
			return err
		}
		for _, data := range resp.InstanceList {
			err = s.updateInstance(ctx, data.DataId, updateData)
			if err != nil {
				logger.Errorf("update report instance fail, dataId: %s, error: %s", data.DataId, err.Error())
				return err
			}
			updateTotal += 1
		}
		logger.Infof("search report instance success, total: %d", len(resp.InstanceList))
		nextId = resp.NextId
		if !resp.HasMore {
			break
		}
	}
	return nil
}

func (s *historyService) UpdateInstance(ctx context.Context, dataId string, instance *fintech_data.ReportInstance, updateFields []string) error {
	updateData := convertUpdateData(instance, updateFields)
	return s.updateInstance(ctx, dataId, updateData)
}

func convertUpdateData(instance *fintech_data.ReportInstance, updateFields []string) *types.Struct {
	data := instanceToData(instance)
	updateData := &types.Struct{Fields: map[string]*types.Value{}}
	for _, key := range updateFields {
		updateData.Fields[key] = data.Fields[key]
	}
	return updateData
}

type InstanceLimitResult struct {
	InstanceList []*fintech_data.ReportInstance
	NextId       string
	HasMore      bool
}

func (s *historyService) SearchInstanceLimit(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int, nextId string) (*InstanceLimitResult, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.LimitRequest{
		CollectionName: collNameInstance,
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
		Limit:          int32(limit),
		NextId:         nextId,
	}
	resp, err := s.monthlyClient.Document.Limit(ctx, req)
	if err != nil {
		logger.Errorf("search report instance fail, nextId: %s , error: %s", nextId, err.Error())
		return nil, err
	}
	instanceList, err := s.GetInstanceList(ctx, resp.List)
	if err != nil {
		logger.Errorf("get instance list fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("search report instance success, total: %d", len(instanceList))
	return &InstanceLimitResult{
		InstanceList: instanceList,
		HasMore:      resp.HaveMore,
		NextId:       resp.NextId,
	}, nil
}

func (s *historyService) GetInstance(ctx context.Context, dataId string) (*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.GETRequest{
		Id:             dataId,
		CollectionName: collNameInstance,
	}
	resp, err := s.monthlyClient.Document.GET(ctx, req)
	if err != nil {
		logger.Errorf("get instance fail, dataId: %s, error: %s", dataId, err.Error())
		return nil, err
	}
	return convertInstance(resp)
}
