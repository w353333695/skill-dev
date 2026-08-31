package report_center

//go:generate mockgen -package=report_center -mock_names=Service=MockService -destination=mock_service.go go.easyops.local/fintech_data/internal/report_center Service
