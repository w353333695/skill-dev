package redis

//go:generate mockgen -package=redis -mock_names=Lock=MockRedisLock -destination=mock_lock.go go.easyops.local/redis-helper/v8/lock Lock
