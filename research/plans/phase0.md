# Phase 0 計畫：研究工具（訊號快取、模擬器、驗證、紀律）

規劃者：Opus。執行者：Sonnet。日期 2026-11-03。分支 `research/phase0`。工作目錄 `/workspace/ChanEdge-research`。
原始任務：`/workspace/cc/phase0_prompt.md`（全文附在本檔末尾附錄 A，照抄）。研究鐵則：`research/CLAUDE.md`（附錄 B，照抄）。

本計畫只把 prompt 拆成步驟。**關卡數字、樣本切分、實驗上限、驗證門檻、允許/禁止修改範圍一律以原文為準**，下面「不可改動的條款」逐字照抄。執行中若發現做不到或想改其中任何一條：停下，把問題寫進報告，不要自己改。

---

## 0. 不可改動的條款（原文照抄）

- 範圍：「新程式全部放 research/，可以 import chanedge，但不要改 src/、config/、tests/ 和架構稿。」
- 鐵則 1：「不改 src/、config/、tests/、docs/ARCHITECTURE.md（架構稿）、pyproject.toml。可以 import chanedge，新程式全部放 research/。」
- 依賴：「只用 pandas、pyarrow（含其依賴 numpy）和標準庫，不加任何依賴。」
- 「research/cache/ 加進 .gitignore。」／鐵則 9：「research/cache/ 不 commit（已加進 .gitignore）。」
- 樣本切分：「research/report.py 預設只顯示樣本內（2024-01-01 → 2025-06-30）。要看樣本外必須加 --oos，每次使用都追加記錄到 research/out/oos_log.md。」／鐵則 3：「樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27。」
- 鐵則 4：「階段 1 全程不准用 --oos；research/out/oos_log.md 必須保持空的。」
- 鐵則 5：「樣本外每組只跑一次，跑完不准改參數、不准追加實驗。」
- 鐵則 6：「實驗總數上限 60 個。每次執行都要在 research/out/registry.md 追加一行（時間、實驗名、設定摘要）。」
- 訊號模式關卡：「若可行，先用整段歷史單次走訪（快）。用 3 個幣 × 3 個月和滾動視窗（marketdata.windows）的結果比對，差異 > 2% 就改用滾動視窗。」
- 驗證關卡：「通過條件：對上 ≥ 80% 的真實交易，平均 net R 差 ≤ 0.05。不過就說明差異原因，不要往下做。」
- 效能關卡：「15m 全期、全幣池模擬一個實驗要在 10 分鐘內跑完。」
- 成本：「taker 5bp、maker 2bp、市價單滑價 1bp。」
- 嚴禁前視：「訊號時間是確認 K 收盤，最早下一根開盤進場。」
- 鐵則 7：「關卡門檻、樣本切分、實驗上限、驗證門檻一律照原文，不准修改。覺得該改就停下來提問。」
- 鐵則 8：「過不了關卡就停下來回報，絕不為了過關調參數或追加實驗。」
- 產出：「程式碼和 research/out/harness_validation.md（開頭 5 行結論）。commit 並 push，不開 PR。」

**關於 push**：原 prompt 寫「commit 並 push，不開 PR」。若執行者收到的流程指令另外規定「只 commit、不要 push」，以流程指令為準：只 commit，並在報告寫明「依流程指令未 push，push 留待驗收後」。不開 PR。

**關於 YAML**：依賴限制下 research/ 內**不得直接 `import yaml`**。實驗 YAML 一律用 `chanedge.config.load._read_mapping(path)` 讀（這是 import chanedge，允許；PyYAML 是 chanedge 既有依賴，不新增依賴）。

**關於測試框架**：research 的單元測試用標準庫 `unittest`（不依賴 pytest）。既有 `tests/` 用 `.venv/bin/python -m pytest` 跑，只當作「沒有改壞」的回歸確認。

---

## 1. 已查明的事實（規劃者已驗證，執行者直接採用）

| 項目 | 事實 |
| --- | --- |
| 設定 | `load_settings('config/default.yaml')` 的 `config_hash` 前 16 碼是 `b78fb5ba0ff45dde`，等於 baseline 目錄名開頭。研究程式用同一份預設設定。 |
| K 線 | `data/bars/binanceusdm/<BASE>/USDT/{15m,1h,4h}.parquet`。欄位 symbol, timeframe, open_time, close_time(=open_time+週期), open, high, low, close, volume, quote_volume, trades, is_closed, source。BTC 15m 從 2023-10-01 到 2026-10-29。 |
| 榜單 | `data/universe/binanceusdm/YYYY-MM-DD.json`，list of {rank, symbol, ...}。2024-01-01→2026-10-27 共 1031 天，前 20 名聯集 591 個幣，共 20,620 個「幣×天」。 |
| 榜單日期 | 回測用 `universe_date = (decision_time - 5 分鐘).date()`（UTC，`refresh_minute=5`，見 `backtest/loop.py::_universe_date`）。00:00 收盤的訊號屬於**前一天**的榜單。研究程式必須用同一規則。 |
| Tick | baseline 用 `chanedge.app.paper_loop.inferred_instrument(settings, symbol, _kline_text(Path('.'), symbol))` 的 `price_tick`（vision CSV 在 `data/futures/um/...`）。 |
| 引擎耗時 | `ChanEngine.compute` 視窗：15m(1500 根) ≈ 19 ms、1h(1000) ≈ 19 ms、4h(500) ≈ 6 ms；BTC 15m 全史單次走訪 ≈ 13 s；讀一個 15m parquet 成 `Bar` 物件 ≈ 2.7 s。機器 8 核、15 GB RAM。 |
| baseline trades | `data/reports/b78fb5ba0ff45dde_921628697ec40df8_2024-01-01_2026-10-27_2026-10-30T19-33-48/trades.parquet`，5,575 列，**所有欄位都是字串**，要 `pd.to_numeric`。欄位含 symbol, side(long/short), qty, entry_price, exit_price, entry_time, exit_time, exit_reason, signal_type, cost_r, partial_reason, fee_quote, pnl, r_multiple, defending_atr。 |
| baseline 時間 | `entry_time` = 進場成交那根 15m 的 open_time = 訊號確認 K 的 close_time（ISO 字串含 +00:00）。`exit_time` = 出場成交那根的 open_time。 |
| baseline R | 已驗證：`r_multiple = pnl / (qty × |entry_reference − structure_stop|)`，pnl 已扣手續費、**不含資金費**，qty 是整筆進場數量（含 TP1 的單也是整筆）。`entry_reference` 是**訊號 K 收盤價**（不是成交價）。非分批列重算殘差 std ≈ 1.6e-4。`mean(r_multiple) = −0.1644`；`mean(r_multiple + fee_quote/(qty×stop_dist)) ≈ −0.034`；fee_r 平均 ≈ 0.13。驗證時直接用 `r_multiple` 欄當 baseline net R。 |
| baseline 出場分布 | structure_stop 2388、breakeven_stop 1406、opposite_signal 1217、ratchet_stop 450、bias_1h 70、breakeven_adverse 43、zhongshu_fail 1。partial_reason：prior_swing 1596、r_multiple 35。 |
| baseline 權益 | max_drawdown 0.99；後期 qty 很小，數量取整會帶來 R 雜訊。這是可能的差異來源之一，寫進報告即可。 |

