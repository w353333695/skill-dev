package timer

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/globalsign/mgo"
	"github.com/go-redis/redis/v8"
	"github.com/golang/mock/gomock"

	"go.easyops.local/contracts/protorepo-models/easyops/model/user_service"
	"go.easyops.local/contracts/protorepo-user_service/organization"
	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/gin-giraffe/pkg/orguser"

	redislock "go.easyops.local/redis-helper/v8/lock"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

type errFakeLock struct {
	lockErr   error
	unLockErr error
	doPanic   bool
}

func (f *errFakeLock) Lock() error {
	return f.lockErr
}

func (f *errFakeLock) Unlock() error {
	return f.unLockErr
}

func (f *errFakeLock) LockContext(ctx context.Context) error {
	return f.lockErr
}

func (f *errFakeLock) UnlockContext(ctx context.Context) error {
	return f.unLockErr
}

func (f *errFakeLock) Extend(ctx context.Context, ttl time.Duration) error {
	return f.lockErr
}

func LockFunc(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
	if opt.Expiration == time.Duration(10)*time.Second {
		return &errFakeLock{lockErr: redislock.ErrLockNotAcquired}
	}
	if opt.Expiration == time.Duration(30)*time.Second {
		return &errFakeLock{lockErr: fmt.Errorf("mock fail")}
	}
	if opt.Expiration == time.Duration(20)*time.Second {
		return &errFakeLock{unLockErr: fmt.Errorf("mock fail")}
	}
	return &errFakeLock{}
}

var _ Job = (*fakeJob)(nil)
var _ JobManager = (*fakeJobManager)(nil)

type fakeJob struct {
	jobFail bool
}

func (f fakeJob) GetJobName() string {
	return "fakeJob"
}

func (f fakeJob) GetLockName(org int) string {
	return "fakeJobLock"
}

func (f fakeJob) Do(ctx context.Context) error {
	if f.jobFail {
		return fmt.Errorf("mock fail")
	}
	println("start fake job", timeutil.NowTime().Format(timeutil.TimeFormat))
	return nil
}

type panicJob struct {
}

func (f panicJob) GetJobName() string {
	return "panicJob"
}

func (f panicJob) GetLockName(org int) string {
	return "panicJobLock"
}

func (f panicJob) Do(ctx context.Context) error {
	panic("fail")
}

type fakeJobManager struct {
	hasResult bool
	listFail  bool
}

func (f fakeJobManager) GetName() string {
	return "jm"
}

func (f fakeJobManager) ListJob(ctx context.Context) ([]Job, error) {
	if f.listFail {
		return nil, fmt.Errorf("mock fail")
	}
	if f.hasResult {
		return []Job{fakeJob{}}, nil
	}
	return nil, nil
}

