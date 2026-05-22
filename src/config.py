"""一元管理する設定値。環境変数で上書き可能。"""
import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Step 1: Finviz スクリーナーの割安フィルタ（値は Finviz の選択肢ラベルと一致させる）
FINVIZ_FILTERS = {
    "Exchange": os.environ.get("FINVIZ_EXCHANGE", "NASDAQ"),
    "P/E": os.environ.get("FINVIZ_PE", "Under 15"),
    "PEG": os.environ.get("FINVIZ_PEG", "Under 1"),
    "P/S": os.environ.get("FINVIZ_PS", "Under 3"),
}

# スクリーニング結果のうち、詳細分析にかける上限（実行時間とAPI負荷の制御）
MAX_TICKERS = _i("MAX_TICKERS", 25)

# 最終的に通知する銘柄数の上限
TOP_N = _i("TOP_N", 10)

# DCF（簡易 FCFE モデル）の前提
DISCOUNT_RATE = _f("DCF_DISCOUNT_RATE", 0.09)      # 割引率（要求利回り）
TERMINAL_GROWTH = _f("DCF_TERMINAL_GROWTH", 0.025)  # 永続成長率
PROJECTION_YEARS = _i("DCF_PROJECTION_YEARS", 5)    # 予測期間
GROWTH_CAP = _f("DCF_GROWTH_CAP", 0.12)             # 成長率の上限
GROWTH_FLOOR = _f("DCF_GROWTH_FLOOR", 0.02)         # 成長率の下限

# 通知対象とする最低限の安全域（Margin of Safety）
MIN_MARGIN_OF_SAFETY = _f("MIN_MARGIN_OF_SAFETY", 0.15)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
