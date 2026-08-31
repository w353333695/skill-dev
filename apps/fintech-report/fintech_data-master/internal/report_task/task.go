package report_task

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/go-redis/redis/v8"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/arrayutil"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/customer_settings"
	"go.easyops.local/fintech_data/internal/extends/idutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_instance"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/types"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

type ReportService interface {
	CreateTask(ctx context.Context, request types.CreateTaskRequest) (string, error)
	CreateAuditTask(ctx context.Context, autoRequestCheck bool, branchList []*fintech_data.ReportBranch, globalConf *fintech_data.ReportGlobalConfig, st, et int64, objectId, taskId string) error
}

func NewReportService(
	redisClient redis.UniversalClient,
	reportCenter report_center.Service,
	taskHistory history.TaskHistory,
	reportInstService report_instance.Service,
	reportConf config.ReportConf,
	mongoClient pmongo.ClientInterface,
	newLockFunc types.NewLockFunc,
) ReportService {
	return &reportService{
		redisClient:       redisClient,
		reportCenter:      reportCenter,
		taskHistory:       taskHistory,
		reportInstService: reportInstService,
		nowTimeFunc:       timeutil.NowTime,
		uidFunc:           idutil.Guid,
		reportConf:        reportConf,
		mongoClient:       mongoClient,
		newLockFunc:       newLockFunc,
	}
}

type reportService struct {
	newLockFunc       types.NewLockFunc
	redisClient       redis.UniversalClient
	reportCenter      report_center.Service
	taskHistory       history.TaskHistory
	reportInstService report_instance.Service
	nowTimeFunc       timeutil.NowTimeFunc
	uidFunc           func() string
	reportConf        config.ReportConf
	mongoClient       pmongo.ClientInterface
}

func (s *reportService) CreateTask(ctx context.Context, request types.CreateTaskRequest) (string, error) {
	logger := logctx.MustGetLogger(ctx)
	// 忽略废弃模型的上报
	if request.ObjectConf.Abandon {
		logger.Warnf("该任务:%s为废弃任务，已忽略上报！", request.ObjectConf.ObjectId)
		return "", nil
	}

	// 初始化任务
	reportTask, err := s.initialTask(ctx, request)
	if err != nil {
		logger.Errorf("%s initial task fail, error: %s", request.ObjectConf.ObjectId, err.Error())
		return "", err
	}

	// 上报任务入库
	taskId, err := s.taskHistory.CreateTask(ctx, reportTask)
	if err != nil {
		logger.Errorf("%s create task fail, error: %s", request.ObjectConf.ObjectId, err.Error())
		return "", err
	}
	reportTask.TaskId = taskId

	// 异步执行上报任务
	if !types.IsEndStatus(reportTask.Status) {
		go s.preReportTask(ctx, request, reportTask)
	}
	return reportTask.TaskId, nil
}

func (s *reportService) initialTask(ctx context.Context, request types.CreateTaskRequest) (*fintech_data.ReportTask, error) {
	logger := logctx.MustGetLogger(ctx)
	reportTask := &fintech_data.ReportTask{
		ConfigId:        request.ObjectConf.InstanceId,
		ObjectId:        request.ObjectConf.ObjectId,
		MappingObjectId: report_rule.GetMappingObjectId(request.ObjectConf),
		Status:          types.StatusInitial,
		Method:          string(request.Method),
		StartTime:       s.nowTimeFunc().Format(timeutil.TimeFormat),
	}
	// 发起人
	if request.Method == types.ManualCreate || request.ObjectConf.ConfigModifier == "" {
		orgUser, _ := orguser.FromContext(ctx)
		reportTask.Sponsor = orgUser.User
	} else {
		reportTask.Sponsor = request.ObjectConf.ConfigModifier
	}
	lastTask, err := s.fetchLastTask(ctx, request.ObjectConf)
	if err != nil {
		logger.Errorf("%s fetch last task fail, error: %s", request.ObjectConf.ObjectId, err.Error())
		return nil, err
	}
	if lastTask != nil {
		if !types.IsEndStatus(lastTask.Status) {
			reportTask.Status = types.StatusConflict
			reportTask.Msg = fmt.Sprintf("同模型任务%s尚未结束", lastTask.TaskId)
			logger.Warnf("%s last task %s is not end", request.ObjectConf.ObjectId, lastTask.TaskId)
		}
		reportTask.LastTaskId = lastTask.TaskId
		reportTask.LastReportTime = lastTask.StartTime
	}
	return reportTask, nil
}

