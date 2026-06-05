"""パイプライン結果を Slack 用ブロックメッセージに整形する。

複数市場（US / JP）の結果を 1 つのメッセージにまとめて表示する。
"""
from datetime import datetime
from typing import List, Optional

from . import config
from .pipeline import PipelineResult

_MARKET_LABEL = {
    "US": ":us: US (Nasdaq)",
    "JP": ":jp: JP (東証プライム)",
}

_FILTER_LABEL = {
    "US": "Finviz 割安フィルタ通過 (P/E<15, PEG<1, P/S<3)",
    "JP": "東証プライム 割安フィルタ通過 (P/E<15, PEG<1, P/S<3)",
}

_UNIVERSE_LABEL = {
    "US": "Nasdaq 上場銘柄",
    "JP": "東証プライム 上場銘柄",
}


def _pct(x: Optional[float]) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def _money(x: Optional[float], market: str = "US") -> str:
    if x is None:
        return "—"
    if market == "JP":
        if abs(x) >= 1e12:
            return f"¥{x / 1e12:.2f}兆"
        if abs(x) >= 1e8:
            return f"¥{x / 1e8:.2f}億"
        if abs(x) >= 1e4:
            return f"¥{x / 1e4:.2f}万"
        return f"¥{x:,.0f}"
    if abs(x) >= 1e9:
        return f"${x / 1e9:.2f}B"
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}M"
    return f"${x:,.2f}"


def _num(x: Optional[float], digits: int = 3) -> str:
    return f"{x:.{digits}f}" if x is not None else "—"


def _signed(x: Optional[float], digits: int = 3) -> str:
    if x is None:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.{digits}f}"


def _trend(label: str, growing: Optional[bool]) -> str:
    if growing is None:
        return f"{label}:—"
    return f"{label}:{'↑' if growing else '↓'}"


def _date(d) -> str:
    return d.isoformat() if d is not None else "—"


def _rsi(x: Optional[float]) -> str:
    return f"{x:.1f}" if x is not None else "—"


def _count(n: Optional[int]) -> str:
    return f"{n:,}" if n is not None else "—"


_CROSS_TAG = {"golden": " [↑GC]", "death": " [↓DC]"}


def _cross_tag(x: Optional[str]) -> str:
    return _CROSS_TAG.get(x, "")


def _bare_ticker(ticker: str, market: str) -> str:
    """表示用に市場のサフィックスを除いたティッカーを返す。"""
    if market == "JP" and ticker.endswith(".T"):
        return ticker[:-2]
    return ticker


def _quote_url(ticker: str, market: str) -> str:
    bare = _bare_ticker(ticker, market)
    if market == "JP":
        return f"https://finance.yahoo.co.jp/quote/{bare}.T"
    return f"https://finviz.com/quote.ashx?t={bare}"


def _tradingview_url(ticker: str, market: str) -> str:
    bare = _bare_ticker(ticker, market)
    if market == "JP":
        return f"https://www.tradingview.com/symbols/TSE-{bare}/"
    return f"https://www.tradingview.com/symbols/NASDAQ-{bare}/"


def _secondary_url(ticker: str, market: str) -> Optional[str]:
    """補助リンク（US: Alpha Spread / JP: みんかぶ）。"""
    bare = _bare_ticker(ticker, market)
    if market == "JP":
        return f"https://minkabu.jp/stock/{bare}"
    return f"https://www.alphaspread.com/security/nasdaq/{bare.lower()}/summary"


def _funnel_text(market: str, f) -> str:
    mos_pct = int(config.MIN_MARGIN_OF_SAFETY * 100)
    return (
        f"*:mag: 銘柄ファネル — {_MARKET_LABEL[market]}*\n"
        f"{_UNIVERSE_LABEL[market]}: *{_count(f.universe_total)}*\n"
        f"↓ {_FILTER_LABEL[market]}: *{_count(f.filter_passed)}*\n"
        f"↓ 詳細分析対象（先頭 {config.MAX_TICKERS} 件）: *{f.analyzed}*\n"
        f"↓ 業績トレンド OK（売上 or 純利益が拡大）: *{f.after_trend}*\n"
        f"↓ 安全域 ≥ {mos_pct}%: *{f.after_valuation}*\n"
        f"↓ RSI14 ≤ 50: *{f.after_rsi}*\n"
        f"↓ 現値 > ボリンジャー下限: *{f.after_bb}*\n"
        f"↓ *Top {config.TOP_N} 通知: {f.notified}*"
    )


