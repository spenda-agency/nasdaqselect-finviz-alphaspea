"""テクニカル指標（RSI / MACD クロス）を株価履歴から自前計算する。

Google Finance には公開 API が無いため、データソースは yfinance に統一する。
RSI は Wilder の指数平滑、MACD は標準パラメータ (12, 26, 9) を用いる。
"""
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class Technicals:
    ticker: str
    rsi14: Optional[float] = None
    rsi30: Optional[float] = None
    rsi90: Optional[float] = None
    # "golden" / "death" / None
    macd_cross_yesterday: Optional[str] = None
    macd_cross_2days_ago: Optional[str] = None


def _rsi(close: pd.Series, period: int) -> Optional[float]:
    """直近の RSI を返す（Wilder 法）。"""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None


def _macd_histogram(close: pd.Series) -> pd.Series:
    """MACD ヒストグラム（MACD − シグナル）を返す。"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _cross_label(hist: pd.Series, idx: int) -> Optional[str]:
    """idx 番目のバーで MACD クロスが発生していれば種類を返す。

    idx は負の値（-1: 最新、-2: ひとつ前）。
    ゴールデンクロス: ヒストグラムが負→正に転じた
    デッドクロス:     ヒストグラムが正→負に転じた
    """
    if abs(idx) + 1 > len(hist):
        return None
    cur = hist.iloc[idx]
    prev = hist.iloc[idx - 1]
    if pd.isna(cur) or pd.isna(prev):
        return None
    if prev <= 0 and cur > 0:
        return "golden"
    if prev >= 0 and cur < 0:
        return "death"
    return None


def fetch(ticker: str) -> Technicals:
    t = Technicals(ticker=ticker)
    try:
        # RSI90 と MACD のウォームアップに十分な期間を確保（約 10 ヶ月）
        hist = yf.Ticker(ticker).history(period="10mo", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or "Close" not in hist:
            return t
        close = hist["Close"].dropna()
        if close.empty:
            return t

        t.rsi14 = _rsi(close, 14)
        t.rsi30 = _rsi(close, 30)
        t.rsi90 = _rsi(close, 90)

        macd_hist = _macd_histogram(close)
        # 実行は US 市場クローズ後（16:00 JST = 07:00 UTC）なので
        # iloc[-1] が「昨日」、iloc[-2] が「2 日前」の確定足。
        t.macd_cross_yesterday = _cross_label(macd_hist, -1)
        t.macd_cross_2days_ago = _cross_label(macd_hist, -2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s のテクニカル指標取得に失敗: %s", ticker, exc)
    return t
