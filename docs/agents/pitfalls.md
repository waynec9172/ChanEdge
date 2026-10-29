# 審查前要先知道的事

每一條都指向已經寫死的地方。數字與公式去讀那一節，不要從本檔抄進程式，也不要把本檔當成第二份預設值。

實作時最容易改壞的句子，全文在實作計畫「寫的時候最容易偏掉的地方」。本檔只補審查者特別會看錯的操作事實。

## 文件哪一份算數

- 行為與數字：架構稿從「架構設計」起。鎖定句在開頭，決策在 §4，目錄與依賴在 §5.1、§5.2，纏論在 §5.6，出場在 §5.7，JEV 在 §5.8，紙交易在 §5.9，撮合在 §5.10，前 20 名在 §5.12，熱路徑在 §5.13，圖在 §5.14，雜湊與資料表在 §7，依賴與授權在 §8、§9，階段在 §11。
- 步驟與測試鎖：實作計畫對應的 PR 節。
- 規格審查的「沒有交易程式」只約束審文字的人。程式審查看 `src/chanedge`。見 [review.md](review.md)。

## 紙交易和回測不共用的幾件事

同一份決策順序：先撮合上一根留下的 `next_open`，再做盤中停損與 TP1，然後才 `run_pipeline`。出場組先於進場組。這段在 §5.10 與 §5.12，兩條迴圈都要遵守。

下面這些是兩條路徑的差別，寫在實作計畫 PR-11 與 PR-12：

- 回測在品質回呼之後把過期視為否。紙交易要呼叫真正的過期判斷。
- 紙交易在抓 K 線之前先等 `close_wait_seconds`。回測不等，回測命令也不睡。
- 紙交易的牆鐘從該根的幣種迴圈開始。超過 60 秒的幣不呼叫 `run_pipeline`，由紙交易迴圈寫一筆只有 `PIPELINE_TIMEOUT` 的 `HOLD`。這筆不是 `run_pipeline` 裡產生的。回測沒有這道牆鐘，也不產生這個拒絕碼。
- 紙交易寫完整決策列。回測只在進場組、沒有候選、沒有歧義時寫精簡列。出場組始終完整。
- 紙交易會寫 `ChartFrame`，而且寫在該根帳簿提交之後。寫圖失敗只記錯誤，不回滾委託。平倉且掉榜的幣刪掉三個週期的幀。回測不寫這些幀。
- 紙交易 SQLite 維持 WAL，`synchronous` 不是 0。報告庫才設 `synchronous=OFF`。不要加 migration 002。結構版本仍是 1。
- `close_wait_seconds`、日誌路徑、`monitor`、`safety`、`runtime.mode`、`initial_equity_quote`、`pin` 不進 `config_hash`。排除清單在架構稿 §7 與實作計畫「規範化雜湊」。

## 依賴與組裝

- 允許的 import 以 §5.2 與 `tests/test_boundaries.py` 為準。`execution` import `journal` 是明確的失敗例。
- `app` 可以組裝其他套件，但不要 import `monitor` 的繪圖程式，也不要把業務公式寫進 `app`。
- 業務套件不 import `config`。`app/bind.py` 把 `Settings` 收成 `domain` 的參數物件，建構時傳入。
- `mode=live` 在讀 `CHANEDGE_API_KEY` 與 `CHANEDGE_API_SECRET` 之前失敗。`mode=paper` 的交易所物件不讀這兩個名字。
- overlay YAML 不得含金鑰欄位。載入時會拒絕。
- Phase 1 依賴只有 pydantic、PyYAML、pandas、pyarrow、SQLAlchemy、structlog、ccxt、pytest。不要加入 czsc、chan.py、chanlun-pro、backtrader、vectorbt、polars、duckdb。

## 兩個同名的 FundingMonth

`marketdata.vision.FundingMonth` 是讀檔結果，欄位是路徑、是否缺檔、以及原始列。`domain.records.FundingMonth` 是領域物件，欄位是年、月、`present`、點列。`app/paper_loop.py` 裡的 vision 轉接把前者對成後者。審查時先看 import 來自哪一個模組。

## id、路徑與榜單

- `decision_id` 在 `domain/ids.py`。七個欄位先做成規範化 JSON 再雜湊，順序寫在實作計畫「三個版本字串」。不要把字串直接接起來。固定夾具是 `dec_ad70ba8d71d416fd`。三個版本字串很長，而且中間有 `|`。
- 報告目錄是 `data/reports/{run_id}/`。`run_id` 含版本字串，超過 800 字；SQLite 在 Linux／macOS 拒絕超過 512 位元組的路徑，所以長 `run_id` 用短目錄名（頭、雜湊、視窗與時間尾），完整 `run_id` 寫在目錄裡的 `run.json`。不要改回拆段。架構稿那句目錄句子仍然成立。
- 今天的榜單檔已經存在，不論 `source`，都不覆寫。回測範圍缺檔則拒絕啟動，並指向 `universe --reconstruct`。不要用 `pin` 填歷史缺檔。`pin` 不跑 `download`、`universe`、`backtest`。
- 重建只補尚不存在的日期。紙交易缺當天檔、而且沒有持倉：不開始。有持倉：只管理既有部位。
- 對帳比的是 `decision_id` 集合。只含 `PIPELINE_TIMEOUT`、或含 `STALE_DATA` 的決策另列，不算策略分歧。沒有紙交易庫就不寫 `reconcile.json`。

## 測試寫法

- 工廠放在測試模組裡。測試檔之間不要互相 import。
- 不要加 `tests/**/__init__.py`。
- 領域模型是關鍵字建構的凍結模型。序列用 `tuple`。不要用 `model_construct`。
- 價格進 `Decimal` 的規則、負零、以及 `Bar.low > 0`，在實作計畫「寫的時候最容易偏掉的地方」的最後幾條。
- 正式的 `min_bi_bars` 與夾具裡用的較小值不是同一個用途。夾具值只活在夾具。不要把夾具值寫回 `default.yaml`。
- 預設 `kill_switch` 是 true。紙交易覆蓋檔才把它設成 false。需要放行進場的測試要自己關掉，不要改預設檔。

## 不要在審查裡順手改的東西

這些已經鎖定。衝突時記問題，不要直接改架構稿的句子，也不要在重構時改程式裡的對應行為：

- 4H、1H、15m 的分工，以及 JEV 不下單、不閘控出場。
- 進場門檻、通道權重、`arm_r`、重疊峰、成本／R、正式 `min_bi_bars`、四種信號形態、出場原因。位置都在架構稿鎖定清單與實作計畫開頭那句「沒有改」。
- 一買、一賣只留列舉，不是 Phase 1 的進場信號。
- 停損距離不夠時縮小口數，或因成本／R 拒絕。不要放寬停損。`MIN_QTY` 不用來表示缺規格。
- 利潤因子不是軟體閘門。
- 一次一個人寫一個 PR。PR-13、實盤與 Telegram 等使用者明確說要做。