func (s *reportService) fetchLastTask(ctx context.Context, objectConf *fintech_data.ReportObjectConf) (*fintech_data.ReportTask, error) {
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "objectId",
			Operator: "eq",
			Value:    protostruct.ToValue(objectConf.ObjectId),
		},
		{
			Name:     "status",
			Operator: "ne",
			Value:    protostruct.ToValue(types.StatusConflict),
		},
		{
			Name:     "failType",
			Operator: "ne",
			Value:    protostruct.ToValue(types.FailTypeInitial),
		},
	}
	fields := map[string]interface{}{
		"startTime": true,
		"status":    true,
	}
	st, et := timeutil.DefaultTimeLimit(s.nowTimeFunc, s.reportConf.TimeLimit)
	return s.taskHistory.SearchOneTask(ctx, query, fields, st, et)
}

//必须全量更新
func (s *reportService) updateReportTask(ctx context.Context, task *fintech_data.ReportTask) {
	logger := logctx.MustGetLogger(ctx)
	if err := s.taskHistory.UpdateTask(ctx, task.TaskId, task); err != nil {
		logger.Errorf("task %s update fail, error: %s", task.TaskId, err.Error())
	}
	logger.Infof("task %s update success, status: %s", task.TaskId, task.Status)
}

// 获取上报的dataType，对应于cmdb里去掉命名空间的模型id
func getReportDataType(objectId string) string {
	if strings.Contains(objectId, "@") {
		return strings.Split(objectId, "@")[0]
	}
	return objectId
}

func genReportData(reportInstance *fintech_data.ReportInstance) interface{} {
	data := protostruct.DecodeToMap(reportInstance.Data)
	data[report_center.KeyReportDataType] = reportInstance.ReportType
	return data
}

func (s *reportService) initReportBranch(ctx context.Context, reportTask *fintech_data.ReportTask, reportList []*fintech_data.ReportInstance) (*fintech_data.ReportBranch, error) {
	branch := &fintech_data.ReportBranch{
		TaskId:       reportTask.TaskId,
		ObjectId:     reportTask.ObjectId,
		DataTotal:    int32(len(reportList)),
		TotalStatus:  types.StatusReporting,
		ReportStatus: types.StatusReporting,
	}
	innerId, err := s.taskHistory.CreateBranch(ctx, branch)
	if err != nil {
		return nil, fmt.Errorf("创建上报批次失败，%s", err.Error())
	}
	branch.InnerId = innerId
	for _, data := range reportList {
		data.InnerBranchId = innerId
	}
	_, err = s.taskHistory.BatchCreateInstance(ctx, reportList)
	if err != nil {
		return nil, fmt.Errorf("创建上报实例失败，%s", err.Error())
	}
	return branch, nil
}

func (s *reportService) initReportRequest(branch *fintech_data.ReportBranch, reportList []*fintech_data.ReportInstance) report_center.ReportRequest {
	reportDataList := make([]interface{}, 0, len(reportList))
	for _, data := range reportList {
		reportDataList = append(reportDataList, genReportData(data))
	}
	return report_center.ReportRequest{
		DataTotal:           len(reportList),
		InnerBranchId:       branch.InnerId,
		FacilityOwnerAgency: "",
		Data: []report_center.ReportData{
			{
				DataType: getReportDataType(branch.ObjectId),
				DataList: reportDataList,
			},
		},
	}
}

func (s *reportService) getBatchNum(conf *fintech_data.ReportObjectConf) int {
	if conf.BatchNum == 0 {
		return 100
	} else {
		return int(conf.BatchNum)
	}
}

// 请求分批并存入分批数据
func (s *reportService) handleReportBatch(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask, reportList []*fintech_data.ReportInstance) ([]report_center.ReportRequest, error) {
	total := len(reportList)
	var requestList []report_center.ReportRequest
	var end int
	size := s.getBatchNum(request.ObjectConf)
	for i := 0; i < total; i += size {
		end += size
		if end > total {
			end = total
		}
		dataList := reportList[i:end]

		// 生成批次信息
		branch, err := s.initReportBranch(ctx, reportTask, dataList)
		if err != nil {
			return nil, err
		}

		// 生成上报请求
		requestList = append(requestList, s.initReportRequest(branch, dataList))
	}

	return requestList, nil
}

