---
name: alarm-access
description: 解析三方告警系统 API 文档，生成告警获取与推送到 EasyOps webhook 的 Python 脚本，支持字段映射、重试机制和多数据源格式适配。
---
# 三方告警接入脚本生成

根据三方告警 API 文档，生成获取告警并推送到 EasyOps webhook 的脚本。

## 强制规则

**必须遵守，无例外：**

1. 解析文档前必须先检索 `./apis/` 缓存
2. 解析后必须将 OpenAPI 文档保存到 `./apis/` 目录
3. 即使文档不是标准 API 文档，也要生成 OpenAPI 规范并保存

## 工作流程

```
┌──────────────────────┐
│ 1. 检索 ./apis/ 缓存 │ ──命中──→ 读取缓存文件
└──────────┬───────────┘
           │未命中
           ▼
┌──────────────────────┐
│ 2. 解析源文档        │
└──────────┬───────────┘
           ▼
┌────────────────────────────────┐
│ 3. 【强制】保存到 ./apis/     │  ← 不可跳过！
└──────────┬─────────────────────┘
           ▼
┌──────────────────────┐
│ 4. 设计字段映射      │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 5. 生成推送脚本      │
└──────────────────────┘
```

## 步骤 1：检索 apis 缓存

```bash
mkdir -p ./apis
ls -la ./apis/*.yaml 2>/dev/null || echo "apis 目录为空"
```

缓存命名规则：

| 源文档            | 缓存文件                       |
| ----------------- | ------------------------------ |
| `gongji.pdf`    | `./apis/gongji-api.yaml`     |
| `prometheus.md` | `./apis/prometheus-api.yaml` |

## 步骤 2：解析源文档（缓存未命中时）

- **PDF 文档**：

  ```bash
  python scripts/doc_reader.py --type pdf --file "path/to/api.pdf"
  ```
- **Word 文档**：

  ```bash
  python scripts/doc_reader.py --type docx --file "path/to/api.docx"
  ```
- **Markdown 文档**：直接使用 Read 工具读取
- **URL**：使用 WebFetch 工具获取网页内容

## 步骤 3：保存 OpenAPI 到 ./apis/（对接**HTTP/HTTPS 的 Web API**时强制）

**这是强制步骤，必须执行！**

```bash
mkdir -p ./apis
# 使用 Write 工具将 OpenAPI 内容写入 ./apis/[api-name]-api.yaml
```

**特殊情况**：如果源文档不是标准 API 文档，基于数据结构推断 API 并保存。

## Webhook 规范

EasyOps 告警 webhook 接收以下格式的 POST 请求：

```json
{
    "alertId": "唯一告警ID",
    "subject": "告警标题",
    "content": "告警详情",
    "time": 1587783926,
    "isRecover": false,
    "source": "告警源标识",
    "originInfo": {}
}
```

### 字段说明

| 字段       | 类型   | 必填 | 说明             |
| ---------- | ------ | ---- | ---------------- |
| alertId    | string | 是   | 告警唯一标识     |
| subject    | string | 是   | 告警标题         |
| content    | string | 是   | 告警详情         |
| time       | int    | 是   | 告警时间戳（秒） |
| isRecover  | bool   | 是   | 是否恢复告警     |
| source     | string | 是   | 告警源标识       |
| originInfo | object | 是   | 原始告警数据     |

### Webhook URL

```
http://{host}/api/gateway/alert_portal.webhook/api/v1/alert/common/{org}/{accessId}
```

## 脚本规范

- 一次性执行模式，不使用 while 循环
- 使用 `logging` 和 `requests`
- 包含重试机制
- **不使用 argparse，直接在脚本顶部定义配置变量**
- **脚本末尾给出使用示例**

## 参考资源

- `references/webhook-spec.md` - Webhook 完整规范
- `references/field-mapping.md` - 字段映射指南
- `examples/webhook_pusher_template.py` - 推送脚本模板
