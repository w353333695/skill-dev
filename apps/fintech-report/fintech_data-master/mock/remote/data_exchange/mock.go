package data_exchange

//go:generate mockgen -package=data_exchange -mock_names=Client=MockStoreClient -destination=mock_store_client.go go.easyops.local/contracts/protorepo-data_exchange/store Client
