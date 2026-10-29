# ChanEdge 實作計畫

這份告訴工程師每個 PR 要建立哪些檔、函式按什麼順序寫、測試先鎖哪幾條。交易規則、預設數字、夾具期望都以 `docs/ARCHITECTURE.md` 為準。兩份不一致時，改這份，不改架構稿裡已經鎖定的句子。

日期對齊架構稿：2026-10-28。倉庫在撰寫這份計畫時還沒有交易程式。狀態是 Draft。交易規則在 2026-10-29 核過，沒有 critical 或 major。PR-1 已完成（設定載入與 config_hash）。PR-2 已完成（領域型別與 id）。PR-3 已完成（行情、榜單、缺口、小數推估）。PR-4 已完成（日誌結構）。PR-5 已完成（纏論引擎，不含買賣點）。PR-6 已完成（二買、三買與對稱賣點）。PR-7 已完成（六通道特徵）。PR-8 已完成（JEV 加權評分）。PR-9 已完成（硬閘門）。PR-10 已完成（風險）。PR-11 已完成（管線、撮合、回測）。PR-12 已完成（CLI、紙交易、重啟）。System One 進場路徑已接入（預檢、映射、JSONL、`jev-warm`、快取未命中退出碼 3）。`config/default.yaml` 與 `config/paper.yaml` 沒有把 `systemone.enabled` 打開。PR-13 還沒開始。

本輪相對上一份計畫，只加工程做法，不改進出場：

- 1H／4H 在 `as_of` 與 `bar_window_hash` 沒變時沿用上一張快照。`as_of` 是該週期最後一根的 `close_time`。`bar_window_hash` 的列格式寫在架構稿 §7。`snapshot_id` 可以快取物件片段，接出來的位元組必須相同。
- 回測進場組的 `NO_CANDIDATE` 寫精簡列。出場組與紙交易寫完整列。報告庫 `synchronous=OFF`，同一根 15m 一次提交。
- 榜單 JSON 與 Parquet 先寫 `*.tmp`，再用 `os.replace`。正式檔解析失敗不自動覆寫。
- `trades.parquet` 加 `funding_estimate_quote`。不進現金。
- 紙交易收盤後等 `close_wait_seconds`（預設 3）。PR-12 用 vision 重跑對帳 `decision_id`。
- PR-2 之後三條線可並行。PR-8、PR-9、PR-10 只依賴 PR-2。

上一輪的三處修正沒有改寫。`0.62`、六個權重、`arm_r` 1.0、`overlap_peak` 0.35、四個信號的形態定義沒有改。

## 怎麼用

一個人依序寫時，一次只做一個 PR。該 PR 的測試通過，再開始下一個。不要把後面 PR 的公式提前寫進前面的模組。PR-2 合併之後，PR-3、PR-4、PR-5 可以同時開，各用一個 worktree。PR-8、PR-9、PR-10 也只依賴 PR-2，可以跟它們一起開。一條線裡的 PR 仍要等它自己的上游。PR-5 與 PR-6 合併之後，夾具數字以 JSON 為準；之後改文件只寫夾具名與索引。

合併順序：

```text
PR-1 → PR-2 ┬→ PR-5 → PR-6 → PR-7 ┬→ PR-11 → PR-12 → PR-13
             ├→ PR-3、PR-4 ────────┤
             └→ PR-8、PR-9、PR-10 ─┘
```

Phase 1 停在 PR-12。PR-13 是 Phase 2 的唯讀網頁。任何 PR 都不寫 `execution/live.py`、不接 Telegram、不開繪圖埠、不把 czsc、chan.py、chanlun-pro 放進依賴。

每個 PR 結束時做三件事：

1. `python -m pytest` 跑該 PR 新增的測試，加上已經存在的測試。
2. 用 `tests/test_boundaries.py` 確認新模組沒有違反 §5.2 的匯入方向。
3. 不把審查用的 `/tmp` 腳本抄進倉庫。夾具是 JSON，期望值從架構稿的表抄進來。

作者機器是 Windows。路徑用 `pathlib`。測試不呼叫 Windows API，也不在單元測試裡打外網。

## 共同寫法

### 語言與套件

`pyproject.toml` 要求 Python `>=3.12`。Phase 1 依賴只有：pydantic v2、PyYAML、pandas、pyarrow、SQLAlchemy 2、structlog、ccxt、pytest。設定檔是 YAML，解析用 PyYAML。不加入 Backtrader、vectorbt、Polars、DuckDB、czsc、Rust 擴充。

價格用 `float`。口數、權益、名義、費用用 `Decimal`。時間一律 UTC aware。

套件入口是 `src/chanedge`。CLI 到 PR-12 才註冊：

```text
[project.scripts]
chanedge = "chanedge.app.cli:main"
```

PR-1 到 PR-11 可以先不要這個入口。若提前註冊，`main` 只能印出「尚未實作」並以非 0 退出，不能偷偷跑交易。

### 模組邊界

`tests/test_boundaries.py` 從 PR-1 就存在。它讀每個套件的 import，對照下面這張允許表。多出來的內部 import 讓測試失敗。設定、帳簿與管線用建構時注入，不靠跨套件 import。

| 模組 | 可以 import |
| --- | --- |
| `domain` | 標準庫 |
| `config` | `domain` |
| `marketdata` | `domain`、`config` |
| `chanlun` | `domain` |
| `features` | `domain` |
| `jev` | `domain` |
| `rules` | `domain` |
| `risk` | `domain` |
| `execution` | `domain` |
| `journal` | `domain` |
| `backtest` | `domain`。撮合函式不 import `chanlun`。不 import `app`、`marketdata`、`journal`。K 線、榜單與報告經 `domain` 的埠，由 `app` 傳入 |
| `monitor` | `domain`、`journal` 的讀取埠 |
| `app` | 上面全部，除了 `monitor` 的繪圖程式 |

`app` 負責把物件組起來。業務公式不要寫在 `app`。注入的寫法：

- `app` 把 `Settings` 收成放在 `domain` 的參數物件，建構時傳入。`JevModel(params).assess(features)`。不要寫成 `evaluate(features, settings)`。`features`、`risk`、`chanlun`、`rules` 需要的 `atr_period`、`max_cost_r`、`min_bi_bars` 同一種。這些套件不 import `config`。
- `PaperBroker` 接收 `domain` 裡的帳簿埠。`app` 傳入 `journal` 的實作。同一筆 SQLite 交易寫 `fills`、`positions`、`accounts`。`execution` 不 import `journal`。
- `backtest` 的迴圈以參數接收 `run_pipeline`。`app` 已經會 import `backtest`，迴圈不要再 import `app`。
- 回測迴圈另以參數接收 K 線來源、榜單來源與報告寫入埠。三個協定定義在 `domain`。`app` 傳入 `marketdata` 的兩個讀取實作，以及 `journal` 的報告寫入實作。`backtest` 不 import `marketdata`，也不 import `journal`。K 線來源讀已落盤的 Parquet，不經 `MarketDataPort.fetch_closed_bars` 打交易所。報告寫入埠寫 `data/reports/{run_id}/`，不是紙交易的 `data/chanedge.sqlite`，也不是 `PaperBroker` 的帳簿埠。
- `decision_id` 放在 `domain/ids.py`，PR-2 就寫好。三個版本字串是參數。`journal` 不 import `chanlun`、`features`、`marketdata`。

### 三個版本字串

三個常數分開，都是純字串，不進 YAML，也不進 `config_hash`。

| 常數 | 放在 | 內容必須能看出 |
| --- | --- | --- |
| `ENGINE_VERSION` | `chanlun/version.py`，PR-5 建立，PR-6 改字串 | 二買不要求一類；三買終點被取代不重發；二買再發沒有次數上限；創建中樞的 ZG／ZD 不因第三筆終點被取代而重算；結束中樞的筆被拉長也不重開；`ZG <= ZD` 時丟掉最早一筆、保留後兩筆，丟掉的已消費，終點被取代也不撿回 |
| `FEATURE_VERSION` | `features/version.py`，PR-7 建立 | 筆端點才是前高前低；沒有前高不扣 0.20；二買位置量到防守價；無中樞清晰度 0.5；波動 tent 峰是該幣 p50 |
| `MARKETDATA_VERSION` | `marketdata/version.py`，PR-3 建立 | vision 路徑、符號過濾、`quote_volume <= 0` 跳過、CSV 原文小數推估 |

