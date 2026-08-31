package dispatch

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/golang/mock/gomock"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/fill_instance"
	fill_instance2 "go.easyops.local/fintech_data/mock/fill_instance"
	redismock "go.easyops.local/fintech_data/mock/remote/redis"
	"go.easyops.local/gin-giraffe/pkg/orguser"

	redislock "go.easyops.local/redis-helper/v8/lock"
	"go.easyops.local/slog"
)

type fakeLock struct {
	lockErr   error
	unLockErr error
	doPanic   bool
}

func (f *fakeLock) Lock() error {
	return f.lockErr
}

func (f *fakeLock) Unlock() error {
	return f.unLockErr
}

func (f *fakeLock) LockContext(ctx context.Context) error {
	return f.lockErr
}

func (f *fakeLock) UnlockContext(ctx context.Context) error {
	return f.unLockErr
}

func (f *fakeLock) Extend(ctx context.Context, ttl time.Duration) error {
	return f.lockErr
}

func Test_WakeUpJob_Success(t *testing.T) {
	ctrl := gomock.NewController(t)
	redisMock := redismock.NewMockRedisClientV8(ctrl)
	key1 := fmt.Sprintf("%saaa:bbb", queuePrefix)
	key2 := fmt.Sprintf("%s8888:server", queuePrefix)
	redisMock.EXPECT().Scan(gomock.Any(), uint64(0), fmt.Sprintf("%s*", queuePrefix), int64(100)).Return(redis.NewScanCmdResult([]string{key1}, 10, nil)).Times(1)
	redisMock.EXPECT().Scan(gomock.Any(), uint64(10), fmt.Sprintf("%s*", queuePrefix), int64(100)).Return(redis.NewScanCmdResult([]string{key2}, 0, nil)).Times(1)
	res1 := redis.NewStringSliceResult([]string{}, nil)
	redisMock.EXPECT().LRange(gomock.Any(), key2, int64(-1), int64(-1)).Return(res1).Times(1)
	redisMock.EXPECT().Del(gomock.Any(), key2).Return(redis.NewIntResult(1, nil)).Times(1)
	lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
		return &fakeLock{}
	}
	dispatcher := &dispatchImp{
		redisClient: redisMock,
		fillService: nil,
		lockBlock:   lb,
		nowTimeFunc: timeutil.NowTime,
		runningJob:  map[string]struct{}{},
		mutex:       &sync.Mutex{},
		config:      config.FillInstance{QueueActiveTime: 2},
		logger:      slog.Noop(),
	}
	err := dispatcher.WakeUpJobs()
	if err != nil {
		t.Errorf("WakeUpJobs fail")
	}
	time.Sleep(1 * time.Second)
	for dispatcher.HasRunningJob() {
		time.Sleep(1 * time.Second)
	}
}

func Test_WakeUpJob_Fail(t *testing.T) {
	ctrl := gomock.NewController(t)
	redisMock := redismock.NewMockRedisClientV8(ctrl)
	redisMock.EXPECT().Scan(gomock.Any(), uint64(0), fmt.Sprintf("%s*", queuePrefix), int64(100)).Return(redis.NewScanCmdResult(nil, 0, fmt.Errorf("mock fail"))).Times(1)
	lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
		return &fakeLock{}
	}
	dispatcher := &dispatchImp{
		redisClient: redisMock,
		fillService: nil,
		lockBlock:   lb,
		nowTimeFunc: timeutil.NowTime,
		runningJob:  map[string]struct{}{},
		mutex:       &sync.Mutex{},
		config:      config.FillInstance{QueueActiveTime: 2},
		logger:      slog.Noop(),
	}
	err := dispatcher.WakeUpJobs()
	if err == nil {
		t.Errorf("WakeUpJobs fail")
	}
}

