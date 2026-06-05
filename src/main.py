"""エントリポイント: 当日の対象市場を判定し、各市場の Top N 候補を Google Sheets に書き出す。

スケジュール仕様:
  - US (Nasdaq): 火〜土 16:00 JST （US 市場クローズ後）
  - JP (東証プライム): 月〜金 16:00 JST （東証クローズ後）

GitHub Actions 側は Mon-Sat 07:00 UTC (= 16:00 JST) で一律トリガし、
本モジュールが JST 曜日で実行対象を絞り込む。

ローカル実行例:
    python -m src.main --dry-run
    GOOGLE_CREDENTIALS_JSON=... SPREADSHEET_ID=... python -m src.main
    python -m src.main --markets US,JP      # 曜日判定を無視して両方走らせる
"""
import argparse
import datetime as _dt
import json
import logging
import sys
from typing import List

from . import pipeline, sheets_writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("finviz-alphaspea")


def _today_jst() -> _dt.date:
    return (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).date()


def _markets_for_today() -> List[str]:
    """JST 曜日に基づいて当日走らせる市場を返す。

    - 月 (0): JP のみ
    - 火〜金 (1-4): US + JP
    - 土 (5): US のみ
    - 日 (6): なし
    """
    dow = _today_jst().weekday()
    markets: List[str] = []
    if dow in (1, 2, 3, 4, 5):  # 火〜土
        markets.append("US")
    if dow in (0, 1, 2, 3, 4):  # 月〜金
        markets.append("JP")
    return markets


def main() -> int:
    parser = argparse.ArgumentParser(description="過小評価銘柄を抽出して Google Sheets に書き出す")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sheets に書かず、生成した行データを標準出力に表示する",
    )
    parser.add_argument(
        "--markets",
        default=None,
        help='実行対象市場をカンマ区切りで明示指定 (例: "US,JP")。指定なしなら JST 曜日で自動判定',
    )
    args = parser.parse_args()

    if args.markets:
        markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    else:
        markets = _markets_for_today()
    logger.info("本日 (JST=%s) の対象市場: %s", _today_jst(), markets or "(なし)")

    if not markets:
        logger.info("本日の対象市場がないため終了します")
        return 0

    results = []
    for m in markets:
        logger.info("==== %s pipeline 開始 ====", m)
        result = pipeline.run(market=m)
        f = result.funnel
        logger.info(
            "[%s] ファネル: universe=%s, filter=%s, 分析=%d, 業績=%d, 安全域=%d, RSI=%d, BB=%d, 通知=%d",
            m,
            f.universe_total,
            f.filter_passed,
            f.analyzed,
            f.after_trend,
            f.after_valuation,
            f.after_rsi,
            f.after_bb,
            f.notified,
        )
        results.append(result)

    if args.dry_run:
        today = _today_jst().isoformat()
        preview = {
            r.market: {
                "tab": sheets_writer.TAB_NAME.get(r.market),
                "today_rows": sheets_writer.build_today_rows(r, today),
            }
            for r in results
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2, default=str))
        return 0

    ok = sheets_writer.write_results(results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

