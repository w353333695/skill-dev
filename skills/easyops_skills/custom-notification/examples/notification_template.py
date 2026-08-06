#! /usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""
EasyOps 自定义通知脚本模板

框架收到通知时，如果命中此通知脚本，则会调起入口函数 run。
在 run 函数中补充通知逻辑即可。
"""
import requests
import logging

# ============ 配置区 ============
# 通知渠道 API 地址
API_URL = "https://example.com/api/notify"
# 认证 Token（如需要）
API_TOKEN = ""
# 请求超时时间（秒）
TIMEOUT = 10
# ================================

logger = logging.getLogger(__name__)


def run(msg_data, users, cmdb_object_key='user_email', **kwargs):
    """
    通知入口函数。

    Args:
        msg_data (dict): 通知消息体
            - subject (str): 通知消息标题
            - content (str): 通知内容
        users (dict): 需要发送的用户信息字典，键为用户名，值为用户详情
            示例: {
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
        cmdb_object_key (str): CMDB 用户模型字段，如 user_email、dingding_userid、wework_userid 等
        **kwargs: 扩展参数

    Returns:
        list: 发送失败的用户名列表，空列表表示全部成功
    """
    failed_users = []
    subject = msg_data.get("subject", "")
    content = msg_data.get("content", "")

    for username, user_info in users.items():
        try:
            # 获取用户通知标识
            notify_target = user_info.get(cmdb_object_key, "")
            if not notify_target:
                logger.warning(f"用户 {username} 缺少字段 {cmdb_object_key}，跳过")
                failed_users.append(username)
                continue

            # TODO: 在此实现具体的通知发送逻辑
            # 示例：
            # payload = {
            #     "to": notify_target,
            #     "title": subject,
            #     "body": content
            # }
            # resp = requests.post(API_URL, json=payload, timeout=TIMEOUT)
            # resp.raise_for_status()

            logger.info(f"通知发送成功: {username} -> {notify_target}")

        except Exception as e:
            logger.error(f"通知发送失败: {username}, 错误: {e}")
            failed_users.append(username)

    return failed_users
if __name__ == "__main__":
    # 测试代码
    run({"subject": "测试标题", "content": "测试内容1111"}, {"easyops": {"user_email": "test"}})