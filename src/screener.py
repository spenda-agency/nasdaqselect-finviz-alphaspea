"""Step 1: Finviz スクリーナーで Nasdaq の割安候補を抽出する。

スクリーニング結果に加え、件数（Nasdaq 上場総数、割安フィルタ通過数）も取得する。
"""
import logging
import re
from typing import Optional, Tuple

import pandas as pd
from finvizfinance.screener.valuation import Valuation

from . import config

logger = logging.getLogger(__name__)


def _parse_total(soup) -> Optional[int]:
    """Finviz スクリーナーページの HTML から「Total: N」件数を取り出す。"""
    if soup is None:
        return None
    # よく使われる class 名を順に試す
    for cls in ("count-text", "screener_count"):
        for tag in ("td", "span", "div"):
            el = soup.find(tag, class_=cls)
            if el and el.get_text(strip=True):
                m = re.search(r"(\d[\d,]*)\s*Total", el.get_text())
                if m:
                    return int(m.group(1).replace(",", ""))
                m = re.search(r"(\d[\d,]*)", el.get_text())
                if m:
                    return int(m.group(1).replace(",", ""))
    # フォールバック: ページ全体から "Total: N" のパターンを拾う
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Total[:\s]+(\d[\d,]*)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _fetch_total(view: Valuation) -> Optional[int]:
    """フィルタが設定済みの view から、Finviz 側の総ヒット件数を取得する。"""
    try:
        from finvizfinance.util import web_scrap  # noqa: WPS433 - lazy import
        soup = web_scrap(view.url)
        return _parse_total(soup)
    except Exception as exc:  # noqa: BLE001
        logger.debug("総件数の取得に失敗: %s", exc)
        return None


def get_nasdaq_total() -> Optional[int]:
    """Nasdaq 上場全銘柄数を返す。"""
    try:
        view = Valuation()
        view.set_filter(filters_dict={"Exchange": config.FINVIZ_FILTERS.get("Exchange", "NASDAQ")})
        return _fetch_total(view)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nasdaq 総数取得に失敗: %s", exc)
        return None


def screen_undervalued() -> Tuple[pd.DataFrame, Optional[int]]:
    """設定された割安フィルタで Finviz スクリーニングを実行する。

    戻り値: (DataFrame, フィルタ通過総数)。失敗時は (空 DataFrame, None)。
    """
    try:
        view = Valuation()
        view.set_filter(filters_dict=config.FINVIZ_FILTERS)
        total = _fetch_total(view)
        df = view.screener_view(verbose=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Finviz スクリーニングに失敗: %s", exc)
        return pd.DataFrame(), None

    if df is None or df.empty:
        logger.info("スクリーニング結果が 0 件でした")
        return pd.DataFrame(), total

    df = df.reset_index(drop=True)
    logger.info("Finviz スクリーニング: %d 件取得 / 総ヒット %s 件", len(df), total)
    return df, total
