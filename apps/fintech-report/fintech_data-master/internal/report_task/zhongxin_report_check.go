package report_task

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/go-redis/redis/v8"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/arrayutil"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/types"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

func NewZhongXinChecker(redisClient redis.UniversalClient, reportCenter report_center.Service, taskHistory history.TaskHistory, centerData history.CenterData, objStat history.ObjectStat, historyRecorder history.Recorder, reportConf config.ReportConf, mongoClient pmongo.ClientInterface, newLockFunc types.NewLockFunc) ReportChecker {
	return &zhongXinChecker{
		redisClient:     redisClient,
		newLockFunc:     newLockFunc,
		reportCenter:    reportCenter,
		taskHistory:     taskHistory,
		centerData:      centerData,
		objStat:         objStat,
		historyRecorder: historyRecorder,
		timeNowFunc:     timeutil.NowTime,
		reportConf:      reportConf,
		mongoClient:     mongoClient,
	}
}

type zhongXinChecker struct {
	newLockFunc     types.NewLockFunc
	redisClient     redis.UniversalClient
	reportCenter    report_center.Service
	taskHistory     history.TaskHistory
	centerData      history.CenterData
	objStat         history.ObjectStat
	historyRecorder history.Recorder
	timeNowFunc     timeutil.NowTimeFunc
	reportConf      config.ReportConf
	mongoClient     pmongo.ClientInterface
}

func (c *zhongXinChecker) TaskCheck(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig) error {
	logger := logctx.MustGetLogger(ctx)

	// 重新查一次任务详情，以最新的任务状态为准
	task, err := c.taskHistory.GetTask(ctx, reportTask.TaskId)
	if err != nil {
		logger.Errorf("get task %s fail", reportTask.TaskId)
		return err
	}
	if task.Status == types.StatusResulting || task.Status == types.StatusPendingCheck {
		return c.taskResultCheck(ctx, task, globalConf)
	}
	logger.Infof("task %s status is not resulting", reportTask.TaskId)
	return nil
}

// 查询出此任务上报成功的实例
func getTaskInstanceQuery(reportTask *fintech_data.ReportTask) []*monthly_model.QueryItem {
	query := []*monthly_model.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.TaskId),
		},
		{
			Name:     "status",
			Operator: "eq",
			Value:    protostruct.ToValue(types.StatusResulting),
		},
		{
			Name:     "branchId",
			Operator: "eq",
			Value:    protostruct.ToValue(""),
		},
	}
	return query
}

// 查询出此任务上报成功且获取到了外部批次id的实例
func getTaskInstanceQueryWithBranchIdCondition(reportTask *fintech_data.ReportTask) []*monthly_model.QueryItem {
	query := []*monthly_model.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.TaskId),
		},
		{
			Name:     "status",
			Operator: "eq",
			Value:    protostruct.ToValue(types.StatusResulting),
		},
		{
			Name:     "branchId",
			Operator: "ne",
			Value:    protostruct.ToValue(""),
		},
	}
	return query
}

func (c *zhongXinChecker) taskResultCheck(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig) error {
	st, et := GetTaskTimeLimit(reportTask, c.timeNowFunc)
	// 1. 更新实例的批次id
	err := c.updateInstanceBranchId(ctx, reportTask, globalConf, st, et)
	if err != nil {
		return err
	}

	// 2. 处理实例的检核结果
	reportCount := &history.ReportCount{}
	err = c.dealWithInstanceCheckResult(ctx, reportTask, globalConf, reportCount, st, et)
	if err != nil {
		return err
	}

	// 3. 全部实例处理完成后，根据所有实例的状态来更新批次的状态
	warning, err := c.updateBranchResult(ctx, reportTask, st, et)
	if err != nil {
		return err
	}

	// 4. 更新任务结果
	return c.updateTaskResult(ctx, reportTask, reportCount, warning)
}

