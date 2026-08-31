package mongo

//go:generate mockgen -package=mongo -mock_names=CollectionHelper=MockCollectionHelper -destination=mock_collection_hepler.go go.easyops.local/fintech_data/internal/mongo CollectionHelper

//go:generate mockgen -package=mongo -mock_names=QueryHelper=MockQueryHelper -destination=mock_query_hepler.go go.easyops.local/fintech_data/internal/mongo QueryHelper

//go:generate mockgen -package=mongo -mock_names=PipeHelper=MockPipeHelper -destination=mock_pipe_hepler.go go.easyops.local/fintech_data/internal/mongo PipeHelper

//go:generate mockgen -package=mongo -mock_names=BulkHelper=MockBulkHelper -destination=mock_bulk_hepler.go go.easyops.local/fintech_data/internal/mongo BulkHelper
