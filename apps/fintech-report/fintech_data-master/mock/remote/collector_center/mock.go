package collector_center

//go:generate mockgen -package=collector_center -mock_names=Client=MockcollectionClient -destination=mock_collection_client.go go.easyops.local/contracts/protorepo-collector_center/collection_config Client
