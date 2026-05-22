"""Step 3 相当: 適正株価（Intrinsic Value）を自前計算し、安全域を求める。

Alpha Spread の公開 API が無いため、同種の指標を独自に算出する:
  - 簡易 DCF（FCFE 近似）
  - グレアム数（Benjamin Graham のフェアバリュー目安）
両者の有効な値を平均して Intrinsic Value とし、現在株価との乖離を
Margin of Safety として返す。
"""
import logging
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from . import config
from .fundamentals import Fundamentals

logger = logging.getLogger(__name__)


@dataclass
class Valuation:
    ticker: str
    price: Optional[float]
    dcf_value: Optional[float]
    graham_value: Optional[float]
    intrinsic_value: Optional[float]
    margin_of_safety: Optional[float]  # (intrinsic - price) / intrinsic


def _historical_growth(fcf_history: list) -> float:
    """FCF 履歴から CAGR を求め、上下限でクリップする。"""
    vals = [v for v in fcf_history if v is not None and not pd.isna(v)]
    if len(vals) < 2 or vals[0] <= 0 or vals[-1] <= 0:
        return config.GROWTH_FLOOR
    years = len(vals) - 1
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1
    return max(config.GROWTH_FLOOR, min(config.GROWTH_CAP, cagr))


def _dcf(f: Fundamentals) -> Optional[float]:
    vals = [v for v in f.fcf_history if v is not None and not pd.isna(v)]
    if not vals or not f.shares_outstanding or f.shares_outstanding <= 0:
        return None
    fcf0 = vals[-1]
    if fcf0 <= 0:
        return None

    g = _historical_growth(f.fcf_history)
    r = config.DISCOUNT_RATE
    g_term = config.TERMINAL_GROWTH
    if r <= g_term:
        return None

    pv = 0.0
    fcf = fcf0
    for year in range(1, config.PROJECTION_YEARS + 1):
        fcf *= (1 + g)
        pv += fcf / ((1 + r) ** year)

    terminal = fcf * (1 + g_term) / (r - g_term)
    pv += terminal / ((1 + r) ** config.PROJECTION_YEARS)

    return pv / f.shares_outstanding


def _graham(f: Fundamentals) -> Optional[float]:
    """グレアム数 = sqrt(22.5 * EPS * BVPS)。正の値のときのみ有効。"""
    if not f.eps or not f.book_value_per_share:
        return None
    if f.eps <= 0 or f.book_value_per_share <= 0:
        return None
    return math.sqrt(22.5 * f.eps * f.book_value_per_share)


def value(f: Fundamentals) -> Valuation:
    dcf_v = _dcf(f)
    graham_v = _graham(f)

    candidates = [v for v in (dcf_v, graham_v) if v and v > 0]
    intrinsic = sum(candidates) / len(candidates) if candidates else None

    mos = None
    if intrinsic and f.price and intrinsic > 0:
        mos = (intrinsic - f.price) / intrinsic

    return Valuation(
        ticker=f.ticker,
        price=f.price,
        dcf_value=dcf_v,
        graham_value=graham_v,
        intrinsic_value=intrinsic,
        margin_of_safety=mos,
    )