// 更新实例的批次id
func (c *zhongXinChecker) updateInstanceBranchId(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig, st int, et int) error {
	logger := logctx.MustGetLogger(ctx)

	// 中信国际上报给中信总行那边是按批次上报的，但是中信总行会将这些实例数据按照500个分成一组上报给人行，这500条数据在一个批次里
	// 1. 先查询出实例 2.根据上报数据元实例设施标识符查询出批次的的id  3.再将实例的branchId更新
	instanceQuery := getTaskInstanceQuery(reportTask)
	fields := map[string]interface{}{
		"_id":                true,
		"facilityDescriptor": true,
	}
	var nextId string
	var instanceList []*fintech_data.ReportInstance
	// 查询出所有实例
	for {
		res, err := c.taskHistory.SearchInstanceLimit(ctx, instanceQuery, fields, c.reportConf.SearchBatch, st, et, nextId)
		if err != nil {
			logger.Errorf("task %s search instance fail, nextId: %s, error: %s", reportTask.TaskId, nextId, err.Error())
			return err
		}
		nextId = res.NextId
		instanceList = append(instanceList, res.InstanceList...)
		if !res.HasMore {
			break
		}
	}
	// 没有正在执行中的实例，那么直接返回，不需要查询批次id
	if len(instanceList) == 0 {
		return nil
	}
	var facilityDescriptorList []string
	for _, instance := range instanceList {
		facilityDescriptorList = append(facilityDescriptorList, instance.FacilityDescriptor)
	}
	branchIdRequest := report_center.BranchIdRequest{
		DataType: getReportDataType(reportTask.ObjectId),
		DataList: facilityDescriptorList,
	}

	branchIdResp, err := c.reportCenter.SelectBranchId(ctx, branchIdRequest, globalConf)
	// 调用接口错误
	if err != nil {
		logger.Errorf("调用接口 search task %s instance branchId fail, error: %s", reportTask.TaskId, err.Error())
		return err
	}
	// 调用接口成功，但是返回错误码
	if branchIdResp.Code == report_center.ZhongXinCodeReportFail {
		logger.Errorf("search task %s instance branchId fail, error: %s", branchIdResp.Msg)
		return fmt.Errorf("search task %s instance branchId fail, error: %s", reportTask.TaskId, branchIdResp.Msg)
	}

	// 更新实例和批次对应的branchId
	branchIdRespList, err := convertBranchIdResponse(branchIdResp.Data)
	if err != nil {
		logger.Errorf("convertBranchIdResponse fail, error: %s", err.Error())
		return err
	}

	// facilityDescriptor与branchId的map映射
	facilityBranchIdMap := make(map[string]string)
	for _, branchData := range branchIdRespList {
		facilityBranchIdMap[branchData.FacilityDescriptor] = branchData.BranchId
	}

	for _, instance := range instanceList {
		instance.BranchId = facilityBranchIdMap[instance.FacilityDescriptor]
		// 更新实例
		err = c.taskHistory.UpdateInstance(ctx, instance.DataId, instance, []string{"branchId"})
		if err != nil {
			logger.Errorf("task %s update instance branchId fail, error: %s", err.Error())
			return err
		}
	}
	return nil
}

