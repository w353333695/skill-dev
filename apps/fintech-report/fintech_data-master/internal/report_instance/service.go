package report_instance

import (
	"context"

	pbtypes "github.com/gogo/protobuf/types"
	"github.com/spf13/cast"
	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/contracts/protorepo-models/easyops/model/notify"
	"go.easyops.local/contracts/protorepo-notify/oplog"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/cmdbutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/types"
)

func NewService(
	instanceClient instance.Client,
	objectClient cmdb_object.Client,
	opLogClient oplog.Client,
	centerData history.CenterData,
	taskHistory history.TaskHistory,
	reportConf config.ReportConf,
	relationFillRules []fill_instance.RelationRule,
) Service {
	return &instanceService{
		instanceClient:    instanceClient,
		objectClient:      objectClient,
		opLogClient:       opLogClient,
		centerData:        centerData,
		taskHistory:       taskHistory,
		reportConf:        reportConf,
		relationFillRules: relationFillRules,
		nowTimeFunc:       timeutil.NowTime,
	}
}

type Service interface {
	SearchReportInstance(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask) ([]*fintech_data.ReportInstance, error)
}

type instanceService struct {
	instanceClient    instance.Client
	objectClient      cmdb_object.Client
	opLogClient       oplog.Client
	centerData        history.CenterData
	taskHistory       history.TaskHistory
	reportConf        config.ReportConf
	nowTimeFunc       timeutil.NowTimeFunc
	relationFillRules []fill_instance.RelationRule
}

const (
	// EventTypeDelete 删除类型事件
	EventTypeDelete = "event.instance.delete"
	// EventTypeArchive 归档类型事件
	EventTypeArchive = "event.instance.archive"
)

