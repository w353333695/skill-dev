package dashboard

import (
	"context"
	"sync"
	"time"

	types "github.com/gogo/protobuf/types"
	"go.mongodb.org/mongo-driver/bson/primitive"

	"go.easyops.local/contracts/protorepo-cmdb/instance"
	"go.easyops.local/contracts/protorepo-collector_center/collection_config"
	message "go.easyops.local/contracts/protorepo-fintech_data/dashboard"
	"go.easyops.local/contracts/protorepo-models/easyops/model/cmdb"
	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	monthly_model "go.easyops.local/contracts/protorepo-models/easyops/model/monthly_collection_service"
	"go.easyops.local/fintech_data/internal/apierrors"
	"go.easyops.local/fintech_data/internal/excelutil"
	"go.easyops.local/fintech_data/internal/extends/timeutil"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_rule"
	internaltypes "go.easyops.local/fintech_data/internal/types"
	statustypes "go.easyops.local/fintech_data/internal/types"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
	logctx "go.easyops.local/slog/context"
)

// ensure implements
var _ DashboardService = (*dashboardService)(nil)

func NewDashboardService(ruleService report_rule.Service, collectionClient collection_config.Client, instanceClient instance.Client, centerData history.CenterData, taskHistory history.TaskHistory, objectStat history.ObjectStat) *dashboardService {
	return &dashboardService{
		ruleService:      ruleService,
		collectionClient: collectionClient,
		instanceClient:   instanceClient,
		centerData:       centerData,
		taskHistory:      taskHistory,
		objectStat:       objectStat,
		nowTimeFunc:      timeutil.NowTime,
		newExporterFunc:  excelutil.NewExporter,
	}
}

type dashboardService struct {
	ruleService      report_rule.Service
	collectionClient collection_config.Client
	instanceClient   instance.Client
	centerData       history.CenterData
	objectStat       history.ObjectStat
	taskHistory      history.TaskHistory
	nowTimeFunc      func() time.Time
	newExporterFunc  excelutil.NewExporterFunc
}

func (s *dashboardService) ReportObjectCount(ctx context.Context, request *types.Empty) (*message.ReportObjectCountResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	confList, err := s.ruleService.SearchRule(ctx, nil, []string{"enable", "objectId", "source", "mappingObjectId"})
	if err != nil {
		logger.Errorf("search object report rule fail, error: %s", err.Error())
		return nil, err
	}

	countResp := &message.ReportObjectCountResponse{
		Total: int32(len(confList)),
	}

	// 统计启用总数&&构造全量模型映射
	objectList := make([]string, len(confList))
	for idx, conf := range confList {
		if conf.Enable {
			countResp.EnableTotal += 1
		}
		objId := report_rule.GetSearchObjectId(conf)
		objectList[idx] = objId
	}
	var errs error
	errC := make(chan error, 2)
	wg := sync.WaitGroup{}

	// 统计启用自动采集模型
	wg.Add(1)
	go func() {
		defer wg.Done()
		collectionTotal, err := s.countCollectionObject(ctx, objectList)
		if err != nil {
			logger.Errorf("search collection config fail, error: %s", err.Error())
			errC <- err
		}
		countResp.CollectionTotal = int32(collectionTotal)
	}()

	// 统计合规性检查启用模型
	wg.Add(1)
	go func() {
		defer wg.Done()
		checkTotal, err := s.countDataFilterObject(ctx, objectList)
		if err != nil {
			logger.Errorf("search data filter strategy fail, error: %s", err.Error())
			errC <- err
		}
		countResp.CheckTotal = int32(checkTotal)
	}()
	wg.Wait()
	select {
	case errs = <-errC:
	default:
	}
	if errs != nil {
		return nil, errs
	}
	return countResp, nil
}

