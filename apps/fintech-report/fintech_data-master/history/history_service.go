package history

import (
	"context"
	"go.easyops.local/fintech_data/internal/report_center"
	"strings"
	"time"

	"go.easyops.local/contracts/protorepo-cmdb/cmdb_object"
	message "go.easyops.local/contracts/protorepo-fintech_data/history"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/excelutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/types"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

// ensure implements
var _ HistoryService = (*historyService)(nil)

const (
	inOpr      = "in"
	ninOpr     = "nin"
	timeFormat = "2006-01-02 15:04:05"
)

func NewHistoryService(taskHistory history.TaskHistory, centerData history.CenterData, objClient cmdb_object.Client) *historyService {
	return &historyService{
		taskHistory:      taskHistory,
		centerData:       centerData,
		objClient:        objClient,
		nowTimeFunc:      timeutil.NowTime,
		newExcelExporter: excelutil.NewExporter,
	}
}

type historyService struct {
	taskHistory      history.TaskHistory
	centerData       history.CenterData
	objClient        cmdb_object.Client
	newExcelExporter excelutil.NewExporterFunc
	nowTimeFunc      func() time.Time
}

func (s *historyService) HandleReportInstance(ctx context.Context, request *message.HandlReportInstanceRequest) error {
	logger := logctx.MustGetLogger(ctx)
	var et, st int
	if len(request.DataId) > 0 {
		if request.Et != 0 {
			et = int(request.Et)
		} else {
			et = int(time.Now().Unix())
		}
		if request.St != 0 {
			st = int(request.St)
		} else {
			st = et - 86400
		}
		// 待更新字段
		updateData := &fintech_data.ReportInstance{
			HandleStatus: report_center.HandleStatusProcessed,
			HandleTime:   int32(time.Now().Unix()), // 处理时间设置为当前时间
		}
		updateFields := []string{"handleStatus", "handleTime"}
		instanceQuery := []*monthly_collection_service.QueryItem{
			{
				Name:     "_id",
				Operator: "in",
				Value:    protostruct.ToValue(request.DataId),
			},
		}
		err := s.taskHistory.UpdateInstanceByFilter(ctx, instanceQuery, updateData, updateFields, st, et)
		if err != nil {
			logger.Errorf("update instance handle status fail, error: %s", err.Error())
			return err
		}
	}
	return nil
}

func (s *historyService) GetReportTask(ctx context.Context, request *message.GetReportTaskRequest) (*fintech_data.ReportTask, error) {
	return s.taskHistory.GetTask(ctx, request.TaskId)
}

func (s *historyService) LastReportTask(ctx context.Context, request *message.LastReportTaskRequest) (*fintech_data.ReportTask, error) {
	var query []*monthly_collection_service.QueryItem
	if request.ObjectId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "objectId",
			Operator: "eq",
			Value:    protostruct.ToValue(request.ObjectId),
		})
	}
	if request.Status != "" {
		query = append(query, parseTaskStatusQuery(request.Status)...)
	}
	if request.HasReport {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "dataTotal",
			Operator: "ne",
			Value:    protostruct.ToValue(0),
		})
	}
	et := s.nowTimeFunc()
	st := et.AddDate(0, 0, -int(request.Days))
	return s.taskHistory.SearchOneTask(ctx, query, nil, int(st.Unix()), int(et.Unix()))
}

func (s *historyService) defaultEt(requestEt int) int {
	var et int
	if requestEt != 0 {
		et = requestEt
	} else {
		et = int(s.nowTimeFunc().Unix())
	}
	return et
}

func (s *historyService) SearchReportBranch(ctx context.Context, request *message.SearchReportBranchRequest) (*message.SearchReportBranchResponse, error) {
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(request.TaskId),
		},
	}
	if request.InnerId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "innerId",
			Operator: "eq",
			Value:    protostruct.ToValue(request.InnerId),
		})
	}
	if request.Status != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "totalStatus",
			Operator: inOpr,
			Value:    protostruct.ToValue(types.GetStatusByType(request.Status)),
		})
	}
	dataList, total, err := s.taskHistory.SearchBranch(ctx, query, protostruct.DecodeToMap(request.Fields), int(request.St), s.defaultEt(int(request.Et)), int(request.Page), int(request.PageSize))
	if err != nil {
		return nil, err
	}
	return &message.SearchReportBranchResponse{
		List:     dataList,
		Total:    int32(total),
		Page:     request.Page,
		PageSize: request.PageSize,
	}, nil
}

