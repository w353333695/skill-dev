package history

import (
	"context"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"go.mongodb.org/mongo-driver/bson"
	mongoModel "go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"

	"go.easyops.local/fintech_data/internal/mongo"
)

func NewCenterData(mongoClient pmongo.ClientInterface) CenterData {
	return &centerDataService{
		collectionFactory:   mongo.GetCollectionFromCtx,
		collectionFactoryV2: mongo.NewCollectionV2,
		mongoClient:         mongoClient,
	}
}

// CenterData 维护已上报至人行的实例基本信息
type CenterData interface {
	Upsert(ctx context.Context, dataList ...*ReportMetaData) (*ChangeInfo, error)
	RemoveAll(ctx context.Context, dataList ...*ReportMetaData) error
	SearchAll(ctx context.Context, query map[string]interface{}, fields []string) ([]*ReportMetaData, error)
	Count(ctx context.Context, query map[string]interface{}) (int, error)
	Aggregate(ctx context.Context, pipeline interface{}, result interface{}) error
}

const (
	ReportDataColl = "fintech_report_data"
	DateBasePrefix = "easyops_"
)

type centerDataService struct {
	collectionFactory   mongo.CollectionFactory
	collectionFactoryV2 mongo.CollectionFactoryV2
	mongoClient         pmongo.ClientInterface
}

func (s *centerDataService) Aggregate(ctx context.Context, pipeline interface{}, result interface{}) error {
	coll := s.getCollectionV2(ctx)
	aggregate, err := coll.Aggregate(ctx, pipeline)
	if err != nil {
		return err
	}
	return aggregate.All(ctx, result)
}

type ReportMetaData struct {
	InstanceId         string `bson:"instanceId"`
	Version            int    `bson:"version"`
	ObjectId           string `bson:"objectId"`
	FacilityCategory   string `bson:"facilityCategory"`
	FacilityDescriptor string `bson:"facilityDescriptor"`
	Ts                 int32  `bson:"ts"`
	DataId             string `bson:"dataId"`
}

func (d *ReportMetaData) ToMap() map[string]interface{} {
	dataMap := make(map[string]interface{})

	if len(d.InstanceId) > 0 {
		dataMap["instanceId"] = d.InstanceId
	}

	if len(d.ObjectId) > 0 {
		dataMap["objectId"] = d.ObjectId
	}

	if len(d.FacilityCategory) > 0 {
		dataMap["facilityCategory"] = d.FacilityCategory
	}

	if len(d.FacilityDescriptor) > 0 {
		dataMap["facilityDescriptor"] = d.FacilityDescriptor
	}

	if len(d.DataId) > 0 {
		dataMap["dataId"] = d.DataId
	}

	if d.Version > 0 {
		dataMap["version"] = d.Version
	}

	if d.Ts > 0 {
		dataMap["ts"] = d.Ts
	}

	return dataMap
}

func (s *centerDataService) getCollection(ctx context.Context) mongo.CollectionHelper {
	return s.collectionFactory(ctx, ReportDataColl)
}

func (s *centerDataService) getCollectionV2(ctx context.Context) pmongo.CollectionInterface {
	return s.collectionFactoryV2(ctx, s.mongoClient, DateBasePrefix, ReportDataColl)
}

type ChangeInfo struct {
	Updated  int
	Inserted int
}

func (s *centerDataService) Upsert(ctx context.Context, dataList ...*ReportMetaData) (*ChangeInfo, error) {
	coll := s.getCollectionV2(ctx)
	writeModelList := make([]mongoModel.WriteModel, 0, len(dataList))
	for _, data := range dataList {
		writeMode := &mongoModel.UpdateOneModel{}
		writeMode.SetUpsert(true)
		filter := bson.M{
			"instanceId": data.InstanceId,
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

func (s *centerDataService) RemoveAll(ctx context.Context, dataList ...*ReportMetaData) error {
	coll := s.getCollectionV2(ctx)

	var deleteList []string
	for _, data := range dataList {
		deleteList = append(deleteList, data.InstanceId)
	}
	filter := bson.M{
		"instanceId": bson.M{
			"$in": deleteList,
		},
	}
	_, err := coll.DeleteMany(ctx, filter)
	return err
}

func (s *centerDataService) SearchAll(ctx context.Context, query map[string]interface{}, fields []string) ([]*ReportMetaData, error) {
	coll := s.getCollectionV2(ctx)

	// 先算总数
	total, err := coll.CountDocuments(ctx, query)
	if err != nil {
		return nil, err
	}
	if total <= 0 {
		return nil, nil
	}

	var dataList []*ReportMetaData
	opt := findOptions(fields, nil, 1, total)

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

func (s *centerDataService) Count(ctx context.Context, query map[string]interface{}) (int, error) {
	coll := s.getCollectionV2(ctx)

	// 先算总数
	total, err := coll.CountDocuments(ctx, query)
	if err != nil {
		return 0, err
	}
	return int(total), nil
}

func findOptions(fields, sorts []string, page, pageSize int64) *options.FindOptions {
	opts := options.Find()
	// field
	projection := make(bson.D, 0, len(fields))
	for i := range fields {
		projection = append(projection, bson.E{
			Key: fields[i], Value: 1,
		})
	}
	// sort
	sortD := make(bson.D, 0, len(sorts))
	for i := range sorts {
		// 将mgo的字段排序声明转换为mongo-driver适配的声明, demo：-_id => (_id, -1)
		field, sort := parseMgoSort(sorts[i])
		sortD = append(sortD, bson.E{
			Key: field, Value: sort,
		})
	}
	// skip
	skip := (page - 1) * pageSize

	return opts.
		SetProjection(&projection).
		SetSort(&sortD).
		SetSkip(skip).
		SetLimit(pageSize)
}

func parseMgoSort(sort string) (string, int64) {
	if sort[0] == '-' {
		return sort[1:], -1
	}
	return sort, 1
}
