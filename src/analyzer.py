"""Claude API を呼び出して銘柄ごとの投資分析レポート（Markdown）を生成する。

入力: SEC EDGAR 文書 + yfinance ファンダメンタル + テクニカル
出力: 完成済み Markdown レポート + 100点満点スコア
"""
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from . import edgar
from .pipeline import Candidate

logger = logging.getLogger(__name__)

# Claude モデル (Sonnet 4.6: コスト/精度のバランス良好)
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 8000

# レポート末尾に必ず付ける固定タグ。スコア抽出に使う。
SCORE_TAG_RE = re.compile(r"<SCORE>\s*(\d{1,3})\s*</SCORE>")


SYSTEM_PROMPT = """あなたは優秀な投資家でありデータサイエンティストです。対象は NASDAQ 上場企業です。

入力として与えられる SEC EDGAR の 10-K / 10-Q テキスト、および yfinance 由来の財務・株価データを統合し、
日本語の投資分析レポートを Markdown 形式で作成してください。

# 出力フォーマット（見出し固定・順序厳守）

1. タイトル（例: 「[ティッカー/社名] 最新決算レポート：業績・財務レビューと投資判断（[期末]）」）
2. 会社概要（事業内容、主要製品・サービス、収益源、ビジネスモデル、主要 KPI、上場市場/ティッカー、CIK、最新提出書類）
3. 決算概要（良い点／悪い点を各 3〜5 点、数値裏付け必須、一過性要因を明示）
4. 経営成績（百万 USD、表形式で当期/前年/前期、増減金額・率併記）
5. 財務状況（百万 USD、総資産・自己資本・現金・有利子負債・主要レバレッジ指標）
6. キャッシュフロー（百万 USD、営業/投資/財務 CF、FCF 定義明記）
7. 業績予想・ガイダンス（百万 USD、未提供なら明記）
8. 配当・株主還元
9. 貸借対照表・損益計算書・キャッシュフローの詳細分析
9b. COSR (株主還元コスト) と TSR (株主総利回り) を 4 象限で判断
9c. WACC と ROIC の数値 + 評価 (ROIC > WACC か否か)
10. 業界動向と競合比較
11. 採点（100 点満点、財務健全性 25 / 成長性 25 / 市場ポジション 25 / 将来性 25）
12. リスクとカタリスト
13. 投資判断（買う／買わない）
14. ディベート（賛成派 vs 反対派、各 3 点）
15. 投資論文（結論 200〜300 字）

# 表記ルール
- 単位は百万 USD、桁区切り `,`、マイナスは △ または () 表記
- YoY/QoQ は金額差と % を併記
- GAAP / 非 GAAP を区別、外部推計は使わず原典に忠実に
- 不明値は「不明」「未開示」と明記

# 最後の必須行
レポート末尾に以下のタグで合計スコアを必ず出力してください（自動抽出に使用）:

<SCORE>XX</SCORE>

XX は 0〜100 の整数。これを欠くとパースに失敗します。"""


@dataclass
class AnalysisResult:
    ticker: str
    score: Optional[int]      # 0-100、抽出失敗時 None
    report_md: str            # 完成済み Markdown レポート
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


def _build_user_message(c: Candidate, bundle: Optional[edgar.EdgarBundle]) -> str:
    fu, v, t = c.fund, c.val, c.tech
    parts = [
        f"# 分析対象\nティッカー: {c.ticker}",
        f"社名 (yfinance): {c.company or '不明'}",
        f"業種: {c.sector or '不明'}",
        "",
        "# yfinance 由来のスナップショット",
        f"- 現在株価: ${v.price}",
        f"- 時価総額: ${fu.market_cap}",
        f"- 発行済株式数: {fu.shares_outstanding}",
        f"- EPS (希薄化後): ${fu.eps}",
        f"- BVPS: ${fu.book_value_per_share}",
        f"- 売上推移 (古→新): {fu.revenue_history}",
        f"- 純利益推移 (古→新): {fu.net_income_history}",
        f"- FCF 推移 (古→新): {fu.fcf_history}",
        f"- 簡易 DCF 値: ${v.dcf_value}",
        f"- グレアム数: ${v.graham_value}",
        f"- 安全域 (MoS): {v.margin_of_safety}",
        f"- 前回決算: {fu.prev_earnings_date}",
        f"- 次回決算: {fu.next_earnings_date}",
        f"- RSI14/30/90: {t.rsi14} / {t.rsi30} / {t.rsi90}",
        f"- BB (lower/mid/upper): {t.bb_lower} / {t.bb_middle} / {t.bb_upper}",
        f"- MACD 昨日 (MACD/Sig/Hist): {t.macd_yesterday} / {t.signal_yesterday} / {t.hist_yesterday}",
        "",
    ]
    if bundle is not None and bundle.text_excerpt:
        parts.append(f"# SEC EDGAR 抜粋 (CIK {bundle.cik}, 社名 {bundle.company})")
        if bundle.annual:
            parts.append(
                f"## 最新 10-K\nアクセッション: {bundle.annual.accession} / 提出日: {bundle.annual.filing_date} / URL: {bundle.annual.url}"
            )
        if bundle.quarterly:
            parts.append(
                f"## 最新 10-Q\nアクセッション: {bundle.quarterly.accession} / 提出日: {bundle.quarterly.filing_date} / URL: {bundle.quarterly.url}"
            )
        parts.append("\n## 本文 (HTML→テキスト変換、上限 ~120K 文字)\n")
        parts.append(bundle.text_excerpt)
    else:
        parts.append(
            "# SEC EDGAR 抜粋\n(取得失敗 or 該当 CIK なし。yfinance データを主に分析してください。)"
        )
    return "\n".join(parts)


def _extract_score(text: str) -> Optional[int]:
    m = SCORE_TAG_RE.search(text)
    if not m:
        # フォールバック: "合計点 73/100" や "73 / 100" を探す
        m = re.search(r"(?:合計|総合)\s*(?:点|スコア)\s*[:：]?\s*(\d{1,3})\s*/?\s*100", text)
    if not m:
        m = re.search(r"\b(\d{1,3})\s*/\s*100\b", text)
    if m:
        score = int(m.group(1))
        return max(0, min(100, score))
    return None


def analyze(c: Candidate) -> Optional[AnalysisResult]:
    """1 銘柄を分析して Markdown レポートとスコアを返す。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY が未設定です")
        return None

    try:
        import anthropic  # noqa: WPS433 - 遅延 import
    except ImportError as exc:
        logger.error("anthropic SDK が未インストール: %s", exc)
        return None

    # SEC EDGAR から本文を取得（失敗してもレポート生成は続行）
    bundle = edgar.fetch(c.ticker)
    user_msg = _build_user_message(c, bundle)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("%s の Claude 呼び出し失敗: %s", c.ticker, exc)
        return None

    if not resp.content:
        return None
    text = "".join(block.text for block in resp.content if hasattr(block, "text"))
    score = _extract_score(text)

    usage = getattr(resp, "usage", None)
    return AnalysisResult(
        ticker=c.ticker,
        score=score,
        report_md=text,
        model=MODEL,
        input_tokens=getattr(usage, "input_tokens", None) if usage else None,
        output_tokens=getattr(usage, "output_tokens", None) if usage else None,
    )
