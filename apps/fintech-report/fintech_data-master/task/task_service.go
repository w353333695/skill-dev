package task

import (
	"context"
	"fmt"
	"time"

	"github.com/gogo/protobuf/types"

	message "go.easyops.local/contracts/protorepo-fintech_data/task"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/extends/ctxutil"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/report_task"
	task_types "go.easyops.local/fintech_data/internal/types"
	logctx "go.easyops.local/slog/context"
)

// ensure implements
var _ TaskService = (*taskService)(nil)

func NewTaskService(
	reportCenter report_center.Service,
	configService report_task.ConfigService,
	ruleService report_rule.Service,
	reportService report_task.ReportService,
) *taskService {
	return &taskService{
		reportCenter:  reportCenter,
		configService: configService,
		ruleService:   ruleService,
		reportService: reportService,
	}
}

type taskService struct {
	reportCenter  report_center.Service
	ruleService   report_rule.Service
	configService report_task.ConfigService
	reportService report_task.ReportService
}

func (s *taskService) GetGlobalConfig(ctx context.Context, request *types.Empty) (*fintech_data.ReportGlobalConfig, error) {
	return s.configService.GetConfig(ctx)
}

func (s *taskService) UpdateGlobalConfig(ctx context.Context, request *fintech_data.ReportGlobalConfig) (*types.Empty, error) {
	err := s.configService.UpdateConfig(ctx, request)
	if err != nil {
		return nil, err
	}
	return nil, nil
}

func (s *taskService) DebugToken(ctx context.Context, request *message.DebugTokenRequest) (*message.DebugTokenResponse, error) {
	resp, err := s.reportCenter.GetToken(ctx, report_center.TokenRequest{
		ClientId:     request.ClientId,
		ClientSecret: request.ClientSecret,
		GrantType:    request.GrantType,
	}, nil)
	if err != nil {
		return nil, err
	}
	return &message.DebugTokenResponse{
		AccessToken: resp.AccessToken,
		ExpiresIn:   int32(resp.ExpiresIn),
	}, nil
}

func (s *taskService) ReportData(ctx context.Context, request *message.ReportDataRequest) (*message.ReportDataResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	globalConfig, err := s.configService.GetConfig(ctx)
	if err != nil {
		logger.Errorf("get global config fail, error: %s", err.Error())
		return nil, err
	}
	reportConf, err := s.ruleService.GetRule(ctx, request.ObjectId)
	if err != nil {
		logger.Errorf("get report config fail, error: %s", err.Error())
		return nil, err
	}
	taskReq := task_types.CreateTaskRequest{
		GlobalConfig: globalConfig,
		ObjectConf:   reportConf,
		Method:       task_types.ManualCreate,
	}
	taskId, err := s.reportService.CreateTask(ctxutil.CtxClone(ctx), taskReq)
	if err != nil {
		logger.Errorf("create report task fail, error: %s", err.Error())
		return nil, err
	}
	return &message.ReportDataResponse{TaskId: taskId}, nil
}

func (s *taskService) RequestAudit(ctx context.Context, request *message.RequestAuditRequest) (*types.Empty, error) {
	logger := logctx.MustGetLogger(ctx)
	globalConfig, err := s.configService.GetConfig(ctx)
	if err != nil {
		logger.Errorf("get global config fail, error: %s", err.Error())
		return nil, err
	}

	loc, _ := time.LoadLocation("Asia/Shanghai")
	startTime, err := time.ParseInLocation("2006-01-02 15:04:05", request.St, loc)
	if err != nil {
		return nil, fmt.Errorf("st:%s, 请求审核失败，解析开始时间失败，%s", request.St, err.Error())
	}
	st := startTime.Unix()
	err = s.reportService.CreateAuditTask(ctxutil.CtxClone(ctx), true, request.BranchList, globalConfig, st, st, request.ObjectId, request.TaskId)
	if err != nil {
		return nil, err
	}
	return &types.Empty{}, nil
}
