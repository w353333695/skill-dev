package history

import (
	"context"

	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	monthly_collection_service "go.easyops.local/contracts/protorepo-monthly_collection_service"
	"go.easyops.local/contracts/protorepo-monthly_collection_service/document"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/extends/typeutil"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

func NewTaskHistory(monthlyClient *monthly_collection_service.Client) TaskHistory {
	return &historyService{
		monthlyClient: monthlyClient,
		nowTimeFunc:   timeutil.NowTime,
	}
}

const (
	collNameTask     = "fintech_report_task"
	collNameBranch   = "fintech_report_branch"
	collNameInstance = "fintech_report_instance"
)

type TaskHistory interface {
	GetTask(ctx context.Context, taskId string) (*fintech_data.ReportTask, error)
	UpdateTask(ctx context.Context, taskId string, task *fintech_data.ReportTask) error
	CreateTask(ctx context.Context, task *fintech_data.ReportTask) (string, error)
	SearchTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportTask, int, error)
	SearchOneTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int) (*fintech_data.ReportTask, error)
	SearchAllTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportTask, error)

	SearchBranch(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportBranch, int, error)
	SearchAllBranch(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportBranch, error)
	CreateBranch(ctx context.Context, branch *fintech_data.ReportBranch) (string, error)
	BatchCreateBranch(ctx context.Context, branchList []*fintech_data.ReportBranch) ([]string, error)
	UpdateBranch(ctx context.Context, innerId string, branch *fintech_data.ReportBranch, updateFields []string) error

	GetInstance(ctx context.Context, dataId string) (*fintech_data.ReportInstance, error)
	SearchInstance(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportInstance, int, error)
	SearchInstanceAll(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportInstance, error)
	SearchInstanceLimit(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int, nextId string) (*InstanceLimitResult, error)
	BatchCreateInstance(ctx context.Context, branchList []*fintech_data.ReportInstance) ([]string, error)
	UpdateInstanceByFilter(ctx context.Context, query []*monthly_model.QueryItem, instance *fintech_data.ReportInstance, updateFields []string, st int, et int) error
	UpdateInstance(ctx context.Context, dataId string, instance *fintech_data.ReportInstance, updateFields []string) error
}

type historyService struct {
	monthlyClient *monthly_collection_service.Client
	nowTimeFunc   timeutil.NowTimeFunc
}

func convertTask(data *types.Struct) (*fintech_data.ReportTask, error) {
	reportTask := &fintech_data.ReportTask{}
	err := typeutil.StructToPbMessage(data, reportTask)
	if err != nil {
		return nil, err
	}
	reportTask.TaskId = data.Fields["_id"].GetStringValue()
	if reportTask.DataTotal > 0 {
		reportTask.SuccessRate = float32(reportTask.SuccessTotal) / float32(reportTask.DataTotal)
	}
	return reportTask, nil
}

func (s *historyService) GetTask(ctx context.Context, taskId string) (*fintech_data.ReportTask, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.GETRequest{
		Id:             taskId,
		CollectionName: collNameTask,
	}
	resp, err := s.monthlyClient.Document.GET(ctx, req)
	if err != nil {
		logger.Errorf("get task fail, taskId: %s, error: %s", taskId, err.Error())
		return nil, err
	}
	return convertTask(resp)
}

func (s *historyService) SearchTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportTask, int, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.SearchRequest{
		CollectionName: collNameTask,
		Page:           int32(page),
		PageSize:       int32(pageSize),
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
	}
	resp, err := s.monthlyClient.Document.Search(ctx, req)
	if err != nil {
		logger.Errorf("search task fail, error: %s", err.Error())
		return nil, 0, err
	}
	taskList := make([]*fintech_data.ReportTask, 0, len(resp.List))
	for _, data := range resp.List {
		reportTask, err := convertTask(data)
		if err != nil {
			logger.Errorf("task convert fail, data: %v, error: %s", data, err.Error())
			return nil, 0, err
		}
		taskList = append(taskList, reportTask)
	}
	return taskList, int(resp.Total), nil
}

func (s *historyService) SearchOneTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int) (*fintech_data.ReportTask, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.LimitRequest{
		CollectionName: collNameTask,
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
		Limit:          1,
	}
	resp, err := s.monthlyClient.Document.Limit(ctx, req)
	if err != nil {
		logger.Errorf("search task one fail, error: %s", err.Error())
		return nil, err
	}
	if len(resp.List) == 0 {
		return nil, nil
	}
	reportTask, err := convertTask(resp.List[0])
	if err != nil {
		logger.Errorf("task convert fail, data: %v, error: %s", resp.List[0], err.Error())
		return nil, err
	}
	return reportTask, nil
}

func taskToData(task *fintech_data.ReportTask) *types.Struct {
	data := typeutil.PbMessageToStruct(task)
	delete(data.Fields, "taskId")
	return data
}

func (s *historyService) CreateTask(ctx context.Context, task *fintech_data.ReportTask) (string, error) {
	data := taskToData(task)
	resp, err := s.monthlyClient.Document.Create(ctx, &document.CreateRequest{
		CollectionName: collNameTask,
		Timestamp:      int32(s.nowTimeFunc().Unix()),
		Document:       data,
	})
	if err != nil {
		return "", err
	}
	return resp.Id, nil
}

func (s *historyService) UpdateTask(ctx context.Context, taskId string, task *fintech_data.ReportTask) error {
	_, err := s.monthlyClient.Document.Update(ctx, &document.UpdateRequest{
		CollectionName: collNameTask,
		Id:             taskId,
		Update:         taskToData(task),
	})
	return err
}

func (s *historyService) SearchAllTask(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportTask, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.LimitRequest{
		CollectionName: collNameTask,
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
		Limit:          int32(limit),
	}
	var taskList []*fintech_data.ReportTask
	var nextId string
	for {
		req.NextId = nextId
		resp, err := s.monthlyClient.Document.Limit(ctx, req)
		if err != nil {
			logger.Errorf("search report task fail, nextId: %s , error: %s", nextId, err.Error())
			return nil, err
		}

		for _, data := range resp.List {
			task, err := convertTask(data)
			if err != nil {
				logger.Errorf("convert report task fail, data: %v , error: %s", data, err.Error())
				return nil, err
			}
			taskList = append(taskList, task)
		}

		logger.Infof("search report task success, total: %d", len(taskList))
		nextId = resp.NextId
		if !resp.HaveMore {
			break
		}
	}
	return taskList, nil
}