### 現行規則（要在模擬器中近似的對象，程式出處）

- 候選：`features/select.py::select_candidate`——同一根 15m 上三類優先於二類；同根同時有買與賣 → 歧義，不進場。
- 硬閘門 `rules/gate.py::RuleGate.evaluate`：STALE（回測恆為否）、GAP_DATA、SESSION_SKIP（預設空清單）、4H 方向（多單需 4h bias ∈ {up, breakout_up}，空單 ∈ {down, breakout_down}）、1H 衝突（多單時 1h bias ∉ {down, breakout_down}，空單對稱）、VOL_BAND（atr_pct ∈ [0.001, 0.030]）、OUTSIDE_UNIVERSE、INSUFFICIENT_HISTORY（15m/1h/4h 已收盤根數 ≥ 1500/1000/500）、POSITION_OPEN、KILL_SWITCH。研究中帳戶為空、kill_switch=False。
- JEV：`jev/model.py::JevModel.assess`，`score >= 0.62`（float 比較）→ BUY/SELL。
- 風險 `risk/size.py::plan_entry`：entry_reference = 訊號 K 收盤；ATR = FeatureBuilder 的 `volatility_volume.atr`（15m Wilder ATR(14)，在 1500 根視窗上算）；buffer = 0.15 × ATR；`structure_stop`：多單 floor_to_tick(防守價 − buffer)，空單 ceil_to_tick(防守價 + buffer)；`cost_r = 0.0012 / (stop_dist / entry_reference)`，> 0.40 拒絕；TP1 = 50%，價位 = 視窗快照中最後一條已確認、方向有利的 15m 筆的終點（多單取最後一條上升筆終點，須 > entry_reference），否則 entry ± 1.5R。
- 撮合 `backtest/matcher.py::match_bar`（每根 15m，順序固定）：
  1. 上一根留下的 next_open 單在本根開盤成交（市價，滑價 1bp：買 ×(1+0.0001)，賣 ×(1−0.0001)），手續費 5bp。出場單成交後該部位結束。
  2. 部位仍在：先看停損——多單 `open <= stop` → 成交在 open；否則 `low <= stop` → 成交在 stop。空單對稱用 high。成交價再套滑價、收 5bp。
  3. 停損沒觸發才看 TP1（只一次）：多單 `open >= tp` → open，否則 `high >= tp` → tp；同樣套滑價、收 5bp。
  4. 同一部位同一根至多一筆出場；停損優先於 TP1。進場那根（開盤成交後）就要做第 2、3 步。
- 收盤檢視 `risk/review.py::review_position`（每根 15m 收盤、在撮合之後，順序固定，命中第一個就排 next_open 全平）：反向訊號（M15 上任何二賣/三賣（多單）且 `signal.time > entry_decision_time`）→ `opposite_signal`；1h bias ∈ 出場集合（多單 {down, breakout_down}）→ `bias_1h`；三買：收盤 < 相關中樞 ZG（三賣：> ZD）→ `zhongshu_fail`；二買：收盤 < prior_extreme（二賣：>）→ `swing_fail`。都沒有才改停損：
  - 保本：停損尚未 ≥ entry_reference（多單）時，若本根 `high >= entry_reference + 1.0R` → 停損改成 entry_reference（下一根生效）。
  - 棘輪：已保本後，若本根**新建立**的下降筆（多單）終點 > 現停損 → 新停損 = floor_to_tick(終點 − buffer)，且須 > 現停損。「新建立」= 該筆終點分型的確認時間 == 本根收盤，且 `established_at` == 本根收盤（端點被替換的不算）。
- 出場原因分類 `matcher._classify`：停損 == 原結構停損 → structure_stop；多單停損 > entry_reference → ratchet_stop；停損 == entry_reference → breakeven_stop（若保本那根的收盤不利則 breakeven_adverse）。

---

## 2. 目錄與檔案

新增（全部在 research/ 下）：

```text
research/
  __init__.py                 # 空檔，讓 `python -m research.xxx` 可用
  common.py                   # 路徑、常數、樣本切分、universe_date、YAML 讀取、bars 讀取
  signals.py                  # 步驟 1：訊號快取（含模式比對 compare 子命令）
  donchian.py                 # 基準策略訊號：1h/4h Donchian 20/55
  sim.py                      # 步驟 2：模擬器
  run.py                      # 跑單一實驗，寫 results 與 registry
  report.py                   # 只讀 results，預設樣本內；--oos 需記錄
  validate.py                 # 步驟 3：對 baseline 的驗證，寫 harness_validation.md
  experiments/
    p0_validate_current_15m.yaml
    p0_perf_15m_all.yaml
    donchian_1h_n20.yaml      # 只提交，不在 phase 0 執行
    donchian_4h_n55.yaml      # 只提交，不在 phase 0 執行
  tests/
    __init__.py
    test_sim.py
    test_signals.py
    test_run_report.py
  out/
    registry.md               # 表頭 + 每次 run.py 一行
    oos_log.md                # 0 位元組空檔，phase 0 不准寫入
    signal_mode_check.md      # 單次走訪 vs 滾動視窗比對結果
    harness_validation.md     # 開頭 5 行結論
  cache/                      # gitignore，不 commit
```

修改：`.gitignore` 追加一行 `research/cache/`（目前尚未加入，鐵則 9 說「已加進」與實況不符，照 prompt 加上）。

**不得修改**：`src/`、`config/`、`tests/`、`docs/ARCHITECTURE.md`、`pyproject.toml`。也不要動 `docs/` 其他檔。

允許的 import：標準庫、`numpy`、`pandas`、`pyarrow`、`chanedge.*`、`research.*`。禁止 `import yaml`、`pytest`（research 內）、`scipy`、`polars`、`duckdb` 等。

---

## 3. 步驟

### 步驟 0：準備

1. `git status`，確認在 `research/phase0`。
2. `.gitignore` 加 `research/cache/`；建立 `research/__init__.py`、`research/tests/__init__.py`、`research/out/`、`research/experiments/`。
3. `research/out/oos_log.md` 建成 0 位元組（`: > research/out/oos_log.md`）。
4. `research/out/registry.md` 寫表頭：
   ```markdown
   # Experiment registry
   | time_utc | name | config_sha | summary |
   | --- | --- | --- | --- |
   ```

### 步驟 1：`research/common.py`

常數與函式（介面固定，其他模組只透過這裡取用）：

