"""パイプライン結果を Slack 用ブロックメッセージに整形する。"""
from datetime import datetime
from typing import Optional

from . import config
from .pipeline import PipelineResult


def _pct(x: Optional[float]) -> str:
    return f"{x * 100:.1f}%" if x is not None else "—"


def _money(x: Optional[float]) -> str:
    if x is None:
        return "—"
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


def _funnel_text(f) -> str:
    mos_pct = int(config.MIN_MARGIN_OF_SAFETY * 100)
    return (
        "*:mag: 銘柄ファネル*\n"
        f"Nasdaq 上場銘柄: *{_count(f.nasdaq_total)}*\n"
        f"↓ 割安フィルタ通過 (P/E<15, PEG<1, P/S<3): *{_count(f.finviz_passed)}*\n"
        f"↓ 詳細分析対象（先頭 {config.MAX_TICKERS} 件）: *{f.analyzed}*\n"
        f"↓ 業績トレンド OK（売上 or 純利益が拡大）: *{f.after_trend}*\n"
        f"↓ 安全域 ≥ {mos_pct}%: *{f.after_valuation}*\n"
        f"↓ RSI14 ≤ 50: *{f.after_rsi}*\n"
        f"↓ 現値 > ボリンジャー下限: *{f.after_bb}*\n"
        f"↓ *Top {config.TOP_N} 通知: {f.notified}*"
    )


def _candidate_text(i: int, c) -> str:
    v, fu, t = c.val, c.fund, c.tech
    name = c.company or c.ticker
    return (
        f"*{i}. <https://finviz.com/quote.ashx?t={c.ticker}|{c.ticker}>* — {name}\n"
        f"   業種: {c.sector or '—'}\n"
        f"   現在株価: {_money(v.price)} / 適正株価: {_money(v.intrinsic_value)} "
        f"→ *安全域 {_pct(v.margin_of_safety)}*\n"
        f"   DCF: {_money(v.dcf_value)} / Graham: {_money(v.graham_value)} / "
        f"時価総額: {_money(fu.market_cap)}\n"
        f"   {_trend('売上', fu.revenue_growing)}  {_trend('純利益', fu.net_income_growing)}  "
        f"前回決算: {_date(fu.prev_earnings_date)} / 次回決算: {_date(fu.next_earnings_date)}\n"
        f"   RSI14: {_rsi(t.rsi14)} / RSI30: {_rsi(t.rsi30)} / RSI90: {_rsi(t.rsi90)}\n"
        f"   ボリンジャー (20, 2σ): 下限 {_money(t.bb_lower)} / 中央 {_money(t.bb_middle)} / "
        f"上限 {_money(t.bb_upper)} (現値 {_money(t.latest_close)})\n"
        f"   MACD 昨日 : MACD {_num(t.macd_yesterday)} / Sig {_num(t.signal_yesterday)} / "
        f"ヒスト {_signed(t.hist_yesterday)}{_cross_tag(t.macd_cross_yesterday)}\n"
        f"   MACD 2日前: MACD {_num(t.macd_2days_ago)} / Sig {_num(t.signal_2days_ago)} / "
        f"ヒスト {_signed(t.hist_2days_ago)}{_cross_tag(t.macd_cross_2days_ago)}\n"
        f"   <https://www.tradingview.com/symbols/NASDAQ-{c.ticker}/|TradingView> "
        f"<https://www.alphaspread.com/security/nasdaq/{c.ticker.lower()}/summary|AlphaSpread>"
    )


def build_blocks(result: PipelineResult, date_str: Optional[str] = None) -> dict:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    candidates = result.candidates
    funnel = result.funnel

    header = (
        f"*:chart_with_upwards_trend: [{date_str}] 過小評価 Nasdaq 有望銘柄 "
        f"Top {len(candidates) if candidates else 0}*\n"
        f"_Finviz スクリーニング → 業績 → Intrinsic Value → RSI/ボリンジャー_"
    )

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _funnel_text(funnel)}},
        {"type": "divider"},
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

    fallback = (
        f"[{date_str}] 過小評価 Nasdaq 銘柄 "
        f"({_count(funnel.notified)} 件 / Nasdaq {_count(funnel.nasdaq_total)})"
    )
    return {"text": fallback, "blocks": blocks}
