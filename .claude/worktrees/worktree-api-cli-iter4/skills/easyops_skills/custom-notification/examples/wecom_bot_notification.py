#! /usr/local/easyops/python/bin/python
# -*- coding: utf-8 -*-
"""
EasyOps 自定义通知脚本 - 企业微信机器人示例

通过企业微信群机器人 Webhook 发送告警通知。
注意：群机器人是发送到群，不区分具体用户，适用于群通知场景。
"""
import requests
import logging

# ============ 配置区 ============
# 企业微信机器人 Webhook 地址
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
# 请求超时时间（秒）
TIMEOUT = 10
# ================================

logger = logging.getLogger(__name__)


def run(msg_data, users, cmdb_object_key='wework_userid', **kwargs):
    """
    企业微信机器人通知入口。

    通过 Webhook 将告警消息推送到企业微信群，并 @ 相关用户。
    """
    failed_users = []
    subject = msg_data.get("subject", "")
    content = msg_data.get("content", "")

    # 收集需要 @ 的用户 ID
    mentioned_users = []
    for username, user_info in users.items():
        userid = user_info.get(cmdb_object_key, "")
        if userid:
            mentioned_users.append(userid)
        else:
            logger.warning(f"用户 {username} 缺少字段 {cmdb_object_key}")
            failed_users.append(username)

    # 构造消息体
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": (
                f"## {subject}\n\n"
                f"{content}\n\n"
                f"<@{'><@'.join(mentioned_users)}>"
            )
        }
    }

    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") != 0:
            logger.error(f"企业微信机器人返回错误: {result}")
            # 机器人发送失败，所有用户都算失败
            failed_users = list(users.keys())
        else:
            logger.info(f"企业微信机器人通知发送成功，通知用户数: {len(mentioned_users)}")
    except Exception as e:
        logger.error(f"企业微信机器人通知发送异常: {e}")
        failed_users = list(users.keys())

    return failed_users

if __name__ == "__main__":
    # 测试代码
    run({"subject": "测试标题", "content": "测试内容1111"}, {"easyops": {"user_email": "test"}})