```python
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "research" / "cache"; OUT = ROOT / "research" / "out"; EXPERIMENTS = ROOT / "research" / "experiments"
VENUE = "binanceusdm"
HISTORY_START = date(2024, 1, 1); HISTORY_END = date(2026, 10, 27)   # 與 baseline 同
IS_START = date(2024, 1, 1); IS_END = date(2025, 6, 30)               # 樣本內（原文）
OOS_START = date(2025, 7, 1); OOS_END = date(2026, 10, 27)            # 樣本外（原文）
WINDOWS = {"15m": 1500, "1h": 1000, "4h": 500}                        # 從 settings.marketdata.windows 讀，斷言等於此值
REFRESH_MINUTE = 5
TAKER_BPS = 5.0; MAKER_BPS = 2.0; SLIPPAGE_BPS = 1.0
BASELINE_DIR = ROOT / "data/reports/b78fb5ba0ff45dde_921628697ec40df8_2024-01-01_2026-10-27_2026-10-30T19-33-48"

def settings(): ...                      # load_settings(ROOT/'config/default.yaml')，lru_cache
def config_digest() -> str: ...          # chanedge.config.hash.config_hash(settings())，斷言開頭 'b78fb5ba0ff45dde'
def universe_date(ts) -> date: ...       # (ts - 5min) 的 UTC 日期；ts 可為 datetime 或 pd.Timestamp / Series（向量版另寫 universe_dates）
def sample_of(signal_time) -> 'IS'|'OOS'|None   # 依 signal_time 的 UTC 日期落在哪一段；兩段外為 None
def read_yaml(path) -> dict: ...         # chanedge.config.load._read_mapping
def load_universe() -> pd.DataFrame      # 欄 date, symbol, rank（只保留 1..20），快取到 cache/universe.parquet
def union_symbols() -> list[str]         # 2024-01-01..2026-10-27 曾進前 20 的幣
def active_segments(symbol) -> list[(date, date)]  # 每段連續在榜日 [d0, d1+30天]，重疊合併，截到 HISTORY_END
def load_bars_df(symbol, tf) -> pd.DataFrame       # 直接 pyarrow 讀 parquet（快），只留 is_closed，依 open_time 排序
def load_bar_objects(symbol, tf) -> tuple[Bar,...] # ParquetBarStore(ROOT).read(VENUE, symbol, Timeframe(tf)) → .bar
def instrument(symbol)                   # inferred_instrument(settings(), symbol, _kline_text(ROOT, symbol))
```

### 步驟 2：`research/signals.py`（訊號快取）

#### 2a. 單次走訪（replicated walk）

不改 chanedge，在 research 內**照抄** `ChanEngine.compute` 的迴圈（用 chanedge 的 `include_merge`、`detect_fenxings`、`confirmed_fenxings`、`WalkState`），在每個事件後記錄：

```python
def walk(bars: tuple[Bar,...], tf: str) -> WalkResult
# 迴圈：for draft in confirmed_fenxings(drafts):
#          before = len(state.signals); event = state.feed_fenxing(draft)
#          if event is None: continue
#          state.apply_zhongshu(event); state.apply_signals(event)
#          新訊號 = state.signals[before:]           -> emitted（含發出時的欄位快照）
#          bi = state.held[-1].bi                    -> bi_events.append((confirm_time, event, bi.direction, bi.end_price, bi.established_at))
# WalkResult.signals: list[ChanSignal]（發出當下的物件；replace 只改 related_bi_id，可忽略）
# WalkResult.bi_events: DataFrame[confirm_time, event('new'|'replace'), direction, end_price, established_at]
```

`confirm_time` = 該分型確認 K 的 close_time（`bars[draft.k_index_right].close_time`）。另外要對 ZG/ZD：三買/三賣的 `related_zhongshu_id` 對應中樞的 zg/zd，從 `state.book` 查不到時改用發出當下 `state.book.publish(state.held, bars)` 的結果查（只在有三類訊號的事件做）。

**必做檢查**（寫進 `test_signals.py`）：
- 對 BTC/USDT 15m 前 20,000 根：`walk()` 的訊號 id 集合 == `ChanEngine.compute(...).signals` 的 id 集合。
- 無前視：對同一序列截到第 N 根（N 取 3 個不同值），`walk(bars[:N])` 的訊號（time ≤ bars[N-1].close_time）與 `walk(bars)` 中 time ≤ 同時間的訊號完全相同（id 與 defending_price）。

#### 2b. 滾動視窗（rolling）

```python
def rolling_signals(bars, tf, start, end) -> list[ChanSignal]
# 對每根 close_time t ∈ [start, end]：window = 最後 WINDOWS[tf] 根已收盤且 close_time <= t 的 K；
# snap = engine.compute(window, timeframe=tf, as_of=t, identify=False)；收 snap.signals 中 time == t 的訊號。
```

#### 2c. 模式比對（關卡：「差異 > 2% 就改用滾動視窗」）

命令：`.venv/bin/python -m research.signals compare`

- 幣：BTC/USDT、ETH/USDT、SOL/USDT。期間：2024-03-01 00:00 → 2024-05-31 24:00 UTC（3 個月，樣本內）。
- 三個週期分別比：鍵 = (symbol, tf, type, time, round(defending_price, 8))。
- 差異率 = |單次走訪集合 △ 滾動集合| / |滾動集合|，三個幣合併算，每個週期一個數。
- 判定：**每個週期各自判定**，差異率 > 0.02 的週期改用 rolling，否則 single。
- 寫 `research/cache/mode.json`：`{"15m": "single"|"rolling", "1h": ..., "4h": ..., "detail": {tf: {"n_single":..,"n_rolling":..,"sym_diff":..,"rate":..}}}`。
- 寫 `research/out/signal_mode_check.md`：表格列出每個週期的數字、判定，以及不一致樣本前 20 筆。
- 這一步約 10–15 分鐘（15m 滾動 3×8,832 根 × 19 ms）。

#### 2d. 建快取

命令：`.venv/bin/python -m research.signals build --workers 6`（可加 `--symbols BTC/USDT,ETH/USDT` 做小樣本）。讀 `mode.json` 決定每個週期用 single 或 rolling；`mode.json` 不存在就報錯退出。

用 `multiprocessing.Pool(processes=workers, maxtasksperchild=1)`，以幣為單位並行。每個幣：

1. 讀三個週期的 `Bar` 物件與 DataFrame。
2. 訊號範圍：`universe_date(time)` 落在 `active_segments(symbol)` 任一段內，且 ∈ [HISTORY_START, HISTORY_END]。
3. 各週期偵測訊號（single：全史 `walk()`；rolling：只對範圍內每根收盤跑 2b）。
4. **方向序列**：對範圍內（第一段起點往前 1 天到最後一段終點）每根 1h 與 4h 收盤 t，用視窗（1000/500 根，close_time ≤ t）算快照，記 `structure_bias`。輸出 `bias_1h`、`bias_4h` 表（symbol, close_time, bias）。這是「只用已收盤 K 線」的 4h/1h 方向；任何時間點 T 的方向 = close_time ≤ T 的最後一列。同一個 worker 內用 dict 快取 (tf, as_of) → snapshot，給下一步重用。
5. **15m 筆事件**：single 模式直接用 `walk().bi_events`；rolling 模式在每根快照中找 end 分型 time == t 的已確認筆，`established_at == t` 記 'new'，否則記 'replace'。輸出 `bi_events_15m`（symbol, confirm_time, event, direction, end_price）。
6. **每筆 15m 訊號**加算（視窗內容與 baseline 同）：
   - `context` = `MultiTimeframeContext`（bars = 三個週期的視窗；snapshots = 15m 視窗快照（當場算）+ 1h/4h 快照（第 4 步快取）；`data_quality` = `chanedge.app.paper_loop.backtest_quality(settings)(symbol, t, windows)`，並把 `stale` 強制為 False（同 `backtest/loop.py::_quality`）；`instrument` = `common.instrument(symbol)`；`universe_date`、`universe_rank`（不在前 20 名為 None））。
   - `features = FeatureBuilder(feature_params(settings)).build(context)`；`assessment = JevModel(jev_params(settings)).assess(features)`；`rules = RuleGate(rule_params(settings)).evaluate(context, assessment, AccountView(equity_quote=Decimal(10000), open_position_count=0, gross_notional_quote=Decimal(0)), SafetyState(kill_switch=False, mode=RuntimeMode.PAPER))`。
   - `select_candidate(snap15.signals, t)` → `candidate`（本訊號 id 是否就是被選中的那個）、`ambiguous`。
   - `in_window`：本訊號 id 是否出現在 15m 視窗快照中且 time == t（single 模式的逐筆一致性指標）。
   - TP1 前高前低：照 `risk/stops.py::_last_endpoint` 在 15m 視窗快照上取最後一條已確認上升筆終點 `last_up_end`、下降筆終點 `last_down_end`（fenxing.time ≤ t）。
