package history

//go:generate mockgen -package=history -mock_names=TaskHistory=MockTaskHistory -destination=mock_task.go go.easyops.local/fintech_data/internal/history TaskHistory

//go:generate mockgen -package=history -mock_names=CenterData=MockCenterData -destination=mock_center_data.go go.easyops.local/fintech_data/internal/history CenterData

//go:generate mockgen -package=history -mock_names=ObjectStat=MockObjectStat -destination=mock_object_stat.go go.easyops.local/fintech_data/internal/history ObjectStat

//go:generate mockgen -package=history -mock_names=Recorder=MockRecorder -destination=mock_recorder.go go.easyops.local/fintech_data/internal/history Recorder
