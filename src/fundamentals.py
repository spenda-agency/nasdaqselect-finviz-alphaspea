"""Step 2 相当: yfinance で業績トレンドと評価に必要な財務データを取得する。"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class Fundamentals:
    ticker: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    eps: Optional[float] = None
    book_value_per_share: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    # 直近のフリーキャッシュフロー（古い→新しい順）
    fcf_history: list = field(default_factory=list)
    # 売上トレンド（古い→新しい順）
    revenue_history: list = field(default_factory=list)
    # 純利益トレンド（古い→新しい順）
    net_income_history: list = field(default_factory=list)

    @property
    def revenue_growing(self) -> Optional[bool]:
        return _is_growing(self.revenue_history)

    @property
    def net_income_growing(self) -> Optional[bool]:
        return _is_growing(self.net_income_history)


def _is_growing(series: list) -> Optional[bool]:
    """先頭→末尾でおおむね右肩上がりかを判定。"""
    vals = [v for v in series if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return None
    return vals[-1] > vals[0]


def _row(df: Optional[pd.DataFrame], *names) -> list:
    """財務諸表 DataFrame から指定行を取り出し、古い→新しい順の値リストを返す。"""
    if df is None or df.empty:
        return []
    for name in names:
        if name in df.index:
            series = df.loc[name].dropna()
            # yfinance は列が新しい→古い順。古い→新しいに反転。
            return list(series[::-1].astype(float).values)
    return []


def fetch(ticker: str) -> Optional[Fundamentals]:
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}

        f = Fundamentals(ticker=ticker)
        f.price = info.get("currentPrice") or info.get("regularMarketPrice")
        f.market_cap = info.get("marketCap")
        f.shares_outstanding = info.get("sharesOutstanding")
        f.eps = info.get("trailingEps")
        f.book_value_per_share = info.get("bookValue")
        f.sector = info.get("sector")
        f.industry = info.get("industry")

        cashflow = tk.cashflow
        f.fcf_history = _row(cashflow, "Free Cash Flow")
        if not f.fcf_history:
            ocf = _row(cashflow, "Operating Cash Flow", "Total Cash From Operating Activities")
            capex = _row(cashflow, "Capital Expenditure", "Capital Expenditures")
            if ocf and capex and len(ocf) == len(capex):
                # CapEx は通常負値。OCF + CapEx = FCF。
                f.fcf_history = [o + c for o, c in zip(ocf, capex)]

        income = tk.income_stmt
        f.revenue_history = _row(income, "Total Revenue")
        f.net_income_history = _row(income, "Net Income", "Net Income Common Stockholders")

        return f
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s の財務取得に失敗: %s", ticker, exc)
        return None
