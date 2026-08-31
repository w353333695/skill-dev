package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-redis/redis/v8"
	"github.com/gogo/protobuf/types"
	"github.com/oklog/run"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"

	"go.easyops.local/agollo"
	"go.easyops.local/api/transport"
	cmdb "go.easyops.local/contracts/protorepo-cmdb"
	collector_center "go.easyops.local/contracts/protorepo-collector_center"
	data_exchange "go.easyops.local/contracts/protorepo-data_exchange"
	user_service_model "go.easyops.local/contracts/protorepo-models/easyops/model/user_service"
	monthly_collection_service "go.easyops.local/contracts/protorepo-monthly_collection_service"
	notify "go.easyops.local/contracts/protorepo-notify"
	user_service "go.easyops.local/contracts/protorepo-user_service"
	"go.easyops.local/contracts/protorepo-user_service/organization"
	"go.easyops.local/fintech_data/dashboard"
	"go.easyops.local/fintech_data/fill_instance"
	history_service "go.easyops.local/fintech_data/history"
	"go.easyops.local/fintech_data/internal/customer_settings"
	fill_instance_service "go.easyops.local/fintech_data/internal/fill_instance"
	"go.easyops.local/fintech_data/internal/fill_instance/dispatch"
	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/report_center"
	"go.easyops.local/fintech_data/internal/report_instance"
	"go.easyops.local/fintech_data/internal/report_rule"
	"go.easyops.local/fintech_data/internal/report_task"
	"go.easyops.local/fintech_data/internal/timer"
	"go.easyops.local/fintech_data/report_conf"
	"go.easyops.local/fintech_data/task"
	gingiraffe "go.easyops.local/gin-giraffe"
	"go.easyops.local/giraffe-micro/pkg/hack"
	girafferest "go.easyops.local/giraffe-micro/v2/rest"
	kithttp "go.easyops.local/kit/http"
	"go.easyops.local/kit/tracing"
	kitmgodriverdync "go.easyops.local/mongo-helper/mongo-driver/dynamic"
	_ "go.easyops.local/nameservice"
	redislock "go.easyops.local/redis-helper/v8/lock"
	dynamicredis "go.easyops.local/redis-helper/v8/redis/dynamic"
	"go.easyops.local/slog"
	zaplog "go.easyops.local/slog/zap"
)