`decision_id` 的雜湊輸入在 PR-2 寫死，函式收三個版本字串。七個欄位先做成規範化 JSON 陣列，再做 sha256。順序是 `symbol`、`decision_time`、`action`、`config_hash`、`engine_version`、`feature_version`、`marketdata_version`。不要把字串直接黏在一起：`'BTCUSDT1' + '2024'` 和 `'BTCUSDT' + '12024'` 會變成同一個雜湊。前 16 個十六進位字元，前綴 `dec_`。三個版本任一變了，id 就變，舊列留著。PR-4 只呼叫這個函式，不在 `journal` 裡重寫一份。

固定期望，測試原樣比對。`decision_time` 是 `2024-01-01T00:15:00.000Z`，`config_hash` 是 64 個 `a`，三個版本字串是 `engine-v1`、`feature-v1`、`marketdata-v1`，動作 `HOLD`，符號 `BTC/USDT`：

```text
dec_ad70ba8d71d416fd
```

結構 id 也各鎖一條。價格都是八位小數，時間都是帶毫秒的 `Z`，不用 `isoformat()`：

```text
fx:15m:bottom:2024-01-01T00:15:00.000Z:100.50000000
bi:15m:down:2024-01-01T00:00:00.000Z:2024-01-01T00:15:00.000Z:100.00000000:90.00000000
zs:15m:2024-01-01T00:15:00.000Z:50.00000000:40.00000000
sig:15m:second_buy:2024-01-01T00:15:00.000Z:100.50000000
```

### 結構 id

放在 `domain/ids.py`，PR-2 寫好，後面只呼叫，不各寫一套格式。

```text
fx:{timeframe}:{mark}:{中柱 open_time}:{price 八位小數}
bi:{timeframe}:{direction}:{start_open_time}:{end_open_time}:{start_price}:{end_price}
zs:{timeframe}:{第一筆終點 open_time}:{zg}:{zd}
sig:{timeframe}:{type}:{信號 K 線 open_time}:{defending_price}
```

視窗序號不進任何 id。價格格式用 `format(x, ".8f")`。格式化後的 `-0.00000000` 改成 `0.00000000`。時間格式 `YYYY-MM-DDTHH:MM:SS.mmmZ`，有時區但不是 UTC 的先轉 UTC。

### 規範化雜湊

`config/hash.py` 在 PR-1 提供 `canonical_json` 與 `config_hash`。規範化函式放在 `domain/canon.py`，`config/hash.py` 再轉出，因為 `domain` 不能 import `config`，而 id 與雜湊必須用同一份格式。規則是架構稿 §7：UTF-8、鍵排序、無空白、浮點與 `Decimal` 都是八位小數。格式化之後的字串若是 `-0.00000000`，改成 `0.00000000`。有時區但不是 UTC 的時間先轉 UTC。NaN 與無限大直接拒絕。排除 `journal`、`monitor`、`safety`、`runtime.mode`、`marketdata.close_wait_seconds`、`initial_equity_quote`、`pin`、當日榜單。不在 §7 納入清單上的鍵不進雜湊。有效合計名義不另加鍵。測試把 `default.yaml` 的每個葉節點各改一次：雜湊有變，若且唯若該路徑在清單裡。這次改值用 `model_copy`，不重新驗證，所以權重總和、`universe.size`、`position_mode` 這種會被驗證擋下的葉節點也要改到，不准因為驗證失敗就略過。新增設定鍵時這份清單對不上，測試要失敗。id 的價格與之後的 `bar_window_hash` 列用同一條負零規則。

## PR-1 套件骨架與設定載入

交付一份能載入、會拒絕壞設定的設定模型。沒有交易。

檔案：

```text
pyproject.toml
.gitignore                      # .env、data/、*.sqlite
config/default.yaml             # 整份抄架構稿 §11.4
config/paper.yaml               # 只覆蓋 runtime.mode=paper、safety.kill_switch=false
src/chanedge/__init__.py
src/chanedge/config/model.py
src/chanedge/config/hash.py
src/chanedge/config/load.py
tests/test_config.py
tests/test_boundaries.py
```

怎麼寫：

1. `Settings` 用 pydantic v2，欄位與 `config/default.yaml` 的鍵一一對應。不要在模型裡再寫一套預設數字；預設只活在 YAML。
2. `load_settings(default_path, overlay_path | None)` 先讀 default，再把 overlay **遞迴合併**進去。只換掉 overlay 裡出現的葉節點。紙交易只蓋 `runtime.mode` 與 `safety.kill_switch`。不准用頂層鍵整份替換，否則 `runtime` 會只剩 `mode`，`venue` 等欄位會不見。
3. 驗證器：
   - 六個頂層權重總和為 1。每個通道內權重總和為 1。用 `Decimal` 加總，容許絕對誤差 `1e-9`。
   - `hold_bias > 0`。`enter_threshold` 在 0 與 1 之間。
   - `reentry_factor` 長度至少 1，每一項在 0 與 1 之間。
   - `universe.size == 20`。`exclude_bases` 沒有重複、沒有空白。
   - `mode=pin` 時清單非空，且 `symbol` 不重複。`pin` 不進 `config_hash`。
   - `max_cost_r` 在 `(0, 1]`。`max_same_direction` 是正整數，且 `<= max_open_positions`。`volatility.min_samples` 是正整數。
   - `position_mode` 只接受 `one_way`。
   - YAML 結構裡沒有 `api_key`、`api_secret`、`token` 這類欄位。模型用 `extra="forbid"`。
4. `config_hash(settings)` 回傳 sha256。測試改一個權重，雜湊要變；改 `initial_equity_quote` 或 `kill_switch`，雜湊不變。

這一步不要寫：K 線、引擎、分數、下單、CLI 的四個子命令。

測試：權重和為 0.99 時載入失敗；`size: 19` 失敗；`paper.yaml` 蓋完之後 `mode` 是 paper、`kill_switch` 是 false，而且 `runtime.venue` 仍是 `binanceusdm`。其餘鍵與 default 相同。

## PR-2 領域值物件

交付 §6 的列舉與不可變資料類別。沒有 I/O。

檔案：`src/chanedge/domain/` 拆成 `enums.py`、`model.py`、`canon.py`、`bars.py`、`chanlun.py`、`decision.py`、`risk.py`、`ids.py`、`ports.py`。測試在 `tests/domain/`。`ports.py` 是 §6 的協定，含 `MarketDataPort`。PR-3 的 `marketdata/port.py` 是紙交易實作，不另宣告一份協定。

怎麼寫：

1. 列舉值用架構稿的字串，不要自創同義詞。`SignalStatus` 保留 `CANDIDATE` 與 `INVALIDATED`，但 Phase 1 的建構函式不要把它們當合法輸出。可以在 `ChanSignal` 的驗證器裡拒絕這兩個值，讓呼叫端只能放 `CONFIRMED`。
2. `Bar`、`Fenxing`、`Bi`、`Segment`、`Zhongshu`、`ChanSignal`、`ChanSnapshot`、`Instrument`、`FeatureVector`、`JevAssessment`、`HardRuleResult`、`RiskPlan`、`OrderIntent`、`PositionState`、`ChartFrame`、`Decision` 全部凍結（`frozen=True` 或等價的不可變模型）。
3. `ChanSnapshot` 不放 K 線序列。K 線留在之後的 context。
4. `JevAssessment` 從第一天就有 `calibrated: bool`。
5. `Instrument.instrument_source` 只有 `exchange` 與 `inferred`。沒有全域 `min_qty` 欄位。
6. `OrderIntent` 沒有 `fill_model`，也沒有 `trigger_price`。
7. `PositionState.entry_decision_id` 用這個名字。不要另開 `opened_decision_id`。
8. `RiskPlan.reject_reason` 用 `VetoCode` 裡的風險碼。`MIN_QTY` 留在列舉裡，口數函式之後不會產生它。
9. id 函式是純函式，含 `decision_id`。三個版本字串是參數，不在這個套件裡 import `chanlun`、`features`、`marketdata`。同一組輸入呼叫兩次，字串相同。`decision_id` 用上面的 JSON 陣列。每種 id 都鎖死「結構 id」那一節寫好的期望字串。
10. 列舉用 `StrEnum`，讓 JSON 與規範化雜湊輸出架構稿上的字串。
11. 凍結模型的序列欄位用 `tuple`。`frozen=True` 的 `list` 仍可以 `.append`，物件也不能進雜湊。測試要斷言 `snapshot.bis` 不能被改。
12. `Bar` 的檢查寫在架構稿 §6：有限數、高低價包住開收、`low > 0`、`volume >= 0`（0 要過，負數拒絕）、`open_time` 對齊週期、`close_time` 是開盤加一個週期。沒有時區的時間拒絕。時間格式用規範化的 `Z`，有時區但不是 UTC 的先轉 UTC。不用 `isoformat()`。
13. 一根 `Bar` 在載入時建一次。視窗從已經建好的 tuple 切片。PR-3 與 PR-11 沿用這個做法，不在每筆決策把 1500 根重建一次。方向性的量測，不是驗收門檻：pydantic 的 `Bar` 建一根約 9 µs；1500 根重建約 13.6 ms，整段回測光 15m 大約多 7 小時。切片約 0.008 ms。
14. 其他結構物件維持 pydantic frozen。不要為了速度改成 dataclass，也不要用 `model_construct`。後者會跳過驗證。同樣只是方向性的量測：frozen 約 1.2 µs，帶 slots 的 dataclass 約 0.8 µs，`model_construct` 約 4.3 µs。
15. `float` 轉 `Decimal` 用 `Decimal(repr(x))`。不要寫 `Decimal(0.1)`，那會帶上二進位尾數。名義與費用都走這條。

