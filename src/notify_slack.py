"""Slack へ通知を送る。Bot Token + チャンネル ID 方式と Incoming Webhook の両方に対応。

優先順位:
  1. SLACK_BOT_TOKEN と SLACK_CHANNEL が両方設定されていれば Web API (chat.postMessage) を使用
  2. SLACK_WEBHOOK_URL が設定されていれば Incoming Webhook を使用
  3. どちらも無ければ送信をスキップ（ログのみ）
"""
import json
import logging
import os

import requests

from . import config

logger = logging.getLogger(__name__)

SLACK_API_URL = "https://slack.com/api/chat.postMessage"


def _send_via_bot_token(payload: dict, token: str, channel: str) -> bool:
    body = {
        "channel": channel,
        "text": payload.get("text", ""),
    }
    if "blocks" in payload:
        body["blocks"] = payload["blocks"]
    try:
        resp = requests.post(
            SLACK_API_URL,
            data=json.dumps(body),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack Web API がエラーを返しました: %s", data.get("error"))
            return False
        logger.info("Slack Web API 経由で送信成功: channel=%s", channel)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Slack Web API 送信に失敗: %s", exc)
        return False


def _send_via_webhook(payload: dict, url: str) -> bool:
    try:
        resp = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Slack Webhook 経由で送信成功")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Slack Webhook 送信に失敗: %s", exc)
        return False


def send(payload: dict) -> bool:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL", "")
    if token and channel:
        return _send_via_bot_token(payload, token, channel)

    if config.SLACK_WEBHOOK_URL:
        return _send_via_webhook(payload, config.SLACK_WEBHOOK_URL)

    logger.warning(
        "SLACK_BOT_TOKEN+SLACK_CHANNEL または SLACK_WEBHOOK_URL が未設定のため Slack 送信をスキップします"
    )
    return False