func (c *zhongXinChecker) dealWithInstanceCheckResult(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig, reportCount *history.ReportCount, st int, et int) error {
	logger := logctx.MustGetLogger(ctx)
	// 查出当前任务所有未完成的批次
	query := getTaskInstanceQueryWithBranchIdCondition(reportTask)
	fields := map[string]interface{}{
		"data":    false,
		"showKey": false,
	}
	var nextId string
	var instanceList []*fintech_data.ReportInstance
	// 查询出所有实例
	for {
		res, err := c.taskHistory.SearchInstanceLimit(ctx, query, fields, c.reportConf.SearchBatch, st, et, nextId)
		if err != nil {
			logger.Errorf("task %s search instance fail, nextId: %s, error: %s", reportTask.TaskId, nextId, err.Error())
			return err
		}
		nextId = res.NextId
		instanceList = append(instanceList, res.InstanceList...)
		if !res.HasMore {
			break
		}
	}

	// 根据实例对相同外部批次id的实例分组，然后获取实例的检核结果，先更新实例，在完成所有实例的更新之后，按照innerBranchId去更新批次的状态
	branchIdInstanceMap := make(map[string][]*fintech_data.ReportInstance)
	for _, instance := range instanceList {
		_, ok := branchIdInstanceMap[instance.BranchId]
		if !ok {
			branchIdInstanceMap[instance.BranchId] = make([]*fintech_data.ReportInstance, 0, len(instanceList))
		}
		branchIdInstanceMap[instance.BranchId] = append(branchIdInstanceMap[instance.BranchId], instance)
	}

	// 逐个批次查询结果, 并更新上报实例结果
	for branchId, instanceList := range branchIdInstanceMap {
		//查询批次的实例的检核结果
		batchStatics := &batchCountStatics{}
		err := c.instanceResultCheck(ctx, reportTask, branchId, globalConf, instanceList, batchStatics)
		if err != nil {
			return err
		}
		reportCount.Inserted += batchStatics.Inserted
		reportCount.Removed += batchStatics.Removed
		reportCount.Updated += batchStatics.Updated
		reportCount.Failed += batchStatics.Failed

		// 更新任务变更成功数量
		reportTask.Inserted += int32(batchStatics.Inserted)
		reportTask.Updated += int32(batchStatics.Updated)
		reportTask.Removed += int32(batchStatics.Removed)
	}
	return nil
}

func (c *zhongXinChecker) updateTaskResult(ctx context.Context, reportTask *fintech_data.ReportTask, reportCount *history.ReportCount, warning bool) error {
	logger := logctx.MustGetLogger(ctx)
	if reportTask.DataTotal == (reportTask.SuccessTotal + reportTask.FailTotal) {
		reportTask.EndTime = c.timeNowFunc().Format(timeutil.TimeFormat)
		parseTaskReportStatus(reportTask, warning)
	}

	//加锁
	locker := c.newLockFunc(c.redisClient, fmt.Sprintf("%s%s", types.TaskLockPrefix, reportTask.TaskId), 60)
	locker.Lock()
	defer locker.Unlock()
	// 更新任务总体结果
	err := c.taskHistory.UpdateTask(ctx, reportTask.TaskId, reportTask)
	if err != nil {
		logger.Errorf("update task %s fail, error: %s", reportTask.TaskId, err.Error())
		return err
	}
	logger.Infof("update task %s success, status: %s", reportTask.TaskId, reportTask.Status)

	// 记录任务结果
	if reportCount.IsEffective() && reportTask.EndTime != "" {
		if err = c.saveReportHistory(ctx, reportCount, reportTask); err != nil {
			logger.Errorf("save task %s report result fail, error: %s", reportTask.TaskId, err.Error())
		}
		if err = c.updateObjectStat(ctx, reportCount, reportTask); err != nil {
			logger.Errorf("update object %s stat fail, taskId: %s, error: %s", reportTask.ObjectId, reportTask.TaskId, err.Error())
		}
	}
	return nil
}

// 单个批次结果检查
func (c *zhongXinChecker) instanceResultCheck(ctx context.Context, reportTask *fintech_data.ReportTask, branchId string, globalConf *fintech_data.ReportGlobalConfig, instanceList []*fintech_data.ReportInstance, batchCount *batchCountStatics) error {
	logger := logctx.MustGetLogger(ctx)

	// 获取批次结果
	checkReq := report_center.CheckRequest{BranchId: branchId}
	checkResp, err := c.reportCenter.CheckReportResult(ctx, checkReq, globalConf)
	if err != nil {
		logger.Errorf("task %s check branch %s fail, error: %s", reportTask.TaskId, branchId, err.Error())
		return err
	}
	logger.Infof("check report result finished")
	// 解析批次结果, 根据结果先更新实例
	err = c.updateInstanceResult(ctx, reportTask, checkResp, instanceList, batchCount)
	if err != nil {
		logger.Errorf("task %s update branch %s instance fail, error: %s", reportTask.TaskId, branchId, err.Error())
		return err
	}
	return nil
}