// 上报数据前的数据采集及入库
func (s *reportService) preReportTask(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask) {

	logger := logctx.MustGetLogger(ctx)
	var reportReqList []report_center.ReportRequest

	// defer更新任务状态
	defer func() {
		if types.IsEndStatus(reportTask.Status) {
			reportTask.EndTime = s.nowTimeFunc().Format(timeutil.TimeFormat)
		}
		if reportTask.Status == types.StatusFail {
			reportTask.FailType = types.FailTypeInitial // 标记错误类型为任务初始化失败
		}
		s.updateReportTask(ctx, reportTask)
		// 如果状态被改为上报中，则异步执行上报任务
		if reportTask.Status == types.StatusReporting {
			go s.doReportTask(ctx, request, reportTask, reportReqList)
		}
	}()

	// 获取待上报数据
	reportList, err := s.reportInstService.SearchReportInstance(ctx, request, reportTask)
	if err != nil {
		reportTask.Msg = fmt.Sprintf("查询上报实例失败：%s", err.Error())
		reportTask.Status = types.StatusFail
		logger.Errorf("%s task %s search report instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return
	}

	logger.Infof("%s task %s search report total: %d", request.ObjectConf.ObjectId, reportTask.TaskId, len(reportList))
	// 如果所有上报实例都为空则直接返回
	if len(reportList) == 0 {
		reportTask.Status = types.StatusNoReport
		reportTask.Msg = "无需要上报实例"
		return
	}
	reportTask.DataTotal = int32(len(reportList))

	// 创建上报请求
	reportReqList, err = s.handleReportBatch(ctx, request, reportTask, reportList)
	if err != nil {
		reportTask.Status = types.StatusFail
		reportTask.Msg = err.Error()
		logger.Errorf("%s task %s batch create report instance fail, error: %s", request.ObjectConf.ObjectId, reportTask.TaskId, err.Error())
		return
	}

	reportTask.Status = types.StatusReporting
	reportTask.BatchTotal = int32(len(reportReqList))
	return
}

func (s *reportService) parseReportResult(resp *report_center.ReportResponse, err error) (*fintech_data.ReportBranch, *fintech_data.ReportInstance) {
	updateInst := &fintech_data.ReportInstance{}
	updateBranch := &fintech_data.ReportBranch{}
	if err != nil {
		resp = &report_center.ReportResponse{
			Msg: fmt.Sprintf("调用上报接口失败：%s", err.Error()),
		}
	}
	if resp.Code != report_center.CodeReportSuccess {
		updateBranch.ReportStatus = types.StatusFail
		updateBranch.TotalStatus = types.StatusFail

		updateInst.IsFail = true
		updateInst.Status = types.FailTypeReporting
		updateInst.Retryable = true
	} else {
		updateBranch.ReportStatus = types.StatusSuccess
		updateBranch.RequestCheckStatus = types.StatusPendingCheck
		updateBranch.TotalStatus = types.StatusPendingCheck

		updateInst.Status = types.StatusPendingCheck
	}

	// branch
	updateBranch.BranchId = resp.BranchId
	updateBranch.Code = resp.Code
	updateBranch.Msg = resp.Msg

	// instance
	updateInst.Code = resp.Code
	updateInst.Msg = resp.Msg
	updateInst.BranchId = resp.BranchId
	return updateBranch, updateInst
}

// 批次上报统计数据
type batchReportStatistics struct {
	hasSuccess bool
	failTotal  int
}

// 按照请求上报数据
func (s *reportService) doReportTask(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask, reportRequestList []report_center.ReportRequest) string {
	logger := logctx.MustGetLogger(ctx)
	objectId := reportTask.ObjectId
	taskId := reportTask.TaskId

	st, _ := timeutil.ParseTimeStrToUnix(reportTask.StartTime)
	et := s.nowTimeFunc().Unix()

	hasSuccess := false
	failTotal := 0
	var batchIds []string
	var pendingCheckBranches []*fintech_data.ReportBranch

	batchReport := &batchReportStatistics{}

	for _, req := range reportRequestList {
		resp, err := s.reportCenter.ReportData(ctx, req, request.GlobalConfig)
		if customer_settings.IsZhongXin {
			batchIds = append(batchIds, req.InnerBranchId)
			s.dealWithZhongXinReportResult(ctx, request, reportTask, st, et, &req, resp, err, batchReport)
			continue
		}
		// 解析结果
		updateBranch, updateInst := s.parseReportResult(resp, err)
		if updateInst.Status != types.FailTypeReporting {
			hasSuccess = true
			logger.Infof("%s task %s report data success, total: %d", reportTask.ObjectId, reportTask.TaskId, req.DataTotal)
		} else {
			failTotal += req.DataTotal
			updateBranch.FailTotal = int32(req.DataTotal)
			logger.Errorf("%s task %s report data fail, total: %d, error: %s", reportTask.ObjectId, reportTask.TaskId, req.DataTotal, updateInst.Msg)
		}
		if updateBranch.BranchId != "" {
			batchIds = append(batchIds, updateBranch.BranchId)
		}
		//获取所有待检核的批次
		if updateBranch.RequestCheckStatus == types.StatusPendingCheck {
			updateBranch.InnerId = req.InnerBranchId
			pendingCheckBranches = append(pendingCheckBranches, updateBranch)
		}

		s.updateTaskDatabase(ctx, st, et, req.InnerBranchId, objectId, taskId, updateBranch, updateInst)
	}

	if customer_settings.IsZhongXin {
		hasSuccess = batchReport.hasSuccess
		failTotal = batchReport.failTotal
	}
	if hasSuccess {
		reportTask.Status = types.StatusPendingCheck
		if customer_settings.IsZhongXin {
			// 有成功上报的实例，那么任务状态为执行中
			reportTask.Status = types.StatusResulting
		}
	} else {
		reportTask.Status = types.StatusFail
		reportTask.FailType = types.FailTypeReporting
		reportTask.Msg = "任务上报阶段失败"
		reportTask.EndTime = s.nowTimeFunc().Format(timeutil.TimeFormat)
	}
	reportTask.FailTotal = int32(failTotal)
	reportTask.BranchIds = batchIds
	s.updateReportTask(ctx, reportTask)

	if hasSuccess && !customer_settings.IsZhongXin {
		autoRequestCheck := request.ObjectConf.AutoRequestCheck
		s.CreateAuditTask(ctx, autoRequestCheck, pendingCheckBranches, request.GlobalConfig, st, et, objectId, taskId)
	}
	return reportTask.Status
}

// 处理中信的上报结果
func (s *reportService) dealWithZhongXinReportResult(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask, st, et int64, req *report_center.ReportRequest, resp *report_center.ReportResponse, err error, batchReport *batchReportStatistics) {
	// 调用接口报错
	if err != nil {
		resp = &report_center.ReportResponse{
			Msg: fmt.Sprintf("调用上报接口失败：%s", err.Error()),
		}
		updateBranch := &fintech_data.ReportBranch{
			ReportStatus: types.StatusFail,
			TotalStatus:  types.StatusFail,
			Code:         resp.Code,
			Msg:          resp.Msg,
			FailTotal:    int32(req.DataTotal),
		}

		updateInstance := &fintech_data.ReportInstance{
			Status:    types.FailTypeReporting,
			Code:      resp.Code,
			Msg:       resp.Msg,
			IsFail:    true,
			Retryable: true,
		}
		// 更新
		batchReport.failTotal += req.DataTotal
		s.updateTaskDatabase(ctx, st, et, req.InnerBranchId, reportTask.ObjectId, reportTask.TaskId, updateBranch, updateInstance)
		return
	}
	// 处理上报成功的批次
	if resp.Code == report_center.ZhongXinCodeReportSuccess {
		batchReport.hasSuccess = true
		updateBranch := &fintech_data.ReportBranch{
			ReportStatus: types.StatusSuccess,
			TotalStatus:  types.StatusResulting,
			CheckStatus:  types.StatusResulting,
			Code:         resp.Code,
			Msg:          resp.Msg,
		}

		// 上报成功实例数据状态全为执行中
		updateInstance := &fintech_data.ReportInstance{
			Status: types.StatusResulting,
			Code:   resp.Code,
			Msg:    resp.Msg,
		}
		batchReport.hasSuccess = true
		// 更新
		s.updateTaskDatabase(ctx, st, et, req.InnerBranchId, reportTask.ObjectId, reportTask.TaskId, updateBranch, updateInstance)
	} else {
		// 处理上报失败的批次
		s.dealWithZhongXinFailReportResult(ctx, request, reportTask, st, et, req, resp, batchReport)
	}
}

// 处理上报失败的批次
func (s *reportService) dealWithZhongXinFailReportResult(ctx context.Context, request types.CreateTaskRequest, reportTask *fintech_data.ReportTask, st, et int64, req *report_center.ReportRequest, resp *report_center.ReportResponse, batchReport *batchReportStatistics) {
	logger := logctx.MustGetLogger(ctx)
	objectId := reportTask.ObjectId
	taskId := reportTask.TaskId
	branchId := req.InnerBranchId

	// 先查出原来的批次
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(taskId),
		},
		{
			Name:     "_id",
			Operator: "eq",
			Value:    protostruct.ToValue(req.InnerBranchId),
		},
	}
	fields := map[string]interface{}{
		"_id":       true,
		"dataTotal": true,
	}
	branchList, _, err := s.taskHistory.SearchBranch(ctx, query, fields, int(st), int(et), 1, 20)
	if err != nil {
		logger.Errorf("%s task %s update branch %s fail, error: %s", objectId, taskId, branchId, err.Error())
		return
	}
	// 当前批次
	branch := branchList[0]

	responseInstanceList, err := Convert(resp.Data)
	if err != nil {
		logger.Errorf("report branch %s response data Convert error: %s", req.InnerBranchId, err.Error())
		return
	}

	var allFail bool
	// 是否全部错误
	if len(responseInstanceList) == 1 {
		responseInstance := responseInstanceList[0]
		if responseInstance.FacilityDescriptor == "" && arrayutil.InArray([]string{"[facilityOwnerAgency]不能为空", "解析参数异常"}, responseInstance.Msg) {
			allFail = true
		}
	}

	updateBranch := &fintech_data.ReportBranch{}
	// 上报的实例数据全部错误
	if int(branch.DataTotal) == len(responseInstanceList) || allFail {
		updateBranch.ReportStatus = types.StatusFail
		updateBranch.TotalStatus = types.StatusFail
		updateBranch.Msg = resp.Msg
		// 全部失败的话那么失败数为总数
		updateBranch.FailTotal = branch.DataTotal
	} else {
		// 批次中的部分实例数据成功，部分失败, 所以不给msg赋值
		updateBranch.ReportStatus = types.StatusPartialSuccess
		updateBranch.TotalStatus = types.StatusResulting
		updateBranch.CheckStatus = types.StatusResulting
		updateBranch.FailTotal = int32(len(responseInstanceList))
		// 有部分实例上报成功也就意味着任务也处于执行中
		batchReport.hasSuccess = true
	}
	updateBranch.Code = resp.Code
	batchReport.failTotal += int(updateBranch.FailTotal)
	// 更新批次信息
	branchUpdateFields := []string{"totalStatus", "reportStatus", "checkStatus", "code", "msg", "failTotal"}
	err = s.taskHistory.UpdateBranch(ctx, branchId, updateBranch, branchUpdateFields)
	if err != nil {
		logger.Errorf("%s task %s update branch %s fail, error: %s", objectId, taskId, branchId, err.Error())
		return
	}

	// 如果是 [facilityOwnerAgency]不能为空 和 解析参数异常这两种错误，那么实例全部失败,更新完成之后直接返回
	if allFail {
		updateFailInst := &fintech_data.ReportInstance{
			Status:    types.FailTypeReporting,
			IsFail:    true,
			Retryable: true,
			Code:      resp.Code,
			Msg:       responseInstanceList[0].Msg,
		}
		// 更新上报实例
		instanceQuery := []*monthly_collection_service.QueryItem{
			{
				Name:     "taskId",
				Operator: "eq",
				Value:    protostruct.ToValue(reportTask.TaskId),
			},
			{
				Name:     "innerBranchId",
				Operator: "eq",
				Value:    protostruct.ToValue(branchId),
			},
		}
		instUpdateFields := []string{"code", "msg", "isFail", "status", "retryable"}
		err = s.taskHistory.UpdateInstanceByFilter(ctx, instanceQuery, updateFailInst, instUpdateFields, int(st), int(et))
		if err != nil {
			logger.Errorf("%s task %s update instance fail, innerBranchId: %s, error: %s", objectId, taskId, branchId, err.Error())
		}
		return
	}

	// 更新实例状态信息，分为成功的实例和失败的实例两部分
	var failFacilityDescriptorList []string
	failReportInstanceMap := make(map[string]*report_center.ReportResponseInstance)
	for _, instance := range responseInstanceList {
		failFacilityDescriptorList = append(failFacilityDescriptorList, instance.FacilityDescriptor)
		failReportInstanceMap[instance.FacilityDescriptor] = instance
	}
	// 查出当前批次所有的实例数据
	instanceQuery := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(reportTask.TaskId),
		},
		{
			Name:     "innerBranchId",
			Operator: "eq",
			Value:    protostruct.ToValue(branchId),
		},
	}
	instanceFields := map[string]interface{}{
		"_id":                true,
		"innerBranchId":      true,
		"facilityDescriptor": true,
	}
	instanceList, _, err := s.taskHistory.SearchInstance(ctx, instanceQuery, instanceFields, int(st), int(et), 1, s.getBatchNum(request.ObjectConf))
	if err != nil {
		logger.Errorf("%s task %s search instance fail, innerBranchId: %s, error: %s", objectId, taskId, branchId, err.Error())
		return
	}

	var successInstanceDataIds []string
	var failResponseInstanceList []*report_center.ReportResponseInstance
	var failInstanceDataIds []string
	for _, instance := range instanceList {
		if arrayutil.InArray(failFacilityDescriptorList, instance.FacilityDescriptor) {
			failResponseInstanceList = append(failResponseInstanceList, failReportInstanceMap[instance.FacilityDescriptor])
			failInstanceDataIds = append(failInstanceDataIds, instance.DataId)
		} else {
			successInstanceDataIds = append(successInstanceDataIds, instance.DataId)
		}
	}

	// 先更新成功的
	if len(successInstanceDataIds) > 0 {
		// 上报成功实例数据状态全为执行中
		updateSuccessInst := &fintech_data.ReportInstance{
			Status: types.StatusResulting,
		}
		// 更新上报实例
		query := []*monthly_collection_service.QueryItem{
			{
				Name:     "_id",
				Operator: "in",
				Value:    protostruct.ToValue(successInstanceDataIds),
			},
		}
		instUpdateFields := []string{"code", "msg", "status"}
		err = s.taskHistory.UpdateInstanceByFilter(ctx, query, updateSuccessInst, instUpdateFields, int(st), int(et))
		if err != nil {
			logger.Errorf("%s task %s update instance fail, innerBranchId: %s, error: %s", objectId, taskId, branchId, err.Error())
			return
		}
	}

	// 更新失败的实例数据
	if len(failResponseInstanceList) > 0 && len(failInstanceDataIds) > 0 {
		for i, responseInstance := range failResponseInstanceList {
			updateFailInst := &fintech_data.ReportInstance{
				Status:    types.FailTypeReporting,
				IsFail:    true,
				Retryable: true,
				Code:      resp.Code,
				Msg:       responseInstance.Msg,
			}
			instUpdateFields := []string{"code", "msg", "isFail", "status", "retryable"}
			err = s.taskHistory.UpdateInstance(ctx, failInstanceDataIds[i], updateFailInst, instUpdateFields)
			if err != nil {
				logger.Errorf("%s task %s update instance fail, innerBranchId: %s, error: %s", objectId, taskId, branchId, err.Error())
				return
			}
		}
	}
}