這一步不要寫：怎麼從 K 線算出這些物件。測試只用手工建構。

測試：snapshot 的欄位清單不含 `bars`。`snapshot.bis` 不能被改。`ChanSignal(status=CANDIDATE)` 被拒絕。兩次 `bi_id(...)` 相同，而且等於上面那條固定的 `bi:` 字串。`fx`、`zs`、`sig`、`decision_id` 同樣各鎖一條。只改一個版本字串，`decision_id` 就變。`OrderIntent` 的欄位集合不含 `fill_model`。成交量 0 的 `Bar` 可以建。負成交量與 `low <= 0` 被拒絕。無時區的時間被拒絕。

## PR-3 行情、榜單、缺口、小數推估

交付 K 線如何變成 `Bar`、榜單 JSON 怎麼寫、下架合約的 tick 怎麼推。不呼叫纏論。

檔案：

```text
src/chanedge/marketdata/version.py
src/chanedge/marketdata/port.py          # 紙交易實作。協定本體在 domain.ports，PR-2 已宣告
src/chanedge/marketdata/vision.py        # 讀本地或下載後的 CSV 目錄
src/chanedge/marketdata/infer.py         # 小數推估
src/chanedge/marketdata/universe.py      # 選幣與 JSON
src/chanedge/marketdata/parquet_store.py
src/chanedge/marketdata/quality.py       # 缺口、未收盤
src/chanedge/marketdata/ccxt_adapter.py  # 只給紙交易增量。測試用假物件
tests/marketdata/
```

怎麼寫：

1. `MarketDataPort` 只有 `fetch_closed_bars` 與讀日 K。不要在協定上放 `create_order`。ccxt 類別自己有這個方法沒關係；紙交易組合根在 PR-12 負責不把金鑰裝進去。
2. 正規化：`open_time` 是交易所給的開盤時間，轉成 UTC。`close_time = open_time + 週期`。`is_closed` 為真若且唯若 `close_time <=` 抓取時鐘。未收盤的那根不寫 Parquet。
3. vision 路徑照架構稿：`data/futures/um/monthly/klines/{SYMBOL}/{interval}/`，當月未收齊用日檔。`interval` 用 `15m`、`1h`、`4h`、`1d`。日 K 不進 `Timeframe` 列舉，也不進 `ChanEngine`。
4. 暖機起點是純函式，先寫測試再寫實作：

```text
warmup_open(history_start, timeframe, window) =
    會在 history_start 當天 00:00:00Z 收盤的那一根的 open_time
    再往前 (window - 1) 根
download_start = 三個週期的 warmup_open 取最早
```

預設 `history_start = 2024-01-01`、4H 視窗 500 時，結果必須是 `2023-10-09T16:00:00Z`。榜單檔從 `history_start` 當天起。回測第一根決策不是當天 00:00，是 00:15，見 PR-11。暖機起點不因為這條往前或往後移。暖機區間不要求有榜單檔。

5. 小數推估讀 CSV **原文**。不要先 `float()`。

```text
decimal_places(token):
    去掉空白
    不是數字 → 推估失敗
    沒有小數點 → 0
    否則取小數部分，去掉右側的 0，剩下幾個字就是位數
price_tick = 10^(-d)，d 是 open/high/low/close 的最大位數；整數則 tick = 1
qty_step 用 volume 欄，同一套
min_qty = qty_step
min_notional = 空
instrument_source = inferred
```

推估失敗時規格物件留空，並標一個失敗旗標。拒絕碼 `INSTRUMENT_SPEC` 是 PR-10 的事。這一步只保證「留空且失敗」和「成功時三個數都是正的 Decimal」。

6. 重建榜單：
   - 檔名日期 D 讀 `open_time = (D-1) 00:00:00Z` 的日 K `quote_volume`。
   - 符號以 `USDT` 結尾、不含 `_`，基幣不在 `exclude_bases`。
   - `quote_volume` 缺值或 `<= 0` 就跳過。
   - 過濾後不足 20 個就失敗，不要悄悄取較小的池。
   - 同額用 `symbol` 字母序。
   - 目標 JSON 已存在就跳過，包含 `daily_kline`、帶 `fallback_from` 的檔、已經寫過的 `reconstructed`。
   - 新檔先寫 `*.tmp`，再用 `os.replace` 換成正式檔名。占用時重試最多 5 次。不要把暫存檔留成正式檔名。
   - 新檔的 `source` 是 `reconstructed`。不要標成 `daily_kline`。
7. 紙交易當天凍結的選幣函式與重建共用過濾，但 `instrument_source` 走 ccxt 的 limits，`source` 寫 `daily_kline`。`min_qty` 缺值或不是正數的合約不進當日池。這條不套到重建檔：重建允許規格還沒推估的名字進榜。
8. Parquet 路徑 `data/bars/{venue}/{symbol}/{timeframe}.parquet`。補資料時若檔是空的，呼叫端要能問到「沒有最後一根」。已有資料時從最後一根 `open_time`（含）覆寫。形成中的 K 線不寫入。整檔重寫走 `*.tmp` 與 `os.replace`。打不開的檔是錯誤，不是空檔。每根 K 線進記憶體時算好 `bar_window_hash` 的那一列，格式見架構稿 §7。`download` 同時抓 fundingRate 月檔，路徑見架構稿 §7。缺月檔不讓這個 PR 失敗。
9. 缺口：只看呼叫端送進來的那個視窗。`missing = (後 open - 前 open) / 週期 - 1`。單一洞的 `missing > max_gap_bars`（預設 1，所以缺 2 根以上）才是缺口。`missing_bar_count` 只加總，不當門檻。

這一步不要寫：`ChanEngine`、JEV、`plan_entry`、真正的 HTTP 下載迴圈（那是 PR-12 的 CLI）。vision 測試用 `tmp_path` 裡的假 CSV。

測試最少要有：暖機起點那一個時間；BTC 風格的原文 `0.10` 與 `0.001` 得到 tick 0.1、步長 0.001；先轉 float 會丟尾數的案例（例如 `0.00000010`）仍得到正確位數；`quote_volume = 0` 被跳過；不足 20 名失敗；已存在的 JSON 不被覆寫；缺 1 根不是缺口、缺 2 根是；未收盤 4H 不進視窗。

## PR-4 日誌結構

交付 SQLite schema 與決策 upsert。不接策略。

檔案：`src/chanedge/journal/schema.py`、`repository.py`、`tests/journal/`。遷移編號從 001 起。

怎麼寫：

1. 表：`decisions`、`orders`、`fills`、`positions`、`accounts`、`chart_frames`、`schema_meta`。全部在 migration 001。`accounts` 是單列，`account_id` 固定為 1，欄位 `cash_quote`。不留到後面的遷移再補。欄位用架構稿 §7 的清單。`decisions` 含 `engine_version`、`feature_version`、`marketdata_version`。`decision_id` 呼叫 PR-2 的函式。
2. `positions.entry_decision_id` 與 `PositionState` 同名。
3. `chart_frames` 的主鍵是 `(symbol, timeframe)`。寫入是覆寫最新一筆，不是追加歷史。
4. `upsert_decision` 以 `decision_id` 為鍵。同一 id 再寫，覆寫該列。不同 version 造成的不同 id 兩列都留著。
5. 紙交易庫路徑是設定裡的 `journal.sqlite_path`，開 WAL。回測庫的路徑由呼叫端傳入；這一步先讓 repository 接受路徑，PR-11 才把報告庫分開。
6. 提供 `load_open_positions()`：`qty != 0`。以及 `load_pending_orders()`：狀態仍是待成交的 `next_open`。PR-12 的重啟用這兩個函式。