func (s *historyService) SearchReportInstance(ctx context.Context, request *message.SearchReportInstanceRequest) (*message.SearchReportInstanceResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	query := parseInstanceQuery(request.Search, request.ObjectId, request.ReportType, request.Status)

	if request.BranchId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "branchId",
			Operator: "eq",
			Value:    protostruct.ToValue(request.BranchId),
		})
	}
	// 待办处理人，如果管理员查看全部待办则置为空
	if request.Username != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "creator",
			Operator: "eq",
			Value:    protostruct.ToValue(request.Username),
		})
	}
	// 处理状态 待处理/已处理
	if request.HandleStatus != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "handleStatus",
			Operator: "eq",
			Value:    protostruct.ToValue(request.HandleStatus),
		})
	}
	if request.InnerBranchId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "innerBranchId",
			Operator: "eq",
			Value:    protostruct.ToValue(request.InnerBranchId),
		})
	}

	// 先通过mappingObjectId查出对应的任务，再通过任务查询实例
	var taskIdList []string
	var err error
	if request.MappingObjectId != "" {
		taskIdList, err = s.GetTaskIdList(ctx, request.MappingObjectId, int(request.St), s.defaultEt(int(request.Et)))
		if err != nil {
			logger.Errorf("GetTaskIdList failed, err: %v", err)
			return nil, err
		}
		if len(taskIdList) == 0 {
			// 意味着实例的mappingObjectId为请求里的mappingObjectId的实例数据没有，返回空
			return &message.SearchReportInstanceResponse{
				Total:    0,
				Page:     request.Page,
				PageSize: request.PageSize,
				List:     nil,
			}, nil
		}
	}
	if request.TaskId != "" {
		taskIdList = append(taskIdList, request.TaskId)
	}
	if len(taskIdList) > 0 {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "taskId",
			Operator: "in",
			Value:    protostruct.ToValue(taskIdList),
		})
	}

	dataList, total, err := s.taskHistory.SearchInstance(ctx, query, protostruct.DecodeToMap(request.Fields), int(request.St), s.defaultEt(int(request.Et)), int(request.Page), int(request.PageSize))
	if err != nil {
		return nil, err
	}
	return &message.SearchReportInstanceResponse{
		List:     dataList,
		Total:    int32(total),
		Page:     request.Page,
		PageSize: request.PageSize,
	}, nil
}

func getStatus(statusStr string) []string {
	if statusStr == "" {
		return nil
	}
	// 实例为失败，有3种
	if statusStr == "fail" {
		return []string{types.FailTypeReporting, types.FailTypeRequestCheck, types.FailTypeResult}
	}
	// 实例为执行中
	if statusStr == "running" {
		return []string{types.StatusPendingCheck, types.StatusResulting}
	}
	return []string{statusStr}
}

func parseStatusQuery(status string) (string, []string) {
	var opr string
	if strings.HasPrefix(status, "!") {
		opr = ninOpr
		status = strings.ReplaceAll(status, "!", "")
	} else {
		opr = inOpr
	}
	statusList := types.GetStatusByType(status)
	return opr, statusList
}

func parseTaskStatusQuery(statusStr string) []*monthly_collection_service.QueryItem {
	var query []*monthly_collection_service.QueryItem
	statusList := strings.Split(statusStr, ",")
	var inStatus, ninStatus []string
	for _, item := range statusList {
		opr, status := parseStatusQuery(item)
		if opr == inOpr {
			inStatus = append(inStatus, status...)
		} else {
			ninStatus = append(ninStatus, status...)
		}
	}
	if len(inStatus) > 0 {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "status",
			Operator: inOpr,
			Value:    protostruct.ToValue(inStatus),
		})
	}
	if len(ninStatus) > 0 {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "status",
			Operator: ninOpr,
			Value:    protostruct.ToValue(ninStatus),
		})
	}
	return query
}

