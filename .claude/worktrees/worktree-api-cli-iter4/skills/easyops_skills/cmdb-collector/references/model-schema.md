# CMDB 模型 JSON 结构

## 完整模型结构

```json
{
    "objectId": "MODEL_ID",
    "name": "模型名称",
    "category": "分类名称",
    "memo": "模型描述",
    "protected": false,
    "isAbstract": false,
    "system": "",
    "wordIndexDenied": false,
    "notifyDenied": false,
    "view": {
        "attr_category_order": ["基本信息"],
        "attr_order": ["field1", "field2"],
        "show_key": ["instanceId"],
        "visible": true,
        "icon": {
            "category": "second-menu",
            "icon": "placeholder-second-menu",
            "lib": "easyops"
        }
    },
    "attrList": [
        {
            "id": "field_id",
            "name": "字段名称",
            "description": "字段描述",
            "tag": ["基本信息"],
            "required": "false",
            "readonly": "false",
            "unique": "false",
            "value": {
                "type": "str",
                "default": "",
                "mode": "default",
                "default_type": "value"
            }
        }
    ]
}
```

## 字段定义 (attrList)

### 基础字段

```json
{
    "id": "hostname",
    "name": "主机名",
    "description": "服务器主机名",
    "tag": ["基本信息"],
    "required": "true",
    "readonly": "false",
    "unique": "true",
    "value": {
        "type": "str",
        "default": "",
        "mode": "default",
        "default_type": "value"
    }
}
```

### 枚举字段

**单选枚举** - 必须包含 `regex` 列出所有选项：

```json
{
    "id": "status",
    "name": "状态",
    "tag": ["状态信息"],
    "required": "false",
    "readonly": "false",
    "unique": "false",
    "value": {
        "type": "enum",
        "regex": ["RUNNING", "STOPPED", "CREATING", "DELETING", "UNAVAILABLE"],
        "default": "",
        "mode": "default",
        "default_type": "value"
    }
}
```

### 多选枚举

**多选枚举** - 必须包含 `regex` 列出所有选项：

```json
{
    "id": "tags",
    "name": "标签",
    "tag": ["基本信息"],
    "required": "false",
    "readonly": "false",
    "unique": "false",
    "value": {
        "type": "enums",
        "regex": ["生产", "测试", "开发", "预发布"],
        "default": "",
        "mode": "default",
        "default_type": "value"
    }
}
```

### 结构体字段

**结构体** - 必须包含 `struct_define` 定义内部字段：

```json
{
    "id": "resourceConfig",
    "name": "资源配置",
    "tag": ["配置信息"],
    "required": "false",
    "readonly": "false",
    "unique": "false",
    "value": {
        "type": "struct",
        "struct_define": [
            {"id": "cpu", "name": "CPU核数", "type": "int"},
            {"id": "memory", "name": "内存GB", "type": "int"},
            {"id": "disk", "name": "磁盘GB", "type": "int"}
        ],
        "default": "",
        "mode": "default",
        "default_type": "value"
    }
}
```

### 结构体数组

**结构体数组** - 必须包含 `struct_define` 定义内部字段：

```json
{
    "id": "rootServers",
    "name": "RootServer列表",
    "tag": ["配置信息"],
    "required": "false",
    "readonly": "false",
    "unique": "false",
    "value": {
        "type": "structs",
        "struct_define": [
            {"id": "address", "name": "地址", "type": "str"},
            {"id": "role", "name": "角色", "type": "str"},
            {"id": "sql_port", "name": "SQL端口", "type": "int"},
            {"id": "status", "name": "状态", "type": "str"}
        ],
        "default": "",
        "mode": "default",
        "default_type": "value"
    }
}
```

## 模型关系 (relation_list)

模型之间的关联关系定义。分析 API 响应中的引用字段（如 `cluster_id`、`tenant_id`）自动生成关系。

**重要：同一个关系只需在关系两端的任意一端定义一次！**

