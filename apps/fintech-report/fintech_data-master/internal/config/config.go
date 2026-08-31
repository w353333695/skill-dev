package config

import "go.easyops.local/fintech_data/internal/fill_instance"

type ReportCenter struct {
	Host                string `yaml:"host"`
	Port                int    `yaml:"port"`
	WithSSL             bool   `yaml:"with_ssl"`
	FacilityOwnerAgency string `yaml:"facilityOwnerAgency"`
	MaxTlsVersion       string `yaml:"max_tls_version"`
	MinTlsVersion       string `yaml:"min_tls_version"`
	Proxy               string `yaml:"proxy"`
}

type TimerConfig struct {
	RunInterval       int `yaml:"run_interval"`
	LockExpiration    int `yaml:"lock_expiration"`
	ReportJobInterval int `yaml:"report_job_interval"`
	CheckJobInterval  int `yaml:"check_job_interval"`
	RecordJobInterval int `yaml:"record_job_interval"`
}

type ReportConf struct {
	SearchBatch     int            `yaml:"search_batch"`
	TimeLimit       int            `yaml:"time_limit"`
	PKTranslate     []KeyTranslate `yaml:"pk_translate"`
	IgnoreConf      IgnoreConf     `yaml:"ignore_conf"`
	OmitemptyFields []string       `yaml:"omitempty_fields"`
	FloatPrecRule   []PrecRule     `yaml:"float_prec_rule"`
	ForceRetry      bool           `yaml:"force_retry"`
}

type PrecRule struct {
	ObjectId string         `yaml:"object_id"`
	Rule     map[string]int `yaml:"rule"`
}

type IgnoreConf struct {
	InstanceIgnoreAttr string   `yaml:"instance_ignore_attr"`
	AttrIgnoreCategory []string `yaml:"attr_ignore_category"`
}

type KeyTranslate struct {
	ObjectId           string `yaml:"object_id"`
	FacilityDescriptor string `yaml:"facilityDescriptor"`
	FacilityCategory   string `yaml:"facilityCategory"`
}

type FillInstance struct {
	QueueActiveTime      int                          `yaml:"queue_active_time"`
	SubscriberProcNum    int                          `yaml:"subscriber_proc_num"`
	InstanceRules        []fill_instance.InstanceRule `yaml:"instance_rules"`
	RelationRules        []fill_instance.RelationRule `yaml:"relation_rules"`
	InstanceFillConfFile string                       `yaml:"instance_fill_conf_file"`
	RelationFillConfFile string                       `yaml:"relation_fill_conf_file"`
}
