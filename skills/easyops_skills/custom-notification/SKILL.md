---
name: custom-notification
description: 开发 EasyOps 自定义通知脚本（Python 2），将告警消息通过企业微信机器人、飞书、短信网关等自定义渠道发送给指定用户，遵循平台通知框架规范。
version: 0.1.0
---
# EasyOps 自定义通知脚本开发指南

本 skill 用于指导开发 EasyOps 平台的自定义通知脚本，实现将告警消息通过自定义渠道（如企业微信机器人、飞书、短信网关、邮件等）发送给指定用户。

## 脚本框架

通知脚本必须遵循 EasyOps 通知框架规范：

```python
#! /usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
import requests
import logging

def run(msg_data, users, cmdb_object_key='user_email', **kwargs):
    """
    通知入口函数，框架命中通知脚本时自动调用。

    Args:
        msg_data: 通知消息体
        users: 需要通知的用户信息字典
        cmdb_object_key: CMDB 用户模型字段标识
        **kwargs: 扩展参数

    Returns:
        list: 发送失败的用户列表（空列表表示全部成功）
    """
    failed_users = []
    # 通知逻辑
    return failed_users
```

## 参数说明

### msg_data（消息体）

```json
{
    "subject": "通知消息标题",
    "content": "通知内容"
}
```

### users（用户信息字典）

键为用户名，值为用户详情：

```json
{
    "easyops": {
        "dingding_userid": "",
        "gender": "女",
        "instanceId": "5b1fe26669fcc",
        "name": "easyops",
        "nickname": "easyops",
        "state": "valid",
        "user_email": "88@qq.com",
        "user_tel": "18212341234"
    }
}
```

### cmdb_object_key（用户标识字段）

指定使用哪个 CMDB 用户模型字段作为通知目标标识：

| 常用值              | 说明           |
| ------------------- | -------------- |
| `user_email`      | 邮箱地址       |
| `user_tel`        | 手机号         |
| `dingding_userid` | 钉钉用户ID     |
| `wework_userid`   | 企业微信用户ID |

## 开发流程

### 1. 确定通知渠道

收集以下信息：

- 通知渠道类型（企业微信机器人、飞书、短信网关、自定义 HTTP 接口等）
- 渠道 API 地址和认证方式
- 消息格式要求（Markdown、文本、卡片等）
- 用户标识字段（邮箱、手机号、第三方 userid 等）

### 2. 生成通知脚本

基于 `examples/notification_template.py` 模板，按需求生成脚本：

- 配置通知渠道的 API 地址和认证信息
- 实现消息格式转换逻辑
- 遍历 users 字典，根据 cmdb_object_key 获取用户标识
- 调用渠道 API 发送通知
- 记录失败用户并返回

### 3. 测试脚本

```bash
# 使用 EasyOps Python 环境执行
/usr/local/easyops/python/bin/python notification_script.py
```

## 脚本规范

- **Python 版本：Python 2**，EasyOps 通知脚本运行在平台内置的 Python 2 环境中
- 解释器：`#! /usr/local/easyops/python/bin/python`
- 编码声明：`# -*- coding: utf-8 -*-`
- 必须导入 `requests` 和 `logging`
- 入口函数签名固定为 `run(msg_data, users, cmdb_object_key='user_email', **kwargs)`
- 返回值为发送失败的用户列表（用户名字符串列表）
- 使用 `logging` 记录关键日志，便于排查问题
- 包含异常处理，确保单个用户发送失败不影响其他用户
- 配置项（如 API 地址、Token）放在脚本顶部作为常量

## 参考资源

- `examples/notification_template.py` - 通知脚本基础模板
- `examples/wecom_bot_notification.py` - 企业微信机器人通知示例
- `api-automation` skill - EasyOps 内部 API 调用模板（脚本需调用平台 API 时参考）