func (s *dashboardService) countCollectionObject(ctx context.Context, objectIdList []string) (int, error) {
	objectIdMap := make(map[string]struct{})
	for _, obj := range objectIdList {
		objectIdMap[obj] = struct{}{}
	}
	collResp, err := s.collectionClient.ListCollectionConfig(ctx, &collection_config.ListCollectionConfigRequest{Disabled: 1, IsAll: 0, Page: 1, PageSize: 300, Fields: "labels,targetRange"})
	if err != nil {
		return 0, apierrors.InternalErrorf("统计自动采集对象失败，%s", err.Error())
	}
	collectionObj := make(map[string]struct{})
	for _, collConf := range collResp.List {
		// labels 存放模型id
		for _, l := range collConf.Labels {
			if _, ok := objectIdMap[l]; ok {
				collectionObj[l] = struct{}{}
				break
			}
		}
	}
	return len(collectionObj), nil
}

func (s *dashboardService) countDataFilterObject(ctx context.Context, objectIdList []string) (int, error) {
	checkResp, err := s.instanceClient.GroupInstance(ctx, &instance.GroupInstanceRequest{
		ObjectId: "_DATAFILTER_STRATEGY",
		Query: protostruct.ToStruct(map[string]interface{}{
			"enable":           true,
			"strategyObjectId": map[string]interface{}{"$in": objectIdList},
		}),
		Funcs:      []*cmdb.GroupInstanceFunc{{Op: "count", Field: "name", Alias: "count"}},
		GroupField: "strategyObjectId",
	})
	if err != nil {
		return 0, err
	}
	return len(checkResp.List), nil
}

func (s *dashboardService) ReportInstanceCount(ctx context.Context, request *types.Empty) (*message.ReportInstanceCountResponse, error) {
	logger := logctx.MustGetLogger(ctx)
	result := &message.ReportInstanceCountResponse{}

	errC := make(chan error, 2)
	wg := sync.WaitGroup{}

	wg.Add(1)
	go func() {
		defer wg.Done()
		allTotal, err := s.centerData.Count(ctx, nil)
		if err != nil {
			logger.Errorf("count all instance fail, error: %s", err.Error())
			errC <- err
		}
		result.Total = int32(allTotal)
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		nowTime := s.nowTimeFunc()
		today := timeutil.GetDateTimeByTime(nowTime)
		st, et := today.Unix(), nowTime.Unix()
		startId := primitive.NewObjectIDFromTimestamp(today.Add(-1 * time.Second))
		query := []*monthly_model.QueryItem{
			{
				Name:     "status",
				Operator: "in",
				Value:    protostruct.ToValue([]string{statustypes.StatusSuccess, statustypes.StatusWithWarn}),
			},
			{
				Name:     "_id",
				Operator: "gt",
				Value:    protostruct.ToValue(startId.Hex()),
			},
		}
		instList, err := s.taskHistory.SearchInstanceAll(ctx, query, map[string]interface{}{"_id": 1}, 1000, int(st), int(et))
		if err != nil {
			logger.Errorf("count today instance fail, error: %s", err.Error())
			errC <- err
		}
		result.TodayTotal = int32(len(instList))
	}()
	wg.Wait()

	var errs error
	select {
	case errs = <-errC:
	default:
	}
	if errs != nil {
		return nil, errs
	}
	return result, nil
}