func Test_PushJob_Success(t *testing.T) {
	queueKey := "fintech_data:fill_instance:job:8888:server"
	itemList := []fill_instance.ProcessItem{
		{
			InstanceId:   "id1",
			ChangeFields: nil,
		},
		{
			InstanceId:   "id2",
			ChangeFields: nil,
		},
		{
			InstanceId:   "id3",
			ChangeFields: nil,
		},
	}
	ctrl := gomock.NewController(t)
	redisMock := redismock.NewMockRedisClientV8(ctrl)
	serviceMock := fill_instance2.NewMockService(ctrl)

	lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
		return &fakeLock{}
	}

	ctx := orguser.WithUser(context.Background(), orguser.OrgUser{Org: 8888, User: "easyops"})
	dispatcher := &dispatchImp{
		redisClient: redisMock,
		fillService: serviceMock,
		lockBlock:   lb,
		nowTimeFunc: timeutil.NowTime,
		runningJob:  map[string]struct{}{},
		mutex:       &sync.Mutex{},
		config:      config.FillInstance{QueueActiveTime: 5},
		logger:      slog.Noop(),
	}

	// get last item
	item1 := fill_instance.ProcessItem{PushTime: timeutil.NowTime().Unix(), InstanceId: "id1"}
	res1 := redis.NewStringSliceResult([]string{item1.ToString()}, nil)
	redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(-1), int64(-1)).Return(res1).Times(2)

	// 获取所有数据
	strRes := make([]string, len(itemList))
	for idx, i := range itemList {
		strRes[idx] = i.ToString()
	}
	res2 := redis.NewStringSliceResult(strRes, nil)
	redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res2).Times(1)

	// 删除队列
	redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntCmd(ctx)).Times(1)

	// 上报数据
	serviceMock.EXPECT().FillInstance(gomock.Any(), "server", itemList).Return(nil).Times(1)

	for _, item := range itemList {
		// mock push
		redisMock.EXPECT().RPush(gomock.Any(), queueKey, gomock.Any()).Return(&redis.IntCmd{}).Times(1)
		go dispatcher.PushJob(ctx, "server", item)
	}
	time.Sleep(1 * time.Second)
	for dispatcher.HasRunningJob() {
		time.Sleep(1 * time.Second)
	}
}