例如 ZONE 和 CLUSTER 的关系，只在 ZONE 模型的 `relation_list` 中定义，不要在 CLUSTER 模型中重复定义。否则导入时会报错："关系定义重复: 模型 XXX 已存在关系名称 YYY"。

### 关系结构

以 TENANT@OCP（租户）关联 CLUSTER@OCP（集群）为例：

```json
{
    "relation_id": "TENANT@OCP_clusters_tenants_CLUSTER@OCP",
    "name": "",
    "protected": false,
    "notifyDenied": false,
    "isInherit": false,
    "left_object_id": "TENANT@OCP",
    "leftInheritObjectId": "",
    "left_id": "clusters",
    "left_description": "关联租户实例",
    "left_remark": "",
    "left_name": "关联集群",
    "left_min": 0,
    "left_max": 1,
    "left_groups": [],
    "left_tags": [],
    "left_required": false,
    "right_object_id": "CLUSTER@OCP",
    "rightInheritObjectId": "",
    "right_id": "tenants",
    "right_description": "关联集群",
    "right_remark": "",
    "right_name": "关联租户实例",
    "right_min": 0,
    "right_max": -1,
    "right_groups": [],
    "right_tags": [],
    "right_required": false,
    "_version": 1,
    "attrList": [],
    "indexList": []
}
```

### 关系字段说明

| 字段 | 说明 | 示例 |
|-----|------|------|
| `relation_id` | 关系唯一ID，格式：`{左模型ID}_{左关系ID}_{右关系ID}_{右模型ID}` | `TENANT@OCP_clusters_tenants_CLUSTER@OCP` |
| `left_object_id` | 左侧模型ID | `TENANT@OCP` |
| `left_id` | 左侧关系ID，复数形式，用于实例数据写入 | `clusters` |
| `left_name` | 左侧关系名称，"关联{右侧模型名称}" | `关联集群` |
| `left_description` | 左侧关系描述，"关联{左侧模型名称}实例" | `关联租户实例` |
| `left_max` | 左侧最大数量，`-1` 表示多个，`1` 表示一个 | `1`（多对一场景） |
| `right_object_id` | 右侧模型ID | `CLUSTER@OCP` |
| `right_id` | 右侧关系ID，复数形式，用于实例数据写入 | `tenants` |
| `right_name` | 右侧关系名称，"关联{左侧模型名称}实例" | `关联租户实例` |
| `right_description` | 右侧关系描述，"关联{右侧模型名称}" | `关联集群` |
| `right_max` | 右侧最大数量，`-1` 表示多个，`1` 表示一个 | `-1`（一对多场景） |

### 实例数据写入关系

写入实例时，使用关系 ID（`left_id` 或 `right_id`）关联其他实例：

```json
{
    "name": "tenant1",
    "clusters": [
        {"cluster_id": 1}
    ]
}
```

其中 `clusters` 是 `left_id`，`cluster_id` 是 CLUSTER@OCP 的唯一键。

### 关系识别规则

分析 API 响应字段，识别以下模式：

| 字段模式 | 关系类型 | 示例 |
|---------|---------|------|
| `{model}_id` | 多对一 | `cluster_id` → 租户关联集群 |
| `{model}Id` | 多对一 | `clusterId` → 租户关联集群 |
| `{model}_ids` / `{model}Ids` | 多对多 | `host_ids` → 集群关联多个主机 |
| `parent_{model}` | 父子关系 | `parent_zone` → Zone 的父级 |

### 关系基数 (left_max / right_max)

| 场景 | left_max | right_max | 说明 |
|-----|----------|-----------|------|
| 一对多 | `1` | `-1` | 如：一个集群有多个租户 |
| 多对一 | `-1` | `1` | 如：多个租户属于一个集群 |
| 多对多 | `-1` | `-1` | 如：主机和标签 |
| 一对一 | `1` | `1` | 如：主机和主机详情 |

## 导入模型 API

```
POST /v2/object_import
{
    "object_list": [模型JSON],
    "ignore_dst_relation": true
}
```
