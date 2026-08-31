package main

import (
	"github.com/openzipkin/zipkin-go"
	"go.easyops.local/agollo"
	"go.easyops.local/redis-helper/v8/redis"
	"go.easyops.local/slog"
	"io/ioutil"
	"os"
	"path/filepath"

	"go.uber.org/zap"
	lumberjack "gopkg.in/natefinch/lumberjack.v2"

	"go.easyops.local/fintech_data/internal/config"
	kitconfig "go.easyops.local/kit/config"
	"go.easyops.local/kit/tracing"
	kitmgodriver "go.easyops.local/mongo-helper/mongo-driver"
)

//自定义配置
type Config struct {
	Service struct {
		Ip   string `json:"ip" yaml:"ip"`
		Port int    `json:"port" yaml:"port"`
		Mode string `json:"mode" yaml:"mode"`
	} `json:"service" yaml:"service"`

	Log       *LogConfig        `yaml:"log"`
	AccessLog lumberjack.Logger `yaml:"accesslog"`
	Tracing   tracing.Config    `yaml:"tracing"`

	//依赖配置
	CmdbService struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"cmdb_service"`

	UserService struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"user_service"`

	MonthlyCollectionService struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"monthly_collection_service"`

	Notify struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"notify"`

	CollectorCenter struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"collector_center"`

	DataExchange struct {
		ServiceName string `yaml:"service_name"`
	} `yaml:"data_exchange"`

	ReportCenter config.ReportCenter `yaml:"report_center"`
	ReportConf   config.ReportConf   `yaml:"report_conf"`
	TimerConfig  config.TimerConfig  `yaml:"timer_config"`
	Redis        RedisConfig         `yaml:"redis"`
	Mongodb      MongoConfig         `yaml:"mongodb"`
	FillInstance config.FillInstance `yaml:"fill_instance"`
}

type LogConfig struct {
	Level               zap.AtomicLevel    `yaml:"level"`
	Logfile             *lumberjack.Logger `yaml:"logfile"`
	ReportTaskLogfile   lumberjack.Logger  `yaml:"report_task_logfile"`
	CheckTaskLogfile    lumberjack.Logger  `yaml:"check_task_logfile"`
	RecordTaskLogfile   lumberjack.Logger  `yaml:"record_task_logfile"`
	RoundTripperLogfile lumberjack.Logger  `yaml:"round_tripper_logfile"`
}

// 处理配置中的相对路径
func (c *Config) setBasePath(basePath string) {
	if !filepath.IsAbs(c.AccessLog.Filename) {
		c.AccessLog.Filename = filepath.Join(basePath, c.AccessLog.Filename)
	}
	if !filepath.IsAbs(c.Log.Logfile.Filename) {
		c.Log.Logfile.Filename = filepath.Join(basePath, c.Log.Logfile.Filename)
	}
	if !filepath.IsAbs(c.Log.ReportTaskLogfile.Filename) {
		c.Log.ReportTaskLogfile.Filename = filepath.Join(basePath, c.Log.ReportTaskLogfile.Filename)
	}
	if !filepath.IsAbs(c.Log.CheckTaskLogfile.Filename) {
		c.Log.CheckTaskLogfile.Filename = filepath.Join(basePath, c.Log.CheckTaskLogfile.Filename)
	}
	if !filepath.IsAbs(c.Log.RecordTaskLogfile.Filename) {
		c.Log.RecordTaskLogfile.Filename = filepath.Join(basePath, c.Log.RecordTaskLogfile.Filename)
	}
	if !filepath.IsAbs(c.Log.RoundTripperLogfile.Filename) {
		c.Log.RoundTripperLogfile.Filename = filepath.Join(basePath, c.Log.RoundTripperLogfile.Filename)
	}
}

func loadConfig() (*Config, error) {
	curPath, err := filepath.Abs(filepath.Dir(os.Args[0]))
	if err != nil {
		return nil, err
	}

	confInstance := new(Config)
	defaultConfFile := curPath + "/../conf/conf.default.yaml"
	customConfFile := curPath + "/../conf/conf.yaml"
	generatedConfFile := curPath + "/../conf/conf.generated.yaml"

	err = kitconfig.LoadYamlConfig(confInstance, defaultConfFile, customConfFile, generatedConfFile)
	if err != nil {
		return nil, err
	}

	err = loadFillInstanceRule(curPath, confInstance)
	if err != nil {
		return nil, err
	}

	return confInstance, nil
}

func loadFillInstanceRule(curPath string, confInstance *Config) error {
	fillInstanceConfig := new(config.FillInstance)
	confPath := curPath + "/../conf"
	fileInfo, err := ioutil.ReadDir(confPath)
	if err != nil {
		return err
	}
	for _, info := range fileInfo {
		if match, _ := filepath.Match(confInstance.FillInstance.InstanceFillConfFile, info.Name()); match {
			fullPath := filepath.Join(confPath, info.Name())
			customConfig := new(config.FillInstance)
			err = kitconfig.LoadYamlConfig(customConfig, fullPath)
			if err != nil {
				return err
			}
			fillInstanceConfig.InstanceRules = append(fillInstanceConfig.InstanceRules, customConfig.InstanceRules...)
			continue
		}
		if match, _ := filepath.Match(confInstance.FillInstance.RelationFillConfFile, info.Name()); match {
			fullPath := filepath.Join(confPath, info.Name())
			customConfig := new(config.FillInstance)
			err = kitconfig.LoadYamlConfig(customConfig, fullPath)
			if err != nil {
				return err
			}
			fillInstanceConfig.RelationRules = append(fillInstanceConfig.RelationRules, customConfig.RelationRules...)
			continue
		}
	}
	confInstance.FillInstance.InstanceRules = fillInstanceConfig.InstanceRules
	confInstance.FillInstance.RelationRules = fillInstanceConfig.RelationRules
	return nil
}

type RedisConfig struct {
	redis.RedisConfig   `yaml:",inline"`
	ServiceName         string `yaml:"service_name"`
	SentinelServiceName string `yaml:"sentinel_service_name"`
}

type MongoConfig struct {
	kitmgodriver.MongoConfig `yaml:",inline"`
	Database                 string `yaml:"database"`

	// DEPRECATED
	ServiceName string `yaml:"service_name"`
}

func setupAppConfig(logger slog.Logger, tracer *zipkin.Tracer, conf *Config) error {
	curPath, err := filepath.Abs(filepath.Dir(os.Args[0]))
	if err != nil {
		return err
	}
	// 根据配置文件件初始化 appconfig client
	appConfigFile := filepath.Join(curPath, "..", "conf/.appconfig/config.yaml")
	err = agollo.StartWithConfigFile(logger, tracer, appConfigFile)
	if err != nil {
		return err
	}
	// get redis-auth from appconfig
	conf.Redis.Password = agollo.MustGetString("password", agollo.WithNamespace("redis-auth"))
	conf.Redis.SentinelModel = agollo.GetBool("sentinel", conf.Redis.SentinelModel, agollo.WithNamespace("redis-auth"))
	// get mongodb-auth from appconfig
	conf.Mongodb.Password = agollo.MustGetString("password", agollo.WithNamespace("mongodb-auth"))
	conf.Mongodb.Username = agollo.GetString("username", conf.Mongodb.Username, agollo.WithNamespace("mongodb-auth"))
	return nil
}
