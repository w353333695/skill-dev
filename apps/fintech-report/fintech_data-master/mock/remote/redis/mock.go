package redis

//go:generate mockgen -package=redis -mock_names=ClientV8=MockRedisClientV8 -destination=mock_redis_client.go go.easyops.local/redis-helper/v8/redis ClientV8