func main() {
	appPath, err := getAppPath()
	if err != nil {
		log.Fatalf("main: getAppPath(): %v", err)
	}

	conf, err := loadConfig()
	if err != nil {
		log.Fatalf("main: loadConfig(): %v", err)
	}
	conf.setBasePath(appPath)
	var rootLogger slog.Logger
	if conf.Service.Mode == gin.DebugMode {
		rootLogger = zaplog.MustNewDevelopment()
	} else {
		rootLogger = SetupLogging(conf.Log)
	}
	defer rootLogger.Flush()

	roundTripperConfig := &LogConfig{
		Level:   conf.Log.Level,
		Logfile: &conf.Log.RoundTripperLogfile,
	}
	roundTripperLogger := SetupLogging(roundTripperConfig)
	defer roundTripperLogger.Flush()

	reporter := tracing.NewReporter(&conf.Tracing)
	var hostPort = fmt.Sprintf("%s:%d", conf.Service.Ip, conf.Service.Port)
	tracer, err := tracing.NewTracer(reporter, conf.Tracing.ServiceName, hostPort)
	if err != nil {
		log.Fatalf("main: init tracer failed: %v", err)
	}

	err = setupAppConfig(rootLogger, tracer, conf)
	if err != nil {
		log.Fatalf("setupAppConfig failed: %v", err)
		return
	}
	customer_settings.IsZhongXin = agollo.GetBool("fintech_data_is_zhongxin", false, agollo.WithNamespace("feature-switch"))
	// 在这里初始化你的依赖, 并装配到service上
	// 新建一个REST Client
	reportCenterClient, err := kithttp.NewClient(tracer)
	if err != nil {
		log.Fatalf("init http client failed: %v", err)
		return
	}
	defaultTransport := http.DefaultTransport.(*http.Transport)
	tlsConf := &tls.Config{
		InsecureSkipVerify: true,
	}
	proxy := defaultTransport.Proxy
	proxyString := agollo.GetString("report_center.proxy", conf.ReportCenter.Proxy)
	if proxyString != "" {
		proxyUrl, err := url.Parse(proxyString)
		if err != nil {
			log.Fatalf("parse proxy url fail: %v", err)
			return
		}
		proxy = http.ProxyURL(proxyUrl)
	}

	loadTlsVersion(conf, tlsConf)
	insecureTransport := &http.Transport{
		Proxy: proxy,
		DialContext: (&net.Dialer{
			Timeout:   time.Duration(90) * time.Second,
			KeepAlive: time.Duration(30) * time.Second,
		}).DialContext,
		MaxIdleConns:          defaultTransport.MaxIdleConns,
		IdleConnTimeout:       defaultTransport.IdleConnTimeout,
		TLSHandshakeTimeout:   defaultTransport.TLSHandshakeTimeout,
		TLSClientConfig:       tlsConf,
		ExpectContinueTimeout: defaultTransport.ExpectContinueTimeout,
	}

	rt := transport.RoundTripperWrapper(roundTripperLogger, http.DefaultTransport, conf.Log.Level.Level() == zap.DebugLevel)
	giraffeClient, err := girafferest.NewClient(girafferest.WithTracer(tracer), girafferest.WithRoundTripper(rt))
	cmdbClient := cmdb.NewClient(hack.ClientWithServiceName(conf.CmdbService.ServiceName, giraffeClient))
	userServiceClient := user_service.NewClient(hack.ClientWithServiceName(conf.UserService.ServiceName, giraffeClient))
	monthlyClient := monthly_collection_service.NewClient(hack.ClientWithServiceName(conf.MonthlyCollectionService.ServiceName, giraffeClient))
	notifyClient := notify.NewClient(hack.ClientWithServiceName(conf.Notify.ServiceName, giraffeClient))
	collectorCenterClient := collector_center.NewClient(hack.ClientWithServiceName(conf.CollectorCenter.ServiceName, giraffeClient))
	dataExchangeClient := data_exchange.NewClient(hack.ClientWithServiceName(conf.DataExchange.ServiceName, giraffeClient))
	orgList, err := listOrg(userServiceClient.Organization)
	if err != nil {
		log.Fatalf("list org fail: %v", err)
	}

	// redis
	redisClient := dynamicredis.NewDynamicClientWithOption(&(conf.Redis.RedisConfig),
		dynamicredis.WithZipkinTracer(tracer), dynamicredis.WithLogger(rootLogger))

	// mongodb
	mongoClient := kitmgodriverdync.NewDynamicClient(tracer, &(conf.Mongodb.MongoConfig))

	reportCenterClient.Transport = transport.RoundTripperWrapper(rootLogger, insecureTransport, conf.Log.Level.Level() == zap.DebugLevel)
	reporterCenter := report_center.NewService(conf.ReportCenter, reportCenterClient, gzipCompress, agollo.DefaultClient())
	// 中信环境
	if customer_settings.IsZhongXin {
		reporterCenter = report_center.NewZhongXinService(conf.ReportCenter, reportCenterClient, gzipCompress, agollo.DefaultClient())
	}
	taskHistory := history.NewTaskHistory(monthlyClient)
	taskConfService := report_task.NewConfigService(cmdbClient.Instance)
	centerData := history.NewCenterData(mongoClient)
	objectStat := history.NewObjectStat(mongoClient)
	historyRecorder := history.NewRecorder(dataExchangeClient.Store)
	reportInstService := report_instance.NewService(cmdbClient.Instance, cmdbClient.CmdbObject, notifyClient.Oplog, centerData, taskHistory, conf.ReportConf, conf.FillInstance.RelationRules)
	reportService := report_task.NewReportService(redisClient, reporterCenter, taskHistory, reportInstService, conf.ReportConf, mongoClient, NewLockFunc)
	reportRuleService := report_rule.NewService(cmdbClient.CmdbObject, cmdbClient.Instance)
	reportChecker := report_task.NewChecker(redisClient, reporterCenter, taskHistory, centerData, objectStat, historyRecorder, conf.ReportConf, mongoClient, NewLockFunc)
	if customer_settings.IsZhongXin {
		reportChecker = report_task.NewZhongXinChecker(redisClient, reporterCenter, taskHistory, centerData, objectStat, historyRecorder, conf.ReportConf, mongoClient, NewLockFunc)
	}
	fillService := fill_instance_service.NewService(conf.FillInstance.InstanceRules, conf.FillInstance.RelationRules, cmdbClient.Instance, notifyClient.Subscriber, conf.FillInstance.SubscriberProcNum)
	if err = fillService.RegisterSubscribers(); err != nil {
		log.Fatalf("register rule subscribers fail: %v", err)
	}
	fillDispatcher := dispatch.NewDispatcher(rootLogger, redisClient, fillService, conf.FillInstance, newRedisLock)
	if err = fillDispatcher.WakeUpJobs(); err != nil {
		log.Fatalf("wake up jobs fail: %v", err)
	}

	gin.SetMode(conf.Service.Mode)
	r := gingiraffe.Default(rootLogger, &conf.AccessLog, tracer)

	taskService := task.NewTaskService(reporterCenter, taskConfService, reportRuleService, reportService)
	taskController := task.NewTaskController(rootLogger, taskService)
	taskController.Register(r)

	reportConfService := report_conf.NewReportConfService(reportRuleService)
	reportConfController := report_conf.NewReportConfController(rootLogger, reportConfService)
	reportConfController.Register(r)

	historyService := history_service.NewHistoryService(taskHistory, centerData, cmdbClient.CmdbObject)
	historyController := history_service.NewHistoryController(rootLogger, historyService)
	historyController.Register(r)

	dashboardService := dashboard.NewDashboardService(reportRuleService, collectorCenterClient.CollectionConfig, cmdbClient.Instance, centerData, taskHistory, objectStat)
	dashboardController := dashboard.NewDashboardController(rootLogger, dashboardService)
	dashboardController.Register(r)

	fillInstanceService := fill_instance.NewFillInstanceService(fillService, fillDispatcher)
	fillInstanceController := fill_instance.NewFillInstanceController(rootLogger, fillInstanceService)
	fillInstanceController.Register(r)

	listenAddr := fmt.Sprintf("%s:%d", conf.Service.Ip, conf.Service.Port)

	srv := &http.Server{
		Addr:    listenAddr,
		Handler: r,
	}

	g := run.Group{}
	{ //设定退出信号
		quit := make(chan os.Signal)
		// kill (no param) default send syscall.SIGTERM
		// kill -2 is syscall.SIGINT
		// kill -9 is syscall.SIGKILL but can't be catch, so don't need add it
		signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
		g.Add(func() error {
			<-quit
			log.Print("shutdown fintech_data ...")
			return nil
		}, func(e error) {
			if e != nil {
				log.Printf("start service err: %s", e.Error())
			}
			signal.Stop(quit)
			close(quit)
			return
		})
	}

	{ // 启动gin
		g.Add(func() error {
			return srv.ListenAndServe()
		}, func(e error) {
			if e != nil {
				log.Printf("stopping service err: %s", e.Error())
			} else {
				log.Println("stopping service ...")
			}
			srv.Shutdown(context.Background())
		})
	}

	// 启动定时上报任务
	{
		reportLogConfig := &LogConfig{
			Level:   conf.Log.Level,
			Logfile: &conf.Log.ReportTaskLogfile,
		}
		reportLogger := SetupLogging(reportLogConfig)
		defer reportLogger.Flush()
		reportJobManager := report_task.NewJobManager(taskConfService, reportService, reportRuleService)
		reportTimerJob := timer.NewTimerJob(redisClient, reportLogger, newRedisLock, conf.TimerConfig, reportJobManager, orgList, conf.TimerConfig.ReportJobInterval)
		reportTimer := timer.NewTimer(reportLogger, conf.TimerConfig, reportTimerJob)

		ctx, cancel := context.WithCancel(context.Background())
		g.Add(func() error {
			return reportTimer.RunTimeTask(ctx)
		}, func(e error) {
			if e != nil {
				log.Printf("stopping report task err: %s", e.Error())
			} else {
				log.Println("stopping report task ...")
			}
			cancel()
		})
	}

	// 启动定时检查任务
	checkLogConfig := &LogConfig{
		Level:   conf.Log.Level,
		Logfile: &conf.Log.CheckTaskLogfile,
	}
	if customer_settings.IsZhongXin {
		checkLogger := SetupLogging(checkLogConfig)
		defer checkLogger.Flush()
		zhongXinCheckerJobManager := report_task.NewZhongXinCheckJobManager(taskHistory, taskConfService, reportChecker, conf.ReportConf)
		zhongXinCheckerTimerJob := timer.NewTimerJob(redisClient, checkLogger, newRedisLock, conf.TimerConfig, zhongXinCheckerJobManager, orgList, conf.TimerConfig.CheckJobInterval)
		zhongXinCheckerTimer := timer.NewTimer(checkLogger, conf.TimerConfig, zhongXinCheckerTimerJob)
		ctx, cancel := context.WithCancel(context.Background())
		g.Add(func() error {
			return zhongXinCheckerTimer.RunTimeTask(ctx)
		}, func(e error) {
			if e != nil {
				log.Printf("stopping check task err: %s", e.Error())
			} else {
				log.Println("stopping check task ...")
			}
			cancel()
		})
	} else {
		checkLogger := SetupLogging(checkLogConfig)
		defer checkLogger.Flush()
		checkerJobManager := report_task.NewCheckJobManager(taskHistory, taskConfService, reportChecker, conf.ReportConf)
		checkerTimerJob := timer.NewTimerJob(redisClient, checkLogger, newRedisLock, conf.TimerConfig, checkerJobManager, orgList, conf.TimerConfig.CheckJobInterval)
		checkerTimer := timer.NewTimer(checkLogger, conf.TimerConfig, checkerTimerJob)
		ctx, cancel := context.WithCancel(context.Background())
		g.Add(func() error {
			return checkerTimer.RunTimeTask(ctx)
		}, func(e error) {
			if e != nil {
				log.Printf("stopping check task err: %s", e.Error())
			} else {
				log.Println("stopping check task ...")
			}
			cancel()
		})
	}

	// 定时记录上报数量至指标表
	{
		recordTaskConfig := &LogConfig{
			Level:   conf.Log.Level,
			Logfile: &conf.Log.RecordTaskLogfile,
		}
		recordLogger := SetupLogging(recordTaskConfig)
		defer recordLogger.Flush()
		recordJobManager := report_task.NewRecordJobManager(centerData, historyRecorder, mongoClient)
		recordTimerJob := timer.NewTimerJob(redisClient, recordLogger, newRedisLock, conf.TimerConfig, recordJobManager, orgList, conf.TimerConfig.CheckJobInterval)
		checkerTimer := timer.NewTimer(recordLogger, conf.TimerConfig, recordTimerJob)
		ctx, cancel := context.WithCancel(context.Background())
		g.Add(func() error {
			return checkerTimer.RunTimeTask(ctx)
		}, func(e error) {
			if e != nil {
				log.Printf("stopping check task err: %s", e.Error())
			} else {
				log.Println("stopping record task ...")
			}
			cancel()
		})
	}

	// 启动run group
	if err := g.Run(); err != nil {
		log.Fatal(err)
	}
}