7. **1h/4h 訊號**：方向欄取第 4 步序列；ATR 用全序列 Wilder ATR(14)（`chanedge.features.atr.wilder_atr`）；`last_up_end`/`last_down_end` 用 `bi_events_15m` 在 t 之前（≤ t）最後一條同方向筆的終點（要套用 replace）。不算 features/JEV/gate（填 NaN）。
8. 合併所有幣，寫：
   - `research/cache/signals_15m.parquet`、`signals_1h.parquet`、`signals_4h.parquet`（必須產出，檔名照 prompt）
   - `research/cache/bias_1h.parquet`、`bias_4h.parquet`、`bi_events_15m.parquet`、`universe.parquet`、`instruments.parquet`（symbol, price_tick）
   - `research/cache/bars_15m.parquet`：所有聯集幣 15m 的 (symbol, open_time, open, high, low, close)，從第一段起點前 1 天到資料尾，給模擬器快速讀。
   - `research/cache/logs/signals_build.log`：每完成一個幣寫一行（幣、訊號數、耗時）。
9. 第 2–7 步出錯的幣：記到 log，整體結束時非 0 退出並列出失敗幣；不要靜默略過。

`signals_{tf}.parquet` 欄位（型別固定；時間一律 `timestamp[us, tz=UTC]`）：

| 欄 | 說明 |
| --- | --- |
| signal_id | chanedge 的 `ChanSignal.id` |
| symbol, tf | |
| type | second_buy / third_buy / second_sell / third_sell |
| side | +1 多 / −1 空 |
| time | 確認 K 的 close_time（= 最早可進場那根 15m 的 open_time） |
| close | 確認 K 收盤（= entry_reference） |
| defending_price, prior_extreme, zs_zg, zs_zd | 防守價；二類的前極值；三類相關中樞 ZG/ZD（沒有填 NaN） |
| atr | 該週期 ATR(14)。15m 用 FeatureBuilder 的 `volatility_volume.atr`；1h/4h 用全序列 Wilder |
| bias_4h, bias_1h, bias_15m | 字串（up/down/neutral/breakout_up/breakout_down）；bias_15m 只有 15m 有 |
| universe_date, rank, in_top20 | rank 為 1..20 或 NaN |
| reemit | 同 symbol、同 type、同 `related_bi_id` 先前已發出過 → True |
| last_up_end, last_down_end | TP1 前高前低候選 |
| （15m 才有）candidate, ambiguous, in_window, gate_pass, veto_codes（逗號字串） | |
| （15m 才有）jev_score, jev_action, atr_pct, session_bucket | |
| （15m 才有）ch_{structure,location,resonance,volatility_volume,signal_bar,session}_{subscore,penalty} | 六通道 |
| hist_ok, gap_veto | 15m 由 gate 得到；1h/4h 填 NaN |

**時間預算**：先 `--symbols BTC/USDT,ETH/USDT,SOL/USDT` 跑一次，量耗時，外推全量並寫在 log 開頭。全量預估（single 模式）約 1–3 小時，rolling 模式更久；用背景執行並等待完成，不要中途改設計來趕時間。

### 步驟 3：`research/donchian.py`（基準策略訊號）

命令：`.venv/bin/python -m research.donchian build`

- 週期 1h、4h；N ∈ {20, 55}（「20/55」解讀為兩組通道長度各自成一組訊號；出場用同 N 的反向突破＋2 ATR 停損。這是規劃者的解讀，寫進 harness_validation.md 的附註）。
- 多單訊號：`close[t] > max(high[t−N .. t−1])` 且 `close[t−1] <= max(high[t−N−1 .. t−2])`（只取第一根突破）；空單對稱用 low。只用已收盤 K。
- `defending_price = close[t]`，`atr` = 該週期全序列 Wilder ATR(14)；模擬時 `stop.buffer_atr = 2.0` → 停損恰為 2 ATR。
- 欄位與 `signals_{tf}.parquet` 相容（type = `dc{N}_long`/`dc{N}_short`，加欄 `n`），`in_top20`/`rank` 用同一榜單規則。
- 輸出 `research/cache/signals_donchian_{1h,4h}.parquet`。範圍：聯集幣、universe_date ∈ [HISTORY_START, HISTORY_END]。

### 步驟 4：`research/sim.py`（模擬器）

#### 介面

```python
@dataclass(frozen=True)
class SimConfig: ...                      # 由 YAML 解析，見第 5 節；from_dict(d) 驗證所有鍵，未知鍵報錯
def load_market(tfs_needed) -> Market     # 讀 bars_15m、bias_1h、bi_events_15m、instruments、各訊號表；按 symbol 轉成 Python list/np 陣列
def select_signals(cfg, market) -> pd.DataFrame   # 依 cfg.signals 與 cfg.filters 篩訊號
def simulate(cfg, market, signals) -> pd.DataFrame  # 每筆訊號獨立模擬，回傳 trades
```

**每個訊號獨立計算，不做帳戶與持倉上限**（原文）。同一幣可同時有多筆重疊的模擬單。

#### 價格路徑與對齊

- 一律用 15m K 線（`bars_15m`）。訊號時間 T（任一週期）→ 進場 K = 第一根 `open_time >= T` 的 15m K（正常就是 open_time == T）。
- 每根 15m K 的「收盤決策時間」= close_time。1h 方向在 15m 第 j 根的值 = `bias_1h` 中 close_time ≤ 該根 close_time 的最後一列（用 `np.searchsorted` 預先對齊成陣列）。
- 筆事件對齊成兩個陣列：`new_up_end[j]`、`new_down_end[j]`（第 j 根收盤時 event=='new' 的筆終點，無則 NaN）。
- 反向訊號：同幣、對向（多單看 second_sell/third_sell；空單看 second_buy/third_buy）、`cfg.exit.opposite_signal.tf`（預設 15m；Donchian 為同 N 的反向突破）的訊號時間，排序後用 bisect 找第一個 `time > T`（entry_decision_time = T）。命中於第 j 根收盤（time == close_time_j）。注意反向訊號**不經過**任何過濾（含不在前 20 名的、歧義的、reemit 的）。

#### 進場（`entry.mode`）

