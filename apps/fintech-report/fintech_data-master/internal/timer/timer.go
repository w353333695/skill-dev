package timer

import (
	"context"
	"time"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/slog"
)

type Task interface {
	Run(ctx context.Context)
	GetInternal() int
}

func NewTimer(logger slog.Logger, timerConfig config.TimerConfig, timerTask Task) *timerService {
	return &timerService{
		logger:      logger,
		timerConfig: timerConfig,
		timerTask:   timerTask,
		nowTimeFunc: timeutil.NowTime,
	}
}

type timerService struct {
	logger      slog.Logger
	timerConfig config.TimerConfig
	timerTask   Task
	nowTimeFunc timeutil.NowTimeFunc
}

func (s *timerService) RunTimeTask(ctx context.Context) error {
	interval := time.Duration(s.timerTask.GetInternal()) * time.Second
	timer := time.NewTimer(s.getStartInterval())
	for {
		select {
		case <-ctx.Done():
			s.logger.Info("timeTask done ...")
			return nil
		case <-timer.C:
			timer.Reset(interval)
			s.timerTask.Run(ctx)
		}
	}
}

func (s *timerService) getStartInterval() time.Duration {
	nowTime := s.nowTimeFunc()
	if nowTime.Second() == 0 {
		return 0
	}
	return time.Minute - time.Duration(nowTime.Second())*time.Second
}
