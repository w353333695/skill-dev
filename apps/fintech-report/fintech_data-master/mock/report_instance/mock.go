package report_instance

//go:generate mockgen -package=report_instance -mock_names=Service=MockService -destination=mock_service.go go.easyops.local/fintech_data/internal/report_instance Service
