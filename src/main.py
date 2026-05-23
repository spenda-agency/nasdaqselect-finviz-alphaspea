"""エントリポイント: 3ステップを実行し、結果を Slack に通知する。

ローカル実行例:
    SLACK_WEBHOOK_URL=... python -m src.main
    python -m src.main --dry-run   # Slack 送信せず標準出力に表示
"""
import argparse
import json
import logging
import sys

from . import notify_slack, pipeline, report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("finviz-alphaspea")


def main() -> int:
    parser = argparse.ArgumentParser(description="過小評価 Nasdaq 銘柄を抽出して Slack 通知")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Slack に送らず、生成したペイロードを標準出力に表示する",
    )
    args = parser.parse_args()

    result = pipeline.run()
    logger.info(
        "ファネル: Nasdaq=%s, 割安通過=%s, 分析=%d, 業績=%d, 安全域=%d, RSI=%d, BB=%d, 通知=%d",
        result.funnel.nasdaq_total,
        result.funnel.finviz_passed,
        result.funnel.analyzed,
        result.funnel.after_trend,
        result.funnel.after_valuation,
        result.funnel.after_rsi,
        result.funnel.after_bb,
        result.funnel.notified,
    )

    payload = report.build_blocks(result)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ok = notify_slack.send(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
