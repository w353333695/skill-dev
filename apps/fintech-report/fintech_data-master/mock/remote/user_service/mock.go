package user_service

//go:generate mockgen -package=user_service -mock_names=Client=MockOrgClient -destination=mock_instance_client.go go.easyops.local/contracts/protorepo-user_service/organization Client