func (c *zhongXinChecker) updateInstanceResult(ctx context.Context, reportTask *fintech_data.ReportTask, checkResp *report_center.CheckResponse, instanceList []*fintech_data.ReportInstance, batchCount *batchCountStatics) error {
	logger := logctx.MustGetLogger(ctx)
	instanceMap := make(map[string]report_center.CheckData)
	for _, inst := range checkResp.Data {
		instanceMap[inst.FacilityDescriptor] = inst
	}

	logger.Infof("updateInstance  len: %s", len(instanceList))
	// 数据处理中或者保存成功则无需更新
	if arrayutil.InArray([]string{report_center.CodeHandling, report_center.CodeSaveSuccess}, checkResp.Code) {
		return nil
	}

	failRespCode := []string{report_center.CodeDataHasFail, report_center.CodeHandleFail, report_center.CodeAgencyIsDiff,
		report_center.CodeBranchIdNoExist, report_center.CodeBranchIdIsEmpty, report_center.CodeCompressFail,
		report_center.CodeDataIsEmpty}

	var allFail bool
	if arrayutil.InArray(failRespCode, checkResp.Code) && len(checkResp.Data) == 0 {
		// 该批次是否所有数据失败
		allFail = true
	}
	commonFailData := report_center.CheckData{Code: report_center.CodeDataHandleFail, Msg: checkResp.Msg}
	nowTs := int32(c.timeNowFunc().Unix())
	var upsertList, removeList []*history.ReportMetaData
	for _, inst := range instanceList {
		key := inst.FacilityDescriptor
		inst.Ts = nowTs

		instRes, ok := instanceMap[key]
		if !ok && allFail {
			instRes = commonFailData
		}
		// 如果 instRes 为nil，表示成功并且
		if err := c.saveInstResult(ctx, instRes, inst); err != nil {
			logger.Errorf("task %s update instance %s fail, error: %s", reportTask.TaskId, inst.InstanceId, err.Error())
			return err
		}

		if instRes.Code != report_center.CodeDataInValid && instRes.Code != report_center.CodeDataHandleFail {
			instMeta := initReportMetaData(inst)
			if inst.ReportType == report_center.ReportTypeDelete {
				batchCount.Removed += 1
				removeList = append(removeList, instMeta)
			} else {
				if inst.ReportType == report_center.ReportTypeNew {
					batchCount.Inserted += 1
				} else {
					batchCount.Updated += 1
				}
				upsertList = append(upsertList, instMeta)
			}
		} else {
			// 统计此批次失败的实例数量
			batchCount.Failed += 1
		}
	}

	// 更新已上报实例
	if len(upsertList) > 0 {
		_, err := c.centerData.Upsert(ctx, upsertList...)
		if err != nil {
			logger.Errorf("task %s upsert report data fail, error: %s", reportTask.TaskId, err.Error())
			return err
		}
	}
	// 删除已上报实例
	if len(removeList) > 0 {
		err := c.centerData.RemoveAll(ctx, removeList...)
		if err != nil {
			logger.Errorf("task %s remove report data fail, error: %s", reportTask.TaskId, err.Error())
			return err
		}
	}

	logger.Infof("task %s handle instance success, upsert total: %d, remove total: %d", reportTask.TaskId, len(upsertList), len(removeList))
	return nil
}

func convertBranchIdResponse(resp interface{}) ([]*report_center.BranchIdData, error) {
	responseList, ok := resp.([]interface{})
	if !ok {
		return nil, fmt.Errorf("response data not is slice")
	}
	var list []*report_center.BranchIdData
	for _, val := range responseList {
		r := &report_center.BranchIdData{}
		data, err := json.Marshal(val)
		if err != nil {
			return nil, err
		}
		err = json.Unmarshal(data, r)
		if err != nil {
			return nil, err
		}
		list = append(list, r)
	}
	return list, nil
}

