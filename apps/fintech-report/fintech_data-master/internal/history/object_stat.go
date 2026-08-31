package history

import (
	"context"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"go.mongodb.org/mongo-driver/bson"
	mongoModel "go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"

	"go.easyops.local/fintech_data/internal/mongo"
)

func NewObjectStat(mongoClient pmongo.ClientInterface) ObjectStat {
	return &objectStatService{
		collectionFactory:   mongo.GetCollectionFromCtx,
		collectionFactoryV2: mongo.NewCollectionV2,
		mongoClient:         mongoClient,
	}
}

// ObjectStat 维护已上报至人行的实例基本信息
type ObjectStat interface {
	Get(ctx context.Context, objectId string) (*StatData, error)
	Upsert(ctx context.Context, dataList ...*StatData) (*ChangeInfo, error)
	SearchAll(ctx context.Context, query map[string]interface{}) ([]*StatData, error)
}

const (
	ObjectStatColl = "fintech_object_stat"
)

type objectStatService struct {
	collectionFactory   mongo.CollectionFactory
	collectionFactoryV2 mongo.CollectionFactoryV2
	mongoClient         pmongo.ClientInterface
}

type StatData struct {
	ObjectId    string `bson:"objectId"`
	Total       int    `bson:"total"`
	ReportTotal int    `bson:"reportTotal"`
	FailTotal   int    `bson:"failTotal"`
	TS          int32  `bson:"ts"`
	LastTaskId  string `bson:"lastTaskId"`
}

func (s *StatData) ToMap() map[string]interface{} {
	dataMap := make(map[string]interface{})

	if len(s.ObjectId) > 0 {
		dataMap["objectId"] = s.ObjectId
	}

	if s.Total > 0 {
		dataMap["total"] = s.Total
	}

	if s.ReportTotal > 0 {
		dataMap["reportTotal"] = s.ReportTotal
	}

	if s.FailTotal > 0 {
		dataMap["failTotal"] = s.FailTotal
	}

	if s.TS > 0 {
		dataMap["ts"] = s.TS
	}

	if len(s.LastTaskId) > 0 {
		dataMap["lastTaskId"] = s.LastTaskId
	}

	return dataMap
}

func (s *objectStatService) getCollection(ctx context.Context) mongo.CollectionHelper {
	return s.collectionFactory(ctx, ObjectStatColl)
}

func (s *objectStatService) getCollectionV2(ctx context.Context) pmongo.CollectionInterface {
	return s.collectionFactoryV2(ctx, s.mongoClient, DateBasePrefix, ObjectStatColl)
}

func (s *objectStatService) Get(ctx context.Context, objectId string) (*StatData, error) {
	coll := s.getCollectionV2(ctx)
	data := &StatData{}

	ret := coll.FindOne(ctx, bson.M{"objectId": objectId}, options.FindOne())

	err := ret.Decode(data)
	if err != nil {
		return nil, err
	}
	return data, nil
}

func (s *objectStatService) Upsert(ctx context.Context, dataList ...*StatData) (*ChangeInfo, error) {
	coll := s.getCollectionV2(ctx)
	writeModelList := make([]mongoModel.WriteModel, 0, len(dataList))
	for _, data := range dataList {
		writeMode := &mongoModel.UpdateOneModel{}
		writeMode.SetUpsert(true)
		filter := bson.M{
			"objectId": data.ObjectId,
		}
		writeMode.SetFilter(filter)
		updateMap := data.ToMap()
		writeMode.SetUpdate(bson.M{"$set": updateMap})
		writeModelList = append(writeModelList, writeMode)
	}
	ret, err := coll.BulkWrite(ctx, writeModelList)
	if err != nil {
		return nil, err
	}
	return &ChangeInfo{
		Updated:  int(ret.ModifiedCount),
		Inserted: len(dataList) - int(ret.ModifiedCount),
	}, nil
}

func (s *objectStatService) SearchAll(ctx context.Context, query map[string]interface{}) ([]*StatData, error) {
	coll := s.getCollectionV2(ctx)

	// 先算总数
	total, err := coll.CountDocuments(ctx, query)
	if err != nil {
		return nil, err
	}
	if total <= 0 {
		return nil, nil
	}

	var dataList []*StatData
	opt := findOptions(nil, nil, 1, total)

	// 分页查询
	cursor, err := coll.Find(ctx, query, opt)
	if err != nil {
		return nil, err
	}
	err = cursor.All(ctx, &dataList)
	if err != nil {
		return nil, err
	}
	return dataList, nil
}
