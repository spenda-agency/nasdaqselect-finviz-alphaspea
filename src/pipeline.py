"""3ステップを連結して、過小評価されている有望銘柄を抽出するパイプライン。"""
import logging
from dataclasses import dataclass
from typing import Optional

from . import config, fundamentals, screener, valuation
from .fundamentals import Fundamentals
from .valuation import Valuation

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    ticker: str
    company: Optional[str]
    sector: Optional[str]
    fund: Fundamentals
    val: Valuation


def _pick_ticker_column(row) -> Optional[str]:
    for key in ("Ticker", "ticker", "Symbol"):
        if key in row and row[key]:
            return str(row[key]).strip()
    return None


def run() -> list:
    # Step 1: Finviz で割安候補を絞り込む
    df = screener.screen_undervalued()
    if df.empty:
        return []

    company_by_ticker = {}
    tickers = []
    for _, row in df.iterrows():
        t = _pick_ticker_column(row)
        if not t:
            continue
        tickers.append(t)
        company_by_ticker[t] = row.get("Company") or row.get("company")
    tickers = tickers[: config.MAX_TICKERS]
    logger.info("詳細分析対象: %d 銘柄", len(tickers))

    candidates = []
    for t in tickers:
        # Step 2: 業績トレンドと財務データを取得
        f = fundamentals.fetch(t)
        if f is None:
            continue
        # Step 3: 適正株価と安全域を算出
        v = valuation.value(f)

        if v.margin_of_safety is None:
            continue
        if v.margin_of_safety < config.MIN_MARGIN_OF_SAFETY:
            continue
        # 業績が明確に縮小している銘柄（売上・利益とも減少）は除外
        if f.revenue_growing is False and f.net_income_growing is False:
            continue

        candidates.append(
            Candidate(
                ticker=t,
                company=company_by_ticker.get(t),
                sector=f.sector,
                fund=f,
                val=v,
            )
        )

    # 安全域の大きい順に並べる
    candidates.sort(key=lambda c: c.val.margin_of_safety or 0, reverse=True)
    return candidates[: config.TOP_N]