- `market_next_open`：進場 K 開盤成交，價 = open ×(1 ± 0.0001)（多買加、空賣減），taker 5bp。`entry_reference` = 訊號 close。
- `limit`：掛單價 `L` 規則：`signal_close`（L = close − side×offset×ATR）、`stop_frac`（L = close − side×f×(close − stop)，f = offset）。從進場 K 起有效 `valid_bars` 根。成交條件**嚴格穿過**：多單 `low < L`、空單 `high > L`（等於不算）。成交價 = L，**maker 2bp、無滑價**。`entry_reference` = L。過期未成交 → 不產生交易（計入 unfilled 計數）。限價成交那根：照樣做停損檢查（保守）；**不做** TP1/固定 R 停利（保守，避免同根先低後高的假設）。
- `confirm`：等 `bars` 根（K ≥ 1）確認：從進場 K 起數 K 根，期間任何一根觸及停損（多單 low ≤ stop）→ 放棄；若 `require_close_beyond: true`，第 K 根收盤須 ≥ 訊號 close（多單；空單 ≤）。通過則在第 K+1 根開盤市價進場（taker+滑價）。`entry_reference` = 第 K 根收盤。
- 所有模式：訊號在 T 時刻才可知，**最早**在 open_time == T 的那根開盤進場；任何計算不得讀 T 之後的 K（限價/確認是在 T 之後逐根前進，只用已發生的那根）。

#### 停損

`stop = defending_price − side × buffer_atr × atr`，`round_to_tick: true` 時多單 floor、空單 ceil 到 `price_tick`（tick 缺失則不取整並計數）。`R_dist = side × (entry_reference − stop)`；`R_dist <= 0` → 不交易（計數 invalid_stop）。`max_cost_r` 篩選用 `cost_r = (2×(taker+slip) bps) / (R_dist / entry_reference)`（現行 = 0.0012/…），在進場前判定。

#### 每根 K 的處理順序（與 matcher + review 相同）

```
for j from entry_bar:
  (1) 開盤：若有待成交的 next_open 出場 → 以 open±滑價、taker 全平，結束。
      （進場 K 的開盤進場也在這一步）
  (2) 盤中停損：open 穿過 → open；否則 low/high 觸及 → stop 價；套滑價、taker；全平剩餘，結束。
  (3) 停損未觸發才看停利（TP1 部分、或 fixed_r 全平）：open 已越過 → open；否則觸及 → 目標價；套滑價、taker。同根至多一筆出場。
  (4) 收盤檢視（部位仍在）：依序 opposite_signal → bias_1h → level_fail(zhongshu/swing) → time_stop；
      命中 → 排 next_open 全平（原因為該項）。否則更新停損：breakeven → ratchet → atr_trail（新停損只往有利方向移，下一根生效）。
  資料結束仍持有 → 以最後一根收盤價平倉（taker+滑價），原因 end_of_data。
```

出場原因（字串）：`structure_stop`、`breakeven_stop`、`breakeven_adverse`、`ratchet_stop`、`trail_stop`、`opposite_signal`、`bias_1h`、`zhongshu_fail`、`swing_fail`、`fixed_r`、`time_stop`、`end_of_data`。停損類分類照 `matcher._classify`：停損 == 初始停損 → structure_stop；停損在 entry_reference 有利側且 ≠ → ratchet_stop（若是 atr_trail 移的 → trail_stop）；== entry_reference → breakeven_stop，若保本觸發那根收盤在不利側 → breakeven_adverse。

#### 出場模組（`exit.*`，可組合）

| 鍵 | 行為 |
| --- | --- |
| `tp1: {enabled, fraction: 0.5, target: prior_swing\|r, r_fallback: 1.5}` | prior_swing：多單用 `last_up_end`（須 > entry_reference）否則 entry_reference + 1.5R；空單對稱用 `last_down_end`。只成交一次 |
| `breakeven: {enabled, arm_r: 1.0}` | 收盤檢視時，本根 high ≥ entry_reference + arm_r×R（空單 low ≤ …）且停損尚未到保本 → 停損 = entry_reference |
| `ratchet: {enabled}` | 已保本後，本根 `new_down_end`（多單）> 現停損 → floor_to_tick(終點 − buffer)，須 > 現停損；空單對稱。buffer = 進場時的 buffer_atr×atr |
| `fixed_r: {enabled, r}` | 全平在 entry_reference + side×r×R，盤中觸及成交（同停利規則） |
| `atr_trail: {enabled, mult, arm_r}` | 從進場起的最高收盤（多單）− mult×ATR(訊號週期 ATR，固定為進場時值)；arm_r>0 時須先達 +arm_r R 才啟動 |
| `opposite_signal: {enabled, tf}` | 見上 |
| `bias_1h: {enabled}` | 多單 1h bias ∈ {down, breakout_down} → 出場；空單對稱 |
| `level_fail: {enabled}` | 三買：收盤 < zs_zg；三賣：收盤 > zs_zd；二買：收盤 < prior_extreme；二賣：收盤 > prior_extreme（從進場 K 起） |
| `time_stop: {enabled, bars}` | 持有滿 `bars` 根的那根收盤 → next_open 出場 |

預設組（YAML 可寫 `exit: {preset: current}`，run.py 展開後存檔）：
- `current`（現行規則近似）= tp1(prior_swing, 0.5, 1.5) + breakeven(1.0) + ratchet + opposite_signal(15m) + bias_1h + level_fail。
- `ratchet_only`（不分批只棘輪）= breakeven(1.0) + ratchet，其餘關。
- `fixed_r`、`atr_trail`、`opposite_only`、`time_stop` 由使用者在 YAML 寫明參數。

#### 成本與 R 的定義

- 成本：taker 5bp、maker 2bp、市價單滑價 1bp（原文）。市價進場、所有市價/停損/停利出場收 taker 並套 1bp 滑價（停損與停利也套滑價，同 matcher 的保守做法）；只有限價進場收 maker、不套滑價。
- 以「每單位數量」計：每一腿成交價（已含滑價）`p_k`、比例 `w_k`（進場 1.0；TP1 0.5、剩餘 0.5；不分批 1.0）。
  - `gross_r = Σ_k w_k × side × (p_exit_k − p_entry) / R_dist`（含滑價、不含手續費）
  - `fee_r = (p_entry × fee_entry + Σ_k w_k × p_exit_k × fee_k) / R_dist`（fee 以小數，如 5bp = 0.0005）
  - `net_r = gross_r − fee_r`（不含資金費，與 baseline r_multiple 一致）
  - `mfe_r = side × (最有利極值 − p_entry) / R_dist`，`mae_r = side × (最不利極值 − p_entry) / R_dist`（通常 ≤ 0），區間為進場 K 到最後持有的那根（盤中出場含出場 K；next_open 出場取到出場決策那根）。
  - `bars_held = 出場 K 索引 − 進場 K 索引`（同根出場為 0）。

#### 輸出欄位（每筆一列）

`signal_id, symbol, tf, type, side, signal_time, entry_time, entry_price, entry_reference, stop_initial, r_dist, exit_time, exit_price（加權平均）, gross_r, net_r, fee_r, mfe_r, mae_r, bars_held, exit_reason, tp1_hit, sample('IS'/'OOS')`。`exit_time` 為最後一腿成交 K 的 open_time（next_open 出場）或盤中成交那根的 open_time（同 baseline）。

#### 效能做法