func getAppPath() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	curPath, err := filepath.Abs(filepath.Dir(exe))
	if err != nil {
		return "", err
	}
	return filepath.Join(curPath, ".."), nil
}

func SetupLogging(lc *LogConfig) slog.Logger {
	w := zapcore.AddSync(lc.Logfile)
	core := zapcore.NewCore(
		zapcore.NewConsoleEncoder(zap.NewDevelopmentEncoderConfig()),
		w,
		lc.Level,
	)
	logger := zap.New(core, zap.AddCaller())
	return zaplog.Wrap(logger)
}

func gzipCompress(data interface{}) (string, error) {
	dataByte, err := json.Marshal(data)
	if err != nil {
		return "", err
	}
	compressedData, err := gZipData(dataByte)
	if err != nil {
		return "", nil
	}

	encodeStr := base64.StdEncoding.EncodeToString(compressedData)
	return encodeStr, nil
}

func gZipData(data []byte) ([]byte, error) {
	var b bytes.Buffer
	gz := gzip.NewWriter(&b)
	_, err := gz.Write(data)
	if err != nil {
		return nil, err
	}
	if err = gz.Flush(); err != nil {
		return nil, err
	}
	if err = gz.Close(); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

func newRedisLock(key, value string, client redis.UniversalClient, opt *redislock.Options) redislock.Lock {
	return redislock.NewDistributedMutex(key, value, client, opt)
}

func listOrg(orgClient organization.Client) ([]*user_service_model.OrgInfo, error) {
	orgList, err := orgClient.ListOrg(context.Background(), &types.Empty{})
	if err != nil {
		return nil, err
	}
	return orgList.Data, nil
}

func loadTlsVersion(conf *Config, tlsConf *tls.Config) {
	maxTlsVersion := agollo.GetString("report_center.max_tls_version", conf.ReportCenter.MaxTlsVersion)
	if maxTlsVersion != "" {
		tlsConf.MaxVersion = parseTlsVersion(maxTlsVersion)
	}
	minTlsVersion := agollo.GetString("report_center.min_tls_version", conf.ReportCenter.MinTlsVersion)
	if minTlsVersion != "" {
		tlsConf.MinVersion = parseTlsVersion(minTlsVersion)
	}
}

func parseTlsVersion(tlsVersion string) uint16 {
	switch tlsVersion {
	case "1.1":
		return tls.VersionTLS11
	case "1.2":
		return tls.VersionTLS12
	case "1.3":
		return tls.VersionTLS13
	default:
		return 0
	}
}

func NewLockFunc(redisClient redis.UniversalClient, lockKey string, lockExpiration int) redislock.Lock {
	redisLock := redislock.NewDistributedMutex(
		lockKey, "", redisClient, &redislock.Options{
			Expiration: time.Duration(lockExpiration) * time.Second,
			RetryCount: 2,
		})
	return redisLock
}
