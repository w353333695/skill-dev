package cmdb

//go:generate mockgen -package=cmdb -mock_names=Client=MockObjectClient -destination=mock_object_client.go go.easyops.local/contracts/protorepo-cmdb/cmdb_object Client

//go:generate mockgen -package=cmdb -mock_names=Client=MockInstanceClient -destination=mock_instance_client.go go.easyops.local/contracts/protorepo-cmdb/instance Client