func (s *dashboardService) ExportReportObjectStat(ctx context.Context, request *types.Empty) (internaltypes.FileExporter, error) {
	logger := logctx.MustGetLogger(ctx)
	statList, err := s.getObjectReportStat(ctx)
	if err != nil {
		logger.Errorf("get object stat fail, error: %s", err.Error())
		return nil, err
	}

	header := []excelutil.HeaderCell{
		{
			Name: "采集接口",
			Id:   "objectName",
		},
		{
			Name: "映射模型",
			Id:   "mappingObjectName",
		},
		{
			Name: "维护实例数量",
			Id:   "instanceTotal",
		},
		{
			Name: "上报成功总数",
			Id:   "successTotal",
		},
		{
			Name: "上报成功率",
			Id:   "successRate",
		},
	}
	excelStream := s.newExporterFunc("上报汇总")
	if err := excelStream.WriteExcelHeader(header); err != nil {
		logger.Errorf("write header fail, error: %s", err.Error())
		return nil, err
	}

	for _, stat := range statList {
		rowValue := map[string]interface{}{
			"objectName":        stat.ReportObjectName,
			"mappingObjectName": stat.MappingObjectName,
			"instanceTotal":     stat.InstanceTotal,
			"successTotal":      stat.SuccessTotal,
			"successRate":       excelutil.FloatToRateStr(stat.SuccessRate),
		}
		if err := excelStream.WriteRow(rowValue); err != nil {
			logger.Errorf("write row fail, error: %s", err.Error())
			return nil, err
		}
	}
	return excelStream, nil
}

func (s *dashboardService) ReportObjectStat(ctx context.Context, request *types.Empty) (*message.ReportObjectStatResponse, error) {
	statList, err := s.getObjectReportStat(ctx)
	if err != nil {
		return nil, err
	}
	return &message.ReportObjectStatResponse{List: statList}, nil
}

func (s *dashboardService) getObjectReportStat(ctx context.Context) ([]*message.ReportObjectStatResponse_List, error) {
	logger := logctx.MustGetLogger(ctx)

	var confList []*fintech_data.ReportObjectConf
	var statMap map[string]*history.StatData
	var instCount *types.Struct
	var errs error
	errC := make(chan error, 3)
	wg := sync.WaitGroup{}
	wg.Add(3)

	// 上报模型基本信息
	go func() {
		defer wg.Done()
		var err1 error
		confList, err1 = s.ruleService.SearchRule(ctx, nil, []string{"objectId", "name", "source", "mappingObjectId", "mappingObjectName"})
		if err1 != nil {
			logger.Errorf("search object report rule fail, error: %s", err1.Error())
			errC <- err1
		}
	}()

	// 上报模型统计信息
	go func() {
		defer wg.Done()
		statList, err2 := s.objectStat.SearchAll(ctx, nil)
		if err2 != nil {
			logger.Errorf("search object stat fail, error: %s", err2.Error())
			errC <- err2
		}
		statMap = make(map[string]*history.StatData)
		for _, stat := range statList {
			statMap[stat.ObjectId] = stat
		}
	}()

	// cmdb上报模型实例数量
	go func() {
		defer wg.Done()
		var err3 error
		instCount, err3 = s.instanceClient.CountAll(ctx, &instance.CountAllRequest{})
		if err3 != nil {
			logger.Errorf("get instance count fail, error: %s", err3.Error())
			errC <- err3
		}
	}()

	// handle wait
	wg.Wait()
	select {
	case errs = <-errC:
	default:
	}
	if errs != nil {
		return nil, errs
	}

	result := make([]*message.ReportObjectStatResponse_List, 0, len(confList))
	for _, item := range confList {
		mappingId := report_rule.GetMappingObjectId(item)
		var mappingName string
		if mappingId != "" {
			mappingName = item.MappingObjectName
		}
		objStat := &message.ReportObjectStatResponse_List{
			ReportObjectId:    item.ObjectId,
			ReportObjectName:  item.Name,
			MappingObjectId:   report_rule.GetMappingObjectId(item),
			MappingObjectName: mappingName,
		}
		if stat, ok := statMap[item.ObjectId]; ok {
			objStat.SuccessTotal = int32(stat.Total)
			if stat.ReportTotal > 0 {
				objStat.SuccessRate = 1 - (float32(stat.FailTotal) / float32(stat.ReportTotal))
			}
		}
		searchObjId := report_rule.GetSearchObjectId(item)
		if v, ok := instCount.GetFields()[searchObjId]; ok {
			objStat.InstanceTotal = int32(v.GetNumberValue())
		}
		result = append(result, objStat)
	}
	return result, nil
}
