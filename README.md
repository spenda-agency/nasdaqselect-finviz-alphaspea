# 割安株を見つけるための「3ステップ」巡回手順

無料ツールを組み合わせて、Nasdaq の割安株候補を効率よく絞り込むためのワークフローです。
まずは無料スクリーナーで広く候補を絞り、徐々に詳細な分析サイトへ移っていくのが最も効率的です。

```
Finviz（広く浅く条件検索）→ TradingView（業績トレンド確認）→ Alpha Spread（適正株価とのズレ確認）
```

| ステップ | 使うサイト | 目的 |
| --- | --- | --- |
| Step 1 | [Finviz](https://finviz.com) | 指標ベースで割安候補を自動抽出 |
| Step 2 | [TradingView](https://tradingview.com) | 業績推移と競合比較で「本物の割安株」を判別 |
| Step 3 | [Alpha Spread](https://alphaspread.com) | 理論上の適正株価と現在株価のズレ（安全域）を確認 |

> 本リポジトリには、この手順を自動実行して **毎日 16:00 JST に Slack へ過小評価銘柄を通知する**
> パイプラインを同梱しています。詳細は [自動化パイプライン](#自動化パイプライン毎日-1600-jst) を参照してください。

---

## Step 1：【Finviz】で Nasdaq の「指標ベースの割安株」を絞り込む

全米の投資家が愛用する高機能スクリーナー「Finviz」を使い、数千ある Nasdaq 企業から、
利益に対して株価や時価総額が抑えられている「割安候補」を自動で洗い出します。

**見るサイト：** Finviz (finviz.com)

**やり方・手順：**

1. トップメニューの **Screener** をクリック。
2. **Descriptive（属性）タブ** で、Exchange（取引所）を **NASDAQ** に設定。
3. **Fundamental（財務）タブ** で、以下の割安指標を好みに応じて設定します。
   - **P/E（株価収益率）：** `Under 15` など（利益に対して株価が安い）
   - **PEG（成長性を加味した PER）：** `Under 1`（成長率に対して株価が極めて割安）
   - **P/S（株価売上高倍率）：** ハイテク・グロース株なら `Under 3` など
4. 画面下に、時価総額（Market Cap）や株価（Price）が一覧で並んだ「割安株リスト」が自動生成されます。

---

## Step 2：【TradingView】で業績の推移と「競合比較」を確認する

Finviz で見つけた銘柄が、「ただ業績が悪くて株価が下がっているだけのボロ株」なのか、
「優秀なのに一時的に過小評価されている割安株」なのかを、視覚的なグラフで判別します。

**見るサイト：** TradingView (tradingview.com)

**やり方・手順：**

1. 検索窓に Step 1 で目をつけた企業のティッカー（例：`AAPL` など）を入力。
2. **「財務」タブ（または「ファンダメンタルズ」）** を開きます。
3. 「時価総額」と「総売上（または純利益）」の過去数年の推移を重ねて見ます。
   - **チェックポイント：** 売上や利益は右肩上がりに伸びているのに、時価総額（株価）だけが
     横ばい、または下がっていれば、市場のミスマッチによる「本物の割安株」の可能性が高まります。
4. 同ページ内の「同業他社（競合）との比較」を見て、Nasdaq 内の同じセクターのライバル企業に比べて
   PER や時価総額が低い（＝出遅れている）かを確認します。

---

## Step 3：【Alpha Spread】で「理論上の適正株価」と今の株価を比べる

その企業の将来のキャッシュフローから計算した「本来あるべき理論上の株価（適正価値）」に対して、
今の株価が何％ディスカウントされているか（安全域＝Margin of Safety）をダイレクトに確認します。

**見るサイト：** Alpha Spread (alphaspread.com)

**やり方・手順：**

1. 検索窓にティッカーを入力して企業ページへ。
2. ページ上部に、DCF（ディスカウント・キャッシュフロー）法などに基づいて自動計算された
   **Intrinsic Value（本源的価値／適正株価）** が大きく表示されます。
3. 今の株価がそれより低ければ、画面に **`Undervalued by 30%`（30% 割安）** のように
   視覚的に表示されます。

---

## 補足

- 各指標のしきい値（P/E や PEG など）はあくまで一例です。投資スタイルやセクターに応じて調整してください。
- 本手順は投資判断を保証するものではありません。最終的な投資判断は自己責任で行ってください。

---

## 自動化パイプライン（毎日 16:00 JST）

上記 3 ステップを自動実行し、過小評価されている Nasdaq 銘柄と詳細データを **Slack に通知**します。

### データ取得の現実（重要）

3 サイトとも「きれいな公開 API」が揃っているわけではないため、本実装は以下の方針を取ります。

| ステップ | 本実装での取得方法 | 備考 |
| --- | --- | --- |
| Step 1 | **Finviz スクリーナーをスクレイピング**（`finvizfinance`） | 公式 API は有料の Finviz Elite。Finviz 側の bot 対策で 403 になる場合あり |
| Step 2 | **`yfinance`** で売上・純利益・FCF の推移を取得 | TradingView に公式公開 API が無いため代替 |
| Step 3 | **適正株価を自前計算**（簡易 DCF ＋ グレアム数の平均） | Alpha Spread に公開 API が無いため独自算出 |

> Step 3 の Intrinsic Value は Alpha Spread の値ではなく、当リポジトリが計算した参考値です。
> 通知内には各銘柄の Finviz / TradingView / Alpha Spread への直接リンクを併記するので、
> 最終確認は各サイトで行ってください。

### 抽出ロジック

1. **Step 1**: `FINVIZ_FILTERS`（既定: Exchange=NASDAQ, P/E<15, PEG<1, P/S<3）で割安候補を抽出。
2. **Step 2**: 候補（上限 `MAX_TICKERS` 件）について `yfinance` で財務トレンドを取得。
   売上・純利益がともに減少している銘柄は除外。
3. **Step 3**: 簡易 DCF（FCFE 近似）とグレアム数で適正株価を算出し、
   安全域 `(適正株価 − 現在株価) / 適正株価` が `MIN_MARGIN_OF_SAFETY`（既定 15%）以上のものを採用。
4. 安全域の大きい順に並べ、上位 `TOP_N` 件（既定 10）を Slack に通知。

### セットアップ

1. **Slack Incoming Webhook** を作成し、その URL を GitHub リポジトリの
   **Settings → Secrets and variables → Actions** に `SLACK_WEBHOOK_URL` という名前で登録します。
2. これだけで、`.github/workflows/daily-screen.yml` が **毎日 07:00 UTC（= 16:00 JST）** に自動実行されます。
3. 初回は手動実行で動作確認することを推奨します
   （**Actions → Daily undervalued Nasdaq screen → Run workflow**、`dry_run=true` で Slack 送信なし）。

### ローカル実行

```bash
pip install -r requirements.txt

# Slack に送らず結果を標準出力に表示
python -m src.main --dry-run

# 実際に Slack へ通知
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ" python -m src.main
```

### 主な環境変数（任意で上書き可能）

| 変数 | 既定値 | 意味 |
| --- | --- | --- |
| `SLACK_WEBHOOK_URL` | （必須） | Slack Incoming Webhook URL |
| `FINVIZ_PE` / `FINVIZ_PEG` / `FINVIZ_PS` | `Under 15` / `Under 1` / `Under 3` | スクリーニング閾値 |
| `MAX_TICKERS` | `25` | 詳細分析にかける最大銘柄数 |
| `TOP_N` | `10` | 通知する上位銘柄数 |
| `MIN_MARGIN_OF_SAFETY` | `0.15` | 通知対象とする最低安全域 |
| `DCF_DISCOUNT_RATE` | `0.09` | DCF の割引率 |
| `DCF_TERMINAL_GROWTH` | `0.025` | DCF の永続成長率 |

### 既知の制約

- **Finviz のスクレイピングは 403 になる場合があります**（データセンター IP への bot 対策）。
  安定運用には有料の **Finviz Elite（CSV エクスポート）** への切り替えを推奨します
  （`src/screener.py` を差し替えるだけで対応可能な構造です）。
- `yfinance` も非公式ライブラリのため、Yahoo Finance 側仕様変更の影響を受けることがあります。
- 適正株価は簡易モデルによる参考値です。投資判断は必ず自己責任で行ってください。

### 構成

```
src/
  config.py        # 設定（環境変数で上書き可能）
  screener.py      # Step 1: Finviz スクリーニング
  fundamentals.py  # Step 2: yfinance で財務トレンド取得
  valuation.py     # Step 3: DCF + グレアム数で適正株価を算出
  pipeline.py      # 3ステップの連結と絞り込み
  report.py        # Slack 用メッセージ整形
  notify_slack.py  # Slack Webhook 送信
  main.py          # エントリポイント
.github/workflows/daily-screen.yml  # 毎日 16:00 JST の定期実行
```
