"""3ステップを連結して、過小評価されている有望銘柄を抽出するパイプライン。

US / JP の両市場に対応。市場ごとに ``run(market='US' | 'JP')`` で実行する。
各段階の通過数（ファネル）も併せて返し、Slack 通知に反映する。
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import config, fundamentals, jp_screener, screener, technicals, valuation
from .fundamentals import Fundamentals
from .technicals import Technicals
from .valuation import Valuation

logger = logging.getLogger(__name__)

# JP は yfinance で 1,500+ 銘柄を捌くためレート制限を喰らいやすい。
# スクリーニング直後にクールダウンを入れ、詳細分析中も per-call で間隔を空ける。
JP_COOLDOWN_SEC = 90
JP_PER_CALL_DELAY_SEC = 1.0


@dataclass
class Candidate:
    market: str                              # 'US' / 'JP'
    ticker: str
    company: Optional[str]
    sector: Optional[str]
    fund: Fundamentals
    val: Valuation
    tech: Technicals
    # US 限定: Claude による分析結果
    score: Optional[int] = None              # 0-100、未分析時 None
    analysis_url: Optional[str] = None       # Drive にアップロードしたレポートの URL


@dataclass
class FunnelCounts:
    universe_total: Optional[int] = None     # 上場全銘柄数（Nasdaq or 東証プライム）
    filter_passed: Optional[int] = None      # 割安フィルタ通過数
    analyzed: int = 0                        # 詳細分析対象（MAX_TICKERS でカット後）
    after_trend: int = 0                     # 業績トレンドが衰退でない銘柄
    after_valuation: int = 0                 # 安全域 ≥ MIN_MARGIN_OF_SAFETY
    after_rsi: int = 0                       # RSI14 ≤ 50
    after_bb: int = 0                        # 現値 > ボリンジャー下限
    notified: int = 0                        # 最終的に Slack 通知される件数
    # 業績トレンド OK まで残った銘柄コード（Top10 の比較対象として保持）
    trend_passed_tickers: List[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    market: str = "US"
    funnel: FunnelCounts = field(default_factory=FunnelCounts)
    candidates: List[Candidate] = field(default_factory=list)


def _pick_ticker_column(row) -> Optional[str]:
    for key in ("Ticker", "ticker", "Symbol"):
        if key in row and row[key]:
            return str(row[key]).strip()
    return None


def _screen(market: str):
    """市場ごとのスクリーニング呼び出しを分岐する。

    戻り値: (DataFrame, フィルタ通過数, 上場全銘柄数)
    """
    if market == "JP":
        df, passed = jp_screener.screen_undervalued()
        return df, passed, jp_screener.get_prime_total()
    df, passed = screener.screen_undervalued()
    return df, passed, screener.get_nasdaq_total()


def run(market: str = "US") -> PipelineResult:
    funnel = FunnelCounts()

    df, filter_passed, universe_total = _screen(market)
    funnel.universe_total = universe_total
    funnel.filter_passed = filter_passed
    if df.empty:
        return PipelineResult(market=market, funnel=funnel)

    company_by_ticker = {}
    tickers = []
    for _, row in df.iterrows():
        t = _pick_ticker_column(row)
        if not t:
            continue
        tickers.append(t)
        company_by_ticker[t] = row.get("Company") or row.get("company")
    tickers = tickers[: config.MAX_TICKERS]
    funnel.analyzed = len(tickers)
    logger.info("[%s] 詳細分析対象: %d 銘柄", market, funnel.analyzed)

    # JP はスクリーニングで Yahoo を叩きすぎているため、詳細分析前に冷却する。
    if market == "JP" and tickers:
        logger.info("[JP] Yahoo クールダウン: %d 秒待機", JP_COOLDOWN_SEC)
        time.sleep(JP_COOLDOWN_SEC)

    candidates: List[Candidate] = []
    for t in tickers:
        # Step 2: 業績トレンドと財務データ
        f = fundamentals.fetch(t)
        if f is None:
            if market == "JP":
                time.sleep(JP_PER_CALL_DELAY_SEC)
            continue
        if f.revenue_growing is False and f.net_income_growing is False:
            continue
        funnel.after_trend += 1
        funnel.trend_passed_tickers.append(t)

        # Step 3: 適正株価と安全域
        v = valuation.value(f)
        if v.margin_of_safety is None:
            continue
        if v.margin_of_safety < config.MIN_MARGIN_OF_SAFETY:
            continue
        funnel.after_valuation += 1

        # 補助: テクニカル指標による絞り込み
        tech = technicals.fetch(t)

        if tech.rsi14 is None or tech.rsi14 > 50:
            continue
        funnel.after_rsi += 1

        if (
            tech.latest_close is None
            or tech.bb_lower is None
            or tech.latest_close <= tech.bb_lower
        ):
            continue
        funnel.after_bb += 1

        candidates.append(
            Candidate(
                market=market,
                ticker=t,
                company=company_by_ticker.get(t),
                sector=f.sector,
                fund=f,
                val=v,
                tech=tech,
            )
        )

        # JP は per-call で間隔を空けてレート制限を回避する
        if market == "JP":
            time.sleep(JP_PER_CALL_DELAY_SEC)

    candidates.sort(key=lambda c: c.val.margin_of_safety or 0, reverse=True)
    candidates = candidates[: config.TOP_N]

    # US の Top10 は Claude で詳細分析し、レポートを Drive へ保存。
    # スコア < MIN_ANALYSIS_SCORE はシート出力からは除外（Drive には全件保存）。
    if market == "US" and candidates:
        _analyze_us_candidates(candidates)
        candidates = [
            c for c in candidates
            if c.score is not None and c.score >= config.MIN_ANALYSIS_SCORE
        ]

    funnel.notified = len(candidates)
    return PipelineResult(market=market, funnel=funnel, candidates=candidates)


def _analyze_us_candidates(candidates: List[Candidate]) -> None:
    """Top10 銘柄を Claude で分析して、レポートを Drive にアップロード。

    各 Candidate に ``score`` と ``analysis_url`` を埋め込む（in-place）。
    分析や Drive アップロードが失敗しても他銘柄の処理は続行する。
    """
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY 未設定のため US 分析をスキップ")
        return

    from . import analyzer, drive_writer  # 遅延 import で起動時の依存を抑える

    today = (
        __import__("datetime").datetime.utcnow()
        + __import__("datetime").timedelta(hours=9)
    ).strftime("%Y-%m-%d")

    for c in candidates:
        try:
            ar = analyzer.analyze(c)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s の分析中に例外: %s", c.ticker, exc)
            continue
        if ar is None:
            logger.warning("%s の分析結果が None", c.ticker)
            continue

        c.score = ar.score
        logger.info(
            "[US] %s: score=%s (tokens in/out=%s/%s)",
            c.ticker, ar.score, ar.input_tokens, ar.output_tokens,
        )

        filename = f"{today}_{c.ticker}.md"
        try:
            url = drive_writer.upload_markdown(filename, ar.report_md)
            if url:
                c.analysis_url = url
        except Exception as exc:  # noqa: BLE001
            logger.error("%s レポートの Drive アップロード失敗: %s", c.ticker, exc)
