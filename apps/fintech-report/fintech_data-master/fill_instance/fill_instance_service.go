package fill_instance

import (
	"context"

	types "github.com/gogo/protobuf/types"

	message "go.easyops.local/contracts/protorepo-fintech_data/fill_instance"
	"go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/fill_instance/dispatch"
	logctx "go.easyops.local/slog/context"
)

// ensure implements
var _ FillInstanceService = (*fillInstanceService)(nil)

func NewFillInstanceService(fillService fill_instance.Service, dispatcher dispatch.Dispatcher) *fillInstanceService {
	return &fillInstanceService{
		fillService: fillService,
		dispatcher:  dispatcher,
	}
}

type fillInstanceService struct {
	fillService fill_instance.Service
	dispatcher  dispatch.Dispatcher
}

func (f *fillInstanceService) InstanceCallback(ctx context.Context, request *message.InstanceCallbackRequest) (*types.Empty, error) {
	logger := logctx.MustGetLogger(ctx)
	processItem := fill_instance.ProcessItem{
		InstanceId:   request.Data.ExtInfo.InstanceId,
		ChangeFields: request.Data.ExtInfo.GetXChangeFields(),
	}
	var updateData *types.Struct
	if request.Data.ExtInfo.DiffData != nil {
		updateData = &types.Struct{Fields: make(map[string]*types.Value)}
		for _, field := range processItem.ChangeFields {
			diffValue := request.Data.ExtInfo.DiffData.Fields[field]
			if diffStruct := diffValue.GetStructValue(); diffStruct != nil {
				updateData.Fields[field] = diffStruct.Fields["new"]
			}
		}
	}
	if f.fillService.HasEffectedRule(ctx, request.Data.ExtInfo.ObjectId, processItem, updateData) {
		logger.Infof("instance should be processed by fill rule, object: %s, instance: %s, topic: %s, event_id: %s", request.Data.ExtInfo.ObjectId, request.Data.ExtInfo.InstanceId, request.Topic, request.Data.EventId)
		err := f.dispatcher.PushJob(ctx, request.Data.ExtInfo.ObjectId, processItem)
		if err != nil {
			logger.Errorf("push fill instance job fail, instance: %s, error: %s", request.Data.ExtInfo.InstanceId, err.Error())
			return nil, err
		}
	}
	return nil, nil
}
