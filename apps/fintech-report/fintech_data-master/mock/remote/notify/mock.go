package notify

//go:generate mockgen -package=notify -mock_names=Client=MockOpLogClient -destination=mock_oplog_client.go go.easyops.local/contracts/protorepo-notify/oplog Client

//go:generate mockgen -package=notify -mock_names=Client=MockSubscriberClient -destination=mock_subscriber_client.go go.easyops.local/contracts/protorepo-notify/subscriber Client
