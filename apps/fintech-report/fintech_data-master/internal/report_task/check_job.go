package report_task

import (
	"context"
	"fmt"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/timer"
	"go.easyops.local/fintech_data/internal/types"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

var _ timer.JobManager = (*checkJobManager)(nil)
var _ timer.Job = (*checkJob)(nil)

func NewCheckJobManager(
	historyService history.TaskHistory,
	configService ConfigService,
	reportChecker ReportChecker,
	reportConf config.ReportConf,
) timer.JobManager {
	return &checkJobManager{
		historyService: historyService,
		configService:  configService,
		reportConf:     reportConf,
		reportChecker:  reportChecker,
		nowTimeFunc:    timeutil.NowTime,
	}
}

type checkJobManager struct {
	historyService history.TaskHistory
	configService  ConfigService
	reportChecker  ReportChecker
	reportConf     config.ReportConf
	nowTimeFunc    timeutil.NowTimeFunc
}

func (c *checkJobManager) GetName() string {
	return "report_check"
}

func getCheckTaskQuery() []*monthly_model.QueryItem {
	return []*monthly_model.QueryItem{
		{
			Name:     "status",
			Operator: "in",
			Value:    protostruct.ToValue([]string{types.StatusResulting, types.StatusPendingCheck}),
		},
	}
}

func (c *checkJobManager) ListJob(ctx context.Context) ([]timer.Job, error) {
	logger := logctx.MustGetLogger(ctx)
	st, et := timeutil.DefaultTimeLimit(c.nowTimeFunc, c.reportConf.TimeLimit)
	taskList, err := c.historyService.SearchAllTask(ctx, getCheckTaskQuery(), nil, 50, st, et)
	if err != nil {
		logger.Errorf("search task fail, error: %s", err.Error())
		return nil, err
	}
	if len(taskList) == 0 {
		return nil, nil
	}
	// 获取全局配置
	globalConfig, err := c.configService.GetConfig(ctx)
	if err != nil {
		logger.Errorf("get task config fail, error: %s", err.Error())
		return nil, err
	}
	jobList := make([]timer.Job, 0, len(taskList))
	for _, task := range taskList {
		jobList = append(jobList, &checkJob{
			reportTask:    task,
			globalConf:    globalConfig,
			reportChecker: c.reportChecker,
		})
	}
	return jobList, nil
}

type checkJob struct {
	reportTask    *fintech_data.ReportTask
	globalConf    *fintech_data.ReportGlobalConfig
	reportChecker ReportChecker
}

func (c *checkJob) GetJobName() string {
	return fmt.Sprintf("check:%s:%s", c.reportTask.ObjectId, c.reportTask.TaskId)
}

func (c *checkJob) GetLockName(org int) string {
	return fmt.Sprintf("fintech:report:check:%d:%s", org, c.GetJobName())
}

func (c *checkJob) Do(ctx context.Context) error {
	return c.reportChecker.TaskCheck(ctx, c.reportTask, c.globalConf)
}
