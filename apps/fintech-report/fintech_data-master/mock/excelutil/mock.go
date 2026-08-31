package excelutil

//go:generate mockgen -package=excelutil -mock_names=Exporter=MockExporter -destination=mock_export.go go.easyops.local/fintech_data/internal/excelutil Exporter