這一步不要寫：誰來產生決策、撮合價格、ChartFrame 的業務內容。測試用假的決策物件。

測試：同一 `decision_id` upsert 後只有一列，`size_qty` 被更新。換一個 `engine_version` 得到第二列。`chart_frames` 同一幣同一週期再寫，仍是一列。

## PR-5 纏論引擎，不含買賣點

交付 `ChanEngine.compute`。輸出含筆、中樞、`structure_bias`。`signals` 先是空清單。`segment_enabled=false` 時 `segments` 是空清單，而且不呼叫 `minimal_break`。

檔案：

```text
src/chanedge/chanlun/version.py
src/chanedge/chanlun/include.py
src/chanedge/chanlun/fenxing.py
src/chanedge/chanlun/bi.py
src/chanedge/chanlun/zhongshu.py
src/chanedge/chanlun/bias.py
src/chanedge/chanlun/engine.py
src/chanedge/chanlun/segment.py      # minimal_break 可寫，預設路徑不呼叫
tests/chanlun/test_include.py
tests/chanlun/test_bi_machine.py
tests/chanlun/test_zhongshu_freeze.py
tests/fixtures/golden_bi_machine.json
tests/fixtures/golden_zs_zd_frozen.json
tests/fixtures/golden_zs_outside_stays_out.json
tests/fixtures/golden_zs_drop_no_revive.json
```

核心寫法是**一次由左向右的走訪**。不要先把全部筆建完，再拿最終筆清單重算中樞。第三筆的終點會在確認之後被拉長；重算會把 ZD 改掉。

把走訪寫成一個狀態物件，PR-6 才能在同一個迴圈裡掛信號，而不必再掃一次：

```text
state = WalkState(min_bi_bars)
merged = include_merge(bars)          # 一次
for fx in confirmed_fenxings(merged): # 依 k_index_mid
    event = state.feed_fenxing(fx)    # "new" | "replace" | None
    if event is None:
        continue
    state.apply_zhongshu(event)       # 下面三條
    # PR-6 在這裡呼叫 state.apply_signals(event, bars)
state.bias = bias_at(state, bars)
return snapshot(signals=[])           # PR-6 才填 signals
```

`feed_fenxing` 就是架構稿的狀態機：

- 沒有端點：這支分型當起點。
- 同型且嚴格更極端：有筆就只換最後一筆的終點，重算該筆 high、low、`end_time`、`end_price`，回傳 `replace`。沒有筆就換起點。價格相等不算更極端。
- 反向，且 `raw_between >= min_bi_bars`，且價格方向成立：新增一筆，回傳 `new`。
- 其他：忽略，回傳 `None`。忽略的分型仍放進 `snapshot.fenxings`。

`apply_zhongshu`：

- `new`：若正在湊創建三筆，把這筆加進去。滿三筆且 `ZG > ZD` 時凍結 `zg`、`zd`、中樞 id、`start_time`、確認棒（這筆終點的右根）。`ZG <= ZD` 不產出物件，而且只丟掉最早那一筆，保留後兩筆繼續湊。丟掉的那一筆算已消費，之後不再撿回。不要把三筆全部清空。例：`[10, 20]`、`[10, 30]`、`[25, 30]` 交集為空；下一筆 `[25, 40]` 得到 ZG／ZD 30／25。其後的新筆若與凍結的 `[ZD, ZG]` 有交集，納入成員，只更新 `GG`、`DD`、`end_time`、`bi_ids`。完全在外側則結束本中樞，這筆成為下一個中樞的第一筆，並記住「確立時在外側」。外側那一筆沒有被消費。
- `replace` 有三種，都不要重測已經做過的判斷：
  - 若被換的是某中樞最後一個成員，不重算 ZG／ZD，不改中樞 id，不改 `start_time`，不把這筆改判成外側。依目前成員重算 GG／DD，`end_time` 改到新終點中柱的 `open_time`，`bi_ids` 裡那一格換成新筆 id。確認棒留在第一次確立的右根。
  - 若被換的是「確立時在外側、因而結束了某個中樞」的那一筆，即使拉長後的區間落回 `[ZD, ZG]`，也不改判，不把這筆補進已結束的中樞。已結束的中樞不重新打開。這筆仍用拉長後的區間去跟後面的新筆湊下一個中樞。
  - 若被換的是緩衝裡、尚未成為成員的筆：只更新它自己的區間。已經因為 `ZG <= ZD` 丟掉的那一筆算已消費，不撿回來，也不重測那個已失敗的三筆組合。等下一筆 `new` 再湊。丟掉只移走中樞的消費指針，這筆仍留在 `bis`。

`high`／`low` 的掃描區間是閉區間 `[起點合併 K 的 raw_start, 終點分型的 k_index_mid]`，再與起終價格取 max／min。

`structure_bias` 的五條順序不要換：先 `BREAKOUT_UP`、`BREAKOUT_DOWN`，再兩段下降筆終點抬高為 `UP`，兩段上升筆終點降低為 `DOWN`，否則 `NEUTRAL`。比較的是 `end_price`，不是 `bi.low`。

夾具的 K 線都是 `open = high = low = close`，`volume = 1`，`min_bi_bars = 2`。正式預設仍是 5。`open_time = 2024-01-01T00:00:00Z + 15 分 * index`。

這一步的測試：

- 六根包含樣本的合併高低是 `[12, 20]`、`[21, 25]`、`[23, 30]`。
- `golden_bi_machine` 只有上升 3→8（18→60）與下降 8→12（60→28）。
- `golden_zs_zd_frozen`：索引 11 的 ZG／ZD 是 50／34，GG／DD 是 60／30；索引 13 的 ZD 仍是 34；索引 15 的 `structure_bias` 是 `BREAKOUT_DOWN`。價格是 `50,60,50,40,30,37,44,50,44,38,34,37,33,36,40,33`。頂 11＝37 在索引 12 確認，頂 14＝40 在索引 15 確認；兩支的 `raw_between` 都小於 2，被忽略，仍在 `snapshot.fenxings`，不是筆端點。這一步不斷言信號。
- `golden_zs_outside_stays_out`：`golden_multi_zs` 的 42 根再接 `59, 55, 58, 60, 64, 62, 60, 58, 61`。索引 44 把 37→40 拉成 37→43、低點 55 落進 ZS2 的 `[52, 56]` 之後，ZS2 的最後成員仍是 34→37。索引 50 由 37→43、43→46、46→49 創建 ZS3，ZG／ZD 是 64／58。不准把 37→43 或 43→46 補進 ZS2。
- 四個區間 `[10, 20]`、`[10, 30]`、`[25, 30]`、`[25, 40]`：第三個進來時不產出中樞，第四個進來時 ZG／ZD 是 30／25。緩衝不能在交集為空時被清空。
- `golden_zs_drop_no_revive`：價格 `15, 20, 17, 13, 10, 17, 24, 30, 28, 26, 25, 27, 18, 22, 24`。索引 11 丟掉 1→4 之後沒有中樞。索引 13 把 7→10 拉成 7→12 之後仍沒有中樞，`structure_bias` 是 `UP`。1→4 仍在 `bis`。不准撿回 1→4 做出 ZG／ZD 20／18 或 `BREAKOUT_UP`。這一步不斷言信號。
- 同一輸入兩次，`snapshot_id` 相同。
- `segment_enabled=false` 時 `segments == []`。
- 視窗起點：長度至少 2N 的合成序列，同一個 `as_of` 餵 N 根與 2N 根，只記錄 `structure_bias` 與活動中樞 `(ZG, ZD)` 的一致根數。不設最低一致率。不要用 42 根的 `golden_multi_zs` 充當這支。

這一步不要發買賣點。換端點的測試只斷言筆與中樞。

## PR-6 二買、三買與對稱賣點

在 PR-5 的同一個 `for fx` 迴圈裡發信號。不要等走訪結束再看最終筆清單。

檔案：`src/chanedge/chanlun/signals.py`，以及

```text
tests/fixtures/golden_multi_zs.json
tests/fixtures/golden_third_buy_no_reemit.json
tests/fixtures/golden_second_buy_reemit.json
tests/chanlun/test_signals.py
```

`ENGINE_VERSION` 在這一步補上信號那三句，讓版本字串和行為一起變。

怎麼寫 `apply_signals`：

