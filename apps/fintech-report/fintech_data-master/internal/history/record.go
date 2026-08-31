package history

import (
	"context"

	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-data_exchange/store"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

const (
	historyTable = "easyops.FINTECH_REPORT_OBJ"
)

func NewRecorder(storeClient store.Client) Recorder {
	return &recorderImp{
		storeClient: storeClient,
		nowTimeFunc: timeutil.NowTime,
	}
}

type Recorder interface {
	Save(ctx context.Context, count ...ReportCount) error
}

type ReportCount struct {
	Total      int
	Inserted   int
	Updated    int
	Removed    int
	ObjectId   string
	InstanceId string // 上报模型配置id
	TaskId     string
	Failed     int
}

func (c ReportCount) IsEffective() bool {
	return c.Inserted != 0 || c.Updated != 0 || c.Removed != 0 || c.Failed != 0
}

type recorderImp struct {
	storeClient store.Client
	nowTimeFunc timeutil.NowTimeFunc
}

func (i *recorderImp) Save(ctx context.Context, count ...ReportCount) error {
	logger := logctx.MustGetLogger(ctx)
	if len(count) == 0 {
		return nil
	}

	orgUser, _ := orguser.FromContext(ctx)
	nowTime := i.nowTimeFunc()
	cols := []string{"org", "time", "objectId", "_ver", "_seriesId", "_job", "instanceId", "total", "inserted", "updated", "removed", "failed"}
	rowList := make([]*types.Struct, len(count))
	for idx, c := range count {
		row := map[string]interface{}{
			"org":        orgUser.Org,
			"time":       nowTime.Unix() * 1000, //毫秒级别
			"objectId":   c.ObjectId,
			"_ver":       nowTime.UnixNano(), //用当前时间戳
			"_seriesId":  c.InstanceId,
			"_job":       c.TaskId, // 上报的任务id
			"instanceId": c.InstanceId,
			"total":      c.Total,
			"inserted":   c.Inserted,
			"updated":    c.Updated,
			"removed":    c.Removed,
			"failed":     c.Failed,
		}
		rowList[idx] = protostruct.ToStruct(row)
	}
	in := &store.ClickHouseInsertDataRequest{
		Model:   historyTable,
		Columns: cols,
		Data:    rowList,
	}
	_, err := i.storeClient.ClickHouseInsertData(ctx, in)
	if err != nil {
		logger.Infof("save report history fail, error: %s", err.Error())
		return err
	}
	logger.Infof("save report history: %+v", count)
	return nil
}