func Test_controllerImp_PushJob_Error(t *testing.T) {
	ctrl := gomock.NewController(t)
	ctx := orguser.WithUser(context.Background(), orguser.OrgUser{Org: 8888, User: "easyops"})
	type fields struct {
		redisClient redis.Client
		fillService fill_instance.Service
		lockBlock   newLockFunc
		nowTimeFunc func() time.Time
		runningJob  map[string]struct{}
		mutex       *sync.Mutex
		config      config.FillInstance
		logger      slog.Logger
	}
	type args struct {
		ctx      context.Context
		objectId string
		item     fill_instance.ProcessItem
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool
	}{
		{
			args: args{
				ctx:      ctx,
				objectId: "server",
				item: fill_instance.ProcessItem{
					InstanceId: "id1",
				},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			redisMock := redismock.NewMockRedisClientV8(ctrl)
			queueKey := "fintech_data:fill_instance:job:8888:server"
			redisMock.EXPECT().RPush(gomock.Any(), queueKey, gomock.Any()).Return(redis.NewIntResult(0, fmt.Errorf("mock fail"))).Times(1)
			c := &dispatchImp{
				redisClient: redisMock,
				nowTimeFunc: timeutil.NowTime,
				logger:      slog.Noop(),
			}
			if err := c.PushJob(tt.args.ctx, tt.args.objectId, tt.args.item); (err != nil) != tt.wantErr {
				t.Errorf("PushJob() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_worker_checkJob_Error(t *testing.T) {
	ctrl := gomock.NewController(t)
	ctx := orguser.WithUser(context.Background(), orguser.OrgUser{Org: 8888, User: "easyops"})
	queueKey := "fintech_data:fill_instance:job:8888:server"
	redisMock := redismock.NewMockRedisClientV8(ctrl)
	type fields struct {
		redisClient redis.Client
		fillService fill_instance.Service
		lockBlock   newLockFunc
		ctx         context.Context
		objectId    string
		config      config.FillInstance
		logger      slog.Logger
		nowTimeFunc func() time.Time
		stopped     chan struct{}
	}
	tests := []struct {
		name     string
		fields   fields
		mockFunc func()
	}{
		{
			name: "get item fail",
			mockFunc: func() {
				res := redis.NewStringSliceResult(nil, fmt.Errorf("mock fail"))
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(-1), int64(-1)).Return(res).Times(1)
			},
		},
		{
			name: "no item",
			mockFunc: func() {
				res := redis.NewStringSliceResult(nil, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(-1), int64(-1)).Return(res).Times(1)
				redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntResult(0, nil)).Times(1)
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.mockFunc()
			w := &worker{
				redisClient: redisMock,
				fillService: tt.fields.fillService,
				lockBlock:   tt.fields.lockBlock,
				ctx:         ctx,
				objectId:    "server",
				config:      tt.fields.config,
				logger:      slog.Noop(),
				nowTimeFunc: tt.fields.nowTimeFunc,
				stopped:     make(chan struct{}),
			}
			go w.checkJob()
			<-w.stopped
		})
	}
}

func Test_worker_runFill_Error(t *testing.T) {
	ctrl := gomock.NewController(t)
	ctx := orguser.WithUser(context.Background(), orguser.OrgUser{Org: 8888, User: "easyops"})
	queueKey := "fintech_data:fill_instance:job:8888:server"
	redisMock := redismock.NewMockRedisClientV8(ctrl)
	serviceMock := fill_instance2.NewMockService(ctrl)
	type fields struct {
		redisClient redis.Client
		fillService fill_instance.Service
		lockBlock   newLockFunc
		ctx         context.Context
		objectId    string
		config      config.FillInstance
		logger      slog.Logger
		nowTimeFunc func() time.Time
		stopped     chan struct{}
	}
	tests := []struct {
		name     string
		fields   fields
		mockFunc func() newLockFunc
	}{
		{
			name: "lock fail",
			mockFunc: func() newLockFunc {
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{
						lockErr: fmt.Errorf("mock fail"),
					}
				}
				return lb
			},
		},
		{
			name: "lock not acquired",
			mockFunc: func() newLockFunc {
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{
						lockErr: redislock.ErrLockNotAcquired,
					}
				}
				return lb
			},
		},
		{
			name: "unlock fail",
			mockFunc: func() newLockFunc {
				res1 := redis.NewStringSliceResult([]string{}, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntResult(0, fmt.Errorf("mock fail"))).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{
						unLockErr: fmt.Errorf("mock fail"),
					}
				}
				return lb
			},
		},
		{
			name:   "fill fail",
			fields: fields{},
			mockFunc: func() newLockFunc {
				item := fill_instance.ProcessItem{InstanceId: "id1"}
				res1 := redis.NewStringSliceResult([]string{item.ToString()}, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntResult(0, nil)).Times(1)
				serviceMock.EXPECT().FillInstance(gomock.Any(), "server", []fill_instance.ProcessItem{item}).Return(fmt.Errorf("mock fail")).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{}
				}
				return lb
			},
		},
		{
			name:   "empty item",
			fields: fields{},
			mockFunc: func() newLockFunc {
				res1 := redis.NewStringSliceResult([]string{}, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntResult(0, nil)).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{}
				}
				return lb
			},
		},
		{
			name:   "delete queue fail",
			fields: fields{},
			mockFunc: func() newLockFunc {
				res1 := redis.NewStringSliceResult([]string{}, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				redisMock.EXPECT().Del(gomock.Any(), queueKey).Return(redis.NewIntResult(0, fmt.Errorf("mock fail"))).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{}
				}
				return lb
			},
		},
		{
			name:   "range fail",
			fields: fields{},
			mockFunc: func() newLockFunc {
				res1 := redis.NewStringSliceResult(nil, fmt.Errorf("mock fail"))
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{}
				}
				return lb
			},
		},
		{
			name:   "convert fail",
			fields: fields{},
			mockFunc: func() newLockFunc {
				res1 := redis.NewStringSliceResult([]string{"error"}, nil)
				redisMock.EXPECT().LRange(gomock.Any(), queueKey, int64(0), int64(-1)).Return(res1).Times(1)
				lb := func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
					return &fakeLock{}
				}
				return lb
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			lb := tt.mockFunc()
			w := &worker{
				redisClient: redisMock,
				fillService: serviceMock,
				lockBlock:   lb,
				ctx:         ctx,
				objectId:    "server",
				config:      tt.fields.config,
				logger:      slog.Noop(),
				nowTimeFunc: timeutil.NowTime,
			}
			w.runFill()
		})
	}
}

func TestNewDispatcher(t *testing.T) {
	type args struct {
		redisClient redis.UniversalClient
		fillService fill_instance.Service
		lockBlock   newLockFunc
		config      config.FillInstance
		logger      slog.Logger
	}
	tests := []struct {
		name string
		args args
		want Dispatcher
	}{
		{
			name: "",
			args: args{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewDispatcher(tt.args.logger, tt.args.redisClient, tt.args.fillService, tt.args.config, tt.args.lockBlock)
		})
	}
}