手上要有一張「已經發出的回離身份」表，鍵是 `(related_zhongshu_id, 回離第一根外側收盤的 open_time)`。還要有「這條筆已經發過哪一種信號」的記錄，因為舊信號要改 `related_bi_id`。

一筆 `new` 的下降筆：

1. 若活動中樞的當前回離向上，而且這是該回離的第一筆下降筆，且 `low > ZG`：發 `THIRD_BUY`。形態像二買也只發三買。
2. 否則若 `L1 > L0`，且這筆不是已發出的三買回檔，且（沒有活動中樞，或 `L1` 不大於 ZG）：發 `SECOND_BUY`。
3. 第一筆回檔的 `low <= ZG` 時，這個回離不再嘗試後面的下降筆。

一筆 `replace`，終點變得更低：

- 若這條筆已經有三買：不新增信號。那筆舊信號除 `related_bi_id` 外全部欄位照抄，包含 `defending_fx_id`、`price`、`bar_open_time`、`prior_extreme`、`notes`。
- 若還沒有三買，而且三點仍成立（新 `L1 > L0`、不是三買回檔、沒有活動中樞或新 `L1` 不大於 ZG）：再發一筆 `SECOND_BUY`，防守價是新的 `L1`。舊的那筆同樣只改 `related_bi_id`。沒有次數上限，不要加設定鍵。
- 有活動中樞且新 `L1` 仍大於 ZG：走三買規則，不把失敗的三買降級成二買。

賣點是鏡像。三賣的回離身份用「第一根收盤低於 ZD 的 open_time」。二賣再發時新 `H1` 仍嚴格小於 `H0`，且沒有活動中樞或新 `H1` 不小於 ZD。

信號的 `time` 是確認棒的 `close_time`。`price` 是該根收盤。`defending_price` 是當時的端點價。id 用 `sig:` 那條公式，所以時間與防守價不變時 id 不變。

`golden_multi_zs` 的 42 個價格與 17 列期望，逐列從架構稿 §5.6 的表抄進 JSON。沒有列出的索引沿用上一列的活動中樞與 bias，信號為無。測試不得只斷言索引 23、34、41。索引 34 的 bias 是 ZS1 的 `BREAKOUT_UP`。索引 35 是 `SECOND_BUY`，防守價 54，`prior_extreme` 52。一買與三賣都沒有輸出。ZS1 是 50／32，ZS2 是 56／52。

`golden_third_buy_no_reemit` 把 `59,57,60,63` 接在那 42 根後面：

| 索引 | 期望 |
| --- | --- |
| 41 | `THIRD_BUY`，防守價 58，序列延長後仍是這筆 |
| 42 | 無。頂 41 被忽略 |
| 43 | 無。沒有新確認的分型 |
| 44 | 無。終點改成 57，沒有第二筆三買，也沒有二買 |
| 45 | 無 |

索引 44 與 45 的 `signals` 裡仍有索引 41 那筆，`related_bi_id` 指向拉長後的筆，其餘欄位與索引 41 當下相同。

`golden_second_buy_reemit` 用 `golden_zs_zd_frozen` 的前 14 根，索引 0 到 13，價格到 36。JSON 不能寫註解，改成一個 `description` 字串欄位，寫明 L0 是 30、舊 L1 是 34、新 L1 是 33。

| 索引 | 期望 |
| --- | --- |
| 11 | `SECOND_BUY`。L0 30、L1 34，防守價 34，`prior_extreme` 30 |
| 12 | 頂 11＝37 確認，距離不足被忽略，仍在 `snapshot.fenxings`。沒有信號 |
| 13 | 底 12 把終點換成 33。沒有活動中樞。再發一筆 `SECOND_BUY`，防守價 33，`prior_extreme` 30。索引 11 那筆仍在，防守價仍是 34 |

這一步不要寫特徵、分數、口數。

## PR-7 六通道特徵

`FeatureBuilder.build(context) -> FeatureVector`。簽名只有 context。不讀持倉，不呼叫交易所。

檔案：`src/chanedge/features/` 六個通道各一個模組，加 `builder.py`、`version.py`。測試在 `tests/features/`。

怎麼寫：

1. 每個通道回傳原始欄位、子分數、懲罰。欄位名用架構稿 §5.8 的表，不要合併成一個總分就算交差。
2. ATR 是 Wilder，週期用設定的 `atr_period`。相對成交量的分母是前 20 根成交量的中位數。`atr == 0` 時比值記 0。
3. 無活動中樞：`clarity_term = 0.5`，raw 含 `zhongshu_absent`。不要記 0。
4. 二買、二賣的位置項用 `dist_defending_atr`。不要改去量 L0／H0。
5. `prior_high` 是信號分型之前、最近一筆已確認上升筆的終點價。`prior_low` 是鏡像。兩者都不包含信號分型自己。沒有前高時距離留空，`room = 0`，不套 0.20 的靠近扣分。前高存在時，`dist_prior_high_atr = (prior_high - price) / atr`，照實寫，可以是 0 或負數。不要改成「只有不高於價格才記 0」。前低同理。
6. 波動 tent：信號之前、該幣自己的 `atr_pct` 樣本數 `>= min_samples` 時，峰是 p50，寬度是 `max(p90-p50, p50-p10, 1e-6)`。樣本不夠時 `vol_tent = 0.5`，raw 含 `vol_center_absent`，這不是 `VOL_BAND`。帶外時 `vol_tent = 0`，否決留給 PR-9。
7. 多空共用一條公式的通道是結構、波動量、時段。位置、共振、信號 K 線維持架構稿裡的空方公式。不要為了「對稱」把空方改成把多方公式乘負號。

測試要斷言這個模組的 import 圖不含 `risk` 與 `execution`。再斷言：無中樞清晰度 0.5；沒有前高時不扣 0.20；樣本數 199 時 tent 是 0.5 且沒有把帶外旗標設上。

## PR-8 JEV 加權評分

只依賴 PR-2。可以和 PR-3、PR-5、PR-9、PR-10 並行。`JevModel(params).assess(features) -> JevAssessment`。`params` 在建構時由 `app` 從設定收成 `domain` 的物件傳入。這個模組不 import `config`。`calibrated` 固定 `False`。不讀硬規則，不改口數。

怎麼寫：

1. 複合分是六個通道 `adjusted * weight` 的和。權重用建構時傳入的參數，不在這裡寫死 0.24 那些數字。
2. 懲罰先打在該通道的子分數上，再進加權。共振用過的布林不要在別的通道再加一次。
3. 未校準機率照架構稿 §5.8 的線性公式，不是 softmax：

```text
z_buy  = max(S_buy, 0) / temperature
z_sell = max(S_sell, 0) / temperature
z_hold = hold_bias
p_*    = z_* / (z_buy + z_sell + z_hold)
```

`temperature` 與 `hold_bias` 必須大於 0。Phase 1 不下單時不讀這個機率。`hold_bias` 只出現在 `z_hold`。

4. `proposed_action`：多頭候選且 `composite >= enter_threshold` 就是 `BUY`。空頭候選且複合分 `>= enter_threshold` 就是 `SELL`。否則 `HOLD`。等於 0.62 也是進場。`hold_bias` 不參與這個比較，也不要求比另一方高出一截。多方公式與空方公式不要同時給出非零的進場分；測試用一組特徵讓一邊為正時另一邊是 0。
5. `reason` 列出每個通道的貢獻，方便日誌。不要只留一個總分。

測試：複合分剛好 0.62 時動作是 `BUY`。權重和不是 1 的設定在 PR-1 已經拒絕，這裡不用再測載入。

## PR-9 硬閘門

只依賴 PR-2。測試用假的 `JevAssessment`，不等 PR-8。`RuleGate.evaluate(context, assessment, account, safety) -> HardRuleResult`。收集全部否決。不改分數，不決定口數。

測試用假的 `JevAssessment` 與 `AccountView`，不啟動引擎。

怎麼寫。`evaluate` 的簽名沒有 `FeatureVector`，所以不讀 `candidate_signal_id` 與 `ambiguous_signal_ids`，也不重數三類與二類。`FeatureBuilder` 仍負責同一方向只留一個、三類優先於二類，以及同一根買賣同時出現時清空候選。

這根 15m、`time == decision_time`、同時有操作型買與賣（二買、三買、二賣、三賣；一買與一賣不算）時，候選類否決是 `AMBIGUOUS_SIGNAL`，即使 `candidate_side` 被填了也不改判，而且不要同時放 `NO_CANDIDATE`。否則 `candidate_side` 是 `LONG` 或 `SHORT` 才是唯一候選。再不然才是 `NO_CANDIDATE`。`time` 不等於 `decision_time` 的 `CONFIRMED` 不當候選。