// 解析并更新实例结果
func (c *zhongXinChecker) saveInstResult(ctx context.Context, instRes report_center.CheckData, reportInst *fintech_data.ReportInstance) error {
	reportInst.Code = instRes.Code
	reportInst.Msg = instRes.Msg
	status := types.StatusSuccess
	switch instRes.Code {
	case report_center.CodeDataInValid, report_center.CodeDataHandleFail:
		if instRes.Code == report_center.CodeDataHandleFail || c.reportConf.ForceRetry {
			reportInst.Retryable = true
		}
		reportInst.IsFail = true
		status = types.FailTypeResult
	case report_center.CodeDataValidWithWarning:
		status = types.StatusWithWarn
	}
	reportInst.Status = status
	return c.taskHistory.UpdateInstance(ctx, reportInst.DataId, reportInst, []string{"code", "msg", "isFail", "status", "retryable"})
}

func (c *zhongXinChecker) updateBranchResult(ctx context.Context, reportTask *fintech_data.ReportTask, st int, et int) (bool, error) {
	logger := logctx.MustGetLogger(ctx)
	query := []*monthly_model.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.TaskId),
		},
	}
	branchList, err := c.taskHistory.SearchAllBranch(ctx, query, nil, 5000, st, et)
	if err != nil {
		logger.Errorf("task %s search branch fail error: %s", reportTask.TaskId, err.Error())
		return false, err
	}

	warning := false
	// 先将任务的失败和成功数置为0,避免不一致导致任务无法结束
	reportTask.FailTotal = 0
	reportTask.SuccessTotal = 0
	for _, branch := range branchList {
		queryInstance := []*monthly_model.QueryItem{
			{
				Name:     "taskId",
				Operator: "eq",
				Value:    protostruct.ToValue(reportTask.TaskId),
			},
			{
				Name:     "innerBranchId",
				Operator: "eq",
				Value:    protostruct.ToValue(branch.InnerId),
			},
		}
		fields := map[string]interface{}{
			"data":    false,
			"showKey": false,
		}
		var nextId string
		var instanceList []*fintech_data.ReportInstance
		// 查询出所有实例
		for {
			res, err := c.taskHistory.SearchInstanceLimit(ctx, queryInstance, fields, c.reportConf.SearchBatch, st, et, nextId)
			if err != nil {
				logger.Errorf("task %s search instance fail, nextId: %s, error: %s", reportTask.TaskId, nextId, err.Error())
				return false, err
			}
			nextId = res.NextId
			instanceList = append(instanceList, res.InstanceList...)
			if !res.HasMore {
				break
			}
		}

		// 更新批次的状态
		updateBranchStatus(branch, instanceList)
		if types.IsEndStatus(branch.TotalStatus) {
			if branch.TotalStatus == types.StatusWithWarn {
				warning = true
			}
			reportTask.FailTotal += branch.FailTotal
			reportTask.SuccessTotal += branch.SuccessTotal
		}
		err = c.taskHistory.UpdateBranch(ctx, branch.InnerId, branch, []string{"successTotal", "failTotal", "checkStatus", "totalStatus"})
		if err != nil {
			logger.Errorf("task %s update branch %s status fail, error: %s", reportTask.TaskId, branch.InnerId, err.Error())
			return false, err
		}
	}
	return warning, nil
}

