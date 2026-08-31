package mongo

import (
	"context"
	"reflect"
	"testing"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/easyops-cn/mongo-driver-helper/pmongo/mock_pmongo"
	"github.com/globalsign/mgo"
	"github.com/golang/mock/gomock"

	"go.easyops.local/gin-giraffe/pkg/orguser"
	kitmgo "go.easyops.local/kit/database/mgo"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func GetTestContext() context.Context {
	ctx := context.Background()
	logger := slog.Noop()
	orgUser := orguser.OrgUser{
		Org:  1888,
		User: "easyops",
	}
	ctx = orguser.WithUser(ctx, orgUser)
	//ctx = kitmgo.WithSession(ctx, &mgo.Session{})
	return logctx.WithLogger(ctx, logger)
}

func TestCollection_Find(t *testing.T) {
	type fields struct {
		Collection *mgo.Collection
	}
	type args struct {
		query interface{}
	}
	coll := &mgo.Collection{
		Database: &mgo.Database{
			Session: &mgo.Session{},
		},
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   QueryHelper
	}{
		{
			name: "",
			fields: fields{
				Collection: coll,
			},
			args: args{
				query: map[string]interface{}{},
			},
			want: Query{Query: coll.Find(map[string]interface{}{})},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Collection{
				Collection: tt.fields.Collection,
			}
			if got := c.Find(tt.args.query); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Find() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestQuery_Limit(t *testing.T) {
	type fields struct {
		Query *mgo.Query
	}
	type args struct {
		n int
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   QueryHelper
	}{
		{
			name: "normal",
			fields: fields{
				Query: &mgo.Query{},
			},
			args: args{
				n: 2,
			},
			want: Query{Query: &mgo.Query{}}.Limit(2),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			q := Query{
				Query: tt.fields.Query,
			}
			if got := q.Limit(tt.args.n); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Limit() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestQuery_Select(t *testing.T) {
	type fields struct {
		Query *mgo.Query
	}
	type args struct {
		selector interface{}
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   QueryHelper
	}{
		{
			name: "normal",
			fields: fields{
				Query: &mgo.Query{},
			},
			args: args{
				selector: nil,
			},
			want: Query{Query: &mgo.Query{}}.Select(nil),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			q := Query{
				Query: tt.fields.Query,
			}
			if got := q.Select(tt.args.selector); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Select() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestQuery_Skip(t *testing.T) {
	type fields struct {
		Query *mgo.Query
	}
	type args struct {
		n int
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   QueryHelper
	}{
		{
			name: "normal",
			fields: fields{
				Query: &mgo.Query{},
			},
			args: args{
				n: 2,
			},
			want: Query{Query: &mgo.Query{}}.Skip(2),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			q := Query{
				Query: tt.fields.Query,
			}
			if got := q.Skip(tt.args.n); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Skip() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestQuery_Sort(t *testing.T) {
	type fields struct {
		Query *mgo.Query
	}
	type args struct {
		fields []string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   QueryHelper
	}{
		{
			name: "normal",
			fields: fields{
				Query: &mgo.Query{},
			},
			args: args{
				fields: []string{"_id"},
			},
			want: Query{Query: &mgo.Query{}}.Sort("_id"),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			q := Query{
				Query: tt.fields.Query,
			}
			if got := q.Sort(tt.args.fields...); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Sort() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetCollectionFromCtx(t *testing.T) {
	ctx := GetTestContext()
	ctx = kitmgo.WithSession(ctx, &mgo.Session{})

	type args struct {
		ctx       context.Context
		tableName string
	}
	tests := []struct {
		name string
		args args
		want CollectionHelper
	}{
		{
			name: "normal",
			args: args{
				ctx:       ctx,
				tableName: "one",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			GetCollectionFromCtx(tt.args.ctx, tt.args.tableName)
		})
	}
}

func TestNewCollectionV2(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := GetTestContext()

	mockClient := mock_pmongo.NewMockClientInterface(ctrl)
	mockDatabase := mock_pmongo.NewMockDatabaseInterface(ctrl)
	mockColl := mock_pmongo.NewMockCollectionInterface(ctrl)

	mockDatabase.EXPECT().Collection("one").Return(mockColl).AnyTimes()
	mockClient.EXPECT().Database("easyops_1888").Return(mockDatabase).AnyTimes()

	type args struct {
		ctx            context.Context
		client         pmongo.ClientInterface
		databasePrefix string
		tableName      string
	}
	tests := []struct {
		name string
		args args
		want pmongo.CollectionInterface
	}{
		{
			name: "normal",
			args: args{
				ctx:            ctx,
				client:         mockClient,
				databasePrefix: "easyops_",
				tableName:      "one",
			},
			want: mockColl,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			NewCollectionV2(tt.args.ctx, tt.args.client, tt.args.databasePrefix, tt.args.tableName)
		})
	}
}

func TestCollection_Pipe(t *testing.T) {
	type fields struct {
		Collection *mgo.Collection
	}
	type args struct {
		pipeline interface{}
	}
	coll := &mgo.Collection{
		Database: &mgo.Database{
			Session: &mgo.Session{},
		},
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   PipeHelper
	}{
		{
			name: "",
			fields: fields{
				Collection: coll,
			},
			args: args{
				pipeline: nil,
			},
			want: Pipe{Pipe: coll.Pipe(nil)},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Collection{
				Collection: tt.fields.Collection,
			}
			if got := c.Pipe(tt.args.pipeline); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Pipe() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestCollection_Bulk(t *testing.T) {
	type fields struct {
		Collection *mgo.Collection
	}
	coll := &mgo.Collection{
		Database: &mgo.Database{
			Session: &mgo.Session{},
		},
	}
	tests := []struct {
		name   string
		fields fields
		want   BulkHelper
	}{
		{
			name: "",
			fields: fields{
				Collection: coll,
			},
			want: Bulk{Bulk: coll.Bulk()},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := Collection{
				Collection: tt.fields.Collection,
			}
			if got := c.Bulk(); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Bulk() = %v, want %v", got, tt.want)
			}
		})
	}
}
