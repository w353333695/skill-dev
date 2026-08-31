package history

import (
	"context"

	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/contracts/protorepo-monthly_collection_service/document"
	"go.easyops.local/fintech_data/internal/extends/typeutil"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

func (s *historyService) SearchBranch(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, st int, et int, page int, pageSize int) ([]*fintech_data.ReportBranch, int, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.SearchRequest{
		CollectionName: collNameBranch,
		Page:           int32(page),
		PageSize:       int32(pageSize),
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
	}
	resp, err := s.monthlyClient.Document.Search(ctx, req)
	if err != nil {
		logger.Errorf("search branch fail, error: %s", err.Error())
		return nil, 0, err
	}
	branchList := make([]*fintech_data.ReportBranch, 0, len(resp.List))
	for _, data := range resp.List {
		branch, err := convertBranch(data)
		if err != nil {
			logger.Errorf("branch convert fail, data: %v, error: %s", data, err.Error())
			return nil, 0, err
		}
		branchList = append(branchList, branch)
	}
	return branchList, int(resp.Total), nil
}

func (s *historyService) SearchAllBranch(ctx context.Context, query []*monthly_model.QueryItem, fields map[string]interface{}, limit int, st int, et int) ([]*fintech_data.ReportBranch, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.LimitRequest{
		CollectionName: collNameBranch,
		Fields:         protostruct.ToStruct(fields),
		Query:          query,
		StartTime:      int32(st),
		EndTime:        int32(et),
		Limit:          int32(limit),
	}
	var branchList []*fintech_data.ReportBranch
	var nextId string
	for {
		req.NextId = nextId
		resp, err := s.monthlyClient.Document.Limit(ctx, req)
		if err != nil {
			logger.Errorf("search report branch fail, nextId: %s , error: %s", nextId, err.Error())
			return nil, err
		}

		for _, data := range resp.List {
			branch, err := convertBranch(data)
			if err != nil {
				logger.Errorf("convert report branch fail, data: %v , error: %s", data, err.Error())
				return nil, err
			}
			branchList = append(branchList, branch)
		}

		logger.Infof("search report branch success, total: %d", len(branchList))
		nextId = resp.NextId
		if !resp.HaveMore {
			break
		}
	}
	return branchList, nil
}

func convertBranch(data *types.Struct) (*fintech_data.ReportBranch, error) {
	branch := &fintech_data.ReportBranch{}
	err := typeutil.StructToPbMessage(data, branch)
	if err != nil {
		return nil, err
	}
	branch.InnerId = data.Fields["_id"].GetStringValue()
	return branch, nil
}

func branchToData(branch *fintech_data.ReportBranch) *types.Struct {
	data := typeutil.PbMessageToStruct(branch)
	delete(data.Fields, "innerId")
	return data
}

func (s *historyService) BatchCreateBranch(ctx context.Context, branchList []*fintech_data.ReportBranch) ([]string, error) {
	logger := logctx.MustGetLogger(ctx)
	dataList := make([]*types.Struct, 0, len(branchList))
	for _, item := range branchList {
		dataList = append(dataList, branchToData(item))
	}
	req := &document.BatchCreateRequest{
		CollectionName: collNameBranch,
		Timestamp:      int32(s.nowTimeFunc().Unix()),
		Documents:      dataList,
	}
	resp, err := s.monthlyClient.Document.BatchCreate(ctx, req)
	if err != nil {
		logger.Errorf("batch create branch fail, error: %s", err.Error())
		return nil, err
	}
	logger.Infof("batch create branch success, total: %d", len(resp.Ids))
	return resp.Ids, nil
}

func (s *historyService) CreateBranch(ctx context.Context, branch *fintech_data.ReportBranch) (string, error) {
	logger := logctx.MustGetLogger(ctx)
	req := &document.CreateRequest{
		CollectionName: collNameBranch,
		Timestamp:      int32(s.nowTimeFunc().Unix()),
		Document:       branchToData(branch),
	}
	resp, err := s.monthlyClient.Document.Create(ctx, req)
	if err != nil {
		logger.Errorf("create branch fail, error: %s", err.Error())
		return "", err
	}
	logger.Infof("create branch success, branchId: %s", resp.Id)
	return resp.Id, nil
}

func (s *historyService) UpdateBranch(ctx context.Context, innerId string, branch *fintech_data.ReportBranch, updateFields []string) error {
	data := branchToData(branch)
	updateData := make(map[string]*types.Value)
	if len(updateFields) == 0 {
		updateData = data.Fields
	} else {
		for _, key := range updateFields {
			updateData[key] = data.Fields[key]
		}
	}
	_, err := s.monthlyClient.Document.Update(ctx, &document.UpdateRequest{
		CollectionName: collNameBranch,
		Id:             innerId,
		Update:         &types.Struct{Fields: updateData},
	})
	return err
}
