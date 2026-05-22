"""Step 1: Finviz スクリーナーで Nasdaq の割安候補を抽出する。"""
import logging

import pandas as pd
from finvizfinance.screener.valuation import Valuation

from . import config

logger = logging.getLogger(__name__)


def screen_undervalued() -> pd.DataFrame:
    """設定された割安フィルタで Finviz スクリーナーを実行し DataFrame を返す。

    無料のスクレイピングに依存するため、失敗時は空の DataFrame を返す。
    """
    try:
        view = Valuation()
        view.set_filter(filters_dict=config.FINVIZ_FILTERS)
        df = view.screener_view(verbose=0)
    except Exception as exc:  # noqa: BLE001 - 外部スクレイピングの失敗を吸収
        logger.warning("Finviz スクリーニングに失敗: %s", exc)
        return pd.DataFrame()

    if df is None or df.empty:
        logger.info("スクリーニング結果が0件でした")
        return pd.DataFrame()

    df = df.reset_index(drop=True)
    logger.info("Finviz スクリーニング: %d 件ヒット", len(df))
    return df
