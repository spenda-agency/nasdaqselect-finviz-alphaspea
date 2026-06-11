"""東証プライム銘柄のスクリーニング（Finviz の代替）。

JPX の公式 Excel から東証プライム上場銘柄一覧を取得し、各銘柄の P/E / PEG / P/S を
yfinance から並列に取得して、US と同じ割安フィルタを適用する。
"""
import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

JPX_PRIME_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)
PRIME_MARKET_LABEL = "プライム（内国株式）"

# 割安フィルタ閾値（US と同じ値）
PE_MAX = 15.0
PEG_MAX = 1.0
PS_MAX = 3.0

# yfinance 並列フェッチのワーカー数。Yahoo のレート制限を回避するため控えめに。
# 過去ログで 10 ワーカーは 1,500+ 銘柄を捌くと Yahoo に 429/401 を返されたため 3 に削減。
# 結果として ~5-8 分かかる想定。
PARALLEL_WORKERS = 3

# モジュールレベルキャッシュ: 同一プロセス内では JPX を 1 回だけ取得
_universe_cache: Optional[List[Tuple[str, str]]] = None


def _fetch_universe() -> List[Tuple[str, str]]:
    """JPX 公式 Excel から (yfinance ティッカー, 銘柄名) のリストを取得する。

    yfinance ティッカー形式: ``4桁コード + ".T"``（例: ``7203.T``）
    """
    try:
        resp = requests.get(JPX_PRIME_URL, timeout=60)
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:  # noqa: BLE001
        logger.error("JPX Excel ダウンロード失敗: %s", exc)
        return []

    # JPX は .xls (旧形式) を配信しているが、将来 .xlsx に変わる可能性に備えて両対応
    df = None
    for engine in ("openpyxl", "xlrd"):
        try:
            df = pd.read_excel(io.BytesIO(content), engine=engine)
            break
        except Exception as exc:  # noqa: BLE001
            logger.debug("read_excel engine=%s 失敗: %s", engine, exc)
    if df is None:
        logger.error("JPX Excel の読み込みに失敗しました")
        return []

    if "市場・商品区分" not in df.columns:
        logger.warning("'市場・商品区分' 列が見つかりません: %s", df.columns.tolist())
        return []

    prime = df[df["市場・商品区分"] == PRIME_MARKET_LABEL]
    out: List[Tuple[str, str]] = []
    for _, row in prime.iterrows():
        code = str(row.get("コード", "")).strip()
        name = str(row.get("銘柄名", "")).strip()
        if code.isdigit() and len(code) == 4:
            out.append((f"{code}.T", name))
    logger.info("JPX 東証プライム取得: %d 件", len(out))
    return out


def _get_universe() -> List[Tuple[str, str]]:
    global _universe_cache
    if _universe_cache is None:
        _universe_cache = _fetch_universe()
    return _universe_cache


def get_prime_total() -> Optional[int]:
    """東証プライム上場銘柄総数を返す。"""
    universe = _get_universe()
    return len(universe) if universe else None


def _passes_filter(info: dict) -> bool:
    pe = info.get("trailingPE")
    peg = info.get("trailingPegRatio") or info.get("pegRatio")
    ps = info.get("priceToSalesTrailing12Months")
    if pe is None or pe <= 0 or pe >= PE_MAX:
        return False
    if peg is None or peg <= 0 or peg >= PEG_MAX:
        return False
    if ps is None or ps <= 0 or ps >= PS_MAX:
        return False
    return True


def _check(ticker_name: Tuple[str, str]) -> Optional[dict]:
    ticker, name = ticker_name
    try:
        info = yf.Ticker(ticker).info or {}
        if not _passes_filter(info):
            return None
        return {
            "Ticker": ticker,
            "Company": name or info.get("shortName") or info.get("longName") or ticker,
        }
    except Exception:  # noqa: BLE001
        return None


def screen_undervalued() -> Tuple[pd.DataFrame, Optional[int]]:
    """東証プライム全銘柄から P/E<15, PEG<1, P/S<3 を通過した銘柄を返す。

    戻り値: (DataFrame[Ticker, Company], 通過件数)。失敗時は (空 DataFrame, None)。
    """
    universe = _get_universe()
    if not universe:
        return pd.DataFrame(), None

    total = len(universe)
    passed: List[dict] = []
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        futures = {ex.submit(_check, tn): tn for tn in universe}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r is not None:
                passed.append(r)
            if i % 200 == 0:
                logger.info("JP 割安フィルタ進捗: %d / %d (通過 %d)", i, total, len(passed))

    df = pd.DataFrame(passed)
    logger.info("JP 割安フィルタ通過: %d / %d 件", len(df), total)
    return df, len(df)