- 進入迴圈前把每個幣的 open/high/low/close、close_time、對齊後的 bias/筆事件轉成 **Python list**（list 索引比 numpy 純量快）。
- 訊號依幣分組；`--workers`（預設 6）用 `multiprocessing` 以幣為單位並行。
- 目標：「15m 全期、全幣池模擬一個實驗要在 10 分鐘內跑完。」（原文）

### 步驟 5：實驗 YAML 格式與 `research/run.py`

YAML（完整鍵；`name` 必須等於檔名主幹）：

```yaml
name: p0_validate_current_15m
description: 15m 訊號 + 現行規則，對 baseline 驗證用
signals:
  source: chan            # chan | donchian
  tf: 15m                 # 15m | 1h | 4h
  types: [second_buy, third_buy, second_sell, third_sell]
  donchian_n: null        # donchian 時 20 或 55
filters:
  in_top20: true
  candidate_only: true    # 15m：candidate==True 且 ambiguous==False
  gate_pass: true         # 15m
  jev_min: 0.62           # 15m；null=關
  max_cost_r: 0.40        # null=關
  exclude_reemit: false
entry:
  mode: market_next_open  # market_next_open | limit | confirm
  limit: {price: signal_close, offset: 0.0, valid_bars: 4}
  confirm: {bars: 1, require_close_beyond: true}
stop:
  buffer_atr: 0.15
  round_to_tick: true
exit:
  preset: current
costs:
  taker_bps: 5
  maker_bps: 2
  slippage_bps: 1
```

`research/run.py` 命令：`.venv/bin/python -m research.run research/experiments/<name>.yaml [--workers 6]`

1. 用 `common.read_yaml` 讀、`SimConfig.from_dict` 驗證（未知鍵、缺鍵、型別錯 → 退出碼 2）；`name` ≠ 檔名主幹 → 退出碼 2。
2. 展開 preset，算 `config_sha = sha256(json.dumps(resolved, sort_keys=True, separators=(',',':')))[:12]`。
3. 讀 registry：實驗數 = registry 中不同 `name` 的數量。
   - 新名字且已有 60 個 → 拒絕，退出碼 3（實驗總數上限 60 個）。
   - 名字已存在但 `config_sha` 不同 → 拒絕，退出碼 3（改設定必須換新名字，避免靜默改參數）。
4. 跑模擬（全期 HISTORY_START → HISTORY_END 的訊號；樣本切分由 report.py 處理）。
5. 寫 `research/cache/results/<name>.parquet`，另寫 `research/cache/results/<name>.json`（resolved 設定、config_sha、訊號數、成交數、unfilled、invalid_stop、tick 缺失數、耗時秒）。
6. 在 `research/out/registry.md` 追加一行：`| <UTC ISO 時間> | <name> | <config_sha> | <摘要> |`，摘要 = `src=chan tf=15m types=4 filt=top20,cand,gate,jev>=0.62,cost<=0.40 entry=market stop=0.15atr exit=current`（簡短、單行）。
7. 終端只印：名稱、成交筆數、耗時。**不印任何績效數字**（績效只能透過 report.py 看）。

### 步驟 6：`research/report.py`

命令：`.venv/bin/python -m research.report <name> [<name> ...] [--by type|exit_reason|tf|month] [--oos]`

- 預設只取 `sample == 'IS'`（signal_time 的 UTC 日期 ∈ 2024-01-01 → 2025-06-30）。輸出首行明寫 `sample=IS 2024-01-01→2025-06-30`。
- `--oos`：只取 `sample == 'OOS'`（2025-07-01 → 2026-10-27），且**先**在 `research/out/oos_log.md` 追加一行 `| UTC 時間 | 實驗名 | 指令全文 |` 再輸出；若該實驗名已在 oos_log.md 出現過 → 拒絕（退出碼 3），對應鐵則 5「樣本外每組只跑一次」。
- 指標：n、mean net_r、mean gross_r、mean fee_r、win rate（net_r > 0）、PF（Σ正 net_r / |Σ負 net_r|）、Σ net_r、median bars_held、mfe/mae 分位數（25/50/75）、出場原因分布；`--by` 分組顯示同樣指標。
- oos_log 的寫入函式要接受路徑參數，讓單元測試用暫存檔，**不碰真正的 oos_log.md**。
- phase 0 **不准執行** `--oos`（鐵則 4 要求 oos_log.md 保持空的）。

### 步驟 7：單元測試（`research/tests/`，unittest）

`test_sim.py`（用合成 K 線與手寫訊號表，不讀真實資料）：
1. 進場時間 = 訊號 time 的那根開盤，價格含 1bp 滑價；訊號 K 本身的價格不被用來成交。
2. 同一根同時觸及停損與 TP1 → 只成交停損。
3. 開盤跳空穿過停損 → 成交在 open（再套滑價），不是停損價。
4. 限價：low == L 不成交；low < L 成交在 L、fee 為 2bp、無滑價；過期未成交不出列。
5. confirm：等待期內觸停損 → 不交易；通過 → 第 K+1 根開盤進場。
6. 保本：+1R 後下一根停損 = entry_reference；之後觸及 → breakeven_stop。
7. 棘輪：保本後出現 new_down_end > 停損 → 停損上移到 floor_to_tick(終點 − buffer)。
8. TP1：50% 在 prior_swing 成交，剩餘 50% 後續出場；gross_r/fee_r/net_r 依第 4 節公式手算相符（容差 1e-9）。
9. 反向訊號 / bias_1h / time_stop：在收盤命中，下一根開盤出場。
10. 進場 K 就被停損（bars_held == 0）。

`test_signals.py`（讀真實資料，BTC/USDT 截短）：
1. replicated walk 的訊號 id == `ChanEngine.compute` 的訊號 id。
2. 無前視（截斷前後一致，見 2a）。
3. `universe_date`：2024-03-02 00:00:00Z → 2024-03-01；00:05:00Z → 2024-03-02；00:04:59Z → 2024-03-01。
4. 若 `research/cache/signals_15m.parquet` 存在：欄位齊全；`time` 皆為 15m 邊界；所有列 `time` 對應的 bar 存在且 close_time == time。
5. Donchian：合成序列上，訊號只在第一根突破出現；只用 t 以前的 high/low。

`test_run_report.py`：
1. YAML 未知鍵 → 報錯；name 與檔名不符 → 報錯。
2. 在暫存 registry 中放 60 個不同名字 → 第 61 個新名字被拒；同名不同 config_sha 被拒。
3. report 預設只含 IS 列；`--oos` 寫入**暫存** oos_log、同名第二次被拒。
4. 掃描 `research/**/*.py` 的 import：只允許標準庫（`sys.stdlib_module_names`）、numpy、pandas、pyarrow、chanedge、research。

### 步驟 8：建快取並跑模式比對（順序固定）

1. `.venv/bin/python -m research.signals compare` → 看 `research/out/signal_mode_check.md` 與 `research/cache/mode.json`。依 2% 規則決定模式，不得因耗時改判定。
2. `.venv/bin/python -m research.signals build --symbols BTC/USDT,ETH/USDT,SOL/USDT --workers 3` → 量耗時。
3. `.venv/bin/python -m research.signals build --workers 6`（背景執行，等待完成）。
4. `.venv/bin/python -m research.donchian build`。
5. `.venv/bin/python -m unittest discover -s research/tests -t . -v` 全過。

