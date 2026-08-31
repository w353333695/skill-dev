package monthly

//go:generate mockgen -package=monthly -mock_names=Client=MockCollectionClient -destination=mock_collection_client.go go.easyops.local/contracts/protorepo-monthly_collection_service/document Client
