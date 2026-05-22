"""候補リストを Slack 用のテキスト/ブロックに整形する。"""
from datetime import datetime
from typing import Optional


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


def _trend(label: str, growing: Optional[bool]) -> str:
    if growing is None:
        return f"{label}:—"
    return f"{label}:{'↑' if growing else '↓'}"


def _date(d) -> str:
    return d.isoformat() if d is not None else "—"


def _rsi(x: Optional[float]) -> str:
    return f"{x:.1f}" if x is not None else "—"


_CROSS_LABEL = {"golden": ":large_green_circle: GC", "death": ":red_circle: DC"}


def _cross(x: Optional[str]) -> str:
    return _CROSS_LABEL.get(x, "—")


def build_blocks(candidates: list, date_str: Optional[str] = None) -> dict:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")

    if not candidates:
        return {
            "text": f"[{date_str}] 過小評価 Nasdaq 銘柄: 本日は条件を満たす候補がありませんでした。",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*[{date_str}] 過小評価 Nasdaq スクリーニング*\n"
                        f"本日は条件を満たす候補がありませんでした。",
                    },
                }
            ],
        }

    header = (
        f"*:chart_with_upwards_trend: [{date_str}] 過小評価 Nasdaq 有望銘柄 "
        f"Top {len(candidates)}*\n"
        f"_Finviz スクリーニング → 業績トレンド → 自前 Intrinsic Value（DCF/Graham 平均）_"
    )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}, {"type": "divider"}]

    lines = []
    for i, c in enumerate(candidates, 1):
        v, f, t = c.val, c.fund, c.tech
        name = c.company or c.ticker
        line = (
            f"*{i}. <https://finviz.com/quote.ashx?t={c.ticker}|{c.ticker}>* — {name}\n"
            f"   業種: {c.sector or '—'}\n"
            f"   現在株価: {_money(v.price)} / 適正株価: {_money(v.intrinsic_value)} "
            f"→ *安全域 {_pct(v.margin_of_safety)}*\n"
            f"   DCF: {_money(v.dcf_value)} / Graham: {_money(v.graham_value)} / "
            f"時価総額: {_money(f.market_cap)}\n"
            f"   {_trend('売上', f.revenue_growing)}  {_trend('純利益', f.net_income_growing)}  "
            f"前回決算: {_date(f.prev_earnings_date)} / 次回決算: {_date(f.next_earnings_date)}\n"
            f"   RSI14: {_rsi(t.rsi14)} / RSI30: {_rsi(t.rsi30)} / RSI90: {_rsi(t.rsi90)}  "
            f"MACDクロス: 昨日 {_cross(t.macd_cross_yesterday)} / 2日前 {_cross(t.macd_cross_2days_ago)}\n"
            f"   <https://www.tradingview.com/symbols/NASDAQ-{c.ticker}/|TradingView> "
            f"<https://www.alphaspread.com/security/nasdaq/{c.ticker.lower()}/summary|AlphaSpread>"
        )
        lines.append(line)

    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(lines)}}
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

    fallback = f"[{date_str}] 過小評価 Nasdaq 有望銘柄 Top {len(candidates)}"
    return {"text": fallback, "blocks": blocks}