// SearchReportInstance 获取需要上报的实例
// link: https://tapd.easyops.local/pages/viewpage.action?pageId=28904179#id-%E9%87%91%E8%9E%8D%E5%85%83%E6%95%B0%E6%8D%AE%E4%B8%8A%E6%8A%A5%E6%8A%80%E6%9C%AF%E6%96%B9%E6%A1%88-%E4%BA%94%E3%80%81%E5%A6%82%E4%BD%95%E6%89%BE%E5%87%BA%E9%9C%80%E8%A6%81%E4%B8%8A%E6%8A%A5%E7%9A%84%E5%AE%9E%E4%BE%8B%EF%BC%9A
func (s *instanceService) SearchReportInstance(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask) ([]*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	deleteInstMap := make(map[string]*deleteInfo)
	newDeleteIds := make(map[string]struct{}) // 没上报过但已经删除的id
	var err error

	// 若非首次上报，则先查从之前上报到现在已删除/已归档的实例
	if reportTask.LastReportTime != "" {
		deleteInstMap, newDeleteIds, err = s.searchDeleteInstance(ctx, EventTypeDelete, request.ObjectConf, reportTask)
		if err != nil {
			logger.Errorf("%s task %s search delete instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
			return nil, err
		}
		logger.Infof("%s task %s search delete instance total: %d", request.ObjectConf.ObjectId, reportTask.TaskId, len(deleteInstMap))

		archiveInstMap, newArchiveIds, err := s.searchDeleteInstance(ctx, EventTypeArchive, request.ObjectConf, reportTask)
		if err != nil {
			logger.Errorf("%s task %s search archive instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
			return nil, err
		}
		logger.Infof("%s task %s search archive instance total: %d", request.ObjectConf.ObjectId, reportTask.TaskId, len(archiveInstMap))
		for k, info := range archiveInstMap {
			deleteInstMap[k] = info
		}
		for id := range newArchiveIds {
			newDeleteIds[id] = struct{}{}
		}
	}

	reportObj, err := s.objectClient.GetDetail(ctx, &cmdb_object.GetDetailRequest{ObjectId: request.ObjectConf.ObjectId})
	if err != nil {
		logger.Errorf("%s task %s search upsert instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return nil, err
	}
	converter := report_rule.NewConverter(reportObj, request.ObjectConf, s.reportConf, s.relationFillRules)

	// 查询插入或更新的实例
	insertList, updateList, err := s.searchUpsertInstance(ctx, converter, request.ObjectConf, reportTask, deleteInstMap, newDeleteIds)
	if err != nil {
		logger.Errorf("%s task %s search upsert instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return nil, err
	}

	// 把更新的实例和已上报的比较
	updateList, err = s.compareWithExisted(ctx, converter, updateList, reportTask)
	if err != nil {
		logger.Errorf("%s task %s compare instance with exist fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return nil, err
	}

	reportList := append(insertList, updateList...)

	deleteList := s.convertDeleteData(ctx, converter, reportTask, deleteInstMap)
	reportList = append(reportList, deleteList...)

	// 获取重试实例
	allDeleteMap := newDeleteIds
	for instId := range deleteInstMap {
		allDeleteMap[instId] = struct{}{}
	}
	retryList, err := s.searchRetryInstance(ctx, converter, reportTask, reportList, allDeleteMap)
	if err != nil {
		logger.Errorf("%s task %s load delete instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return nil, err
	}
	logger.Infof("%s task %s get retry inst total: %d", request.ObjectConf.ObjectId, reportTask.TaskId, len(retryList))
	reportList = append(reportList, retryList...)

	// 数据映射转换
	for _, inst := range reportList {
		converter.ConvertReportInst(inst)
	}

	result := s.filterIgnoreInst(reportList)
	return result, nil
}

func (s *instanceService) filterIgnoreInst(reportList []*fintech_data.ReportInstance) []*fintech_data.ReportInstance {
	result := make([]*fintech_data.ReportInstance, 0, len(reportList))
	for _, inst := range reportList {
		if ignore, ok := inst.Data.Fields[s.reportConf.IgnoreConf.InstanceIgnoreAttr]; ok {
			if ignore.GetBoolValue() {
				continue
			}
			delete(inst.Data.Fields, s.reportConf.IgnoreConf.InstanceIgnoreAttr)
		}
		result = append(result, inst)
	}
	return result
}

type deleteInfo struct {
	deleteTime int32
	data       *history.ReportMetaData
	name       string
}

// 查找已删除的实例
func (s *instanceService) searchDeleteInstance(ctx context.Context, event string, objectConf *fintech_data.ReportObjectConf, reportTask *fintech_data.ReportTask) (map[string]*deleteInfo, map[string]struct{}, error) {
	logger := logctx.MustGetLogger(ctx)
	total := 0
	deleteInstMap := make(map[string]*deleteInfo)
	newDeleteIds := make(map[string]struct{})
	req := &notify.ListOperationLogRequest{
		PageSize:     int32(s.reportConf.SearchBatch),
		System:       "cmdb",
		TargetId:     report_rule.GetSearchObjectId(objectConf),
		Event:        event,
		StartTime:    reportTask.LastReportTime,
		EndTime:      reportTask.StartTime,
		WithoutTotal: "false",
	}
	for page := 1; ; page++ {
		req.Page = int32(page)
		resp, err := s.opLogClient.ListOperationLog(ctx, req)
		if err != nil {
			logger.Errorf("search %s delete instance fail, error: %s", objectConf.ObjectId, err.Error())
			return nil, nil, err
		}
		deleteIds := make([]string, 0, len(resp.List))
		tmpDeleteMap := make(map[string]*deleteInfo, len(resp.List))
		for _, item := range resp.List {
			instName := item.ExtInfo.Fields["instance_name"].GetStringValue()
			tmpDeleteMap[item.TargetId] = &deleteInfo{name: instName, deleteTime: item.Ctime}
			deleteIds = append(deleteIds, item.TargetId)
		}
		if page == 1 {
			total = int(resp.Total)
		}
		logger.Infof("search %s delete instance success, page: %d, total: %d", objectConf.ObjectId, page, total)
		req.WithoutTotal = "true"

		existMap, err := s.loadExistInstance(ctx, "instanceId", deleteIds)
		if err != nil {
			logger.Errorf("load delete instance info fail, error: %s", err.Error())
			return nil, nil, err
		}
		for instId, info := range tmpDeleteMap {
			if data, ok := existMap[instId]; ok {
				inst, ok := deleteInstMap[data.FacilityDescriptor]
				if (ok && inst.deleteTime < info.deleteTime) || !ok {
					info.data = data
					deleteInstMap[data.FacilityDescriptor] = info
				}
			} else {
				newDeleteIds[instId] = struct{}{}
			}
		}

		if page*s.reportConf.SearchBatch >= total {
			break
		}
	}
	return deleteInstMap, newDeleteIds, nil
}

// 查找新增或更新的实例
func (s *instanceService) searchUpsertInstance(ctx context.Context, converter report_rule.Converter, objectConf *fintech_data.ReportObjectConf, reportTask *fintech_data.ReportTask, deleteInstMap map[string]*deleteInfo, newDeleteIds map[string]struct{}) ([]*fintech_data.ReportInstance, []*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	et, _ := timeutil.ParseTimeStr(reportTask.StartTime)
	queryList := []interface{}{
		map[string]interface{}{
			"_ts": map[string]interface{}{
				"$lt": et.Unix(),
			},
		},
	}
	stUnix := int64(0)
	if reportTask.LastReportTime != "" {
		st, _ := timeutil.ParseTimeStr(reportTask.LastReportTime)
		stUnix = st.Unix()
		queryList = append(queryList, map[string]interface{}{
			"_ts": map[string]interface{}{
				"$gte": stUnix,
			},
		})
	}
	query := map[string]interface{}{"$and": queryList}
	req := &instance.PostSearchV2Request{
		ObjectId: report_rule.GetSearchObjectId(objectConf),
		Query:    protostruct.ToStruct(query),
		Fields: protostruct.ToStruct(map[string]interface{}{
			"*":                   true,
			cmdbutil.ShowKeyLabel: true,
		}),
		PageSize: int32(s.reportConf.SearchBatch),
	}
	var insertList, updateList []*fintech_data.ReportInstance
	for page := 1; ; page++ {
		req.Page = int32(page)
		resp, err := s.instanceClient.PostSearchV2(ctx, req)
		if err != nil {
			logger.Errorf("%s search upsert instance fail, error: %s", objectConf.ObjectId, err.Error())
			return nil, nil, err
		}
		logger.Infof("search %s upsert instance success, page: %d, total: %d", objectConf.ObjectId, page, resp.Total)

		for _, inst := range resp.List {
			reportData := genReportInstance(inst, converter, reportTask, deleteInstMap, newDeleteIds, stUnix)
			if reportData == nil {
				continue
			} else if reportData.ReportType == report_center.ReportTypeNew {
				insertList = append(insertList, reportData)
			} else if reportData.ReportType == report_center.ReportTypeUpdate {
				updateList = append(updateList, reportData)
			}
		}

		if page*s.reportConf.SearchBatch >= int(resp.Total) {
			break
		}
	}
	return insertList, updateList, nil
}

func createBeforeSt(inst *pbtypes.Struct, st int64) bool {
	if st == 0 {
		return false
	}
	return getInstCtimeSt(inst) < st
}

func getInstCtimeSt(inst *pbtypes.Struct) int64 {
	ctime := inst.Fields["ctime"].GetStringValue()
	ct, _ := timeutil.ParseTimeStr(ctime)
	return ct.Unix()
}

func genReportInstance(inst *pbtypes.Struct, converter report_rule.Converter, reportTask *fintech_data.ReportTask, deleteInstMap map[string]*deleteInfo, newDeleteIds map[string]struct{}, stUnix int64) *fintech_data.ReportInstance {
	reportData := initReportInstance(reportTask, inst)
	instDescriptor := converter.GetFacilityDescriptor(reportData)
	reportData.FacilityDescriptor = instDescriptor
	// 判断实例是否在查询区间内创建的
	if createBeforeSt(inst, stUnix) {
		reportData.ReportType = report_center.ReportTypeUpdate
	} else {
		// 如果新增实例被删除过，则忽略新增
		if _, ok := newDeleteIds[reportData.InstanceId]; ok {
			return nil
		}
		reportData.ReportType = report_center.ReportTypeNew
	}

	if info, ok := deleteInstMap[instDescriptor]; ok {
		// 如果删除是在实例变更之后的，则忽略它.
		// 如果删除是在实例变更之前的，则为更新已删除的实例.
		if info.deleteTime > int32(reportData.Data.Fields["_ts"].GetNumberValue()) {
			return nil
		} else {
			delete(deleteInstMap, instDescriptor)
			reportData.ReportType = report_center.ReportTypeUpdate
		}
	}
	return reportData
}

func initReportInstance(reportTask *fintech_data.ReportTask, inst *pbtypes.Struct) *fintech_data.ReportInstance {
	return &fintech_data.ReportInstance{
		InstanceId: cmdbutil.GetInstanceId(inst),
		TaskId:     reportTask.TaskId,
		ObjectId:   reportTask.ObjectId,
		ShowKey:    cmdbutil.GetShowName(inst),
		Version:    int32(inst.Fields["_version"].GetNumberValue()),
		Data:       inst,
		Creator:    cmdbutil.GetCreator(inst),
	}
}

func (s *instanceService) loadExistInstance(ctx context.Context, queryKey string, ids []string) (map[string]*history.ReportMetaData, error) {
	fields := []string{"instanceId", report_center.KeyFacilityCategory, report_center.KeyFacilityDescriptor, "objectId", "dataId"}
	dataList, err := s.centerData.SearchAll(ctx, map[string]interface{}{queryKey: map[string][]string{"$in": ids}}, fields)
	if err != nil {
		return nil, err
	}
	dataMap := make(map[string]*history.ReportMetaData)
	for _, data := range dataList {
		pk := cast.ToString(data.ToMap()[queryKey])
		dataMap[pk] = data
	}
	return dataMap, nil
}

// 将要删除和更新的实例和已成功上报的数据比较
func (s *instanceService) compareWithExisted(ctx context.Context, converter report_rule.Converter, updateList []*fintech_data.ReportInstance, reportTask *fintech_data.ReportTask) ([]*fintech_data.ReportInstance, error) {
	logger := logctx.MustGetLogger(ctx)
	descriptors := make([]string, 0, len(updateList))
	for _, data := range updateList {
		descriptor := converter.GetFacilityDescriptor(data)
		descriptors = append(descriptors, descriptor)
	}

	if len(descriptors) == 0 {
		logger.Infof("%s task %s no update or delete data", reportTask.ObjectId, reportTask.TaskId)
		return nil, nil
	}

	existMap, err := s.loadExistInstance(ctx, report_center.KeyFacilityDescriptor, descriptors)
	if err != nil {
		return nil, err
	}

	resultList := make([]*fintech_data.ReportInstance, 0, len(updateList))
	for _, data := range updateList {
		// 若要更新的实例不存在已上报的实例中，则改为新增
		descriptor := converter.GetFacilityDescriptor(data)
		if _, ok := existMap[descriptor]; !ok {
			data.ReportType = report_center.ReportTypeNew
			logger.Infof("%s task %s instance %s(%s) no exists, set reportType as new", reportTask.ObjectId, reportTask.TaskId, data.ShowKey, data.InstanceId)
		}
		resultList = append(resultList, data)
	}
	return resultList, nil
}

// 查询需要重试的实例
func (s *instanceService) searchRetryInstance(ctx context.Context, converter report_rule.Converter, reportTask *fintech_data.ReportTask, reportList []*fintech_data.ReportInstance, deleteInstMap map[string]struct{}) ([]*fintech_data.ReportInstance, error) {
	st, et := timeutil.DefaultTimeLimit(s.nowTimeFunc, s.reportConf.TimeLimit)
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.LastTaskId),
		},
		{
			Name:     "retryable",
			Operator: "eq",
			Value:    protostruct.ToValue(true),
		},
	}
	retryList, err := s.taskHistory.SearchInstanceAll(ctx, query, nil, s.reportConf.SearchBatch, st, et)
	if err != nil {
		return nil, err
	}
	shouldRetry := make([]*fintech_data.ReportInstance, 0, len(retryList))
	retryIds := make(map[string]struct{})
	if len(retryList) > 0 {
		reportMap := make(map[string]struct{})
		for _, inst := range reportList {
			reportMap[inst.FacilityDescriptor] = struct{}{}
		}
		for _, inst := range retryList {
			// 重试的实例如果在这次有删除的实例中，则忽略
			_, ok1 := deleteInstMap[inst.InstanceId]
			_, ok2 := deleteInstMap[inst.FacilityDescriptor]
			if ok1 || ok2 {
				continue
			}
			// 重试的实例不在最新需上报的数据中，则进入上报队列
			if _, ok := reportMap[inst.FacilityDescriptor]; !ok {
				if _, found := retryIds[inst.FacilityDescriptor]; !found {
					// 重置基础信息
					retryIds[inst.FacilityDescriptor] = struct{}{}
					shouldRetry = append(shouldRetry, initRetryInst(converter, inst, reportTask.TaskId))
				}
			}
		}
	}
	return shouldRetry, nil
}

func initRetryInst(converter report_rule.Converter, inst *fintech_data.ReportInstance, taskId string) *fintech_data.ReportInstance {
	return &fintech_data.ReportInstance{
		InstanceId:         inst.InstanceId,
		TaskId:             taskId,
		ReportType:         inst.ReportType,
		ObjectId:           inst.ObjectId,
		Retryable:          false,
		RetryTimes:         inst.RetryTimes + 1,
		FacilityCategory:   inst.FacilityCategory,
		FacilityDescriptor: inst.FacilityDescriptor,
		ShowKey:            inst.ShowKey,
		Data:               inst.Data,
		Creator:            inst.Creator,
	}
}

func (s *instanceService) convertDeleteData(ctx context.Context, converter report_rule.Converter, reportTask *fintech_data.ReportTask, deleteInstMap map[string]*deleteInfo) []*fintech_data.ReportInstance {
	logger := logctx.MustGetLogger(ctx)
	deleteList := make([]*fintech_data.ReportInstance, 0, len(deleteInstMap))
	for _, info := range deleteInstMap {
		var data *pbtypes.Struct
		inst, err := s.taskHistory.GetInstance(ctx, info.data.DataId)
		if err != nil {
			data = protostruct.ToStruct(converter.RecoverReportInst(*info.data))
			logger.Warnf("task %s load delete data %s fail, error: %s", reportTask.TaskId, info.data.DataId, err.Error())
		} else {
			data = inst.Data
		}
		deleteList = append(deleteList, &fintech_data.ReportInstance{
			InstanceId:         info.data.InstanceId,
			TaskId:             reportTask.TaskId,
			ReportType:         report_center.ReportTypeDelete,
			ObjectId:           reportTask.ObjectId,
			FacilityCategory:   info.data.FacilityCategory,
			FacilityDescriptor: info.data.FacilityDescriptor,
			ShowKey:            info.name,
			Data:               data,
		})
	}
	return deleteList
}
