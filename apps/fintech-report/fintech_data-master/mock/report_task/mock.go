package report_task

//go:generate mockgen -package=report_task -mock_names=Service=MockConfigService -destination=mock_config_service.go go.easyops.local/fintech_data/internal/report_task ConfigService

//go:generate mockgen -package=report_task -mock_names=ReportService=MockReportService -destination=mock_report_service.go go.easyops.local/fintech_data/internal/report_task ReportService

//go:generate mockgen -package=report_task -mock_names=ReportChecker=MockReportChecker -destination=mock_report_checker.go go.easyops.local/fintech_data/internal/report_task ReportChecker
