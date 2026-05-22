"""Slack Incoming Webhook へ通知を送る。"""
import json
import logging

import requests

from . import config

logger = logging.getLogger(__name__)


def send(payload: dict) -> bool:
    if not config.SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL が未設定のため Slack 送信をスキップします")
        return False
    try:
        resp = requests.post(
            config.SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Slack 送信に成功しました")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Slack 送信に失敗: %s", exc)
        return False
