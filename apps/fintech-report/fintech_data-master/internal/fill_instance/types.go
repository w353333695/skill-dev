package fill_instance

import funk "github.com/thoas/go-funk"

type RuleObjectConf struct {
	ObjectId     string   `yaml:"object_id"`
	ObjectIdList []string `yaml:"object_id_list"`
}

func (c RuleObjectConf) EffectedObject(objectId string) bool {
	if c.ObjectId == objectId {
		return true
	}
	if funk.Contains(c.ObjectIdList, objectId) {
		return true
	}
	return false
}

type InstanceRule struct {
	RuleObjectConf `yaml:",inline"`
	AttrId         string       `yaml:"attr_id"`
	AttrSource     []AttrDefine `yaml:"attr_source"`
	Case           []Case       `yaml:"case"`
	Default        *Value       `yaml:"default"`
}

type AttrDefine struct {
	Key        string `yaml:"key"`
	IgnoreFail bool   `yaml:"ignore_fail"`
	ValuePath  `yaml:",inline"`
}

type CaseRelation string

const (
	RelOr  CaseRelation = "or"
	RelAnd CaseRelation = "and"
)

type Case struct {
	Rel       CaseRelation `yaml:"rel"`
	Condition []Condition  `yaml:"condition"`
	Value     Value        `yaml:"value"`
}

type ConditionOpr string

const (
	OprEqual   ConditionOpr = "=="
	OprNoEqual ConditionOpr = "!="
	OprIsNull  ConditionOpr = "isNull"
	OprNotNull ConditionOpr = "notNull"
	OprIn      ConditionOpr = "in"
	OprNin     ConditionOpr = "nin"
)

type Condition struct {
	Key   string       `yaml:"key"`
	Opr   ConditionOpr `yaml:"opr"`
	Value interface{}  `yaml:"value"`
}

type ValueType string

const (
	ValueTypeConst   ValueType = "const"
	ValueTypeMapping ValueType = "mapping"
)

type Value struct {
	Type      ValueType   `yaml:"type"`
	Const     interface{} `yaml:"const"`
	ValuePath `yaml:",inline"`
}

type SourceType string

const (
	SourceTypeInstance SourceType = "instance"
	SourceTypeStruct   SourceType = "struct"
)

type ValuePath struct {
	Path   string     `yaml:"path"`
	Source SourceType `yaml:"source"`
}

type RelationRule struct {
	RuleObjectConf  `yaml:",inline"`
	SourceField     string           `yaml:"source_field"`
	RelatedInstance RelatedInstance  `yaml:"related_instance"`
	Mapping         []RelatedMapping `yaml:"mapping"`
}

type RelatedInstance struct {
	ObjectId     string `yaml:"object_id"`
	RelatedField string `yaml:"related_field"`
}

type RelatedMapping struct {
	AttrId     string `yaml:"attr_id"`
	MappingKey string `yaml:"mapping_key"`
}