func Test_isValidOrg(t *testing.T) {
	type args struct {
		org *user_service.OrgInfo
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			args: args{
				org: &user_service.OrgInfo{
					Valid:   true,
					Expires: 1576060843,
				},
			},
		},
		{
			args: args{
				org: &user_service.OrgInfo{
					Id: 1,
				},
			},
		},
		{
			args: args{
				org: &user_service.OrgInfo{
					Id:    8888,
					Valid: false,
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &jobService{
				nowTimeFunc: func() time.Time {
					t, _ := time.Parse("2006-01-02 15:04:05", "2019-12-04 15:09:46")
					return t
				},
			}
			if got := s.isValidOrg(tt.args.org); got != tt.want {
				t.Errorf("isValidOrg() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_jobService_Run(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	type fields struct {
		redisClient redis.UniversalClient
		logger      slog.Logger
		orgClient   organization.Client
		lockBlock   newLockFunc
	}
	tests := []struct {
		name    string
		fields  fields
		orgList []*user_service.OrgInfo
		orgErr  error
	}{
		{
			name: "",
			orgList: []*user_service.OrgInfo{
				{
					Id:       8888,
					Expires:  0,
					CreateAt: "",
					Valid:    true,
				},
			},
			orgErr: nil,
		},
		{
			name:   "",
			orgErr: fmt.Errorf("mock fail"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &jobService{
				redisClient: tt.fields.redisClient,
				logger:      slog.Noop(),
				orgList:     tt.orgList,
				lockBlock:   LockFunc,
				timerConfig: config.TimerConfig{LockExpiration: 10},
				jobManager:  fakeJobManager{},
			}
			s.Run(context.Background())
		})
	}
}

func Test_jobService_jobWrapper(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()
	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "defaultUser"})
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		redisClient redis.UniversalClient
		logger      slog.Logger
		orgClient   organization.Client
		lockBlock   newLockFunc
		timerConfig config.TimerConfig
	}
	type args struct {
		ctx context.Context
		job Job
	}
	tests := []struct {
		name   string
		fields fields
		args   args

		searchErr error
	}{
		{
			name: "lock fail",
			fields: fields{
				timerConfig: config.TimerConfig{
					LockExpiration: 30,
				},
			},
			args: args{
				ctx: ctx,
				job: fakeJob{jobFail: false},
			},
		},
		{
			name: "unlock fail",
			fields: fields{
				timerConfig: config.TimerConfig{
					LockExpiration: 20,
				},
			},
			args: args{
				ctx: ctx,
				job: fakeJob{jobFail: false},
			},
		},
		{
			name: "lock not acquired",
			fields: fields{
				timerConfig: config.TimerConfig{
					LockExpiration: 10,
				},
			},
			args: args{
				ctx: ctx,
				job: fakeJob{jobFail: false},
			},
		},
		{
			name: "job fail",
			fields: fields{
				timerConfig: config.TimerConfig{
					LockExpiration: 40,
				},
			},
			args: args{
				ctx: ctx,
				job: fakeJob{jobFail: true},
			},
			searchErr: fmt.Errorf("mockf ail"),
		},
		{
			name: "panic",
			fields: fields{
				timerConfig: config.TimerConfig{},
			},
			args: args{
				ctx: ctx,
				job: panicJob{},
			},
		},
	}
	for _, tt := range tests {
		wg := &sync.WaitGroup{}
		t.Run(tt.name, func(t *testing.T) {
			s := &jobService{
				redisClient: tt.fields.redisClient,
				logger:      slog.Noop(),
				orgClient:   tt.fields.orgClient,
				lockBlock:   LockFunc,
				timerConfig: tt.fields.timerConfig,
				nowTimeFunc: timeutil.NowTime,
			}
			wg.Add(1)
			s.jobWrapper(tt.args.ctx, tt.args.job, wg)
		})
		wg.Wait()
	}
}

func Test_jobService_handleJobManager(t *testing.T) {
	ctx := context.Background()
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "defaultUser"})
	ctx = logctx.WithLogger(ctx, slog.Noop())

	type fields struct {
		redisClient redis.UniversalClient
		logger      slog.Logger
		orgClient   organization.Client
		jobManagers []JobManager
		lockBlock   newLockFunc
		timeNowFunc timeutil.NowTimeFunc
		timerConfig config.TimerConfig
	}
	type args struct {
		ctx     context.Context
		manager JobManager
	}
	tests := []struct {
		name   string
		fields fields
		args   args
	}{
		{
			name:   "no job",
			fields: fields{},
			args: args{
				ctx:     ctx,
				manager: fakeJobManager{},
			},
		},
		{
			name:   "normal",
			fields: fields{},
			args: args{
				ctx: ctx,
				manager: fakeJobManager{
					hasResult: true,
				},
			},
		},
		{
			name:   "list job fail",
			fields: fields{},
			args: args{
				ctx: ctx,
				manager: fakeJobManager{
					listFail: true,
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &jobService{
				redisClient: tt.fields.redisClient,
				logger:      slog.Noop(),
				lockBlock:   LockFunc,
				timerConfig: config.TimerConfig{LockExpiration: 10},
				jobManager:  fakeJobManager{},
				nowTimeFunc: timeutil.NowTime,
			}
			s.handleJobManager(tt.args.ctx, tt.args.manager)
		})
	}
}

func TestNewTimerJob(t *testing.T) {
	type args struct {
		redisClient redis.UniversalClient
		logger      slog.Logger
		orgClient   organization.Client
		lockBlock   newLockFunc
		timerConfig config.TimerConfig
		jobManager  JobManager
		orgList     []*user_service.OrgInfo
		mgoSession  *mgo.Session
	}
	tests := []struct {
		name string
		args args
		want *jobService
	}{
		{
			name: "",
			args: args{},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewTimerJob(tt.args.redisClient, tt.args.logger, tt.args.lockBlock, tt.args.timerConfig, tt.args.jobManager, tt.args.orgList, 0)
		})
	}
}

func Test_jobService_GetInternal(t *testing.T) {
	type fields struct {
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
	tests := []struct {
		name   string
		fields fields
		want   int
	}{
		{
			name:   "",
			fields: fields{internal: 10},
			want:   10,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &jobService{
				redisClient: tt.fields.redisClient,
				logger:      tt.fields.logger,
				orgClient:   tt.fields.orgClient,
				jobManager:  tt.fields.jobManager,
				lockBlock:   tt.fields.lockBlock,
				nowTimeFunc: tt.fields.nowTimeFunc,
				timerConfig: tt.fields.timerConfig,
				internal:    tt.fields.internal,
				orgList:     tt.fields.orgList,
				mgoSession:  tt.fields.mgoSession,
			}
			if got := s.GetInternal(); got != tt.want {
				t.Errorf("GetInternal() = %v, want %v", got, tt.want)
			}
		})
	}
}
