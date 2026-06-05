"""Google Sheets に Top N 候補を表形式で書き出す。

書き込み方式:
  - 各市場ごとにタブを使い分ける（既定: "Nasdaq" / "日本株"）
  - 1 行 1 候補（先頭列は実行日）。複数日が蓄積される。
  - **同じ「実行日」の既存行は削除してから今日分を append** = 同日再実行時は上書き。
  - タブが無ければ自動作成。
"""
import datetime as _dt
import json
import logging
import os
from typing import List, Optional

from . import config
from .pipeline import Candidate, PipelineResult

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TAB_NAME = {
    "US": os.environ.get("SHEETS_TAB_US", "Nasdaq"),
    "JP": os.environ.get("SHEETS_TAB_JP", "日本株"),
}

HEADERS = [
    "実行日", "Rank", "Ticker", "Company", "Sector",
    "Price", "Intrinsic", "MoS %",
    "DCF", "Graham", "Market Cap",
    "Rev Trend", "NI Trend",
    "Prev Earnings", "Next Earnings",
    "RSI14", "RSI30", "RSI90",
    "BB Lower", "BB Middle", "BB Upper",
    "MACD (昨日)", "Signal (昨日)", "Hist (昨日)", "Cross (昨日)",
    "MACD (2日前)", "Signal (2日前)", "Hist (2日前)", "Cross (2日前)",
]


def _today_jst() -> _dt.date:
    return (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).date()


def _bare_ticker(ticker: str, market: str) -> str:
    if market == "JP" and ticker.endswith(".T"):
        return ticker[:-2]
    return ticker


def _quote_url(ticker: str, market: str) -> str:
    bare = _bare_ticker(ticker, market)
    if market == "JP":
        return f"https://finance.yahoo.co.jp/quote/{bare}.T"
    return f"https://finviz.com/quote.ashx?t={bare}"


def _arrow(b: Optional[bool]) -> str:
    if b is None:
        return "—"
    return "↑" if b else "↓"


def _cell(x):
    """None を空文字に置換。それ以外はそのまま返す。"""
    return "" if x is None else x


def _candidate_row(date_str: str, rank: int, c: Candidate) -> list:
    v, fu, t = c.val, c.fund, c.tech
    market = c.market
    bare = _bare_ticker(c.ticker, market)
    url = _quote_url(c.ticker, market)
    mos = round(v.margin_of_safety * 100, 2) if v.margin_of_safety is not None else ""
    return [
        date_str, rank,
        f'=HYPERLINK("{url}","{bare}")',
        c.company or "", c.sector or "",
        _cell(v.price), _cell(v.intrinsic_value), mos,
        _cell(v.dcf_value), _cell(v.graham_value), _cell(fu.market_cap),
        _arrow(fu.revenue_growing), _arrow(fu.net_income_growing),
        str(fu.prev_earnings_date) if fu.prev_earnings_date else "",
        str(fu.next_earnings_date) if fu.next_earnings_date else "",
        _cell(t.rsi14), _cell(t.rsi30), _cell(t.rsi90),
        _cell(t.bb_lower), _cell(t.bb_middle), _cell(t.bb_upper),
        _cell(t.macd_yesterday), _cell(t.signal_yesterday), _cell(t.hist_yesterday),
        t.macd_cross_yesterday or "",
        _cell(t.macd_2days_ago), _cell(t.signal_2days_ago), _cell(t.hist_2days_ago),
        t.macd_cross_2days_ago or "",
    ]


def build_today_rows(result: PipelineResult, today_str: Optional[str] = None) -> list:
    """今日分の候補行（dry-run プレビュー用にも使える）。"""
    today_str = today_str or _today_jst().isoformat()
    return [_candidate_row(today_str, i, c) for i, c in enumerate(result.candidates, 1)]


def _client():
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON が未設定です")
    import gspread  # noqa: WPS433
    from google.oauth2.service_account import Credentials  # noqa: WPS433
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_ws(sh, name: str):
    import gspread  # noqa: WPS433
    try:
        return sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=500, cols=len(HEADERS))
        logger.info("タブ '%s' を新規作成しました", name)
        return ws


def _upsert_market(ws, result: PipelineResult, today_str: str) -> int:
    """同じ実行日の既存行を削除して今日の Top N を append する。

    戻り値: 書き込んだ今日分の行数
    """
    # 既存値の取得（無ければ空）
    try:
        existing = ws.get_all_values()
    except Exception as exc:  # noqa: BLE001
        logger.warning("既存データの取得に失敗、空として扱う: %s", exc)
        existing = []

    has_valid_header = bool(existing) and existing[0][: len(HEADERS)] == HEADERS
    if has_valid_header:
        # ヘッダ以外で、実行日 != 今日 の行を保持
        kept = [
            row for row in existing[1:]
            if row and len(row) > 0 and row[0] != today_str
        ]
    else:
        # ヘッダ無し or スキーマ不一致なら作り直し
        kept = []

    today_rows = build_today_rows(result, today_str)
    full = [HEADERS] + kept + today_rows
    ws.clear()
    ws.update(range_name="A1", values=full, value_input_option="USER_ENTERED")
    return len(today_rows)


def write_results(results: List[PipelineResult]) -> bool:
    """全市場分のシートを更新する。"""
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "")
    if not spreadsheet_id:
        logger.error("SPREADSHEET_ID が未設定です")
        return False
    if not os.environ.get("GOOGLE_CREDENTIALS_JSON", ""):
        logger.error("GOOGLE_CREDENTIALS_JSON が未設定です")
        return False

    try:
        gc = _client()
        sh = gc.open_by_key(spreadsheet_id)
    except ImportError as exc:
        logger.error("gspread / google-auth がインストールされていません: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Google Sheets への接続失敗: %s", exc)
        return False

    today_str = _today_jst().isoformat()
    all_ok = True
    for r in results:
        tab = TAB_NAME.get(r.market)
        if not tab:
            continue
        try:
            ws = _get_or_create_ws(sh, tab)
            n = _upsert_market(ws, r, today_str)
            logger.info(
                "Sheets 更新成功: tab=%s, 今日分=%d 件 (実行日=%s)",
                tab, n, today_str,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Sheets 書き込み失敗 (tab=%s): %s", tab, exc)
            all_ok = False
    return all_ok