無候選與同時買賣：先 `STALE_DATA`、`GAP_DATA`、`INSUFFICIENT_HISTORY`，再放那一個候選碼，然後返回。不檢查方向、1H、波動帶、時段、持倉、kill switch，也不記 `OUTSIDE_UNIVERSE`。可以另有 `STALE_DATA`。不能有 `PIPELINE_TIMEOUT`。

有唯一候選時，順序照架構稿 §6 的 1 到 10 條一次回傳：`KILL_SWITCH`、`STALE_DATA`、`GAP_DATA`、`SESSION_SKIP`、`HTF_DIRECTION`、`MTF_1H_CONFLICT`、`VOL_BAND`、`OUTSIDE_UNIVERSE`、`INSUFFICIENT_HISTORY`、`POSITION_OPEN`。類型那一條沒有否決碼。`KILL_SWITCH` 只在做多且提議 `BUY`，或做空且提議 `SELL`。`HOLD` 不加。

`atr_pct` 與時段 bucket 讀評估分量裡已經算好的原始值。帶界、`hard_skip_buckets`、三個週期的已收盤根數視窗，用建構時傳入的 `RuleParams`，不在閘門裡寫死 YAML 數字。不重算 tent。樣本數少於 `min_samples` 不是否決。資金費率窗口不是否決。過期只讀 `data_quality.stale`。缺口只認理由裡的 `gap_data`，不把 `missing_bar_count > 0` 當成缺口。回測時鐘不產生 `STALE_DATA`。這個函式不產生 `PIPELINE_TIMEOUT`。

分數已經是 `HOLD` 時，不加「分數不夠」這種 veto。`passed` 可以為真。呼叫端（PR-10、PR-11）看到 `HOLD` 就不呼叫 `plan_entry`。閘門不改分數，不決定口數。

`universe_rank is None` 只在有唯一候選時是 `OUTSIDE_UNIVERSE`。正常出場組不會呼叫這個函式。測試仍要能在有人誤送時回傳這個碼。

高分且 4H 為反向時，`passed` 是假，`HTF_DIRECTION` 在清單裡。共振的 `htf_gate_would_pass` 不寫回分數。

## PR-10 風險

只依賴 PR-2。`ChanSignal` 與 `HardRuleResult` 用 `domain` 裡的型別手工建構，不等 PR-6 與 PR-9。

`plan_entry` 與 `review_open`。`review_open` 的參數沒有 `JevAssessment`，也沒有 `FeatureVector`。

檔案：`src/chanedge/risk/size.py`、`stops.py`、`review.py`。

`plan_entry` 的拒絕順序寫成提早返回，不要先算完全部再挑一個碼：

順序照架構稿 §6 的公式抄，不要自己重排：

```text
1. price_tick、qty_step、min_qty 缺值或不是正數 → INSTRUMENT_SPEC。cost_r 留空
2. 已開倉數達到 max_open_positions → MAX_OPEN_POSITIONS。cost_r 留空
3. 同方向已達 max_same_direction → MAX_SAME_DIRECTION。cost_r 留空
4. stop_dist、equity_quote 或 entry_reference 不是正數 → RISK_CAP。cost_r 留空
5. 算出 cost_r = round_trip / (stop_dist / entry_reference)。cost_r > max_cost_r → COST_R，寫上 cost_r
6. 風險口數 < min_qty，或 min_notional 有值且名義不夠 → RISK_CAP。這時 cost_r 已經算出，要寫上
7. 再看單筆名義與有效合計名義
   單筆上限 = min(max_notional_quote, equity * max_leverage)
   gross_cap = min(max_gross_notional_quote, equity * max_leverage)
   縮到下限之下才分別是 MAX_NOTIONAL 或 MAX_GROSS_NOTIONAL。cost_r 寫上
```

不要產生 `MIN_QTY`。`COST_R` 發生時不要改停損價。口數用 `floor` 到 `qty_step`。停損價用 `price_tick` 往遠離進場的方向取整。

`entry_reference` 是信號收盤。`atr` 從 `FeatureVector` 抄，不另算一套。`stop_buffer = stop_buffer_atr * atr`，進場時凍結。

`cost_r = round_trip / (stop_dist / entry_reference)`，`round_trip = 2 * (fee_bps + slippage_bps) * 1e-4`。預設 5 bp 與 1 bp 時，`round_trip` 是 0.0012。停損窄於價格的 0.30% 就會超過 0.40。

通過時寫 `target_risk_fraction`、`realized_risk_fraction = qty * stop_dist / equity_quote`、`binding_constraint`。綁定名稱：合計名義有縮小則 `max_gross_notional`；否則單筆上限有縮小且較緊的是槓桿則 `max_leverage`；單筆上限有縮小則 `max_notional`；都沒有則 `risk_fraction`。

`review_open` 只產出下一根開盤的整筆 `EXIT`，以及 `AmendStop`。不產出盤中成交。盤中停損與 TP1 是 PR-11 撮合器的事。

出場條件照架構稿 §5.7 的價位表，多空都要寫。忽略 `open_time` 早於 `entry_bar_open_time` 的 K 線，也忽略 `signal.time` 不大於 `entry_decision_time` 的反向信號。

TP1：多單只看信號棒當時已經確認的最後一個上升筆端點。沒有這個端點，或它不高於 `entry_reference`，就用 `entry_reference + 1.5 * R`。不要往更早的上升筆找一個更高的端點。空單只看最後一個下降筆端點；沒有，或該低點不低於 `entry_reference`，就用 `entry_reference - 1.5 * R`。只讀筆端點。

棘輪：多單只在「這根新確認了一筆下降筆的終點，且該價格高於目前止損」時上移。終點被更低的分型取代，不為多單棘輪。空單鏡像。緩衝用凍結的 `stop_buffer`，不讀當根 ATR。

武裝：多單看當根 `high` 是否達到 `entry_reference + arm_r * R`。不要求收盤留在有利側。`arm_r` 用設定，預設 1.0。

整筆 `EXIT` 時不要同時留 `AmendStop`。

測試用架構稿裡的數字鎖住：權益 10000、停損佔價格 0.34% 時名義約 14706，綁定 `risk_fraction`。停損 0.20% 時 `COST_R`，到不了 20000。權益 5000、槓桿 2 時有效合計是 10000。權益 1000 時單筆與合計都是 2000。`passed=true` 但 `proposed_action=HOLD` 時，上層測試斷言 `plan_entry` 沒被呼叫；這個斷言放在 PR-11 的管線測試，PR-10 自己測試「直接呼叫」的行為即可。

## PR-11 管線、撮合、回測

這一步把前面的純函式串成一次決策，並擁有撮合。`backtest/loop.py` 以參數接收 `run_pipeline`、時鐘、`Broker`、K 線來源、榜單來源與報告寫入埠。決策順序只來自 `run_pipeline`。三個資料埠的協定在 `domain`，由 `app` 傳入 `marketdata` 與 `journal` 的實作。迴圈不 import `app`、`marketdata`、`journal`。K 線來源讀已落盤的 Parquet，不經 `MarketDataPort.fetch_closed_bars` 打交易所。報告寫入埠寫 `data/reports/{run_id}/`，含 `journal.sqlite` 與 parquet 報告；不寫 `data/chanedge.sqlite`，也不是 `PaperBroker` 的帳簿埠。紙交易的記帳在 `PaperBroker`，它接收帳簿埠，由 `app` 傳入 `journal`。成交價規則只寫在這裡。`fills`、`positions`、`accounts` 同一筆交易更新。

檔案：

```text
src/chanedge/app/pipeline.py          # run_pipeline
src/chanedge/backtest/matcher.py      # 純函式
src/chanedge/backtest/loop.py
src/chanedge/backtest/report.py
src/chanedge/execution/port.py        # Broker 協定
src/chanedge/execution/paper.py       # 只記帳、只排隊 next_open
tests/backtest/
```

`run_pipeline` 由呼叫端傳進來，回測迴圈不 import `app`。函式內部的順序固定。先分出場組。參數 `full_log`：回測傳假，紙交易傳真。函式不讀 `Settings`。1H／4H 的沿用發生在呼叫 `compute` 之前，`compute` 自己不讀上一張快照。`as_of` 是該週期最後一根的 `close_time`。

