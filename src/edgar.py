"""SEC EDGAR から銘柄の最新 10-K / 10-Q 文書を取得する。

SEC は user-agent ヘッダで識別可能なメールアドレスを必須とし、
レート制限は 10 req/sec。一致しない場合 403 を返す。
"""
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# SEC が要求する User-Agent。GitHub Variables `EDGAR_USER_AGENT` で上書き可。
_DEFAULT_UA = "finviz-alphaspea-bot research@spenda-c.com"


def _ua() -> str:
    return os.environ.get("EDGAR_USER_AGENT") or _DEFAULT_UA


def _headers() -> dict:
    return {"User-Agent": _ua(), "Accept-Encoding": "gzip, deflate"}


@dataclass
class Filing:
    form: str          # "10-K" / "10-Q"
    accession: str     # 例: "0000320193-23-000106"
    filing_date: str   # "YYYY-MM-DD"
    primary_doc: str   # 例: "aapl-20230930.htm"
    url: str           # 直接アクセス可能な URL


@dataclass
class EdgarBundle:
    cik: str
    company: Optional[str]
    annual: Optional[Filing]     # 最新 10-K
    quarterly: Optional[Filing]  # 最新 10-Q
    text_excerpt: str            # 抽出した本文（Claude に渡す）


_TICKER_CIK_CACHE: Optional[dict] = None


def _ticker_cik_map() -> dict:
    """ticker (大文字) -> CIK (10 桁ゼロ埋め文字列) のマップを取得。"""
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is not None:
        return _TICKER_CIK_CACHE
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        out = {}
        for _, v in data.items():
            t = str(v.get("ticker", "")).upper()
            cik = str(v.get("cik_str", "")).zfill(10)
            if t and cik:
                out[t] = cik
        _TICKER_CIK_CACHE = out
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("SEC ticker->CIK マップ取得失敗: %s", exc)
        _TICKER_CIK_CACHE = {}
        return {}


def _strip_html(html: str, limit: int = 80000) -> str:
    """HTML タグを削除して可読テキスト化。サイズを制限して Claude に渡す。"""
    # スクリプト/スタイルを除去
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # タグ除去
    text = re.sub(r"<[^>]+>", " ", html)
    # HTML エンティティ簡易デコード
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#160;", " ")
    )
    # 連続空白圧縮
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


def _fetch_filing_text(cik: str, accession: str, primary_doc: str) -> str:
    accession_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary_doc}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        return _strip_html(resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("filing 本文取得失敗 %s: %s", url, exc)
        return ""


def fetch(ticker: str) -> Optional[EdgarBundle]:
    """Ticker から最新 10-K と 10-Q を取得し、テキスト抽出済みで返す。"""
    ticker_upper = ticker.upper()
    cik_map = _ticker_cik_map()
    cik = cik_map.get(ticker_upper)
    if not cik:
        logger.info("%s の CIK が見つからない (SEC に登録のない銘柄)", ticker_upper)
        return None

    try:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(sub_url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s submissions 取得失敗: %s", ticker_upper, exc)
        return None

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])

    def _latest(form: str) -> Optional[Filing]:
        for i, f in enumerate(forms):
            if f == form:
                acc = accessions[i]
                doc = primary_docs[i] if i < len(primary_docs) else ""
                date = filing_dates[i] if i < len(filing_dates) else ""
                acc_clean = acc.replace("-", "")
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
                return Filing(form=form, accession=acc, filing_date=date, primary_doc=doc, url=url)
        return None

    annual = _latest("10-K")
    quarterly = _latest("10-Q")

    parts = []
    if annual:
        text = _fetch_filing_text(cik, annual.accession, annual.primary_doc)
        parts.append(f"=== 最新 10-K (提出日 {annual.filing_date}, アクセッション {annual.accession}) ===\n{text}")
    if quarterly:
        text = _fetch_filing_text(cik, quarterly.accession, quarterly.primary_doc)
        # 10-Q は短めに切り出し（10-K と合計 120K まで）
        parts.append(f"=== 最新 10-Q (提出日 {quarterly.filing_date}, アクセッション {quarterly.accession}) ===\n{text[:40000]}")

    return EdgarBundle(
        cik=cik,
        company=data.get("name"),
        annual=annual,
        quarterly=quarterly,
        text_excerpt="\n\n".join(parts),
    )