func updateBranchStatus(branch *fintech_data.ReportBranch, instanceList []*fintech_data.ReportInstance) {
	// 批次在上报阶段就失败了，那么此批次无需更改
	if branch.ReportStatus == types.StatusFail || branch.ReportStatus == types.StatusReporting {
		if branch.ReportStatus == types.StatusFail {
			branch.FailTotal = branch.DataTotal
		}
		return
	}

	var successCount int
	var failCount int

	var instanceStatusList []string
	for _, instance := range instanceList {
		if instance.Status != "" && !arrayutil.InArray(instanceStatusList, instance.Status) {
			instanceStatusList = append(instanceStatusList, instance.Status)
		}
		if arrayutil.InArray([]string{types.FailTypeReporting, types.FailTypeResult}, instance.Status) {
			failCount += 1
		}

		if arrayutil.InArray([]string{types.StatusSuccess, types.StatusWithWarn}, instance.Status) {
			successCount += 1
		}
	}
	branch.SuccessTotal = int32(successCount)
	branch.FailTotal = int32(failCount)

	// 去重
	instanceStatusList = arrayutil.ArraySet(instanceStatusList)
	// 只要有一个实例的状态在执行中，那么此批次的状态就是执行中
	if arrayutil.InArray(instanceStatusList, types.StatusResulting) {
		branch.CheckStatus = types.StatusResulting
		branch.TotalStatus = types.StatusResulting
		return
	}

	// （检核或者上报阶段）失败+成功 || 警告+ 失败+成功 || 警告 + 失败 ==》 部分成功
	if (isContainFailStatus(instanceStatusList) && arrayutil.InArray(instanceStatusList, types.StatusSuccess)) ||
		(isContainFailStatus(instanceStatusList) && arrayutil.InArray(instanceStatusList, types.StatusWithWarn)) {
		branch.CheckStatus = types.StatusPartialSuccess
		branch.TotalStatus = types.StatusPartialSuccess
		return
	}

	// 警告+成功 || 警告+警告 ==> 警告
	if (arrayutil.InArray(instanceStatusList, types.StatusWithWarn) && arrayutil.InArray(instanceStatusList, types.StatusSuccess) && !isContainFailStatus(instanceStatusList)) ||
		(arrayutil.InArray(instanceStatusList, types.StatusWithWarn) && !arrayutil.InArray(instanceStatusList, types.StatusSuccess) && !isContainFailStatus(instanceStatusList)) {
		branch.CheckStatus = types.StatusWithWarn
		branch.TotalStatus = types.StatusWithWarn
		return
	}

	// 成功+成功 ==> 成功
	if arrayutil.InArray(instanceStatusList, types.StatusSuccess) && !arrayutil.InArray(instanceStatusList, types.StatusWithWarn) && !isContainFailStatus(instanceStatusList) {
		branch.CheckStatus = types.StatusSuccess
		branch.TotalStatus = types.StatusSuccess
		return
	}

	// 失败+失败 ==> 失败
	if !arrayutil.InArray(instanceStatusList, types.StatusSuccess) && !arrayutil.InArray(instanceStatusList, types.StatusWithWarn) && isContainFailStatus(instanceStatusList) {
		branch.CheckStatus = types.StatusFail
		branch.TotalStatus = types.StatusFail
		return
	}
}

func isContainFailStatus(instanceStatusList []string) bool {
	if arrayutil.InArray(instanceStatusList, types.FailTypeReporting) || arrayutil.InArray(instanceStatusList, types.FailTypeResult) {
		return true
	}
	return false
}

func (c *zhongXinChecker) saveReportHistory(ctx context.Context, count *history.ReportCount, task *fintech_data.ReportTask) error {
	logger := logctx.MustGetLogger(ctx)
	total, err := c.centerData.Count(ctx, map[string]interface{}{"objectId": task.ObjectId})
	if err != nil {
		logger.Errorf("count %s instance fail, error: %s", task.ObjectId, err.Error())
		return err
	}
	count.Total = total
	count.ObjectId = task.ObjectId
	count.InstanceId = task.ConfigId
	count.TaskId = task.TaskId
	return c.historyRecorder.Save(ctx, *count)
}

func (c *zhongXinChecker) updateObjectStat(ctx context.Context, count *history.ReportCount, task *fintech_data.ReportTask) error {
	logger := logctx.MustGetLogger(ctx)
	currentStat, err := c.objStat.Get(ctx, task.ObjectId)
	if err != nil {
		logger.Errorf("get object %s stat fail, error: %s", task.ObjectId, err.Error())
		return err
	}
	updateStat := &history.StatData{
		ObjectId:    task.ObjectId,
		Total:       count.Total,
		ReportTotal: currentStat.ReportTotal + int(task.DataTotal),
		FailTotal:   currentStat.FailTotal + int(task.FailTotal),
		TS:          int32(c.timeNowFunc().Unix()),
		LastTaskId:  task.TaskId,
	}
	_, err = c.objStat.Upsert(ctx, updateStat)
	if err != nil {
		logger.Errorf("update object %s stat fail, data: %+v, error: %s", task.ObjectId, updateStat, err.Error())
		return err
	}
	logger.Infof("update object %s stat success, data: %+v", task.ObjectId, updateStat)
	return nil
}