func Convert(resp interface{}) ([]*report_center.ReportResponseInstance, error) {
	responseInstanceList, ok := resp.([]interface{})
	if !ok {
		return nil, fmt.Errorf("response data not is slice")
	}
	var list []*report_center.ReportResponseInstance
	for _, val := range responseInstanceList {
		r := &report_center.ReportResponseInstance{}
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

func (s *reportService) updateTaskDatabase(ctx context.Context, st, et int64, branchId, objectId, taskId string, updateBranch *fintech_data.ReportBranch, updateInst *fintech_data.ReportInstance) {
	logger := logctx.MustGetLogger(ctx)
	// 更新批次信息
	branchUpdateFields := []string{"branchId", "totalStatus", "reportStatus", "requestCheckStatus", "code", "msg", "failTotal"}
	if updateBranch.CheckStatus != "" {
		branchUpdateFields = append(branchUpdateFields, "checkStatus")
	}
	err := s.taskHistory.UpdateBranch(ctx, branchId, updateBranch, branchUpdateFields)
	if err != nil {
		logger.Errorf("%s task %s update branch %s fail, error: %s", objectId, taskId, branchId, err.Error())
		return
	}

	// 更新上报实例
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "innerBranchId",
			Operator: "eq",
			Value:    protostruct.ToValue(branchId),
		},
	}
	instUpdateFields := []string{"branchId", "code", "msg", "isFail", "status", "retryable"}
	err = s.taskHistory.UpdateInstanceByFilter(ctx, query, updateInst, instUpdateFields, int(st), int(et))
	if err != nil {
		logger.Errorf("%s task %s update instance fail, innerBranchId: %s, error: %s", objectId, taskId, branchId, err.Error())
		return
	}
}

