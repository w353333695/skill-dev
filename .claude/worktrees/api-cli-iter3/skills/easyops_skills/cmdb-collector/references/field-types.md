# CMDB 字段类型详解

## 基础类型

| 类型 | 说明 | CMDB 格式要求 | Python 对应 |
|-----|------|--------------|------------|
| str | 字符串 | - | str |
| int | 整数 | - | int |
| float | 浮点数 | - | float |
| bool | 布尔值 | - | bool |
| date | 日期 | `YYYY-MM-DD` | str |
| datetime | 日期时间 | `YYYY-MM-DD HH:MM:SS` | str |
| ip | IP 地址 | - | str |

## 日期时间格式转换（重要！）

**CMDB 严格要求的格式：**
- `date`：`YYYY-MM-DD`（如 `2024-01-15`）
- `datetime`：`YYYY-MM-DD HH:MM:SS`（如 `2024-01-15 10:30:00`）

**三方系统常见格式及转换：**

| 源格式 | 示例 | 转换方法 |
|-------|------|---------|
| ISO 8601 | `2024-01-15T10:30:00Z` | 去掉 `T` 和 `Z`，截取前 19 位 |
| ISO 8601 带毫秒 | `2024-01-15T10:30:00.000Z` | 去掉 `T`、毫秒和 `Z` |
| ISO 8601 带时区 | `2024-01-15T10:30:00+08:00` | 去掉 `T` 和时区 |
| Unix 时间戳（秒） | `1705297800` | `datetime.fromtimestamp()` |
| Unix 时间戳（毫秒） | `1705297800000` | 除以 1000 后转换 |
| 斜杠格式 | `2024/01/15 10:30:00` | 替换 `/` 为 `-` |

**采集脚本必须实现 `parse_datetime()` 和 `parse_date()` 函数处理格式转换！**

## 复合类型

| 类型 | 说明 | Python 对应 | 必须字段 |
|-----|------|------------|---------|
| arr | 字符串数组 | list[str] | - |
| enum | 单选枚举 | str | `regex` (选项列表) |
| enums | 多选枚举 | list[str] | `regex` (选项列表) |
| struct | 结构体 | dict | `struct_define` (字段定义) |
| structs | 结构体数组 | list[dict] | `struct_define` (字段定义) |

## 复合类型详细定义

### enum (单选枚举)

当 API 字段有固定选项时使用，必须提供 `regex` 字段列出所有选项：

```json
{
  "id": "status",
  "name": "状态",
  "value": {
    "type": "enum",
    "regex": ["RUNNING", "STOPPED", "CREATING", "DELETING", "UNAVAILABLE"],
    "default": "",
    "mode": "default",
    "default_type": "value"
  }
}
```

**识别方式**：OpenAPI 中 `type: string` + `enum: [...]`

### enums (多选枚举)

当字段是枚举值数组时使用：

```json
{
  "id": "capabilities",
  "name": "能力列表",
  "value": {
    "type": "enums",
    "regex": ["READ", "WRITE", "ADMIN", "BACKUP"],
    "default": "",
    "mode": "default",
    "default_type": "value"
  }
}
```

**识别方式**：OpenAPI 中 `type: array` + `items.enum: [...]`

### struct (结构体)

当字段是嵌套对象时使用，必须提供 `struct_define` 定义内部字段：

```json
{
  "id": "resourceConfig",
  "name": "资源配置",
  "value": {
    "type": "struct",
    "struct_define": [
      {"id": "cpu", "name": "CPU核数", "type": "int"},
      {"id": "memory", "name": "内存GB", "type": "int"},
      {"id": "disk", "name": "磁盘GB", "type": "int"},
      {"id": "iops", "name": "IOPS", "type": "int"}
    ],
    "default": "",
    "mode": "default",
    "default_type": "value"
  }
}
```

**识别方式**：OpenAPI 中 `type: object` + `properties: {...}`

### structs (结构体数组)

当字段是对象数组时使用：

```json
{
  "id": "rootServers",
  "name": "RootServer列表",
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

**识别方式**：OpenAPI 中 `type: array` + `items.type: object` + `items.properties: {...}`

## struct_define 字段格式

`struct_define` 数组中每个元素的格式：

```json
{"id": "字段ID", "name": "字段名称", "type": "字段类型"}
```

支持的内部类型：`str`, `int`, `float`, `bool`, `date`, `datetime`

**注意**：struct_define 内部不支持嵌套 struct/structs，复杂嵌套结构需要扁平化处理。

## 类型推断规则

```python
def infer_cmdb_type(value):
    """根据 Python 值推断 CMDB 类型"""
    if isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, str):
        # 检查是否为 IP
        if is_valid_ip(value):
            return "ip"
        # 检查是否为日期
        if is_valid_date(value):
            return "date"
        return "str"
    elif isinstance(value, list):
        if not value:
            return "arr"
        if all(isinstance(i, str) for i in value):
            return "arr"
        if all(isinstance(i, dict) for i in value):
            return "structs"
        return "arr"
    elif isinstance(value, dict):
        return "struct"
    return "str"
```

## 从 OpenAPI 识别字段类型

```yaml
# 1. 枚举类型 → enum
status:
  type: string
  enum: [RUNNING, STOPPED]  # 有 enum 就用 enum 类型

# 2. 枚举数组 → enums
tags:
  type: array
  items:
    type: string
    enum: [tag1, tag2]  # 数组内有 enum 就用 enums 类型

# 3. 对象类型 → struct
config:
  type: object
  properties:
    cpu: {type: integer}
    memory: {type: integer}

# 4. 对象数组 → structs
servers:
  type: array
  items:
    type: object
    properties:
      ip: {type: string}
      port: {type: integer}
```

## 字段属性

### required
- `"true"` - 必填字段
- `"false"` - 可选字段

### unique
- `"true"` - 唯一字段，用于数据去重
- `"false"` - 非唯一字段

### readonly
- `"true"` - 只读字段
- `"false"` - 可编辑字段

## 特殊字段模式

### 密码字段
```json
{
    "value": {
        "type": "str",
        "mode": "password"
    }
}
```

### 自增序列
```json
{
    "value": {
        "type": "str",
        "mode": "series-number",
        "prefix": "SN",
        "start_value": 1,
        "series_number_length": 6
    }
}
```

### 附件字段
```json
{
    "value": {
        "type": "structs",
        "mode": "attachment",
        "struct_define": [
            {"id": "name", "name": "name", "type": "str"},
            {"id": "type", "name": "type", "type": "str"},
            {"id": "url", "name": "url", "type": "str"},
            {"id": "size", "name": "size", "type": "float"}
        ]
    }
}
```
