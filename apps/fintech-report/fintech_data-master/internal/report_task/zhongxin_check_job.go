package report_task

import (
	"context"
	"fmt"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/timer"
	logctx "go.easyops.local/slog/context"
)

var _ timer.JobManager = (*zhongXinCheckJobManager)(nil)
var _ timer.Job = (*zhongXinCheckJob)(nil)

func NewZhongXinCheckJobManager(
	historyService history.TaskHistory,
	configService ConfigService,
	reportChecker ReportChecker,
	reportConf config.ReportConf,
) timer.JobManager {
	return &zhongXinCheckJobManager{
		historyService: historyService,
		configService:  configService,
		reportConf:     reportConf,
		reportChecker:  reportChecker,
		nowTimeFunc:    timeutil.NowTime,
	}
}

type zhongXinCheckJobManager struct {
	historyService history.TaskHistory
	configService  ConfigService
	reportChecker  ReportChecker
	reportConf     config.ReportConf
	nowTimeFunc    timeutil.NowTimeFunc
}

func (c *zhongXinCheckJobManager) GetName() string {
	return "zhongxin_report_check"
}

func (c *zhongXinCheckJobManager) ListJob(ctx context.Context) ([]timer.Job, error) {
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
		jobList = append(jobList, &zhongXinCheckJob{
			reportTask:    task,
			globalConf:    globalConfig,
			reportChecker: c.reportChecker,
		})
	}
	return jobList, nil
}

type zhongXinCheckJob struct {
	reportTask    *fintech_data.ReportTask
	globalConf    *fintech_data.ReportGlobalConfig
	reportChecker ReportChecker
}

func (c *zhongXinCheckJob) GetJobName() string {
	return fmt.Sprintf("check:%s:%s", c.reportTask.ObjectId, c.reportTask.TaskId)
}

func (c *zhongXinCheckJob) GetLockName(org int) string {
	return fmt.Sprintf("fintech:report:check:%d:%s", org, c.GetJobName())
}

func (c *zhongXinCheckJob) Do(ctx context.Context) error {
	return c.reportChecker.TaskCheck(ctx, c.reportTask, c.globalConf)
}
