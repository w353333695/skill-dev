package timer

import (
	"context"
	"runtime/debug"
	"sync"
	"time"

	"github.com/globalsign/mgo"
	"github.com/go-redis/redis/v8"

	"go.easyops.local/contracts/protorepo-models/easyops/model/user_service"
	"go.easyops.local/contracts/protorepo-user_service/organization"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	redislock "go.easyops.local/redis-helper/v8/lock"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

type JobManager interface {
	GetName() string
	ListJob(ctx context.Context) ([]Job, error)
}

type Job interface {
	GetJobName() string
	GetLockName(org int) string
	Do(ctx context.Context) error
}

type newLockFunc func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock

func NewTimerJob(
	redisClient redis.UniversalClient,
	logger slog.Logger,
	lockBlock newLockFunc,
	timerConfig config.TimerConfig,
	jobManager JobManager,
	orgList []*user_service.OrgInfo,
	internal int,
) *jobService {
	return &jobService{
		redisClient: redisClient,
		logger:      logger,
		lockBlock:   lockBlock,
		nowTimeFunc: timeutil.NowTime,
		timerConfig: timerConfig,
		jobManager:  jobManager,
		orgList:     orgList,
		internal:    internal,
	}
}

type jobService struct {
	redisClient redis.UniversalClient
	logger      slog.Logger
	orgClient   organization.Client
	jobManager  JobManager
	lockBlock   newLockFunc
	nowTimeFunc timeutil.NowTimeFunc
	timerConfig config.TimerConfig
	internal    int
	orgList     []*user_service.OrgInfo
	mgoSession  *mgo.Session
}

func (s *jobService) isValidOrg(org *user_service.OrgInfo) bool {
	if org.Id == 1 {
		// 过滤掉ensClient的org
		return false
	}
	if !org.Valid {
		return false
	}
	if org.Expires != 0 && org.Expires > int32(s.nowTimeFunc().Unix()) {
		return false
	}
	return true
}

// 这里所有任务都产生统一的ctx，如果需要定制，可以给jobManager加一个genCtx的方法
func (s *jobService) genCtx(org int, ctx context.Context) context.Context {
	orgUser := orguser.OrgUser{
		Org:  org,
		User: "defaultUser",
	}
	ctx = orguser.WithUser(ctx, orgUser)
	_, ctx = logctx.WithField(ctx, s.logger, "org", org)
	return ctx
}

// 定时任务执行入口
func (s *jobService) Run(ctx context.Context) {
	for _, orgData := range s.orgList {
		if s.isValidOrg(orgData) {
			jobCtx := s.genCtx(int(orgData.Id), ctx)
			s.handleJobManager(jobCtx, s.jobManager)
		}
	}
}

// 调度jobManager执行任务
func (s *jobService) handleJobManager(ctx context.Context, manager JobManager) {
	logger := logctx.MustGetLogger(ctx)
	jobList, err := manager.ListJob(ctx)
	if err != nil {
		logger.Errorf("list job fail, error: %s", err.Error())
		return
	}
	if len(jobList) == 0 {
		logger.Debugf("manager %s has no runnable job", manager.GetName())
		return
	}
	wg := &sync.WaitGroup{}
	for _, job := range jobList {
		wg.Add(1)
		go s.jobWrapper(ctx, job, wg)
	}
	wg.Wait()
	logger.Infof("timer %s done, job: %d", manager.GetName(), len(jobList))
}

func (s *jobService) getLockExpiration() time.Duration {
	if s.timerConfig.LockExpiration <= 0 {
		return 30 * time.Minute
	}
	return time.Duration(s.timerConfig.LockExpiration) * time.Second
}

func (s *jobService) newMutex(org int, job Job) redislock.Lock {
	opt := &redislock.Options{
		Expiration: s.getLockExpiration(),
		RetryCount: 1,
	}
	value := s.nowTimeFunc().Format(timeutil.TimeFormat)
	return s.lockBlock(job.GetLockName(org), value, s.redisClient, opt)
}

func (s *jobService) jobWrapper(ctx context.Context, job Job, wg *sync.WaitGroup) {
	defer wg.Done()
	orgUser, _ := orguser.FromContext(ctx)
	logger := logctx.MustGetLogger(ctx)
	org := orgUser.Org
	mutex := s.newMutex(org, job)
	if err := mutex.Lock(); err != nil {
		if err == redislock.ErrLockNotAcquired {
			logger.Infof("task %s lock not acquired", job.GetJobName())
		} else {
			logger.Errorf("task %s lock error: %v\n", job.GetJobName(), err)
		}
		return
	}
	// 异常捕获
	defer func() {
		err := mutex.Unlock()
		if err != nil {
			logger.Errorf("task %s unlock error: %v\n", job.GetJobName(), err)
		}
		if e := recover(); e != nil {
			logger.Errorf("task %s jobFunc logic error: %v, %v\n", job.GetJobName(), e, string(debug.Stack()))
		}
	}()

	// 运行作业
	logger.Infof("task %s started", job.GetJobName())
	err := job.Do(ctx)
	if err != nil {
		logger.Errorf("task %s error: %v", job.GetJobName(), err.Error())
	}
	logger.Infof("task %s done", job.GetJobName())
}

func (s *jobService) GetInternal() int {
	return s.internal
}