func parseQuery(objectId string, mappingObjectId string, status string, method string) []*monthly_collection_service.QueryItem {
	var query []*monthly_collection_service.QueryItem
	if status != "" {
		query = append(query, parseTaskStatusQuery(status)...)
	}
	if method != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "method",
			Operator: "eq",
			Value:    protostruct.ToValue(method),
		})
	}
	if objectId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "objectId",
			Operator: "eq",
			Value:    protostruct.ToValue(objectId),
		})
	}
	if mappingObjectId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "mappingObjectId",
			Operator: "eq",
			Value:    protostruct.ToValue(mappingObjectId),
		})
	}
	return query
}

func (s *historyService) SearchReportTask(ctx context.Context, request *message.SearchReportTaskRequest) (*message.SearchReportTaskResponse, error) {
	query := parseQuery(request.ObjectId, request.MappingObjectId, request.Status, request.Method)
	var st, et int
	et = s.defaultEt(int(request.Et))
	if request.St != 0 {
		st = int(request.St)
	} else {
		st = et - 3600*24
	}
	dataList, total, err := s.taskHistory.SearchTask(ctx, query, protostruct.DecodeToMap(request.Fields), st, et, int(request.Page), int(request.PageSize))
	if err != nil {
		return nil, err
	}
	return &message.SearchReportTaskResponse{
		List:     dataList,
		Total:    int32(total),
		Page:     request.Page,
		PageSize: request.PageSize,
	}, nil
}

func (s *historyService) GetReportInstanceTotal(ctx context.Context, request *message.GetReportInstanceTotalRequest) (*message.GetReportInstanceTotalResponse, error) {
	query := make(map[string]interface{})
	if request.ObjectIds != "" {
		query["objectId"] = map[string]interface{}{
			"$in": strings.Split(request.ObjectIds, ","),
		}
	}
	total, err := s.centerData.Count(ctx, query)
	if err != nil {
		return nil, err
	}
	return &message.GetReportInstanceTotalResponse{Total: int32(total)}, nil
}

func getTaskExcelHeader() []excelutil.HeaderCell {
	return []excelutil.HeaderCell{
		{
			Name: "上报时间",
			Id:   "time",
		},
		{
			Name: "采集接口",
			Id:   "objectName",
		},
		{
			Name: "映射模型",
			Id:   "mappingObjectName",
		},
		{
			Name: "上报数量",
			Id:   "total",
		},
		{
			Name: "上报成功",
			Id:   "successTotal",
		},
		{
			Name: "新增成功",
			Id:   "inserted",
		},
		{
			Name: "更新成功",
			Id:   "updated",
		},
		{
			Name: "删除成功",
			Id:   "removed",
		},
		{
			Name: "上报成功率",
			Id:   "successRate",
		},
		{
			Name: "批次数量",
			Id:   "batchTotal",
		},
		{
			Name: "批次ID",
			Id:   "branchIds",
		},
		{
			Name: "执行类型",
			Id:   "trigger",
		},
		{
			Name: "执行用户",
			Id:   "execUser",
		},
		{
			Name: "任务状态",
			Id:   "status",
		},
	}
}

func getInstanceExcelHeader(isHandle bool) []excelutil.HeaderCell {
	header := []excelutil.HeaderCell{
		{
			Name: "设施名称",
			Id:   "showKey",
		},
		{
			Name: "采集接口",
			Id:   "objectName",
		},
		{
			Name: "映射模型",
			Id:   "mappingObjectName",
		},
		{
			Name: "数据元分类标识符",
			Id:   "facilityCategory",
		},
		{
			Name: "数据元设施标识符",
			Id:   "facilityDescriptor",
		},
		{
			Name: "上报类型",
			Id:   "reportType",
		},
		{
			Name: "状态",
			Id:   "status",
		},
		{
			Name: "详细信息",
			Id:   "msg",
		},
	}
	if isHandle { // 判断是否为导出待处理实例
		extraColumns := []excelutil.HeaderCell{
			{
				Name: "上报时间",
				Id:   "ts",
			},
			{
				Name: "负责人",
				Id:   "creator",
			},
		}
		header = append(header, extraColumns...)
	}
	return header
}

