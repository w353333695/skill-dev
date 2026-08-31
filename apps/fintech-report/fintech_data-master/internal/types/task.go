package types

import (
	"github.com/go-redis/redis/v8"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	redislock "go.easyops.local/redis-helper/v8/lock"
)

type CreateMethod string

const (
	ManualCreate   CreateMethod = "manual"
	TimerCreate    CreateMethod = "timer"
	TaskLockPrefix string       = "fintech_data:task:"
)

type NewLockFunc func(redisClient redis.UniversalClient, lockKey string, lockExpiration int) redislock.Lock

type CreateTaskRequest struct {
	GlobalConfig *fintech_data.ReportGlobalConfig
	ObjectConf   *fintech_data.ReportObjectConf
	Method       CreateMethod
}

const (
	StatusInitial        = "initial"
	StatusReporting      = "reporting"
	StatusPendingCheck   = "pendingCheck"
	StatusResulting      = "resulting"
	StatusConflict       = "conflict"
	StatusFail           = "fail"
	StatusSuccess        = "success"
	StatusWithWarn       = "warning"
	StatusNoReport       = "noReport"
	StatusPartialSuccess = "partialSuccess"

	FailTypeInitial      = "initial-fail"      // 任务初始化失败
	FailTypeReporting    = "reporting-fail"    // 任务上报时失败
	FailTypeRequestCheck = "requestCheck-fail" // 任务上报时失败
	FailTypeResult       = "result-fail"       // 上报结果失败
)

func IsEndStatus(status string) bool {
	switch status {
	case StatusFail, StatusSuccess, StatusWithWarn, StatusPartialSuccess, StatusConflict, StatusNoReport:
		return true
	}
	return false
}

func GetStatusByType(status string) []string {
	switch status {
	case "running":
		return []string{StatusReporting, StatusInitial, StatusResulting}
	default:
		return []string{status}
	}
}

func ConvertStatus(status string) string {
	switch status {
	case StatusSuccess:
		return "成功"
	case StatusPartialSuccess:
		return "部分成功"
	case StatusFail:
		return "失败"
	case StatusConflict:
		return "冲突"
	case StatusNoReport:
		return "暂无数据"
	case StatusInitial, StatusReporting, StatusResulting:
		return "执行中"
	default:
		return ""
	}
}

func ConvertInstanceStatus(status string) string {
	switch status {
	case StatusPendingCheck, StatusResulting:
		return "执行中"
	case FailTypeReporting, FailTypeRequestCheck, FailTypeResult:
		return "失败"
	case StatusSuccess:
		return "成功"
	case StatusWithWarn:
		return "警告"
	default:
		return ""
	}
}

// 获取优先级更高的状态
func SwitchMoreHighLevelStatus(status1 string, status2 string) string {
	statusLevelMap := map[string]int{
		StatusPendingCheck:   6,
		StatusResulting:      5,
		StatusPartialSuccess: 4,
		StatusFail:           3,
		StatusWithWarn:       2,
		StatusSuccess:        1,
	}

	finalStatus := status1
	if statusLevelMap[status1] < statusLevelMap[status2] {
		finalStatus = status2
	}
	return finalStatus
}
