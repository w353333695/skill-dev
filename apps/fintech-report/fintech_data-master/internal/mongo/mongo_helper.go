package mongo

import (
	"context"
	"fmt"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/globalsign/mgo"

	"go.easyops.local/gin-giraffe/pkg/orguser"
	authnaive "go.easyops.local/kit/auth/naive"
	kitmgo "go.easyops.local/kit/database/mgo"
)

type CollectionFactory func(ctx context.Context, tableName string) CollectionHelper

type CollectionFactoryV2 func(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface

func GetCollectionFromCtx(ctx context.Context, tableName string) CollectionHelper {
	orgUser, _ := orguser.FromContext(ctx)
	mgoSession := kitmgo.MustGetSession(ctx)
	db := mgoSession.DB(fmt.Sprintf("easyops_%d", orgUser.Org))
	return Collection{Collection: db.C(tableName)}
}

func NewCollectionV2(ctx context.Context, client pmongo.ClientInterface, databasePrefix string, tableName string) pmongo.CollectionInterface {
	orgUser, _ := authnaive.OrgUserFromContext(ctx)
	dbName := fmt.Sprintf("%s%d", databasePrefix, orgUser.Org)
	db := client.Database(dbName)
	return db.Collection(tableName)
}

type CollectionHelper interface {
	Find(query interface{}) QueryHelper
	Insert(docs ...interface{}) error
	Remove(selector interface{}) error
	Update(selector interface{}, update interface{}) error
	Upsert(selector interface{}, update interface{}) (info *mgo.ChangeInfo, err error)
	Pipe(pipeline interface{}) PipeHelper
	UpdateAll(selector interface{}, update interface{}) (info *mgo.ChangeInfo, err error)
	Bulk() BulkHelper
}

type QueryHelper interface {
	Select(selector interface{}) QueryHelper
	One(result interface{}) (err error)
	Skip(n int) QueryHelper
	Limit(n int) QueryHelper
	Sort(fields ...string) QueryHelper
	Count() (n int, err error)
	All(result interface{}) error
}

type PipeHelper interface {
	All(result interface{}) error
}

type BulkHelper interface {
	Insert(docs ...interface{})
	Upsert(pairs ...interface{})
	Remove(selectors ...interface{})
	Run() (*mgo.BulkResult, error)
	RemoveAll(selectors ...interface{})
}

type Collection struct {
	*mgo.Collection
}

type Pipe struct {
	*mgo.Pipe
}

type Bulk struct {
	*mgo.Bulk
}

func (c Collection) Find(query interface{}) QueryHelper {
	return Query{Query: c.Collection.Find(query)}
}

func (c Collection) Pipe(pipeline interface{}) PipeHelper {
	return Pipe{Pipe: c.Collection.Pipe(pipeline)}
}

func (c Collection) Bulk() BulkHelper {
	return Bulk{Bulk: c.Collection.Bulk()}
}

type Query struct {
	*mgo.Query
}

func (q Query) Select(selector interface{}) QueryHelper {
	return Query{Query: q.Query.Select(selector)}
}

func (q Query) Skip(n int) QueryHelper {
	return Query{Query: q.Query.Skip(n)}
}

func (q Query) Limit(n int) QueryHelper {
	return Query{Query: q.Query.Limit(n)}
}

func (q Query) Sort(fields ...string) QueryHelper {
	return Query{Query: q.Query.Sort(fields...)}
}