func (s *historyService) ExportReportTask(ctx context.Context, request *message.ExportReportTaskRequest) (types.FileExporter, error) {
	logger := logctx.MustGetLogger(ctx)
	query := parseQuery(request.ObjectId, request.MappingObjectId, request.Status, request.Method)
	var st, et int
	et = s.defaultEt(int(request.Et))
	if request.St != 0 {
		st = int(request.St)
	} else {
		st = et - 3600*24
	}
	dataList, err := s.taskHistory.SearchAllTask(ctx, query, protostruct.DecodeToMap(request.Fields), 10000, st, et)
	if err != nil {
		logger.Errorf("search all task fail, error: %s", err.Error())
		return nil, err
	}

	objIdName, err := s.objClient.GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{})
	if err != nil {
		logger.Errorf("get objectId and name map fail, error: %s", err.Error())
		return nil, err
	}

	exporter := s.newExcelExporter("上报历史")
	if err := exporter.WriteExcelHeader(getTaskExcelHeader()); err != nil {
		logger.Errorf("write header fail, error: %s", err.Error())
		return nil, err
	}
	for _, task := range dataList {
		var trigger string
		if task.Method == "timer" {
			trigger = "定时执行"
		} else {
			trigger = "手动执行"
		}

		mappingObjectName := ""
		if task.MappingObjectId != "" {
			if v, ok := objIdName.Fields[task.MappingObjectId]; ok {
				mappingObjectName = v.GetStringValue()
			} else {
				mappingObjectName = "已删除模型"
			}
		}
		value := map[string]interface{}{
			"time":              task.StartTime,
			"objectName":        objIdName.Fields[task.ObjectId].GetStringValue(),
			"mappingObjectName": mappingObjectName,
			"total":             task.DataTotal,
			"successTotal":      task.SuccessTotal,
			"inserted":          task.Inserted,
			"updated":           task.Updated,
			"removed":           task.Removed,
			"successRate":       excelutil.FloatToRateStr(task.SuccessRate),
			"batchTotal":        task.BatchTotal,
			"branchIds":         strings.Join(task.BranchIds, ","),
			"trigger":           trigger,
			"execUser":          task.Sponsor,
			"status":            types.ConvertStatus(task.Status),
		}
		if err := exporter.WriteRow(value); err != nil {
			logger.Errorf("write row fail, error: %s", err.Error())
			return nil, err
		}
	}
	return exporter, nil
}

func parseInstanceQuery(search string, objectId string, reportType string, status string) []*monthly_collection_service.QueryItem {
	var query []*monthly_collection_service.QueryItem
	// 搜索框输入有值，目前只是对showKey进行模糊搜索
	if search != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "showKey",
			Operator: "regex",
			Value:    protostruct.ToValue(search),
		})

		// 忽略大小写
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "showKey",
			Operator: "options",
			Value:    protostruct.ToValue("$i"),
		})
	}
	// 模型
	if objectId != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "objectId",
			Operator: "eq",
			Value:    protostruct.ToValue(objectId),
		})
	}
	// 上报类型
	if reportType != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "reportType",
			Operator: "eq",
			Value:    protostruct.ToValue(reportType),
		})
	}
	// 获取状态
	statusList := getStatus(status)
	if statusList != nil {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "status",
			Operator: "in",
			Value:    protostruct.ToValue(statusList),
		})
	}
	return query
}

func (s *historyService) GetTaskIdList(ctx context.Context, mappingObjectId string, st int, et int) ([]string, error) {
	logger := logctx.MustGetLogger(ctx)
	var queryTask []*monthly_collection_service.QueryItem
	queryTask = append(queryTask, &monthly_collection_service.QueryItem{
		Name:     "mappingObjectId",
		Operator: "eq",
		Value:    protostruct.ToValue(mappingObjectId),
	})
	dataList, err := s.taskHistory.SearchAllTask(ctx, queryTask, map[string]interface{}{
		"_id": true,
	}, 10000, st, et)
	if err != nil {
		logger.Errorf("search all task fail, error: %s", err.Error())
		return nil, err
	}
	if len(dataList) == 0 {
		// 意味着实例的mappingObjectId为请求里的mappingObjectId的实例数据没有，返回空
		return nil, nil
	}
	var taskIdList []string
	for _, data := range dataList {
		taskIdList = append(taskIdList, data.TaskId)
	}
	return taskIdList, nil
}

