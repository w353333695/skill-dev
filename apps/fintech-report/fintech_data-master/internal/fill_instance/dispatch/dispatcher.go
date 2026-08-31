package dispatch

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"

	"go.easyops.local/fintech_data/internal/config"
	"go.easyops.local/fintech_data/internal/extends/idutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	redislock "go.easyops.local/redis-helper/v8/lock"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

type newLockFunc func(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock

func NewDispatcher(
	logger slog.Logger,
	redisClient redis.UniversalClient,
	fillService fill_instance.Service,
	config config.FillInstance,
	lockBlock newLockFunc,
) Dispatcher {
	return &dispatchImp{
		redisClient: redisClient,
		fillService: fillService,
		lockBlock:   lockBlock,
		nowTimeFunc: timeutil.NowTime,
		mutex:       &sync.Mutex{},
		config:      config,
		logger:      logger,
		runningJob:  map[string]struct{}{},
	}
}

type Dispatcher interface {
	WakeUpJobs() error
	PushJob(ctx context.Context, objectId string, item fill_instance.ProcessItem) error
}

type dispatchImp struct {
	redisClient redis.UniversalClient
	fillService fill_instance.Service
	lockBlock   newLockFunc
	nowTimeFunc func() time.Time
	runningJob  map[string]struct{}
	mutex       *sync.Mutex
	config      config.FillInstance
	logger      slog.Logger
}

type worker struct {
	redisClient redis.UniversalClient
	fillService fill_instance.Service
	lockBlock   newLockFunc
	ctx         context.Context
	objectId    string
	config      config.FillInstance
	logger      slog.Logger
	nowTimeFunc func() time.Time
	stopped     chan struct{}
}

const queuePrefix = "fintech_data:fill_instance:job:"

func getQueueKey(ctx context.Context, objectId string) string {
	orgUser, _ := orguser.FromContext(ctx)
	return fmt.Sprintf("%s%d:%s", queuePrefix, orgUser.Org, objectId)
}

// 唤起那些有队列但是没有定时检查任务的job
func (i *dispatchImp) WakeUpJobs() error {
	var cursor uint64
	var keysList []string
	for {
		cmd := i.redisClient.Scan(context.Background(), cursor, fmt.Sprintf("%s*", queuePrefix), 100)
		if cmd.Err() != nil {
			return cmd.Err()
		}
		keys, newCursor := cmd.Val()
		keysList = append(keysList, keys...)
		if newCursor == 0 {
			break
		}
		cursor = newCursor
	}

	for _, key := range keysList {
		pattern := strings.ReplaceAll(key, queuePrefix, "")
		if strings.Contains(pattern, ":") {
			patterns := strings.Split(pattern, ":")
			org, err := strconv.ParseInt(patterns[0], 10, 64)
			if err != nil {
				i.logger.Errorf("invalid queue %s", key)
				continue
			}
			ctx := orguser.WithUser(context.Background(), orguser.OrgUser{Org: int(org), User: "defaultUser"})
			objectId := patterns[1]
			i.startCheckTimer(ctx, objectId)
			i.logger.Infof("wake up queue %s job", key)
		}
	}
	return nil
}

// 1.将任务放入队列 2.开启定时检查任务
func (i *dispatchImp) PushJob(ctx context.Context, objectId string, item fill_instance.ProcessItem) error {
	item.PushTime = i.nowTimeFunc().Unix()
	queueKey := getQueueKey(ctx, objectId)
	cmd := i.redisClient.RPush(context.Background(), queueKey, item.ToString())
	if cmd.Err() != nil {
		i.logger.Errorf("push item to queue fail, item: %+v, error: %s", item, cmd.Err().Error())
		return cmd.Err()
	}
	i.startCheckTimer(ctx, objectId)
	return nil
}

func (i *dispatchImp) jobExisted(key string) bool {
	_, ok := i.runningJob[key]
	return ok
}

// 启动定时任务
func (i *dispatchImp) startCheckTimer(ctx context.Context, objectId string) {
	i.mutex.Lock()
	defer i.mutex.Unlock()
	if i.jobExisted(objectId) {
		return
	}
	orgUser, _ := orguser.FromContext(ctx)
	w := &worker{
		redisClient: i.redisClient,
		fillService: i.fillService,
		lockBlock:   i.lockBlock,
		ctx:         orguser.WithUser(context.Background(), orgUser),
		objectId:    objectId,
		config:      i.config,
		logger:      i.logger,
		nowTimeFunc: i.nowTimeFunc,
		stopped:     make(chan struct{}),
	}
	go w.checkJob()
	i.runningJob[objectId] = struct{}{}
	go i.stopJob(w)
}

func (i *dispatchImp) HasRunningJob() bool {
	return len(i.runningJob) > 0
}

func (i *dispatchImp) stopJob(w *worker) {
	for {
		select {
		case <-w.stopped:
			i.mutex.Lock()
			delete(i.runningJob, w.objectId)
			i.mutex.Unlock()
		}
	}
}

func (w *worker) stop() {
	w.stopped <- struct{}{}
}

// 定时任务调度
func (w *worker) checkJob() {
	defer w.stop()
	for {
		// 获取队列最后一个记录
		lastItem, err := w.getLastItem()
		if err != nil {
			w.logger.Errorf("get object %s queue last item fail, error: %s", err.Error())
			return
		}
		if lastItem == nil {
			w.logger.Infof("object %s queue has no item", w.objectId)
			_ = w.delQueue()
			return
		}
		// 是否可以执行
		diff := int(w.nowTimeFunc().Unix() - lastItem.PushTime)
		if diff >= w.config.QueueActiveTime {
			w.runFill()
			return
		}
		// 下次循环
		sleepTime := w.config.QueueActiveTime - diff
		w.logger.Infof("check object %s queue after %d second", w.objectId, sleepTime)
		time.Sleep(time.Duration(sleepTime) * time.Second)
	}
}

// 到redis获取数据列表执行实例填充任务
func (w *worker) runFill() {
	jobId := idutil.Guid()
	logger, ctx := logctx.WithField(w.ctx, w.logger, "jobId", jobId)
	logger.Infof("start to running fill instance, object: %s, jobId: %s", w.objectId, jobId)
	items, err := w.popItemWrapper()
	if err != nil {
		return
	}
	if len(items) == 0 {
		logger.Infof("no item need to fill, object: %s", w.objectId)
		return
	}
	err = w.fillService.FillInstance(ctx, w.objectId, items)
	if err != nil {
		logger.Errorf("running fill instance fail, object: %s, error: %s", w.objectId, err.Error())
		return
	}
	logger.Infof("running fill instance done, object: %s", w.objectId)
}

func (w *worker) newMutex() redislock.Lock {
	opt := &redislock.Options{
		Expiration: 30 * time.Minute,
		RetryCount: 1,
	}
	value := w.nowTimeFunc().Format(timeutil.TimeFormat)
	lockName := fmt.Sprintf("%s:lock", getQueueKey(w.ctx, w.objectId))
	return w.lockBlock(lockName, value, w.redisClient, opt)
}

func (w *worker) popItemWrapper() ([]fill_instance.ProcessItem, error) {
	mutex := w.newMutex()
	if err := mutex.Lock(); err != nil {
		if err == redislock.ErrLockNotAcquired {
			w.logger.Infof("object %s lock not acquired", w.objectId)
			return nil, nil
		}
		w.logger.Errorf("object %s lock error: %s", w.objectId, err.Error())
		return nil, err
	}
	// 异常捕获
	defer func() {
		err := mutex.Unlock()
		if err != nil {
			w.logger.Errorf("object %s unlock error: %s", w.objectId, err.Error())
		}
	}()
	return w.popAllItem()
}

// 获取队列里所有数据，并删除队列，操作需要加锁
func (w *worker) popAllItem() ([]fill_instance.ProcessItem, error) {
	key := getQueueKey(w.ctx, w.objectId)
	cmd := w.redisClient.LRange(context.Background(), key, 0, -1)
	if cmd.Err() != nil {
		w.logger.Errorf("get item form queue fail, object: %s, error: %s", w.objectId, cmd.Err())
		return nil, cmd.Err()
	}
	items := make([]fill_instance.ProcessItem, 0)
	for _, val := range cmd.Val() {
		item := fill_instance.ProcessItem{}
		err := json.Unmarshal([]byte(val), &item)
		if err != nil {
			w.logger.Errorf("convert item fail, object: %s, value: %s, error: %s", w.objectId, val, err.Error())
			return nil, err
		}
		items = append(items, item)
	}

	// 删除队列
	err := w.delQueue()
	if err != nil {
		return nil, err
	}
	return items, nil
}

func (w *worker) delQueue() error {
	key := getQueueKey(w.ctx, w.objectId)
	delCmd := w.redisClient.Del(context.Background(), key)
	if delCmd.Err() != nil {
		w.logger.Errorf("delete queue fail, object: %s, error: %s", w.objectId, delCmd.Err())
		return delCmd.Err()
	}
	return nil
}

// 获取队列里最后一个
func (w *worker) getLastItem() (*fill_instance.ProcessItem, error) {
	key := getQueueKey(w.ctx, w.objectId)
	cmd := w.redisClient.LRange(context.Background(), key, -1, -1)
	err := cmd.Err()
	if err != nil {
		return nil, err
	}
	if len(cmd.Val()) == 0 {
		return nil, nil
	}
	item := &fill_instance.ProcessItem{}
	err = json.Unmarshal([]byte(cmd.Val()[0]), item)
	return item, err
}
