package fill_instance

//go:generate mockgen -package=fill_instance -mock_names=Service=MockService -destination=mock_service.go go.easyops.local/fintech_data/internal/fill_instance Service

//go:generate mockgen -package=fill_instance -mock_names=Dispatcher=MockDispatcher -destination=mock_dispatcher.go go.easyops.local/fintech_data/internal/fill_instance/dispatch Dispatcher
