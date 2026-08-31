package report_task

import (
	"context"
	"fmt"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"go.mongodb.org/mongo-driver/bson/primitive"

	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/timer"
	logctx "go.easyops.local/slog/context"
)

var _ timer.JobManager = (*recordJobManager)(nil)
var _ timer.Job = (*recordJobManager)(nil)

func NewRecordJobManager(
	centerData history.CenterData,
	historyRecorder history.Recorder,
	mongoClient pmongo.ClientInterface,
) timer.JobManager {
	return &recordJobManager{
		centerData:      centerData,
		historyRecorder: historyRecorder,
		mongoClient:     mongoClient,
	}
}

type recordJobManager struct {
	centerData      history.CenterData
	historyRecorder history.Recorder
	mongoClient     pmongo.ClientInterface
}

func (r recordJobManager) GetName() string {
	return "record_task"
}

func (r recordJobManager) ListJob(ctx context.Context) ([]timer.Job, error) {
	return []timer.Job{r}, nil
}

func (r recordJobManager) GetJobName() string {
	return "record_job"
}

func (r recordJobManager) GetLockName(org int) string {
	return fmt.Sprintf("fintech:report:record:%d:%s", org, r.GetJobName())
}

func (r recordJobManager) makeQuery() []primitive.M {
	return []primitive.M{
		{
			"$group": primitive.M{
				"_id":   "$objectId",
				"total": primitive.M{"$sum": 1},
			},
		},
	}
}

type objCount struct {
	Id    string `bson:"_id"`
	Total int    `bson:"total"`
}

func (r recordJobManager) Do(ctx context.Context) error {
	logger := logctx.MustGetLogger(ctx)
	itemList := make([]objCount, 0)

	err := r.centerData.Aggregate(ctx, r.makeQuery(), &itemList)
	if err != nil {
		logger.Errorf("count report instance fail, error: %s", err.Error())
		return err
	}

	objectCount := make([]history.ReportCount, len(itemList))
	for idx, item := range itemList {
		objectCount[idx] = history.ReportCount{
			Total:      item.Total,
			ObjectId:   item.Id,
			InstanceId: "record_job",
			TaskId:     "record_job",
		}
	}
	err = r.historyRecorder.Save(ctx, objectCount...)
	if err != nil {
		logger.Errorf("record report instance fail, error: %s", err.Error())
		return err
	}
	logger.Infof("record report instance success, data: %+v", itemList)
	return nil
}
