"""Step 1: Finviz スクリーナーで Nasdaq の割安候補を抽出する。

スクリーニング結果に加え、件数（Nasdaq 上場総数、割安フィルタ通過数）も取得する。
"""
import logging
from typing import Optional, Tuple

import pandas as pd
from finvizfinance.screener.valuation import Valuation

from . import config

logger = logging.getLogger(__name__)


def _estimate_total(view: Valuation) -> Optional[int]:
    """指定 view の総ヒット件数を、Finviz のページネーション option から概算する。

    Finviz のページ下部 select には各ページの開始行番号が value として並ぶ。
    最終 option の value が「最終ページの開始行」なので、value + 19 を上限として返す
    （最終ページは 1〜20 行なので最大 20 行ぶんを加算）。1 ページ完結時は 0 行を加算。
    """
    try:
        from finvizfinance.util import web_scrap  # noqa: WPS433 - lazy import
        soup = web_scrap(view.url)
        options = soup.find_all("option")
        if options:
            try:
                last_value = int(options[-1].get("value") or options[-1].text)
                # last_value=1 (1 ページ) なら最大 20 行、value=3501 なら 3501..3520
                return last_value + 19
            except (ValueError, TypeError):
                pass
        # ページネーション無し: ページ上のティッカーセルを数える
        rows = soup.find_all("a", class_="screener-link-primary")
        if rows:
            return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug("総件数の概算取得に失敗: %s", exc)
    return None


def get_nasdaq_total() -> Optional[int]:
    """Nasdaq 上場全銘柄数の概算値を返す。"""
    try:
        view = Valuation()
        view.set_filter(
            filters_dict={"Exchange": config.FINVIZ_FILTERS.get("Exchange", "NASDAQ")}
        )
        return _estimate_total(view)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nasdaq 総数取得に失敗: %s", exc)
        return None


def screen_undervalued() -> Tuple[pd.DataFrame, Optional[int]]:
    """設定された割安フィルタで Finviz スクリーニングを実行する。

    戻り値: (DataFrame, フィルタ通過総数)。失敗時は (空 DataFrame, None)。
    通過総数は ``screener_view()`` が全ページ取得済みなので ``len(df)`` を採用する
    （Finviz の HTML パースより確実）。
    """
    try:
        view = Valuation()
        view.set_filter(filters_dict=config.FINVIZ_FILTERS)
        df = view.screener_view(verbose=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Finviz スクリーニングに失敗: %s", exc)
        return pd.DataFrame(), None

    if df is None or df.empty:
        logger.info("スクリーニング結果が 0 件でした")
        return pd.DataFrame(), 0

    df = df.reset_index(drop=True)
    total = len(df)
    logger.info("Finviz スクリーニング: %d 件取得", total)
    return df, total