func (s *reportService) CreateAuditTask(ctx context.Context, autoRequestCheck bool, branchList []*fintech_data.ReportBranch, globalConf *fintech_data.ReportGlobalConfig, st, et int64, objectId, taskId string) error {
	if !autoRequestCheck {
		return nil
	}
	branchIds := make([]string, 0)
	innerBranchIds := make([]string, 0)
	auditBranchMap := make(map[string]int32, 0)

	for _, branch := range branchList {
		branchIds = append(branchIds, branch.BranchId)
		innerBranchIds = append(innerBranchIds, branch.InnerId)
		auditBranchMap[branch.InnerId] = 0
	}

	branchNum := len(branchIds)
	request := report_center.AuditRequest{
		FacilityOwnerAgency: "",
		BranchNumber:        branchNum,
		BranchIdList:        branchIds,
	}
	resp, err := s.reportCenter.Audit(ctx, request, globalConf)
	if err != nil {
		return fmt.Errorf("请求检核失败，请稍后重试")
	}
	// 解析结果
	updateBranch, updateInst, isFailed := s.parseRequestCheckResult(resp)

	//解析批次下的实例数量
	failInstanceNum, auditBranchMap := s.parseBranchFailTotal(ctx, isFailed, innerBranchIds, auditBranchMap, st, et)

	// 更新数据库
	for _, branch := range branchList {
		updateBranch.InnerId = branch.InnerId
		updateBranch.BranchId = branch.BranchId
		if isFailed {
			updateBranch.FailTotal += auditBranchMap[branch.InnerId]
		}
		s.updateTaskDatabase(ctx, st, et, branch.InnerId, objectId, taskId, updateBranch, updateInst)
	}

	//更新任务状态
	s.updateReportTaskAfterRequestAudit(ctx, taskId, st, et, auditBranchMap, isFailed, failInstanceNum, resp.Msg)
	return getRequestAuditErr(isFailed, resp.Msg)
}