### 步驟 9：驗證（`research/validate.py`）

1. 建 `research/experiments/p0_validate_current_15m.yaml`（內容即第 5 節範例）。
2. `.venv/bin/python -m research.run research/experiments/p0_validate_current_15m.yaml`（registry 第 1 個實驗）。記錄耗時。
3. `.venv/bin/python -m research.validate --experiment p0_validate_current_15m`：
   - 讀 baseline `trades.parquet`（數值欄 `pd.to_numeric`；`entry_time` 轉 UTC Timestamp）。
   - 鍵 =（symbol, signal_type/type, entry_time）。baseline 的 `entry_time` 對 sim 的 `entry_time`。
   - 對上比例 = 對上的 baseline 列數 / 5,575（分母是**全部真實交易**）。
   - 對上的配對上：`corr(sim.net_r, baseline.r_multiple)`（Pearson）；平均差 = `mean(sim.net_r) − mean(baseline.r_multiple)`（等於 `mean(sim.net_r − baseline.r_multiple)`）。同時報告 `mean |sim.net_r − baseline.r_multiple|`、差值分位數、出場原因一致率與混淆表、TP1 是否一致。
   - 判定（原文）：「對上 ≥ 80% 的真實交易，平均 net R 差 ≤ 0.05。」實作為：`match_ratio >= 0.80` 且 `abs(mean(sim.net_r) − mean(baseline.r_multiple)) <= 0.05`。報告中**另列** `mean |diff|`；若用 `mean |diff| <= 0.05` 判定會得出不同結論，在結論第 5 行明寫兩種讀法的結果，交由使用者決定，不要自行挑選有利讀法。
   - 未對上的 baseline 交易逐筆歸因並統計：(a) 快取中沒有這個 (symbol, type, time) 訊號；(b) 有訊號但 candidate/ambiguous 不符；(c) gate_pass 為否（列出 veto_codes 分布）；(d) jev_score < 0.62；(e) cost_r > 0.40；(f) 其他。
   - 印出並寫入的只有「保真度」數字；**不要**輸出 sim 的樣本內外績效分段（績效只走 report.py）。
4. 寫 `research/out/harness_validation.md`，**開頭 5 行固定格式**：
   ```
   結論：PASS|FAIL（對上 ≥ 80% 且 平均 net R 差 ≤ 0.05）
   對上比例：X / 5575 = Y%
   net R 相關係數：r = …（n = 對上筆數）
   平均 net R 差（sim − baseline）：… ；平均絕對差：…
   訊號模式：15m=single|rolling，1h=…，4h=…；模擬耗時 … 秒；備註：…
   ```
   之後：模式比對表（從 signal_mode_check.md 摘）、未對上歸因表、出場原因混淆表、差值分位數、已知差異來源（數量取整與極小權益、帳戶上限造成 sim 多出的單不影響對上率、反向訊號只看發出當根、資金費不計等）、Donchian 解讀附註、各步驟耗時。
5. **若 FAIL**：照原文「不過就說明差異原因，不要往下做」——在 harness_validation.md 寫清差異原因，跳過步驟 10，直接到步驟 11 提交。不得為了過關調參數、改過濾、改模擬規則重跑或追加實驗。

### 步驟 10：效能（只有驗證 PASS 才做）

1. 建 `research/experiments/p0_perf_15m_all.yaml`：同驗證檔，但 `filters` 只留 `in_top20: true`（`candidate_only/gate_pass` false、`jev_min/max_cost_r` null），`exit: {preset: current}`。這是「15m 全期、全幣池」最重的情況。
2. `/usr/bin/time -v .venv/bin/python -m research.run research/experiments/p0_perf_15m_all.yaml 2>&1 | tee research/cache/logs/perf.log`（registry 第 2 個實驗）。
3. Wall clock 必須 < 600 秒（「要在 10 分鐘內跑完」）。把數字寫進 harness_validation.md。超過就回報（可以優化程式碼後重跑**同一個**實驗名與同設定，config_sha 不變所以允許；不得改設定）。

phase 0 只執行這兩個實驗（共 2 / 60）。`donchian_1h_n20.yaml`、`donchian_4h_n55.yaml` 只建立並通過 `SimConfig.from_dict` 驗證（在 unittest 裡驗證，不透過 run.py），不執行。

### 步驟 11：提交

1. 確認 `research/cache/` 沒有被追蹤：`git status --porcelain | grep research/cache` 應無輸出。
2. `git add .gitignore research/`（含 `research/CLAUDE.md`、`research/plans/phase0.md`、程式、experiments、tests、out/）。
3. `git commit`，訊息例如 `Phase 0: research harness (signal cache, simulator, validation)`，結尾附 `Co-Authored-By` 行（依流程規定）。不要 `--no-verify`。
4. push：見第 0 節「關於 push」。不開 PR。

---

## 4. 驗收指令與通過條件

全部在 `/workspace/ChanEdge-research` 執行。

| # | 指令 | 通過條件 |
| --- | --- | --- |
| A1 | `git diff --name-only main...HEAD -- . ':!research' ':!.gitignore'` | 無輸出（沒有動 src/、config/、tests/、docs/、pyproject.toml） |
| A2 | `git diff main...HEAD -- .gitignore` | 只新增 `research/cache/` 一行 |
| A3 | `git ls-files research/cache \| wc -l` 與 `git check-ignore -q research/cache/x && echo ignored` | `0`；印出 `ignored` |
| A4 | `.venv/bin/python -m unittest discover -s research/tests -t . -v` | 全部 OK，無 skip（cache 測試在 cache 存在時必須實際執行） |
| A5 | `.venv/bin/python -m pytest -q` | 既有測試全過（回歸確認；數字以終端為準） |
| A6 | `grep -rnE "^\s*(import\|from)\s+(yaml\|pytest\|scipy\|polars\|duckdb\|sklearn)" research --include=*.py` | 無輸出（另有 A4 中的 import 掃描測試） |
| A7 | `cat research/cache/mode.json; cat research/out/signal_mode_check.md` | 三個週期都有 rate；判定符合「差異 > 2% 就改用滾動視窗」 |
| A8 | `.venv/bin/python -c "import pandas as pd;[print(tf,len(pd.read_parquet(f'research/cache/signals_{tf}.parquet'))) for tf in ('15m','1h','4h')]"` | 三檔存在且列數 > 0 |
| A9 | `.venv/bin/python -c "import pandas as pd;d=pd.read_parquet('research/cache/signals_15m.parquet');need={'signal_id','symbol','tf','type','time','defending_price','atr','bias_4h','bias_1h','in_top20','jev_score','gate_pass','candidate','ch_structure_subscore','ch_session_subscore'};print(need-set(d.columns));print(d[d.in_top20].jev_score.isna().mean())"` | 印 `set()`；在榜訊號 jev_score 缺值比例 0.0 |
| A10 | `head -5 research/out/harness_validation.md` | 5 行，格式同步驟 9；數字與 validate.py 終端輸出一致 |
| A11 | `.venv/bin/python -m research.validate --experiment p0_validate_current_15m` | 重跑數字與 harness_validation.md 相同（validate 不寫 registry） |
| A12 | 驗證 PASS 時：`grep -E "Elapsed \(wall" research/cache/logs/perf.log` | < 10:00（600 秒） |
| A13 | `cat research/out/registry.md` | 每次 run.py 一行；不同實驗名 ≤ 60（phase 0 應為 2，FAIL 時為 1） |
| A14 | `test ! -s research/out/oos_log.md && echo empty` | 印 `empty`（oos_log.md 保持空的） |
| A15 | `.venv/bin/python -m research.report p0_validate_current_15m \| head -3` | 首行顯示 `sample=IS 2024-01-01→2025-06-30`；無 OOS 列 |
| A16 | `git log -1 --stat` | 有 phase 0 commit，包含上述檔案，不含 research/cache |