def _candidate_text(i: int, c) -> str:
    v, fu, t = c.val, c.fund, c.tech
    m = c.market
    name = c.company or c.ticker
    bare = _bare_ticker(c.ticker, m)
    quote_link = f"<{_quote_url(c.ticker, m)}|{bare}>"
    tv_link = f"<{_tradingview_url(c.ticker, m)}|TradingView>"
    sec_url = _secondary_url(c.ticker, m)
    sec_label = "AlphaSpread" if m == "US" else "みんかぶ"
    sec_link = f"<{sec_url}|{sec_label}>" if sec_url else ""
    return (
        f"*{i}. {quote_link}* — {name}\n"
        f"   業種: {c.sector or '—'}\n"
        f"   現在株価: {_money(v.price, m)} / 適正株価: {_money(v.intrinsic_value, m)} "
        f"→ *安全域 {_pct(v.margin_of_safety)}*\n"
        f"   DCF: {_money(v.dcf_value, m)} / Graham: {_money(v.graham_value, m)} / "
        f"時価総額: {_money(fu.market_cap, m)}\n"
        f"   {_trend('売上', fu.revenue_growing)}  {_trend('純利益', fu.net_income_growing)}  "
        f"前回決算: {_date(fu.prev_earnings_date)} / 次回決算: {_date(fu.next_earnings_date)}\n"
        f"   RSI14: {_rsi(t.rsi14)} / RSI30: {_rsi(t.rsi30)} / RSI90: {_rsi(t.rsi90)}\n"
        f"   ボリンジャー (20, 2σ): 下限 {_money(t.bb_lower, m)} / 中央 {_money(t.bb_middle, m)} / "
        f"上限 {_money(t.bb_upper, m)} (現値 {_money(t.latest_close, m)})\n"
        f"   MACD 昨日 : MACD {_num(t.macd_yesterday)} / Sig {_num(t.signal_yesterday)} / "
        f"ヒスト {_signed(t.hist_yesterday)}{_cross_tag(t.macd_cross_yesterday)}\n"
        f"   MACD 2日前: MACD {_num(t.macd_2days_ago)} / Sig {_num(t.signal_2days_ago)} / "
        f"ヒスト {_signed(t.hist_2days_ago)}{_cross_tag(t.macd_cross_2days_ago)}\n"
        f"   {tv_link} {sec_link}"
    )


def _market_blocks(result: PipelineResult) -> list:
    """1 つの市場分の Slack ブロックを生成する（divider + funnel + 候補 + 圏外）。"""
    market = result.market
    funnel = result.funnel
    candidates = result.candidates
    blocks = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{_MARKET_LABEL[market]}*",
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": _funnel_text(market, funnel)}},
    ]
    if candidates:
        for i, c in enumerate(candidates, 1):
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": _candidate_text(i, c)}}
            )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_本日は全フィルタを通過する候補がありませんでした。_",
                },
            }
        )

    # 業績トレンド OK まで残ったが Top10 入りしなかった銘柄をコードのみ列挙
    top_set = {c.ticker for c in candidates}
    others = [t for t in funnel.trend_passed_tickers if t not in top_set]
    if others:
        # 表示時にサフィックス除去
        bare_others = [_bare_ticker(t, market) for t in others]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*業績トレンド OK・Top{config.TOP_N} 圏外の銘柄 "
                        f"({len(bare_others)} 件)*\n`{','.join(bare_others)}`"
                    ),
                },
            }
        )
    return blocks


def build_blocks(results: List[PipelineResult], date_str: Optional[str] = None) -> dict:
    """1 つ以上の市場結果を 1 つの Slack メッセージに整形する。"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")

    if not results:
        return {
            "text": f"[{date_str}] 過小評価銘柄通知: 本日は対象市場がありません。",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*[{date_str}] 過小評価銘柄通知*\n本日は対象市場がありません。",
                    },
                }
            ],
        }

    market_labels = " / ".join(_MARKET_LABEL[r.market] for r in results)
    total_notified = sum(r.funnel.notified for r in results)
    header = (
        f"*:chart_with_upwards_trend: [{date_str}] 過小評価 有望銘柄 "
        f"(合計 {total_notified} 件)*\n"
        f"対象市場: {market_labels}"
    )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]

    for r in results:
        blocks.extend(_market_blocks(r))

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "適正株価は簡易 DCF とグレアム数の自前計算による参考値です。"
                    "投資判断は自己責任で。",
                }
            ],
        }
    )

    fallback_markets = ",".join(r.market for r in results)
    fallback = f"[{date_str}] 過小評価銘柄通知 ({fallback_markets}: {total_notified} 件)"
    return {"text": fallback, "blocks": blocks}
