# 地圖與職責

匯入路徑是 `chanedge.*`。`src` 只為了打包。規格上的目錄在架構稿 §5.1，允許的依賴方向在 §5.2。底下是倉庫裡實際有的檔。§5.1 多出來、而樹上還沒有的，只表示那個 PR 還沒做。

## 倉庫頂層

```text
ChanEdge/
  pyproject.toml          # 依賴、chanedge 入口、pytest 的 pythonpath=src
  config/default.yaml     # 整份預設。數值以架構稿 §11.4 為準
  config/paper.yaml       # 只蓋 runtime.mode=paper 與 safety.kill_switch=false
  docs/ARCHITECTURE.md    # 行為與數字
  docs/IMPLEMENTATION.md  # 步驟
  docs/agents/            # 本導覽，不是規格
  src/chanedge/           # 程式
  tests/                  # 測試與 fixtures
  .venv/                  # 本機虛擬環境，不要裝進系統 Python
  data/                   # gitignore。Parquet、SQLite、報告。不一定存在
```

`paper.yaml` 的註解寫明遞迴合併必須留下 `runtime.venue` 與其餘沒寫到的欄位。

## 各套件負責什麼

禁止欄以架構稿 §5.2 的表為準，這裡不另寫一份。執行期依賴由 `tests/test_boundaries.py` 鎖住。想讓新的 import 通過時，先改架構稿與那份允許表，不要只改允許表。

| 套件 | 現有檔 | 負責 |
| --- | --- | --- |
| `domain` | `model`、`enums`、`bars`、`records`、`decision`、`risk`、`accounting`、`chanlun`、`params`、`ports`、`ids`、`canon`、`serialize`、`systemone` | 列舉、凍結值物件、協定、id、System One 值。不做 I/O |
| `config` | `load`、`model`、`hash` | YAML 到 `Settings`，以及 `config_hash` |
| `marketdata` | `vision`、`universe`、`parquet_store`、`quality`、`ccxt_adapter`、`infer`、`port`、`version` | K 線變成 `Bar`、Parquet、缺口與過期、榜單、小數推估 |
| `chanlun` | `engine`、`include`、`fenxing`、`bi`、`zhongshu`、`signals`、`bias`、`segment`、`version` | `ChanEngine.compute` → `ChanSnapshot` |
| `features` | `builder`、`select`、`structure`、`location`、`volatility`、`signal_bar`、`session`、`resonance`、`atr`、`version` | 六通道純函數。候選在這裡決定 |
| `jev` | `model.py`、`compose.py`、`questions.py` | 本地加權 `assess`，以及 System One 答案映射。預設旗標關閉時只走本地加權。不開 HTTP，不下單，也不決定出場。見 [logic.md](logic.md) |
| `typesafe` | `__init__.py`、`cache.py`、`client.py` | JSONL 快取、排他鎖、紙交易與暖機的 HTTP 客戶端。只有這裡出現 `typesafe_sdk`。回測用只讀 `lookup` |
| `rules` | `gate.py` | 硬否決。不改分數，不決定口數 |
| `risk` | `size`、`stops`、`review` | 口數、結構止損、分批、移動停損、出場檢視 |
| `execution` | `port.py`、`paper.py` | `Broker` 協定與 `PaperBroker`。沒有 `live.py`。不重算纏論，不自己寫撮合 |
| `journal` | `schema`、`repository`、`book` | 決策、訂單、成交、持倉、現金、`ChartFrame` |
| `backtest` | `matcher`、`loop`、`report`、`shadow` | 步驟 1 與步驟 2 的撮合、回測迴圈、費用、報告、影子單 |
| `app` | `bind`、`pipeline`、`compose`、`paper_loop`、`cli`、`jev_warm` | 把設定收成領域參數、共用的 `run_pipeline`、組合根、紙交易迴圈、CLI、`jev-warm`。預檢順序在 `pipeline` |
| `monitor` | `__init__.py` 只有說明 | Phase 2 唯讀畫面。Phase 1 不啟動 |

`src/chanedge/__init__.py` 不匯入內部套件。

`run_pipeline` 放在 `app/pipeline.py`。回測迴圈以參數接收它，`backtest` 不 import `app`。紙交易迴圈呼叫同一份，也呼叫 `backtest.matcher.match_bar`。`PaperBroker` 自己不撮合，也不含滑價規則。

設定、帳簿與管線用建構時注入。`execution` 不 import `journal`。`backtest` 不 import `marketdata` 或 `journal`。K 線、榜單、報告三個協定在 `domain/ports.py`，由 `app` 傳入實作。回測讀的是已經落盤的 Parquet，不經 `MarketDataPort.fetch_closed_bars` 打交易所。報告寫 `data/reports/{run_id}/`。紙交易帳簿是 `data/chanedge.sqlite`。兩套 SQLite 分開。

## 測試對到哪

測試目錄跟套件走。沒有 `tests/**/__init__.py`。測試不互相 import，也不把 `tests` 當套件。工廠函式寫在該測試檔裡。pytest 會注入 `conftest` 的 fixture，測試檔不要 import `conftest`。

| 測試 | 鎖什麼 |
| --- | --- |
| `tests/test_config.py`、`tests/test_boundaries.py` | 設定、`config_hash`、依賴方向、CLI 入口 |
| `tests/domain/` | 值物件、id、K 線約束 |
| `tests/marketdata/` | vision、榜單、Parquet、品質、ccxt、小數推估 |
| `tests/chanlun/` | 包含、筆、中樞凍結、信號。夾具在 `tests/fixtures/` |
| `tests/features/`、`tests/jev/`、`tests/rules/`、`tests/risk/` | 六通道、評分、硬閘門、口數與出場 |
| `tests/journal/` | SQLite 結構與 `ChartFrame` |
| `tests/backtest/` | 管線、撮合、回測迴圈、紙交易 Broker |
| `tests/app/`、`tests/typesafe/` | 組合根、CLI、紙交易一輪、重啟、暖機門檻、JSONL 快取與假傳輸 |
| `tests/fixtures/*.json` | 七個 golden。期望以架構稿與這些 JSON 為準 |

`tests/monitor/` 與 `tests/execution/` 都不存在。紙交易 Broker 的測試在 `tests/backtest/test_paper.py`。`conftest.py` 只在 `tests/chanlun/`、`tests/features/`、`tests/marketdata/`。

## 規格目錄和樹上的差別

這些差別是進度，不是規格寫錯：

- §5.1 列出 `tests/monitor/`。PR-13 沒做，所以還沒有這個目錄。
- §5.1 說 Phase 1 不建立可送單的 `execution/live.py`。樹上只有 `port.py` 與 `paper.py`。
- `data/` 在 `.gitignore`。新鮮的工作目錄可以沒有它。
- `app/pipeline.py` 與 `app/bind.py` 是實作計畫把管線與參數組裝放進 `app` 的結果。§5.1 只列到套件，沒有逐檔命名。