```text
15m 快照 = ChanEngine.compute(15m 視窗)
1H、4H：as_of 與 bar_window_hash 和上一張相同就沿用，否則 compute
若是出場組：
    仍算 features 與 JEV，只為日誌
    只呼叫 review_open。不呼叫 RuleGate，也不呼叫 plan_entry
    寫完整列
否則若是回測，而且沒有 15m 候選、ambiguous 也是空的：
    不跑 FeatureBuilder，不跑 JEV，不算 snapshot_id
    寫精簡 HOLD。hard_rule 是 NO_CANDIDATE，加上 context 裡已有的資料品質碼
否則：
    features = FeatureBuilder.build(context)
    assessment = JevModel(params).assess(features)
    rules = RuleGate.evaluate(...)
    閘門不重數候選：唯一候選看 candidate_side；同一根同時有操作型買賣則是 AMBIGUOUS_SIGNAL
    若 rules 未過，或 proposed 是 HOLD：決策 HOLD，不呼叫 plan_entry
    否則 plan = plan_entry(...)
    若 plan.rejected：決策 HOLD
    否則排隊 next_open 進場
    寫完整列
紙交易不走精簡那條
```

每個幣種、每根 15m，呼叫端保證最多進來一次。這個函式自己不要迴圈掃宇宙。

撮合器 `match_bar` 是純函式。輸入是部位、待成交單、這根 K 線、費用與滑價。輸出是成交清單。回測迴圈呼叫它；之後的 `paper_loop` 也呼叫同一份。`execution/paper.py` 不計價、不寫停損價，只記帳與排隊。`execution` 不能 import `backtest`。

```text
步驟 1，bar_seq = 0，fill_time = 本根 open_time
    上一根留下的 next_open，全部在本根開盤加不利滑價
    同一 fill_time：出場先於進場，其後用上一根的組序
    這張出場單若把部位平掉，它就是該部位本根的唯一成交
步驟 2，bar_seq = 1，只有步驟 1 沒把部位平掉才做
    盤中停損優先於 TP1
    多單：開盤已 <= stop 則成交在開盤，否則 low <= stop 則成交在 stop，再加不利滑價
    空單用 high，滑價向上
    TP1 是 REDUCE。停損是整筆 EXIT
    同一部位本根至多一張出場單
```

`exit_reason` 在停損成交時分類：

- 止損仍是進場時的結構停損：`structure_stop`
- 止損等於 `entry_reference`，而且武裝那根的收盤在有利側：`breakeven_stop`
- 止損等於 `entry_reference`，而且武裝那根的收盤已在不利側：`breakeven_adverse`。看武裝那根，不看出場那根
- 止損已經比 `entry_reference` 更有利：`ratchet_stop`

回測時鐘只在 15m 收盤前進。第一根決策是 `universe_date` 等於 `history_start` 的第一根 15m 收盤。`refresh_minute` 預設 5 時，就是 `history_start` 00:15（`open_time` 為當天 00:00 的那根）。當天 00:00 的 `universe_date` 是前一天，重建又沒有寫前一天，所以不從 00:00 起跑，也不多補前一天的榜。暖機起點仍是 PR-3 的 `download_start`。00:15 時，最後一根已收盤的 4H 仍是 00:00 收盤的那根。開跑前，從這根起實際會走到的每個 `universe_date` 都要有檔，缺一就退出，錯誤訊息指向 `universe --reconstruct`。不要改用 `pin`，也不要把缺檔日跑成全員無排名。`universe_date = (decision_time - refresh_minute 分鐘).date()`，UTC。

`run_id` 含 `config_hash`、三個版本、資料視窗、`started_at` 到秒。報告寫到 `data/reports/{run_id}/`，含 `journal.sqlite`、`trades.parquet`、`shadows.parquet`、`equity.parquet`、`timing.json`。`run_id` 超過 96 字時，目錄名改成短名：`run_id` 前 16 字、整個 `run_id` 的 sha256 前 16 個十六進位字元、`run_id` 最後 41 字（資料視窗與 `started_at`），以 `_` 相接。完整 `run_id` 寫在該目錄的 `run.json`。不拆成多段路徑：真實版本字串讓 `run_id` 超過 800 字，SQLite 在 Linux／macOS 上拒絕超過 512 位元組的資料庫路徑。架構稿仍把目錄寫成 `data/reports/{run_id}/`，指的是這個目錄。不寫 `data/chanedge.sqlite`，不寫 `chart_frames`。報告庫連線後設 `synchronous=OFF`。同一根 15m 的全部幣種一次提交。紙交易庫維持 WAL，不設 `synchronous=OFF`。`trades.parquet` 加 `funding_estimate_quote`，算法見架構稿 §7，不進現金。`timing.json` 寫 `elapsed_ms`、`decision_count`、`mean_decision_ms`。開跑前每個要用的榜單檔都要能解析；解析失敗就退出，不自動覆寫。

影子：進場組裡每一個有唯一 15m 候選的決策都寫一列，`shadow = true`，包含被 veto 和被風險拒絕的。`NO_CANDIDATE` 與 `AMBIGUOUS_SIGNAL` 不寫。影子不改現金與持倉。幣掉出榜單且真實倉已平之後，未結束的影子仍留在計算集合，直到自己的出場。

同一 `decision_time` 的多幣順序：先步驟 1 與 2，再出場組（掉榜的字母序，然後榜內持倉的名次），再進場組（名次）。本根已平倉的幣寫 `HOLD`，原因 `FLATTENED_THIS_BAR`，不呼叫 `plan_entry`。

重放排序鍵是 `(fill_time, bar_seq, 出場先於進場, 組序)`。不要用 `fill_id` 排序。

報告至少累計：按信號類型的終點被取代比例、同一條下降筆的二買再發次數、`inside_low_broke_prior_end`、`overlap_term` 平均與大於 0.85 的比例、按幣的 `COST_R`、`instrument_source = inferred` 的成交筆數、`INSTRUMENT_SPEC` 筆數。回測不產生 `PIPELINE_TIMEOUT`。

這一步的測試用合成 K 線與假榜單，不打外網：

- 收盤反向信號之後，下一根開盤仍在停損上方、最低價跌破停損：只在開盤價加滑價出場一次。
- 進場那根開盤穿停損：先寫進場（`bar_seq = 0`），再寫出場（`bar_seq = 1`）。
- 武裝那根的 high 觸及 `+1R` 但收盤低於 `entry_reference`，下一根開盤跌破進場價：`exit_reason` 是 `breakeven_adverse`。
- 已有 3 筆持倉時第 4 個幣被拒。同方向第 3 筆被拒。掉榜持倉不能再加倉。
- 兩次相同版本的 `decision_id` 一致，`run_id` 不同。
- 現金例子：10000 買 1 單位於 100、賣於 110、費用 5 bp、滑價 0，平倉後現金 `10009.895`。

不要寫 `LiveBroker`。kill switch 為真時，非 `reduce_only` 的 `submit` 失敗；既有多單的停損仍成交。

## PR-12 CLI 與紙交易迴圈

把 PR-3 與 PR-11 接成四個命令。決策順序不再寫一次。

檔案：`src/chanedge/app/cli.py`、`paper_loop.py`、`compose.py`，測試 `tests/app/test_compose.py`、`test_restart.py`。

命令：

| 命令 | 行為 |
| --- | --- |
| `chanedge download` | 讀範圍內榜單檔出現過的符號，抓 vision 的 15m、1h、4h 與 fundingRate 月檔，含已下架名字，起點是 PR-3 的 `download_start` |
| `chanedge universe` | 當天已收盤日 K。今天的檔已經存在，不論 `source` 是什麼，都不寫。不存在才寫，`source: daily_kline` |
| `chanedge universe --reconstruct` | 只補 `history_start` 到終點之間尚不存在的日期 |
| `chanedge backtest` | 注入時鐘、`Broker`、K 線來源、榜單來源與報告寫入埠，呼叫 PR-11 的迴圈 |
| `chanedge paper` | 睡到下一根 15m 收盤，再等 `close_wait_seconds`。`mode=paper` |

`compose` 在 `mode=paper` 時建立的 ccxt 不讀 `CHANEDGE_API_KEY` 與 `CHANEDGE_API_SECRET`。測試用一個會在被讀時失敗的環境，斷言這兩個名字沒被讀到。同時斷言紙交易路徑沒有呼叫 `create_order`。`mode=live` 直接失敗。

`paper_loop` 一輪的順序：

