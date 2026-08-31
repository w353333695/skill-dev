package report_rule

//go:generate mockgen -package=report_rule -mock_names=Service=MockService -destination=mock_service.go go.easyops.local/fintech_data/internal/report_rule Service
