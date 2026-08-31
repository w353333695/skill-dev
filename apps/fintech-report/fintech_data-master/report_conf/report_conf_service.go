package report_conf

import (
	"context"
	"time"

	message "go.easyops.local/contracts/protorepo-fintech_data/report_conf"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/report_task"
	"go.easyops.local/gin-giraffe/pkg/orguser"
)

// ensure implements
var _ ReportConfService = (*reportConfService)(nil)

func NewReportConfService(reportRuleService report_rule.Service) *reportConfService {
	return &reportConfService{
		reportRuleService: reportRuleService,
		nowTimeFunc:       timeutil.NowTime,
	}
}

type reportConfService struct {
	reportRuleService report_rule.Service
	nowTimeFunc       func() time.Time
}

func (s *reportConfService) UpdateMappingRule(ctx context.Context, request *fintech_data.ReportObjectConf) (*message.UpdateMappingRuleResponse, error) {
	orgUser, err := orguser.FromContext(ctx)
	if err != nil {
		return nil, err
	}
	request.ConfigModifier = orgUser.User
	updateFields := []string{"source", "mappingObjectId", "mappingObjectName", "mappingRule", "configModifier"}
	err = s.reportRuleService.UpdateRule(ctx, request.InstanceId, request, updateFields)
	if err != nil {
		return nil, err
	}
	return &message.UpdateMappingRuleResponse{InstanceId: request.InstanceId}, nil
}

func (s *reportConfService) UpdateReportConf(ctx context.Context, request *fintech_data.ReportObjectConf) (*message.UpdateReportConfResponse, error) {
	orgUser, err := orguser.FromContext(ctx)
	if err != nil {
		return nil, err
	}
	request.ConfigModifier = orgUser.User
	updateFields := []string{"enable", "autoRequestCheck", "crontab", "batchNum", "nextExecTime", "configModifier"}
	nextExecTime, err := report_task.NextExecTime(request.Crontab, s.nowTimeFunc())
	if err != nil {
		return nil, apierrors.InvalidArgumentErrorf("crontab格式不合法: %s", err.Error())
	}
	request.NextExecTime = nextExecTime
	err = s.reportRuleService.UpdateRule(ctx, request.InstanceId, request, updateFields)
	if err != nil {
		return nil, err
	}
	return &message.UpdateReportConfResponse{InstanceId: request.InstanceId}, nil
}