func (s *reportService) parseBranchFailTotal(ctx context.Context, isFailed bool, innerBranchIds []string, auditBranchMap map[string]int32, st, et int64) (int, map[string]int32) {
	if !isFailed {
		return 0, auditBranchMap
	}
	logger := logctx.MustGetLogger(ctx)
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "innerBranchId",
			Operator: "in",
			Value:    protostruct.ToValue(innerBranchIds),
		},
	}
	instanceList, total, err := s.taskHistory.SearchInstance(ctx, query, nil, int(st), int(et), 1, 3000)
	if err != nil {
		logger.Errorf("innerBranchId:%v,查询实例失败：%s", innerBranchIds, err.Error())
	}
	failInstanceNum := total
	for _, instance := range instanceList {
		auditBranchMap[instance.InnerBranchId] += 1
	}

	return failInstanceNum, auditBranchMap
}

func getRequestAuditErr(isFailed bool, msg string) error {
	err := fmt.Errorf(msg)
	if !isFailed {
		err = nil
	}
	return err
}

func (s *reportService) updateReportTaskAfterRequestAudit(ctx context.Context, taskId string, st, et int64, auditBranchMap map[string]int32, isFailed bool, failInsNum int, auditMsg string) {
	logger := logctx.MustGetLogger(ctx)

	//获取任务详情
	reportTask, err := s.taskHistory.GetTask(ctx, taskId)
	if err != nil {
		logger.Errorf("task %s  update fail,search task error: %s", taskId, err.Error())
		return
	}
	totalStatus := types.StatusSuccess

	//解析当前传入的branchList检核状态
	reportTask.Status = types.StatusResulting
	//检核失败
	if isFailed {
		totalStatus = types.StatusFail
		reportTask.FailTotal += int32(failInsNum)
		reportTask.Status = types.StatusFail
		reportTask.FailType = types.FailTypeRequestCheck
		reportTask.Msg = fmt.Sprintf("请求审核失败:%s", auditMsg)
		reportTask.EndTime = s.nowTimeFunc().Format(timeutil.TimeFormat)
		if reportTask.SuccessTotal > 0 {
			reportTask.Status = types.StatusPartialSuccess
		}
	}

	//获取任务是否存在其他批次（不包含branchIds）为待审核/成功的状态
	query := []*monthly_collection_service.QueryItem{
		{
			Name:     "taskId",
			Operator: "eq",
			Value:    protostruct.ToValue(taskId),
		},
	}

	fields := map[string]interface{}{
		"branchId":    true,
		"innerId":     true,
		"totalStatus": true,
	}
	taskBranches, err := s.taskHistory.SearchAllBranch(ctx, query, fields, 1000, int(st), int(s.nowTimeFunc().Unix()))
	if err != nil {
		logger.Errorf("task %s  update fail,search all branches error: %s", taskId, err.Error())
		return
	}
	for _, branch := range taskBranches {
		if _, ok := auditBranchMap[branch.InnerId]; ok {
			continue
		}
		//组合优先级：成功 < 警告 < 失败 < 部分成功 < 执行中 < 待检核
		//如果该任务存在分支未请求检核的，则最终状态为待检核
		if branch.TotalStatus == types.StatusPendingCheck {
			totalStatus = types.StatusPendingCheck
			break
		}
		//如果该任务存在分支检核成功的，则最终状态为部分成功
		if branch.TotalStatus == types.StatusSuccess && isFailed {
			totalStatus = types.StatusPartialSuccess
			continue
		}
	}

	//加锁
	locker := s.newLockFunc(s.redisClient, fmt.Sprintf("%s%s", types.TaskLockPrefix, taskId), 60)
	locker.Lock()
	defer locker.Unlock()

	//获取任务状态优先级，更新任务
	reportTask.Status = types.SwitchMoreHighLevelStatus(reportTask.Status, totalStatus)
	s.updateReportTask(ctx, reportTask)
}

func (s *reportService) parseRequestCheckResult(resp *report_center.AuditResponse) (*fintech_data.ReportBranch, *fintech_data.ReportInstance, bool) {
	updateInst := &fintech_data.ReportInstance{}
	updateBranch := &fintech_data.ReportBranch{}
	isFailed := false
	if resp.Code == report_center.CodeRequestCheckSuccess {
		updateBranch.ReportStatus = types.StatusSuccess
		updateBranch.RequestCheckStatus = types.StatusSuccess
		updateBranch.CheckStatus = types.StatusResulting
		updateBranch.TotalStatus = types.StatusResulting

		updateInst.Status = types.StatusResulting
	} else {
		updateBranch.ReportStatus = types.StatusSuccess
		updateBranch.RequestCheckStatus = types.StatusFail
		updateBranch.TotalStatus = types.StatusFail
		isFailed = true

		updateInst.IsFail = true
		updateInst.Status = types.FailTypeRequestCheck
		updateInst.Retryable = true
	}

	// branch
	updateBranch.Code = resp.Code
	updateBranch.Msg = resp.Msg

	// instance
	updateInst.Code = resp.Code
	updateInst.Msg = resp.Msg
	return updateBranch, updateInst, isFailed
}
