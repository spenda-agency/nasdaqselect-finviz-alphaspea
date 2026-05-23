"""テクニカル指標（RSI / MACD / ボリンジャーバンド）を株価履歴から自前計算する。

Google Finance には公開 API が無いため、データソースは yfinance に統一する。
RSI は Wilder の指数平滑、MACD は標準パラメータ (12, 26, 9)、
ボリンジャーバンドは 20 日 SMA ± 2σ を採用。
"""
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class Technicals:
    ticker: str
    latest_close: Optional[float] = None

    rsi14: Optional[float] = None
    rsi30: Optional[float] = None
    rsi90: Optional[float] = None

    # ボリンジャーバンド（20 日 SMA ± 2σ）
    bb_lower: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_upper: Optional[float] = None

    # MACD: 昨日（直近の確定足）と 2 日前
    macd_yesterday: Optional[float] = None
    signal_yesterday: Optional[float] = None
    hist_yesterday: Optional[float] = None
    macd_2days_ago: Optional[float] = None
    signal_2days_ago: Optional[float] = None
    hist_2days_ago: Optional[float] = None

    # ヒストグラムの符号反転で検出するクロス: "golden" / "death" / None
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


def _macd_lines(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """MACD ライン、シグナル、ヒストグラムを返す。"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def _bollinger(close: pd.Series, period: int = 20, k: float = 2.0):
    """ボリンジャーバンドの (下限, 中央, 上限) の最新値を返す。"""
    if len(close) < period:
        return None, None, None
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    lower = sma - k * std
    upper = sma + k * std
    return _last(lower), _last(sma), _last(upper)


def _last(series: pd.Series) -> Optional[float]:
    if series is None or series.empty:
        return None
    val = series.iloc[-1]
    return float(val) if pd.notna(val) else None


def _at(series: pd.Series, idx: int) -> Optional[float]:
    if series is None or abs(idx) + 1 > len(series):
        return None
    val = series.iloc[idx]
    return float(val) if pd.notna(val) else None


def _cross_label_from_values(prev: Optional[float], cur: Optional[float]) -> Optional[str]:
    if prev is None or cur is None:
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

        t.latest_close = _last(close)

        t.rsi14 = _rsi(close, 14)
        t.rsi30 = _rsi(close, 30)
        t.rsi90 = _rsi(close, 90)

        t.bb_lower, t.bb_middle, t.bb_upper = _bollinger(close)

        macd, signal, hist_series = _macd_lines(close)
        # 実行は US 市場クローズ後（16:00 JST = 07:00 UTC）なので
        # iloc[-1] が「昨日」、iloc[-2] が「2 日前」の確定足。
        t.macd_yesterday = _at(macd, -1)
        t.signal_yesterday = _at(signal, -1)
        t.hist_yesterday = _at(hist_series, -1)
        t.macd_2days_ago = _at(macd, -2)
        t.signal_2days_ago = _at(signal, -2)
        t.hist_2days_ago = _at(hist_series, -2)

        t.macd_cross_yesterday = _cross_label_from_values(
            _at(hist_series, -2), _at(hist_series, -1)
        )
        t.macd_cross_2days_ago = _cross_label_from_values(
            _at(hist_series, -3), _at(hist_series, -2)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s のテクニカル指標取得に失敗: %s", ticker, exc)
    return t
