package report_task

import (
	"context"
	"fmt"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/extends/cmdbutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/timer"
	"go.easyops.local/fintech_data/internal/types"
	logctx "go.easyops.local/slog/context"
)

var _ timer.JobManager = (*jobManager)(nil)
var _ timer.Job = (*reportJob)(nil)

func NewJobManager(
	configService ConfigService,
	reportService ReportService,
	ruleService report_rule.Service,
) timer.JobManager {
	return &jobManager{
		configService: configService,
		reportService: reportService,
		ruleService:   ruleService,
		nowTimeFunc:   timeutil.NowTime,
	}
}

type jobManager struct {
	configService ConfigService
	reportService ReportService
	ruleService   report_rule.Service
	nowTimeFunc   timeutil.NowTimeFunc
}

func getNextRunQuery() map[string]interface{} {
	return map[string]interface{}{
		"enable":                 true,
		report_rule.NextExecTime: map[string]string{"$lte": timeutil.NowTime().Format(timeutil.TimeFormat)},
	}
}

func (j *jobManager) GetName() string {
	return "report_task"
}

func (j *jobManager) ListJob(ctx context.Context) ([]timer.Job, error) {
	logger := logctx.MustGetLogger(ctx)
	// 获取可执行的任务
	jobList := make([]timer.Job, 0)
	configList, err := j.ruleService.SearchRule(ctx, getNextRunQuery(), nil)
	if err != nil {
		logger.Errorf("search rule fail, error: %s", err.Error())
		return nil, err
	}
	// 没有可执行任务直接返回
	if len(configList) == 0 {
		return nil, nil
	}

	// 获取全局配置
	globalConfig, err := j.configService.GetConfig(ctx)
	if err != nil {
		logger.Errorf("get task config fail, error: %s", err.Error())
		return nil, err
	}
	for _, conf := range configList {
		jobList = append(jobList, &reportJob{
			globalConfig:  globalConfig,
			reportService: j.reportService,
			reportConf:    conf,
			nowTimeFunc:   j.nowTimeFunc,
			ruleService:   j.ruleService,
		})
	}
	return jobList, nil
}

type reportJob struct {
	globalConfig  *fintech_data.ReportGlobalConfig
	reportService ReportService
	reportConf    *fintech_data.ReportObjectConf
	nowTimeFunc   timeutil.NowTimeFunc
	ruleService   report_rule.Service
}

func (r reportJob) GetJobName() string {
	return r.reportConf.ObjectId
}

func (r reportJob) GetLockName(org int) string {
	return fmt.Sprintf("fintech:data:report:%d:%s", org, r.GetJobName())
}

func (r reportJob) Do(ctx context.Context) error {
	logger := logctx.MustGetLogger(ctx)
	// 更新下次执行时间
	nextExecTime, err := NextExecTime(r.reportConf.Crontab, r.nowTimeFunc())
	if err != nil {
		logger.Errorf("report config %s get next execute time fail, error: %s", r.reportConf.InstanceId, err.Error())
		return err
	}
	query := map[string]interface{}{
		cmdbutil.InstanceIdLabel: r.reportConf.InstanceId,
		"nextExecTime":           r.reportConf.NextExecTime,
	}
	r.reportConf.NextExecTime = nextExecTime
	updateCount, err := r.ruleService.UpdateRuleByQuery(ctx, query, r.reportConf, []string{report_rule.NextExecTime})
	if err != nil {
		logger.Errorf("report config %s update nextExecTime fail, error: %s", r.reportConf.InstanceId, err.Error())
		return err
	}
	if updateCount == 0 {
		logger.Infof("report config %s not update, nextExecTime: %s", r.reportConf.InstanceId, nextExecTime)
		return nil
	}
	createRequest := types.CreateTaskRequest{
		GlobalConfig: r.globalConfig,
		ObjectConf:   r.reportConf,
		Method:       types.TimerCreate,
	}
	taskId, err := r.reportService.CreateTask(ctx, createRequest)
	if err != nil {
		return err
	}
	logger.Infof("initial %s report task %s success", r.GetJobName(), taskId)
	return nil
}