0. 預期的 15m 收盤時刻到了之後，先等 `marketdata.close_wait_seconds`（預設 3）。再抓 K 線。最後一根已收盤 15m 的 `open_time` 必須是預期那根。還不是就再等、再抓，直到是，或已經落入 `STALE_DATA`。回測不等這幾秒。這個鍵不進 `config_hash`。
1. 若今天的榜單檔不存在，寫當天檔。已經存在就不寫，不論 `source` 是 `daily_kline`、`reconstructed` 或帶 `fallback_from`。日 K 失敗且昨天的檔在、而且今天的檔還不存在，才把昨天的名次抄過來，標 `fallback_from`，`source` 沿用被抄的那份。不要改打 ticker。手動 `chanedge universe` 用同一條，不准蓋掉當天的沿用檔。寫入走 `*.tmp` 與 `os.replace`。
2. 一天的檔都沒有，而且沒有持倉：不開始。有持倉但當天檔不存在：仍跑出場。
3. 對今天仍在 `exchangeInfo` 的幣補 K 線。Parquet 沒有列時，往前補滿最長視窗。已有列時從最後一根 `open_time`（含）重抓，丟掉未收盤的那根。已下架的幣不走 REST，用 `download` 先寫好的 vision Parquet。
4. 先對全池做步驟 1 與步驟 2，呼叫 `backtest.matcher`。
5. 出場組，再進場組。每個幣至多一次 `run_pipeline`。
6. 牆鐘從這根的幣種迴圈開始。輪到某幣時若已超過 60 秒：不呼叫 `run_pipeline`，寫一筆 `HOLD`，`hard_rule_json` 只有 `PIPELINE_TIMEOUT`。不另記 `NO_CANDIDATE` 或 `STALE_DATA`。已經跑完的單仍送出。回測命令不走這道牆鐘。
7. 仍該留在畫面上的幣，每個週期覆寫一筆 `ChartFrame`，含 `last_action`。平倉且掉榜的幣刪除三個週期的幀。寫圖失敗只記錯誤，不改委託。

重啟：啟動時 `load_open_positions()` 與 `load_pending_orders()`。`test_restart` 用 `pin` 清單。兩筆斷言都要有：某幣有未平倉時，重啟後下一根不得再進該幣；獲利平倉後重啟，下一筆 `plan_entry` 的權益是 `10009.895`。

structlog 的 JSON 行在 `event=decision` 時帶 `symbol`、`rank`、各段延遲。處理器丟棄 `CHANEDGE_API_KEY` 與 `CHANEDGE_API_SECRET`。

對帳：有紙交易庫時，用 vision 把同一段重跑回測，比對 `decision_id` 集合。差集分成只在紙交易、只在回測。`PIPELINE_TIMEOUT` 與 `STALE_DATA` 另列，不算策略分歧。其餘寫進 `data/reports/{run_id}/reconcile.json`。

這一步仍不包含實盤下單、第二交易所、Telegram、繪圖網頁。

## PR-13 唯讀圖形監控

Phase 2。依賴 PR-12 已經在寫 `ChartFrame`。

檔案：`src/chanedge/monitor/`，測試 `tests/monitor/test_reads_frames.py`。

怎麼寫：

1. 實作前打開 `lightweight-charts` 的 LICENSE，確認 Apache-2.0 與架構稿一致再釘版。核對結果寫進 PR 說明，不寫進交易邏輯。
2. `chanedge monitor` 只綁 `127.0.0.1:8765`。不聽 `0.0.0.0`。
3. 只讀 SQLite 的 `chart_frames`。K 線用幀裡的 `bars`，不讀 Parquet。不 import `chanlun`、`jev`、`execution`。測試用 import 圖鎖住。
4. 畫 K 線、筆、中樞、買賣點、停損、六通道。左欄的最後動作讀 `ChartFrame.last_action`。
5. 幀不存在時顯示「尚無幀」，畫面不呼叫 `ChanEngine`。
6. 沒有下單路由。已刪除的掉榜平倉幀不會留在清單。

## 寫的時候最容易偏掉的地方

這些句子在架構稿裡已經鎖定。實作時用測試守住，不要在重構時改掉。

- 信號在走訪中第一次合格時寫下。最終筆清單只用來畫圖與算特徵，不用來重發三買。
- 創建中樞的 ZG／ZD 在第三筆確認的那一根凍結。其後的 replace 只動 GG、DD、`end_time`、筆 id。
- 確立時在外側的筆，拉長後也不改判。已結束的中樞不重新打開。
- `ZG <= ZD` 時丟掉最早一筆，保留後兩筆。丟掉的已消費，拉長後也不撿回。不要清空緩衝。這筆仍留在 `bis`。
- 舊信號除 `related_bi_id` 外不變。`defending_fx_id` 可以指向已經不是筆端點的分型。
- 二買再發沒有上限。Phase 1 不加設定鍵。
- 候選由 `FeatureBuilder` 決定。閘門只讀 `candidate_signal_id` 與 `ambiguous_signal_ids`，不自己重數。
- 出場組在 `RuleGate` 之前就分開。JEV 不決定出場，也不決定口數。
- 撮合在 `run_pipeline` 之前。同一部位一根 K 線只有一筆出場。停損優先於 TP1。
- `download` 的 K 線早於 `history_start`。回測第一根決策是 `history_start` 00:15。
- 今天的榜單檔已經存在，不論 `source`，都不寫。
- 小數推估在 `marketdata_version`。纏論規則在 `engine_version`。
- `enter_threshold` 0.62，比較是 `>=`。`hold_bias` 只做 `z_hold`。機率是線性三元組。六個權重、`arm_r` 1.0、`overlap_peak` 0.35、`max_cost_r` 0.40、`min_bi_bars` 正式值 5，都不在實作時改。夾具裡的 `min_bi_bars = 2` 只活在夾具。
- TP1 只看最後一個筆端點。不夠高或不夠低就用 1.5R。
- `accounts` 在 migration 001。`decision_id` 在 `domain/ids.py`。
- 回測的 K 線、榜單與報告都經 `domain` 的埠。`backtest` 不 import `marketdata` 或 `journal`。決策順序只來自 `run_pipeline`。
- `as_of` 是該週期最後一根的 `close_time`。1H／4H 視窗沒變才沿用。`compute` 不讀上一張快照。出場組不走精簡列。
- 榜單與 Parquet 用 `*.tmp` 再 `os.replace`。半截正式檔不算「已存在的有效檔」，也不要自動覆寫。
- `funding_estimate_quote` 不進現金。`close_wait_seconds` 不進 `config_hash`。報告庫才設 `synchronous=OFF`。
- `decision_id` 的七個欄位是規範化 JSON 陣列，不是把字串接起來。時間是 `YYYY-MM-DDTHH:MM:SS.mmmZ`。有時區但不是 UTC 的先轉 UTC。
- 凍結模型的序列用 `tuple`。`Bar` 載入時建一次，視窗用切片。不用 `model_construct`。`float` 轉 `Decimal` 用 `Decimal(repr(x))`。`Decimal` 與浮點都用八位小數。格式化後的 `-0.00000000` 改成 `0.00000000`。`Bar.low > 0`，負成交量拒絕，成交量 0 仍合法。
- 距離不足被忽略的分型仍在 `snapshot.fenxings`。`golden_zs_zd_frozen` 的頂 11 與頂 14 不是筆端點。

## 做完 Phase 1 的對照

架構稿 §11.1 的完成定義，就是 PR-12 合併前要同時為真的那一組測試：同一份榜單檔回測兩次，`decision_id` 序列一致；假日 K 濾完是 20 名，穩定幣基幣不在其中；缺一日榜單就拒絕啟動；`golden_third_buy_no_reemit` 的索引 44 沒有第二筆三買，索引 41 的防守價仍是 58；`golden_zs_zd_frozen` 的索引 13 仍是 ZD 34，索引 15 是 `BREAKOUT_DOWN`；`golden_zs_outside_stays_out` 的索引 50 有 ZS3，ZG／ZD 是 64／58，ZS2 的最後成員仍是 34→37；`golden_zs_drop_no_revive` 的索引 13 沒有中樞，`structure_bias` 是 `UP`；`golden_second_buy_reemit` 的索引 13 再發二買、防守價 33，索引 11 的防守價仍是 34；回測第一根是 `history_start` 00:15，不要求前一天的榜；高分但 4H 為 `DOWN` 沒有訂單；分數剛好 0.62 是 `BUY`；三買樣本有結構止損與六通道日誌；第 4 筆持倉與第 3 筆同方向被拒；`cost_r` 超過門檻被 `COST_R` 拒絕；推不出 tick 被 `INSTRUMENT_SPEC` 拒絕；掉榜持倉只出場；視窗未滿是 `INSUFFICIENT_HISTORY`。
