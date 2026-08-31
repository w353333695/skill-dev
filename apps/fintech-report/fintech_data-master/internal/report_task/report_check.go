package report_task

import (
	"context"
	"fmt"
	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/go-redis/redis/v8"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/types"
)

func NewChecker(redisClient redis.UniversalClient, reportCenter report_center.Service, taskHistory history.TaskHistory, centerData history.CenterData, objStat history.ObjectStat, historyRecorder history.Recorder, reportConf config.ReportConf, mongoClient pmongo.ClientInterface, newLockFunc types.NewLockFunc) ReportChecker {
	return &checker{
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

type ReportChecker interface {
	TaskCheck(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig) error
}

type checker struct {
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

func (c *checker) TaskCheck(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig) error {
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

// 需要查询结果的query
func getTaskBranchQuery(reportTask *fintech_data.ReportTask) []*monthly_model.QueryItem {
	query := []*monthly_model.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.TaskId),
		},
		{
			Name:     "totalStatus",
			Operator: "eq",
			Value:    protostruct.ToValue(types.StatusResulting),
		},
	}
	return query
}

func GetTaskTimeLimit(reportTask *fintech_data.ReportTask, nowTimeFunc timeutil.NowTimeFunc) (int, int) {
	st, _ := timeutil.ParseTimeStrToUnix(reportTask.StartTime)
	et := nowTimeFunc().Unix()
	return int(st), int(et)
}

func (c *checker) taskResultCheck(ctx context.Context, reportTask *fintech_data.ReportTask, globalConf *fintech_data.ReportGlobalConfig) error {
	logger := logctx.MustGetLogger(ctx)

	// 查出当前任务所有未完成的批次
	query := getTaskBranchQuery(reportTask)
	st, et := GetTaskTimeLimit(reportTask, c.timeNowFunc)
	branchList, err := c.taskHistory.SearchAllBranch(ctx, query, nil, c.reportConf.SearchBatch, st, et)
	if err != nil {
		logger.Errorf("search task %s branch fail, error: %s", reportTask.TaskId, err.Error())
		return err
	}

	endCount := 0
	reportCount := &history.ReportCount{}
	warning := false
	// 逐个批次查询结果, 并更新批次和上报实例结果
	for _, branch := range branchList {
		//忽略之前已经结束的批次
		if types.IsEndStatus(branch.TotalStatus) {
			endCount += 1
			if branch.TotalStatus == types.StatusWithWarn {
				warning = true
			}
			continue
		}
		//查询执行中的批次
		err := c.branchResultCheck(ctx, reportTask, branch, globalConf, reportCount)
		if err != nil {
			return err
		}
		if types.IsEndStatus(branch.TotalStatus) {
			endCount += 1
			reportTask.FailTotal += branch.FailTotal
			reportTask.SuccessTotal += branch.SuccessTotal
		}
		if branch.TotalStatus == types.StatusWithWarn {
			warning = true
		}
	}

	// 全部批次都结束, 统计结果
	if reportTask.DataTotal == (reportTask.SuccessTotal + reportTask.FailTotal) {
		reportTask.EndTime = c.timeNowFunc().Format(timeutil.TimeFormat)
		parseTaskReportStatus(reportTask, warning)
	}

	//加锁
	locker := c.newLockFunc(c.redisClient, fmt.Sprintf("%s%s", types.TaskLockPrefix, reportTask.TaskId), 60)
	locker.Lock()
	defer locker.Unlock()
	// 更新任务总体结果
	err = c.taskHistory.UpdateTask(ctx, reportTask.TaskId, reportTask)
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

func parseTaskReportStatus(reportTask *fintech_data.ReportTask, existWarning bool) {
	if reportTask.FailTotal == 0 {
		reportTask.Status = types.StatusSuccess
		// existWarning:实例存在告警，则批次组也应提示这个告警;
		// 优先级：成功 < 警告 < 失败 < 部分成功 < 执行中 < 待检核
		if existWarning {
			reportTask.Status = types.StatusWithWarn
		}
		reportTask.SuccessTotal = reportTask.DataTotal
		reportTask.Msg = fmt.Sprintf("任务上报数据成功%d个", reportTask.SuccessTotal)
	} else if reportTask.FailTotal == reportTask.DataTotal {
		reportTask.Status = types.StatusFail
		reportTask.FailTotal = reportTask.DataTotal
		reportTask.FailType = types.FailTypeResult
		reportTask.Msg = fmt.Sprintf("任务上报数据失败%d个", reportTask.SuccessTotal)
	} else {
		reportTask.Status = types.StatusPartialSuccess
		reportTask.SuccessTotal = reportTask.DataTotal - reportTask.FailTotal
		reportTask.FailType = types.FailTypeResult
		reportTask.Msg = fmt.Sprintf("任务上报数据成功%d个，失败%d个", reportTask.SuccessTotal, reportTask.FailTotal)
	}
}

// 单个批次结果检查
func (c *checker) branchResultCheck(ctx context.Context, reportTask *fintech_data.ReportTask, branch *fintech_data.ReportBranch, globalConf *fintech_data.ReportGlobalConfig, reportCount *history.ReportCount) error {
	logger := logctx.MustGetLogger(ctx)

	// 获取批次结果
	checkReq := report_center.CheckRequest{BranchId: branch.BranchId}
	checkResp, err := c.reportCenter.CheckReportResult(ctx, checkReq, globalConf)
	if err != nil {
		logger.Errorf("task %s check branch %s fail, error: %s", branch.TaskId, branch.BranchId, err.Error())
		return err
	}

	// 解析批次结果
	c.parseBranchResult(checkResp, branch)

	logger.Infof("task %s branch %s status is %s", branch.TaskId, branch.BranchId, branch.TotalStatus)

	// 如果状态是未结束则直接返回
	if !types.IsEndStatus(branch.TotalStatus) {
		// 更新当前批次状态
		err = c.taskHistory.UpdateBranch(ctx, branch.InnerId, branch, []string{})
		if err != nil {
			logger.Errorf("task %s update branch %s fail, error: %s", branch.TaskId, branch.BranchId, err.Error())
			return err
		}
		return nil
	}

	reportCount.Failed += int(branch.FailTotal)

	// 记录所有的实例map
	instanceMap := make(map[string]report_center.CheckData)
	for _, inst := range checkResp.Data {
		key := inst.FacilityDescriptor
		instanceMap[key] = inst
	}
	err = c.handleInstanceResult(ctx, instanceMap, reportTask, branch, reportCount)
	if err != nil {
		logger.Errorf("task %s branch %s update instance fail, error: %s", branch.TaskId, branch.BranchId, err.Error())
		return err
	}

	// 更新任务变更成功数量
	reportTask.Inserted += branch.Inserted
	reportTask.Updated += branch.Updated
	reportTask.Removed += branch.Removed

	// 更新当前批次状态
	err = c.taskHistory.UpdateBranch(ctx, branch.InnerId, branch, []string{})
	if err != nil {
		logger.Errorf("task %s update branch %s fail, error: %s", branch.TaskId, branch.BranchId, err.Error())
		return err
	}

	return nil
}

// 解析批次结果
func (c *checker) parseBranchResult(checkResp *report_center.CheckResponse, branch *fintech_data.ReportBranch) *fintech_data.ReportBranch {
	branch.Code = checkResp.Code
	branch.Msg = checkResp.Msg
	var status string
	//特殊处理警告状态，需要解析实例状态
	isWarning := false
	warningLen := 0
	for _, instanceCheckData := range checkResp.Data {
		if instanceCheckData.Code == report_center.CodeDataValidWithWarning {
			isWarning = true
			warningLen += 1
			continue
		}
	}
	switch checkResp.Code {
	case report_center.CodeHandling, report_center.CodeSaveSuccess:
		status = types.StatusResulting
	case report_center.CodeHandleSuccess, report_center.CodeHandleWithWarn:
		status = types.StatusSuccess
		branch.SuccessTotal = branch.DataTotal
		if isWarning {
			status = types.StatusWithWarn
		}
	case report_center.CodeDataHasFail, report_center.CodeHandleFail, report_center.CodeAgencyIsDiff, report_center.CodeBranchIdNoExist, report_center.CodeBranchIdIsEmpty, report_center.CodeCompressFail, report_center.CodeDataIsEmpty:
		if len(checkResp.Data) == 0 {
			// 若批次状态码为失败，但没有失败实例数据，则将该批次所有数据标记为失败
			branch.FailTotal = branch.DataTotal
		} else {
			branch.FailTotal = int32(len(checkResp.Data) - warningLen)
		}
		branch.SuccessTotal = branch.DataTotal - branch.FailTotal
		if branch.SuccessTotal == 0 {
			status = types.StatusFail
		} else {
			status = types.StatusPartialSuccess
			if branch.FailTotal == 0 && isWarning {
				status = types.StatusWithWarn
			}
		}
	}

	branch.TotalStatus = status
	branch.CheckStatus = status
	return branch
}

func (c *checker) handleInstanceResult(ctx context.Context, instMap map[string]report_center.CheckData, reportTask *fintech_data.ReportTask, branch *fintech_data.ReportBranch, reportCount *history.ReportCount) error {
	logger := logctx.MustGetLogger(ctx)
	st, et := GetTaskTimeLimit(reportTask, c.timeNowFunc)
	query := []*monthly_model.QueryItem{
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
	allFail := branch.DataTotal > 0 && branch.SuccessTotal == 0 // 该批次是否所有数据失败
	commonFailData := report_center.CheckData{Code: report_center.CodeDataHandleFail, Msg: branch.Msg}
	for {
		res, err := c.taskHistory.SearchInstanceLimit(ctx, query, fields, c.reportConf.SearchBatch, st, et, nextId)
		if err != nil {
			logger.Errorf("task %s search instance fail, nextId: %s, error: %s", reportTask.TaskId, nextId, err.Error())
			return err
		}

		// 更新实例结果
		var upsertList, removeList []*history.ReportMetaData
		for _, inst := range res.InstanceList {
			key := getInstPk(inst)
			inst.Ts = int32(st)
			instRes, ok := instMap[key]
			if !ok && allFail {
				instRes = commonFailData
			}

			// 如果上报失败或异常，将状态改为待处理
			if allFail || !instReportResSuccess(instRes.Code) {
				inst.HandleStatus = report_center.HandleStatusPending
			}

			if err = c.saveInstResult(ctx, instRes, inst); err != nil {
				logger.Errorf("task %s update instance %s fail, error: %s", reportTask.TaskId, inst.InstanceId, err.Error())
				return err
			}
			// 实例核检通过
			if instReportResSuccess(instRes.Code) {
				instMeta := initReportMetaData(inst)
				if inst.ReportType == report_center.ReportTypeDelete {
					branch.Removed += 1
					removeList = append(removeList, instMeta)
				} else {
					if inst.ReportType == report_center.ReportTypeNew {
						branch.Inserted += 1
					} else {
						branch.Updated += 1
					}
					upsertList = append(upsertList, instMeta)
				}
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
			err = c.centerData.RemoveAll(ctx, removeList...)
			if err != nil {
				logger.Errorf("task %s remove report data fail, error: %s", reportTask.TaskId, err.Error())
				return err
			}
		}

		logger.Infof("task %s handle instance success, upsert total: %d, remove total: %d", reportTask.TaskId, len(upsertList), len(removeList))
		nextId = res.NextId
		if !res.HasMore {
			break
		}
	}
	reportCount.Inserted += int(branch.Inserted)
	reportCount.Updated += int(branch.Updated)
	reportCount.Removed += int(branch.Removed)

	return nil
}

func instReportResSuccess(code string) bool {
	return code != report_center.CodeDataInValid && code != report_center.CodeDataHandleFail
}

func initReportMetaData(inst *fintech_data.ReportInstance) *history.ReportMetaData {
	return &history.ReportMetaData{
		InstanceId:         inst.InstanceId,
		Version:            int(inst.Version),
		ObjectId:           inst.ObjectId,
		FacilityCategory:   inst.FacilityCategory,
		FacilityDescriptor: inst.FacilityDescriptor,
		Ts:                 inst.Ts,
		DataId:             inst.DataId,
	}
}

// 解析并更新实例结果
func (c *checker) saveInstResult(ctx context.Context, instRes report_center.CheckData, reportInst *fintech_data.ReportInstance) error {
	reportInst.Code = instRes.Code
	reportInst.Msg = instRes.Msg
	status := types.StatusSuccess
	switch instRes.Code {
	case report_center.CodeDataInValid, report_center.CodeDataHandleFail:
		if instRes.Code == report_center.CodeDataHandleFail || c.reportConf.ForceRetry {
			reportInst.Retryable = true
		}
		reportInst.IsFail = true
		reportInst.HandleStatus = report_center.HandleStatusPending
		status = types.FailTypeReporting
	case report_center.CodeDataValidWithWarning:
		status = types.StatusWithWarn
		reportInst.HandleStatus = report_center.HandleStatusPending
	}
	reportInst.Status = status
	return c.taskHistory.UpdateInstance(ctx, reportInst.DataId, reportInst, []string{"code", "msg", "isFail", "status", "retryable", "handleStatus", "ts"})
}

func getInstPk(reportInst *fintech_data.ReportInstance) string {
	return reportInst.FacilityDescriptor
}

func (c *checker) saveReportHistory(ctx context.Context, count *history.ReportCount, task *fintech_data.ReportTask) error {
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

func (c *checker) updateObjectStat(ctx context.Context, count *history.ReportCount, task *fintech_data.ReportTask) error {
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