func (s *historyService) ExportReportInstance(ctx context.Context, request *message.ExportReportInstanceRequest) (types.FileExporter, error) {
	logger := logctx.MustGetLogger(ctx)
	exporter := s.newExcelExporter("上报历史")
	isHandle := false               // 自定义表格列，false 导出全部实例 true 导出待处理实例
	if request.HandleStatus == report_center.HandleStatusPending { // 判断是否为导出未处理待办
		isHandle = true
	}
	if err := exporter.WriteExcelHeader(getInstanceExcelHeader(isHandle)); err != nil {
		logger.Errorf("write header fail, error: %s", err.Error())
		return nil, err
	}

	var st, et int
	et = s.defaultEt(int(request.Et))
	if request.St != 0 {
		st = int(request.St)
	} else {
		st = et - 3600*24
	}
	query := parseInstanceQuery(request.Search, request.ObjectId, request.ReportType, request.Status)
	// 选中实例
	if len(request.DataId) > 0 {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "_id",
			Operator: "in",
			Value:    protostruct.ToValue(request.DataId),
		})
	}
	if request.Username != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "creator",
			Operator: "eq",
			Value:    protostruct.ToValue(request.Username),
		})
	}
	if request.HandleStatus != "" {
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "handleStatus",
			Operator: "eq",
			Value:    protostruct.ToValue(request.HandleStatus),
		})
	}
	// 先通过mappingObjectId查出对应的任务，再通过任务查询实例
	if request.MappingObjectId != "" {
		taskIdList, err := s.GetTaskIdList(ctx, request.MappingObjectId, st, et)
		if err != nil {
			logger.Errorf("GetTaskIdList failed, err: %v", err)
			return nil, err
		}
		if len(taskIdList) == 0 {
			return exporter, nil
		}
		query = append(query, &monthly_collection_service.QueryItem{
			Name:     "taskId",
			Operator: "in",
			Value:    protostruct.ToValue(taskIdList),
		})
	}

	dataList, err := s.taskHistory.SearchInstanceAll(ctx, query, protostruct.DecodeToMap(request.Fields), 10000, st, et)
	if err != nil {
		logger.Errorf("search all task fail, error: %s", err.Error())
		return nil, err
	}

	// 获取 MappingObjectId 和 MappingObjectName 的映射关系
	objIdName, err := s.objClient.GetIdMapName(ctx, &cmdb_object.GetIdMapNameRequest{})
	if err != nil {
		logger.Errorf("get objectId and name map fail, error: %s", err.Error())
		return nil, err
	}

	for _, instance := range dataList {
		mappingObjectName := ""
		if instance.MappingObjectId != "" {
			if v, ok := objIdName.Fields[instance.MappingObjectId]; ok {
				mappingObjectName = v.GetStringValue()
			} else {
				mappingObjectName = "已删除模型"
			}
		}
		value := map[string]interface{}{
			"showKey":            instance.ShowKey,
			"objectName":         objIdName.Fields[instance.ObjectId].GetStringValue(),
			"mappingObjectName":  mappingObjectName,
			"facilityCategory":   instance.FacilityCategory,
			"facilityDescriptor": instance.FacilityDescriptor,
			"reportType":         report_center.ConvertReportType(instance.ReportType),
			"status":             types.ConvertInstanceStatus(instance.Status),
			"msg":                instance.Msg,
		}
		if isHandle {
			value["ts"] = time.Unix(int64(instance.Ts), 0).Format(timeFormat) // 上报时间
			value["creator"] = instance.Creator                               // 实例创建人 待办负责人
		}

		if err := exporter.WriteRow(value); err != nil {
			logger.Errorf("write row fail, error: %s", err.Error())
			return nil, err
		}
	}
	return exporter, nil
}