研究驗證門檻（A10 的 PASS/FAIL）本身未達時，只要程式正確、原因在 harness_validation.md 誠實說明、且沒有為過關改參數或追加實驗，這是合法結果。

---

## 5. 常見錯誤（執行者注意）

- 用全序列 ATR 或成交價當 entry_reference 去對 baseline → R 會偏。15m 現行規則一律用 FeatureBuilder 的 ATR 與訊號 K 收盤。
- 用 `time.date()` 而非 `universe_date()` 判斷是否在前 20 名 → 每天 00:00 那根會錯。
- 方向用了尚未收盤的 1h/4h K → 前視。只取 close_time ≤ T。
- 停損與 TP1 同根時先算 TP1 → 違反「同一根先停損後停利」。
- 限價「觸及即成交」→ 違反「必須嚴格穿過限價才算成交」。
- run.py 印績效 → 造成未經 report.py 的樣本外窺視。只印筆數與耗時。
- 開發期間反覆用 run.py 試跑會灌 registry；開發測試請用 unittest 或直接呼叫 `sim.simulate` 於合成資料，不要用 run.py。
- 不要執行 `report.py --oos`。

---

## 附錄 A：原始任務 prompt（`/workspace/cc/phase0_prompt.md`，照抄）

> 先讀 docs/agents/README.md、docs/agents/logic.md、docs/agents/map.md、docs/agents/pitfalls.md。這是研究工作：新程式全部放 research/，可以 import chanedge，但不要改 src/、config/、tests/ 和架構稿。只用 pandas、pyarrow（含其依賴 numpy）和標準庫，不加任何依賴。research/cache/ 加進 .gitignore。
>
> 背景：正式事件回測一次要 15–18 小時，結果是 15m 版虧損：約 5,570 筆，淨 R −0.16、毛 R 約 −0.035，手續費每筆約 0.13R，16% 的單在進場後第一根 15m 就被結構停損打掉。停損越近表現越差，持有越久越賺。接下來要大量試週期、進場、出場與過濾，所以需要幾分鐘就能跑完一輪的研究工具。
>
> 資料：K 線在 data/bars，每日前 20 名榜單在 data/universe/binanceusdm/。資料都在本機（data/ 是指向本機資料的 symlink），不需要下載。對照用的正式回測（0.15 baseline）在 data/reports/b78fb5ba0ff45dde_921628697ec40df8_2024-01-01_2026-10-27_2026-10-30T19-33-48/（含 trades.parquet、run.json、summary.json、journal.sqlite）。Python 環境：.venv/bin/python（已 editable 安裝 chanedge）。
>
> 要做的：
> 1. 訊號快取 research/signals.py
>    - 對 15m、1h、4h 三個週期，用現有 ChanEngine 產生每個第一次合格的二買、三買、二賣、三賣。
>    - 每筆記錄：幣種、週期、類型、確認那根的收盤時間、防守價、該週期 ATR(14)、當時的 4h 與 1h 方向（只用已收盤 K 線）、當天是否在前 20 名。
>    - 15m 另外附上 FeatureBuilder 的六通道和本地 JEV 分數。
>    - 嚴禁前視：訊號時間是確認 K 收盤，最早下一根開盤進場。
>    - 若可行，先用整段歷史單次走訪（快）。用 3 個幣 × 3 個月和滾動視窗（marketdata.windows）的結果比對，差異 > 2% 就改用滾動視窗。
>    - 輸出 research/cache/signals_{tf}.parquet。
> 2. 模擬器 research/sim.py
>    - 每個訊號獨立計算，不做帳戶與持倉上限。
>    - 一律用 15m K 線當價格路徑。撮合規則和 backtest/matcher.py 一樣保守：同一根先停損後停利；開盤跳空穿過停損就成交在開盤價。
>    - 可設定項：
>      - 進場：下一根開盤市價；限價（價位規則、有效 N 根，必須嚴格穿過限價才算成交，收 maker 費）；等 K 根確認。
>      - 停損：防守價 ± buffer×ATR。
>      - 出場：現行規則的近似（TP1 50% 在前高前低、找不到用 1.5R；+1R 後保本；結構棘輪）、不分批只棘輪、固定 R 停利、ATR 追蹤、反向訊號、時間停損。
>      - 成本：taker 5bp、maker 2bp、市價單滑價 1bp。
>    - 每筆輸出：進出時間與價格、gross_r、net_r、fee_r、MFE_R、MAE_R、持有根數、出場原因。
>    - 另外實作一個基準策略：1h 與 4h 的 Donchian 突破（20/55），停損 2 ATR，相同成本模型和每日前 20 名幣池。
> 3. 驗證
>    - 用 15m 訊號加現行規則跑一次，以（幣種、類型、進場時間）對到 baseline 的 trades.parquet。
>    - 報告：對上比例、net R 相關係數、平均差。
>    - 通過條件：對上 ≥ 80% 的真實交易，平均 net R 差 ≤ 0.05。不過就說明差異原因，不要往下做。
> 4. 紀律
>    - 每個實驗一個 YAML，放 research/experiments/。research/run.py 跑單一實驗，結果寫 research/cache/results/<name>.parquet。
>    - 每次執行在 research/out/registry.md 追加一行：時間、實驗名、設定摘要。
>    - research/report.py 預設只顯示樣本內（2024-01-01 → 2025-06-30）。要看樣本外必須加 --oos，每次使用都追加記錄到 research/out/oos_log.md。
> 5. 效能：15m 全期、全幣池模擬一個實驗要在 10 分鐘內跑完。
>
> 產出：程式碼和 research/out/harness_validation.md（開頭 5 行結論）。commit 並 push，不開 PR。

## 附錄 B：研究鐵則（`research/CLAUDE.md`，照抄）

> 1. 不改 src/、config/、tests/、docs/ARCHITECTURE.md（架構稿）、pyproject.toml。可以 import chanedge，新程式全部放 research/。
> 2. 不加任何依賴：只用 pandas、pyarrow（含 numpy）和標準庫。
> 3. 樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27。
> 4. 階段 1 全程不准用 --oos；research/out/oos_log.md 必須保持空的。
> 5. 樣本外每組只跑一次，跑完不准改參數、不准追加實驗。
> 6. 實驗總數上限 60 個。每次執行都要在 research/out/registry.md 追加一行（時間、實驗名、設定摘要）。
> 7. 關卡門檻、樣本切分、實驗上限、驗證門檻一律照原文，不准修改。覺得該改就停下來提問。
> 8. 過不了關卡就停下來回報，絕不為了過關調參數或追加實驗。
> 9. research/cache/ 不 commit（已加進 .gitignore）。
