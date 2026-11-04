# Phase 1 計畫：找優勢（只看樣本內）

規劃者：Opus。執行者：Sonnet。日期 2026-11-04。分支 `research/phase1`（由已通過的 `research/phase0` 建立）。工作目錄 `/workspace/ChanEdge-research`。
原始任務：`/workspace/cc/phase1_prompt.md`（A–E 節；相關原文附在本檔附錄 A，照抄）。研究鐵則：`research/CLAUDE.md`。
裁決紀錄：`/workspace/cc/ph1.decisions.md`。**開工前必讀，裁決優先於本計畫的任何敘述**。本計畫中的「D 編號」指該檔的條目。

本計畫把 prompt 拆成可照做的步驟，並把所有離散選擇事先寫死。**關卡數字、樣本切分、實驗上限 60、階段 0 驗證門檻一律以原文為準**（第 0 節逐字照抄）。執行中若覺得其中任何一條要改：停下，寫 `/workspace/cc/ph1.QUESTION.md`，結束本次工作。要跑本計畫第 4 節清單以外的實驗，也一樣要寫 QUESTION。其他問題或歧義寫 `/workspace/cc/ph1.issue.md`（背景、選項、建議），然後結束本次工作。

---

## 0. 不可改動的條款（原文照抄）

### 0.1 關卡 A

使用者原始計畫（t50u）：

> * A（樣本內，2024-01 → 2025-06，簡化模擬）：要全部同時成立。
>   * 淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500
>   * ≥ 70% 的季度為正
>   * 手續費乘 1.5 倍後仍為正
>   * 相鄰參數同號

階段 1 prompt：

> 關卡 A（全部同時成立才算過）：淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500、≥ 70% 的季度為正、手續費 ×1.5 後仍為正、相鄰參數（±20%）同號。

使用者注意事項第 5 點：

> 關卡 A 的筆數、季度、PF 都用第二種計算。

（第二種 = 「每幣同時最多一筆版」。D10 規定六條全部用第二種算，獨立版照樣報。）

### 0.2 樣本切分

> 全程只看樣本內（2024-01-01 → 2025-06-30），不准用 --oos。

> 所有關卡數字、樣本切分（樣本內 2024-01 → 2025-06、樣本外 2025-07 → 2026-10）、實驗上限 60，一律原文照抄，不得改動。

研究鐵則 3：「樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27。」
研究鐵則 4：「階段 1 全程不准用 --oos；research/out/oos_log.md 必須保持空的。」

### 0.3 實驗上限

> 目標：找出扣成本後有優勢的組合。實驗總數上限 60 個，全部要記進 registry.md。

研究鐵則 6：「實驗總數上限 60 個。每次執行都要在 research/out/registry.md 追加一行（時間、實驗名、設定摘要）。」

### 0.4 階段 0 驗證門檻（本階段不重判，但不得改動）

> 階段 0 的驗證門檻（對上 ≥ 80%、平均 net R 差 ≤ 0.05）

### 0.5 其他照抄條款

- 鐵則 1：「不改 src/、config/、tests/、docs/ARCHITECTURE.md（架構稿）、pyproject.toml。可以 import chanedge，新程式全部放 research/。」
- 鐵則 2：「不加任何依賴：只用 pandas、pyarrow（含 numpy）和標準庫。」
- 鐵則 7：「關卡門檻、樣本切分、實驗上限、驗證門檻一律照原文，不准修改。覺得該改就停下來提問。」
- 鐵則 8：「過不了關卡就停下來回報，絕不為了過關調參數或追加實驗。」
- 鐵則 9：「research/cache/ 不 commit（已加進 .gitignore）。」
- 成本（階段 0 原文）：「taker 5bp、maker 2bp、市價單滑價 1bp。」
- 嚴禁前視（階段 0 原文）：「訊號時間是確認 K 收盤，最早下一根開盤進場。」
- 流程：只 commit，不 push、不開 PR、不用 `--no-verify`。不要開始階段 2。（原 prompt 寫「commit 並 push，不開 PR」；流程規則 E 改成只 commit，以流程規則為準。）

### 0.6 關卡 A 的實作讀法（不改數字，只寫清楚怎麼算）

全部用「每幣同時最多一筆版」（v2，§3.7）的**樣本內已成交交易**計算，比較時用原始浮點數，不先四捨五入：

| 條件 | 實作 |
| --- | --- |
| 淨 R ≥ +0.08 | `mean(net_r) >= 0.08`，net_r 已扣手續費與資金費（§3.5） |
| PF ≥ 1.2 | `sum(net_r[net_r>0]) / abs(sum(net_r[net_r<0])) >= 1.2` |
| 筆數 ≥ 500 | v2 已成交筆數 `>= 500`（限價未成交、確認放棄不算筆數） |
| ≥ 70% 的季度為正 | 6 個季度（2024Q1…2025Q2，依 signal_time 的 UTC 日期）。季度淨 R = 該季 v2 交易 net_r 的總和；> 0 為正；沒有交易的季算不為正。`正季數 / 6 >= 0.70`，等於至少 5 季（D11） |
| 手續費 ×1.5 後仍為正 | `mean(gross_r − 1.5 × fee_r − funding_r) > 0`（只放大手續費，不放大滑價與資金費，D28） |
| 相鄰參數（±20%）同號 | §3.10 對照表中這組設定的每一個鄰居，v2 `mean(net_r) > 0`（D12 P3）。這組設定沒有任何表內參數時，記為「無可測鄰居」，此條視為成立，並在報告中明列（D30） |

---

## 1. 已查明的事實（規劃者已驗證，執行者直接採用）

| 項目 | 事實 |
| --- | --- |
| 階段 0 結果 | `harness_validation.md`：對上 5575/5575 = 100%，r = 0.999913，平均差 −2.708e-04；三個週期都是 single 模式。registry 有 2 個實驗：`p0_validate_current_15m`（`422b2b9d5ca3`）、`p0_perf_15m_all`（`9b64a9e432ea`）。`oos_log.md` 0 位元組。 |
| 既有 YAML 的 config_sha | `donchian_1h_n20` = `84a0bcbc2647`，`donchian_4h_n55` = `5676294a19f3`（用目前的 run.config_sha 算）。改程式後四個既有 YAML 的 sha 都不得改變（D21）。 |
| 訊號快取 | `signals_15m` 365,387 列、`signals_1h` 91,298、`signals_4h` 22,903。`(symbol, time)` 在每個表內都唯一（所以 D9 的同時多訊號規則在實際資料不會觸發，但仍要實作與測試）。`signal_id` 有重複（15m 14 個、1h 1 個），鍵一律用 `(symbol, type, time)`（D25）。 |
| 樣本內在榜訊號數 | 15m 52,346（4h 方向過 23,336，再加波動帶 22,816，再加 JEV ≥ 0.62 是 6,031）；1h 12,928（4h 方向過 5,099）；4h 2,764（4h 方向過 1,314）。**4h 很可能湊不到 500 筆**，這是事實，不得為此改門檻。 |
| 1h/4h 表欄位 | 沒有 atr_pct、jev、gate。`last_up_end`/`last_down_end` 是用 15m 筆算的（階段 0 步驟 7），不是訊號週期的筆（D4 要訊號週期的，見 §3.3）。`atr` 是訊號週期全序列 Wilder ATR(14)。`bias_4h`/`bias_1h` 無缺值。 |
| 筆事件 | 快取只有 `bi_events_15m.parquet`，沒有 1h/4h 的，prep 要補（§3.3）。 |
| bars_15m 快取 | 每個幣只從「第一段在榜起點前 1 天」開始，ATR 暖機只有 96 根。atr15_pct 一律改從 `data/bars/.../15m.parquet` 全序列算（D35）。 |
| Donchian 快取 | 只有 N ∈ {20, 55}。鄰居要 16/24/44/66，prep 要重建（D26）。 |
| 資金費資料 | `data/futures/um/monthly/fundingRate/<BASE>USDT/<BASE>USDT-fundingRate-YYYY-MM.csv`，888 個幣。欄位 `calc_time`（ms，偶有 +1 ms，例如 `1693584000001`）、`funding_interval_hours`（4 或 8）、`last_funding_rate`。BTC 從 2023-09 到 **2026-09**（沒有 2026-10，屬樣本外，本階段不處理，只在報告註明）。樣本內 350 個在榜幣全部有資料夾。 |
| 傳統金融永續 | D15 的 25 個名稱中，有 25 個出現在 2024-01→2026-10 的前 20 名聯集，**但 2024-01-01→2025-06-30 一個都沒有**。 |
| 分群 core | 樣本內 547 天中在榜 ≥ 274 天的幣：BTC、ETH、SOL、XRP、DOGE、1000PEPE、BNB、WIF、SUI、ADA。扣掉 major（BTC、ETH）後 core 是其餘 8 個（D22）。 |
| 波動帶 | `C.settings().volatility.atr_pct_min = 0.001`、`atr_pct_max = 0.03`；gate 在 `pct < min or pct > max` 時否決，所以通過是閉區間 `[min, max]`，缺值否決。 |
| 效能紀錄 | `harness_validation.md` 末尾的「效能關卡」段是人工追加的；`research.validate` 重跑會蓋掉它（階段 0 驗收觀察 1）。`signals_build.log` 開頭沒有小樣本推估（觀察 2）。小樣本 log 在 `research/cache/logs/signals_build_small.log`：BTC/ETH/SOL 各約 608–622 秒，workers=3。全量 `# done total=61423s failed=[]`（含機器暫停）。`p0_perf_15m_all`：97,680 筆，`real 0m14.424s`；驗收者冷快取重量 47.8 秒。環境沒有 `/usr/bin/time`。 |
| YAML | research 內不准 `import yaml`。`C.read_yaml` 是 `yaml.safe_load`，已驗證可讀 JSON 格式（含中文、null、小數）。所以程式產生的 YAML 一律寫成 `json.dumps(..., ensure_ascii=False, indent=2)` 的內容（D38）。 |
| git | 環境沒有 user.email。commit 用 `git -c user.name="Wayne" -c user.email="waynec9172@gmail.com" commit ...`（和階段 0 commit 相同作者）。訊息結尾加 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`（執行者）或依流程給的署名行。pre-commit hook 會擋 src/ config/ tests/ docs/ARCHITECTURE.md pyproject.toml。 |
| 危險操作 | `python -m research.signals build --symbols ...` 會把 **全量快取覆寫成少數幾個幣**（重建全量要 17 小時）。本階段**絕對不要**不加 `--out-dir` 就跑 `signals build`（§5.1 步驟 3）。 |

---

## 2. 檔案總覽

新增（全部在 research/）：

```text
research/
  augment.py                 # 快取補件：bi_events_{1h,4h}、signals_{tf}_aug、funding
  metrics.py                 # 樣本內載入、v2（每幣最多一筆）、指標、季度、分群、關卡 A、晉級條件
  phase1.py                  # gen / runround / neighbors / table / gatea / sanity / audit / final
  perf.py                    # 產生 research/out/harness_perf.md
  experiments/
    p1s1_*.yaml              # S1（prep 產生 22 個；另 2 個是既有的 donchian YAML）
    p1s2_*.yaml              # S2（S2 階段才產生）
    p1s3_*.yaml              # S3（S3 階段才產生）
    neighbors/*.yaml         # 鄰居測試（不算 60）
    p1_manifest.json         # 每輪的清單、沿用關係、鄰居對應（由 phase1.py 維護）
  tests/
    test_htf.py              # 注意事項 2-1：1h/4h 不偷看未來
    test_limit_cost.py       # 注意事項 2-2、2-3：限價單、成本
    test_donchian.py         # 注意事項 2-4：Donchian
    test_funding.py          # 注意事項 3：資金費
    test_onepos.py           # 注意事項 5：每幣同時最多一筆
    test_phase1.py           # 設定鍵、registry、gen、鄰居表、指標、關卡 A
  out/
    harness_perf.md          # 新：效能紀錄（只由 research.perf 產生）
    phase1_S1.md / phase1_S2.md / phase1_S3.md   # 每輪的表（由 phase1.py table 產生）
    phase1.md                # 最終結論（由 phase1.py final 產生，末尾可加人工備註）
```

修改：`research/sim.py`、`research/run.py`、`research/validate.py`、`research/signals.py`、`research/donchian.py`、`research/common.py`、`research/report.py`（只加顯示 funding）、`research/out/harness_validation.md`（改由 validate 重新產生）、既有測試檔（只在必要時調整呼叫方式，不得刪減斷言）。

**不得修改**：`src/`、`config/`、`tests/`、`docs/`（全部）、`pyproject.toml`、`research/CLAUDE.md`、`research/plans/phase0.md`、本計畫的 §0、§3.10、§4（這些是寫死的清單）。

---

## 3. 規格

### 3.1 樣本、季度、分群（`research/common.py`）

```python
IS_QUARTERS = ("2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2")
def quarter_of_series(signal_time: pd.Series) -> pd.Series      # UTC，格式 "2024Q1"
TRADFI_BASES = ("XAU","XAG","XAUT","PAXG","CL","BZ","GOOGL","INTC","MRVL","MSTR","MU","NVDA","TSLA",
                "SAMSUNG","SKHY","SKHYNIX","SNDK","SOXL","SOXS","CRCL","EWY","SPCX","DRAM","KORU","SNXX")   # D15，25 個
MAJORS = ("BTC/USDT", "ETH/USDT")
def core_symbols() -> tuple[str, ...]   # 樣本內（2024-01-01..2025-06-30）在榜天數 >= 274 的幣，扣掉 MAJORS；斷言 547 天
def symbol_group(symbol) -> "major" | "core" | "tradfi" | "other"   # 判斷順序 major → tradfi → core → other
TF_US = {"15m": 900_000_000, "1h": 3_600_000_000, "4h": 14_400_000_000}
BARS_PER_TF = {"15m": 1, "1h": 4, "4h": 16}
```

- 交易屬於哪一段，沿用階段 0：看 `signal_time` 的 UTC 日期（`sample` 欄）。樣本內訊號的交易若持有到 2025-07-01 之後，照算進樣本內，不截斷；每組另報這種交易的筆數 `n_cross`（D34）。
- 研究程式**只**讀 `sample == "IS"` 的列。`metrics.py` 不提供任何讀 OOS 的參數。

### 3.2 過濾鍵（`sim.SimConfig` 與 `sim.select_signals`）

既有 6 個鍵（`in_top20, candidate_only, gate_pass, jev_min, max_cost_r, exclude_reemit`）維持必填。新增 5 個**選填**鍵（D21），`resolved()` 遇到預設值就**不輸出**這個鍵，所以既有 YAML 的 sha 不變：

| 鍵 | 型別／預設 | 意義 | 限制 |
| --- | --- | --- | --- |
| `htf_4h` | bool / false | 多單要 `bias_4h ∈ {up, breakout_up}`，空單要 `∈ {down, breakout_down}` | 只限 source=chan |
| `vol_band` | bool / false | `atr_pct_min <= atr15_pct <= atr_pct_max`（讀 `C.settings().volatility`，斷言 0.001 / 0.03）；atr15_pct 缺值 → 不通過 | 只限 source=chan |
| `exclude_tradfi` | bool / false | `symbol.split("/")[0] not in TRADFI_BASES` | — |
| `min_stop_atr` | num 或 null / null | `R_dist / atr_tf >= 值`（atr_tf = 訊號表的 `atr` 欄，即訊號週期 ATR） | 值 > 0 |
| `min_stop_pct` | num 或 null / null | `R_dist / entry_reference >= 值` | 值 > 0 |

- `htf_4h`、`vol_band`、`exclude_tradfi` 在 `select_signals` 裡篩（訊號層）。被篩掉的訊號不產生 attempt，不佔用（D9）。
- `min_stop_*` 在模擬器裡判定（因為要知道 entry_reference 與停損）：市價與限價在掛單前判定，沒過記 `minstop_rejected`，不下單、不佔用；確認模式在確認完成後判定，沒過記 `abandoned`，佔用到確認那根（D17）。
- `jev_min` 沿用階段 0：只限 chan 15m。
- **S1 硬閘門 = `in_top20: true, htf_4h: true, vol_band: true`**，其餘全關（`candidate_only false, gate_pass false, jev_min null, max_cost_r null, exclude_reemit false`）。三個週期一律相同（注意事項第 4 點、D3）。不用 candidate、1h 衝突、歷史長度、成本過濾。
- `select_signals` 回傳前依 `(symbol, time)` 穩定排序，加一欄 `attempt_id = 0..n-1`（D25 的鍵之外的流水號，方便 trades 與 attempts 對應）。

### 3.3 1h/4h 的結構元素（D4、D36）

管理節奏仍是每根 15m 收盤檢查一次；結構元素跟著訊號週期走：

| 元素 | 15m 訊號 | 1h / 4h 訊號 |
| --- | --- | --- |
| 停損 buffer 的 ATR | `atr`（FeatureBuilder 15m ATR） | `atr`（訊號週期全序列 Wilder ATR(14)） |
| TP1 前高前低（`current` 的 TP1） | `tp_up_end/tp_down_end` = 既有 `last_up_end/last_down_end` | `tp_up_end/tp_down_end` = 訊號週期筆事件中 `confirm_time <= t` 的最後一條同方向筆終點（套用 replace；用 `signals._last_ends`） |
| 棘輪用的筆 | `bi_events_15m` 的 new 事件 | `bi_events_{tf}` 的 new 事件；在 `close_time == confirm_time` 的那根 15m 收盤判定，下一根生效 |
| 反向訊號 | 15m 未過濾的對向訊號 | 訊號週期未過濾的對向訊號（YAML 寫 `opposite_signal.tf = <tf>`） |
| bias 出場 | 1h bias | 1h bias（三個週期都一樣） |
| level_fail（中樞/前極值失守） | 15m 收盤對訊號的 zs_zg/zs_zd/prior_extreme | 15m 收盤對**訊號週期**的 zs_zg/zs_zd/prior_extreme |
| ATR 追蹤 | `atr`（進場時固定） | `atr`（訊號週期，進場時固定） |
| 波動帶的 atr15_pct | 15m 全序列 Wilder ATR(14) / 收盤，在 `close_time == time` 那根 | 同左（15m，不是訊號週期） |
| 4h 方向 | `bias_4h` 欄（close_time ≤ t 的最後一根 4h） | 同左 |

`research/augment.py`（命令 `.venv/bin/python -m research.augment build [--workers 6] [--only bi,sig,funding]`）產生：

1. `research/cache/bi_events_1h.parquet`、`bi_events_4h.parquet`：對每個聯集幣，用 `signals.walk(closed_bars(tf, symbol), tf).bi_events`（完整已收盤序列），加 `symbol` 欄。欄位同 `bi_events_15m`（symbol, confirm_time, event, direction(int8), end_price, established_at）。
2. `research/cache/signals_{15m,1h,4h}_aug.parquet`：**列數與列順序和 `signals_{tf}.parquet` 完全相同**，欄位 `symbol, type, time, atr15_pct, tp_up_end, tp_down_end`。
   - `atr15_pct`：`C.load_bars_df(symbol, "15m")` 全序列，`donchian.wilder_atr_np(high, low, close, 14) / close`，取 `close_time == time` 那根；找不到填 NaN。
   - 15m 表：`tp_*_end` = 原表 `last_*_end`（照抄）。1h/4h 表：用第 1 項的事件算。
3. `research/cache/funding.parquet`（symbol, funding_time[us, UTC], rate, interval_h）與 `funding_months.parquet`（symbol, month "YYYY-MM"，有 CSV 檔的月份）。`funding_time = round(calc_time / 60000) × 60000 ms`（四捨五入到分鐘）。只讀聯集幣。
4. log 寫 `research/cache/logs/augment.log`，每幣一行，最後一行 `# done ... failed=[...]`；有失敗幣就非 0 退出。

`sim.load_signal_table`：chan 來源若有 `signals_{tf}_aug.parquet`，先斷言列數相同、`symbol/type/time` 三欄逐列相等，再把 `atr15_pct, tp_up_end, tp_down_end` 接上。設定用到 `vol_band`，或 tf ∈ {1h, 4h} 且啟用 tp1 時，aug 檔不存在就報錯。模擬器的 TP1 一律讀 `tp_up_end/tp_down_end`；欄不存在時（合成測試）退回 `last_up_end/last_down_end`。15m 兩者相同，所以階段 0 結果不變。

`sim.load_market(bi_tf="15m")`：筆事件改讀 `bi_events_{bi_tf}.parquet`；另載入資金費（§3.5）。`run.py` 傳 `bi_tf = cfg.signals["tf"]`（chan）或 `"15m"`（donchian，不用棘輪）。

### 3.4 進場（D5、D6、D17、D42）

所有模式：訊號在 T（確認 K 收盤）才可知；`j0` = 第一根 `open_time >= T` 的 15m K；任何判斷不得讀 T 之前那根訊號 K 以外的未來資料，也不得讀 j 之後的 K。

| 模式 | 規則 |
| --- | --- |
| `market_next_open` | 不變：j0 開盤成交，價 = open × (1 + side × 1bp)，taker。entry_reference = 訊號 close。 |
| `limit` | 掛單價 L：`signal_close`：L = close − side × offset × atr；`stop_frac`（既有，不用）；**新增 `defend_frac`**：L = close − offset × (close − defending_price)，offset = 0.5 就是收盤價與防守價的中點（D6，用防守價，不用停損價）。有效期：**N 根訊號週期 K**（D5），以時間判定：15m K 的 `open_time < T + N × TF_US[tf]` 才有效。成交：多單 `low < L`、空單 `high > L`（**嚴格穿過**，等於不算）。成交價 = L，maker 2bp，無滑價。entry_reference = L。成交那根照樣做停損檢查，不做停利（沿用階段 0）。過期沒成交 → attempt 狀態 `unfilled`，不產生交易。L 必須在停損有利側（多單 L > stop），否則 `invalid_stop`。 |
| `confirm` | 等 K 根訊號週期 K（D5，K = 1）：等待窗 = `open_time < T + K × TF_US[tf]` 的 15m K。窗內任何一根觸及停損（多單 `low <= stop`）→ `abandoned`（end_time = 那一根的 open_time）。窗的最後一根必須 `close_time == T + K × TF_US[tf]`（缺資料 → `abandoned`）。`require_close_beyond: true` 時最後一根收盤須 ≥ 訊號 close（多單；空單 ≤），否則 `abandoned`。通過後先判 `min_stop_*`（沒過 → `abandoned`），再於下一根 15m 開盤市價進場（taker + 滑價）。entry_reference = 等待窗最後一根收盤。K = 0 不用 confirm 表示，用 `market_next_open`（D13）。 |

`min_stop_*`（§3.2）：市價用 entry_reference = 訊號 close；限價用 L；確認模式用確認收盤。R_dist = side × (entry_reference − stop)，stop 是含 buffer、已取整的結構停損。

### 3.5 成本與資金費（D7、D8、D27、D28）

**手續費與滑價**

| 腿 | 費率 | 滑價 | 成交價 |
| --- | --- | --- | --- |
| 市價進場、確認後進場 | taker 5bp | 1bp | open × (1 ± 1bp) |
| 限價進場 | maker 2bp | 無 | L |
| 所有停損類出場（structure / breakeven / ratchet / trail） | taker 5bp | 1bp | 跳空穿過 → open；否則停損價；再套滑價 |
| 收盤檢視排的下一根開盤出場（opposite / bias_1h / level_fail / time_stop） | taker 5bp | 1bp | open × (1 ∓ 1bp) |
| `current` 的 TP1（50%） | taker 5bp | 1bp | 不變（和 baseline 一致） |
| **固定 R 停利（`fixed_r`）** | **maker 2bp** | **無** | **目標價**。視為掛在目標價的限價單：多單 `high > 目標`、空單 `low < 目標` 才成交（等於不算）；開盤跳空越過目標也成交在目標價（D7） |
| 資料結束仍持有 | taker 5bp | 1bp | 最後一根收盤 |

`fixed_r` 的新語意無條件生效（沒有階段 0 實驗用過 fixed_r，所以不影響既有結果與 sha）。同一根至多一筆出場、停損優先於停利、限價成交那根不做停利：都沿用階段 0。

**資金費（funding_r）**

- 事件：`funding.parquet` 中該幣的 `(funding_time F, rate)`。
- 計入範圍：`entry_time < F <= exit_time`。entry_time 是進場那根 15m 的 open_time，exit_time 是最後一腿出場那根的 open_time（兩者都是階段 0 已有的欄位定義）。等價於 D8 的 `[held_from, held_to)`，`held_from = entry_time + 1µs`、`held_to = exit_time + 1µs`。讀法：在開盤成交的進出場都發生在 F 那一刻之後一點點，所以「在 F 開盤進場」不付 F 的資金費，「在 F 開盤出場」要付；盤中成交同理。
- 權重：`w(F) = Σ 出場腿中 leg_open_time >= F 的比例`（TP1 成交那根之後剩 0.5）。
- mark 價：`close_time == F` 那根 15m K 的收盤；沒有就用 `open_time == F` 那根的開盤；兩者都沒有 → 該事件不計並把 `funding_missing` 設為 True。
- `funding_r = Σ_F w(F) × side × rate(F) × mark(F) / R_dist`（正數 = 成本：多單在正費率時付錢）。
- `funding_missing`：持倉區間 `(entry_time, exit_time]` 經過的任何一個月份，在 `funding_months` 中沒有該幣的檔案 → True。該事件不計（當 0），並在每組報告缺漏筆數。
- 每筆欄位：`gross_r`（含滑價、不含手續費）、`fee_r`、`funding_r`、`n_funding`（計入的事件數）、`funding_missing`、`net_r_ex_funding = gross_r − fee_r`、**`net_r = gross_r − fee_r − funding_r`**（注意事項 3）。
- `validate.py`：結果檔有 `net_r_ex_funding` 欄就用它對 baseline，否則用 `net_r`（D8）。階段 0 的結果檔沒有這欄，所以照舊。
- 手續費 ×1.5：`net_fee15 = gross_r − 1.5 × fee_r − funding_r`（D28）。
- 資料只到 2026-09（樣本外的 2026-10 沒有）。本階段不處理，報告註明，留給階段 2。

### 3.6 模擬器輸出：trades 與 attempts

`sim.simulate(cfg, market, signals, workers=1, opp=None, return_attempts=False)`：`return_attempts=False` 時回傳 `(trades, counters)`（階段 0 介面不變）；True 時回傳 `(trades, attempts, counters)`。`simulate_symbol(..., funding=None, attempts_out=None)` 新增兩個選填參數，回傳值仍是 `(rows, cnt)`；`attempts_out` 是 list 時把每個訊號的 attempt 附加進去。

trades 欄位 = 階段 0 的 `_COLS`（順序不變）＋ 依序追加 `attempt_id, funding_r, net_r_ex_funding, n_funding, funding_missing`，再加 `sample`。`net_r` 的定義改為扣資金費（`funding=None` 時 funding_r = 0，所以既有合成測試數字不變）。

attempts 欄位：`attempt_id, signal_id, symbol, tf, type, side, signal_time, status, end_time, sample`。`status` 與 `end_time`：

| status | 何時 | end_time | 佔用（v2） |
| --- | --- | --- | --- |
| `filled` | 有成交 | trade 的 exit_time | 是 |
| `unfilled` | 限價過期 | 最後一根有效 15m K 的 open_time | 是 |
| `abandoned` | 確認失敗（觸停損、收盤不符、缺資料、確認後 min_stop 不過） | 放棄那根的 open_time | 是 |
| `minstop_rejected` | 市價/限價在掛單前 min_stop 不過 | signal_time | 否 |
| `invalid_stop` | R_dist ≤ 0、ATR 缺值、L 不在停損有利側 | signal_time | 否 |
| `cost_rejected` | max_cost_r 不過（本階段都是 null） | signal_time | 否 |
| `no_entry_bar` / `no_bars` | 沒有進場 K / 沒有 K 線 | signal_time | 否 |

`run.py` 寫 `research/cache/results/<name>.parquet`（trades）、`<name>.attempts.parquet`、`<name>.json`（meta：resolved、config_sha、core_sha、kind、counters、各 status 數、funding_missing 筆數、耗時）。

### 3.7 每幣同時最多一筆（v2，注意事項第 5 點、D9、D43）

`metrics.one_per_symbol(attempts_is, trades_is) -> (trades_v2, attempts_v2)`：

1. 只用樣本內 attempts（`sample == "IS"`），每個幣分開處理，依 `signal_time` 遞增。
2. 同一幣、同一 `signal_time` 有多個 attempt：多空都有 → 這一刻全部跳過（不佔用）；同方向 → 三類（third_*）優先於二類（second_*），再以 `signal_id` 字典序取第一個（Donchian 只有單一類型，直接取 signal_id 最小者）。
3. 只考慮佔用類 status（filled / unfilled / abandoned）；非佔用類直接略過。
4. `busy_until` 初始為 −∞。attempt 的 `signal_time > busy_until`（**嚴格大於**）才收；收下後 `busy_until = end_time`。否則跳過。
5. v2 trades = 收下且 status = filled 的 attempt 對應的交易。v2 成交率 = filled / (filled + unfilled)（只對限價有意義），v2 確認放棄率 = abandoned / 收下數。

獨立版 = 全部樣本內 filled 交易（階段 0 的定義）。兩版都要報。

### 3.8 每組都報的指標（`metrics.summarize`）

對獨立版與 v2 各算一次，全部只用樣本內：

| 指標 | 定義 |
| --- | --- |
| n | 已成交筆數 |
| net_r / gross_r / fee_r / funding_r | 各欄平均（每筆） |
| net_fee15 | `mean(gross_r − 1.5 fee_r − funding_r)` |
| pf | 見 §0.6 |
| win | `mean(net_r > 0)` |
| first_bar_stop | `mean(exit_reason == "structure_stop" & bars_held == 0)`（D23） |
| first_tf_bar_stop | `mean(exit_reason == "structure_stop" & bars_held < BARS_PER_TF[tf])`（參考） |
| mfe_med / mae_med | `median(mfe_r)` / `median(mae_r)` |
| quarters | 6 季各自的 n、sum(net_r)、mean(net_r)；`pos_q` = sum > 0 的季數 |
| long / short | side = +1 / −1 分開的 n、net_r、pf |
| groups | major / core / tradfi / other 各自的 n、net_r、pf |
| fill_rate | filled / (filled + unfilled)（限價）；`abandon_rate`（確認） |
| exit_reasons | 出場原因分布 |
| n_cross | exit_time ≥ 2025-07-01 00:00 UTC 的筆數（D34） |
| n_funding_missing | funding_missing 筆數 |

任何一組 v2 淨 R ≥ +0.5R（使用者原文：「出現每筆 +0.5R、回撤 5%，第一反應應該是懷疑過擬合或程式錯誤」）：在該輪報告標紅「疑似錯誤」，驗收者要抽 20 筆逐筆手算。這不是關卡，不得據此刪改實驗。

### 3.9 晉級規則與關卡 A（注意事項第 6 點、D12、D18、D24、D31）

**晉級條件**（每輪各自判定，用 v2）：

- P1：`net_r > 0`。
- P2：`net_fee15 >= −0.02`（「大幅轉負」= < −0.02R）。
- P3：§3.10 對照表中這組設定的每個鄰居 `net_r > 0`；沒有表內參數 → 「無可測鄰居」，P3 成立（D30）。
- 符合 P1–P3 的組依 v2 net_r 由高到低，同分取 v2 n 多的，再同分取名稱字典序，取最多 2 組。**不到 2 組就照實晉級 1 組或 0 組，不硬湊。**
- Donchian 兩組與 15m+JEV 參考列**不參加晉級**。
- 誰決定：執行者只負責跑實驗、跑鄰居、產生表格（表格可以列 P1–P3 的機械判定），**不寫晉級名單**。驗收者（Opus）自己重算後寫 `/workspace/cc/ph1.promote.S{1,2}.md`（§6）。
- 鄰居觸發（D24）：每一輪，凡是符合 P1 且 P2 的組（S1 含 Donchian、不含 JEV 參考列；S2 含市價列；S3 含基底），執行者都要把它的鄰居跑完。
- 推論：S2 的候選包含市價列（就是 S1 晉級組本身，結果與鄰居都相同），所以 S1 有晉級時 S2 不會是 0 組；同理 S3 的受檢組含基底。「無候選」實際上只會發生在 S1 或 S3。

**關卡 A**（只在 S3 判定，D18）：受檢組 = S3 各組（含沿用列）＋它們的基底（S2 晉級組）。六條照 §0.6，全部用 v2，同時另列獨立版的六條結果；兩版結論不同就標出來（D10）。通過的組依 v2 net_r 取前 3。Donchian 在 S1 另外檢查關卡 A（只用於研究停損條件的判讀）。

**無候選**（注意事項第 10 點）：任何一輪結束時沒有可晉級的組（S3 是沒有組通過關卡 A），就直接寫 `phase1.md` 的「無候選」結論，不再用剩下的名額找補。

### 3.10 相鄰參數對照表（注意事項第 7 點；寫死，事後不可改）

規則：連續參數取 ±20%（照原文「相鄰參數（±20%）」與例子「固定 2R 的鄰居是 1.6R 和 2.4R；ATR 追蹤 2.5 的鄰居是 2.0 和 3.0」）；整數根數取 ±1（例子「限價有效根數 N 的鄰居是 N±1」）。每個鄰居一次只改一個參數，其他保持原值。一組設定的鄰居 = 它用到的所有表內參數的鄰居聯集。

| 代號 | 參數 | 出現在 | 原值 | 鄰居 |
| --- | --- | --- | --- | --- |
| `fixr` | `exit.fixed_r.r` | 出場 fx2 | 2.0 | 1.6、2.4 |
| `fixr` | `exit.fixed_r.r` | 出場 fx3 | 3.0 | 2.4、3.6 |
| `atrm` | `exit.atr_trail.mult` | 出場 at2 | 2.0 | 1.6、2.4 |
| `atrm` | `exit.atr_trail.mult` | 出場 at3 | 3.0 | 2.4、3.6 |
| `limn` | `entry.limit.valid_bars` | 進場 lc、lm | 4 | 3、5 |
| `limf` | `entry.limit.offset`（defend_frac） | 進場 lm | 0.5 | 0.4、0.6 |
| `cfk` | `entry.confirm.bars` | 進場 cf1 | 1 | 0（= `market_next_open`，其他不變）、2 |
| `msa` | `filters.min_stop_atr` | 過濾 ms10a | 1.0 | 0.8、1.2 |
| `msa` | `filters.min_stop_atr` | 過濾 ms13a | 1.3 | 1.04、1.56 |
| `msp` | `filters.min_stop_pct` | 過濾 ms1p | 0.010 | 0.008、0.012 |
| `msp` | `filters.min_stop_pct` | 過濾 ms15p | 0.015 | 0.012、0.018 |
| `jev` | `filters.jev_min` | 過濾 jev055 | 0.55 | 0.44、0.66 |
| `jev` | `filters.jev_min` | 過濾 jev062、S1 參考列 | 0.62 | 0.496、0.744 |
| `dcn` | `signals.donchian_n`（types 跟著改成 `dc{N}_long/short`） | donchian_1h_n20 | 20 | 16、24 |
| `dcn` | `signals.donchian_n` | donchian_4h_n55 | 55 | 44、66 |

**不測鄰居的參數**（D13、D30）：訊號週期（15m/1h/4h 不是彼此的鄰居）；出場種類 cur / rat / opp（沒有數值參數）；TP1 50% 與 1.5R 後備、保本 1R、ATR 追蹤啟動門檻 0、ATR 週期 14、停損 buffer（纏論 0.15 ATR、Donchian 2 ATR）、波動帶 [0.001, 0.03]——這些沿用現行系統或原文、本階段沒有搜尋；開關類（`htf_4h`、`exclude_tradfi`、`require_close_beyond`）；限價 `signal_close` 的價位（offset 0 的 ±20% 仍是 0，只測 `limn`）；成本參數。

**數值格式**：鄰居實驗名 `<原名>__nb_<代號>_<值>`，值的小數點寫成 `p`（`1p6`、`0p496`、`1p04`、`0p008`、`3`、`0`）。YAML 放 `research/experiments/neighbors/`，`description` 以 `NEIGHBOR of <原名>: <參數>=<值>` 開頭。

**沿用**：鄰居設定的 core_sha（resolved 去掉 name、description 後的 sha，§3.11）若等於任何已有結果的實驗（主實驗或鄰居），直接沿用，不重跑（例如 fx2 的 2.4R 鄰居與 fx3 的 2.4R 鄰居；cf1 的 K=0 鄰居 = 同設定的市價列）。沿用關係記在 `p1_manifest.json`。

### 3.11 名額、registry、重跑、檢查（`research/run.py`，D2、D19、D20）

命令：`.venv/bin/python -m research.run <yaml> [--workers 6] [--registry PATH] [--neighbor] [--rerun "<原因>"] [--check]`

- `core_sha(resolved)` = `config_sha` 去掉 `name`、`description` 後的同一算法。`config_sha` 算法不變。
- **60 的算法**：registry 中**不含 `__nb_` 的不同名字**的數量（含階段 0 的 2 個，D2）。新主實驗名且已達 60 → 退出碼 3。
- `--neighbor`：名字必須含 `__nb_`、YAML 必須在 `research/experiments/neighbors/`、description 必須以 `NEIGHBOR of ` 開頭；registry 摘要 = description 的第一段 + `; ` + 一般摘要。反過來，名字含 `__nb_` 卻沒加 `--neighbor` → 退出碼 2。鄰居不算進 60。
- 同名實驗已在 registry：沒加 `--rerun` → 拒絕（退出碼 3）。加 `--rerun "<原因>"` 且 sha 相同 → 允許，覆寫結果，registry 摘要以 `RERUN(<原因>):` 開頭。sha 不同 → 拒絕（改設定一律換新名）。`--rerun` 只限 issue 裁決同意的修 bug（D20）。
- `--check`：在記憶體重算，和 `results/<name>.parquet`（與 attempts 檔，若存在）比對，**不寫 registry、不寫結果**，只在 `research/cache/logs/checks.log` 追加一行，終端只印 `CHECK OK|FAIL <name> trades=<n> attempts=<n> max_abs_diff=<x>`，不印任何績效。比對：列數相同、依 `attempt_id`（舊檔沒有就依 `signal_time, symbol, type`）排序後逐欄比較雙方都有的欄位；數值絕對差 ≤ 1e-9、時間與字串完全相等。舊檔沒有 `net_r_ex_funding` 時，改拿舊 `net_r` 對新 `net_r_ex_funding`，並跳過 `net_r`。一致退出碼 0，不一致 4。
- 每次正式執行（非 `--check`）另在 `research/cache/logs/runs.log` 追加 `time name sha kind(new|rerun|neighbor)`。
- 終端只印名稱、筆數、耗時（不印績效，沿用階段 0）。
- registry 摘要要能看出 tf、過濾（`top20,htf4h,vol,ms>=1.0atr,ms>=1.0%,xtf,jev>=0.62`）、進場（`market` / `limit:close,N4` / `limit:mid0.5,N4` / `confirm:K1`）、出場（`cur` / `rat` / `fx2.0` / `atr2.0` / `opp`）。

### 3.12 槓桿與比較的定義（final 用，D39）

全部用 v2 net_r。只看纏論主實驗（不含參考列、Donchian、鄰居）。

- 週期：對每種出場 e，`max(net(1h,e), net(4h,e)) − net(15m,e)`，取最大者與它的配對。
- 出場：對每個週期 tf，`max_e net(tf,e) − net(tf,cur)`，取最大者。
- 進場：對每個 S2 基底 b，`max(net(b,lc), net(b,lm), net(b,cf1)) − net(b,市價)`，取最大者。
- 過濾：對每個 S3 基底 b，`max_f net(b,f) − net(b)`，取最大者。
- JEV（參考，不排名）：`net(p1s1_15m_cur_jevref) − net(p1s1_15m_cur)`。
- 「改善最多的槓桿」= 上面四項中 Δ 最大的那項；沒跑到的輪次標「未測」。
- 纏論最佳組：有通過關卡 A 時取通過組第 1 名；否則取全部纏論主實驗（不含參考列）中 v2 net_r 最高者。和 `donchian_1h_n20`、`donchian_4h_n55` 並排比較 §3.8 的全部 v2 指標，另列 JEV 參考列。

---

## 4. 實驗清單（注意事項第 8 點；事前排定）

名額總表（主實驗才算 60；鄰居另計、不算）：

| 區段 | 數量 | 累計 |
| --- | --- | --- |
| 階段 0（已在 registry） | 2 | 2 |
| S1 | 24（21 組纏論 + 2 組 Donchian 基準 + 1 組 15m+JEV 參考列，D1） | 26 |
| S2 | 最多 6（2 基底 × 3 種新進場；市價列沿用 S1，D14） | 32 |
| S3 | 最多 16（2 基底 × 最多 8 種過濾；實際會因跳過/沿用而更少） | 48 |
| 備用 | 10（只能依 §4.4 使用） | 58 ≤ 60 |

### 4.1 S1（24 組，prep 產生 YAML，S1 階段才跑）

共同設定（所有 `p1s1_*`）：

```json
{
  "signals": {"source": "chan", "tf": "<tf>", "types": ["second_buy", "third_buy", "second_sell", "third_sell"], "donchian_n": null},
  "filters": {"in_top20": true, "candidate_only": false, "gate_pass": false, "jev_min": null, "max_cost_r": null, "exclude_reemit": false, "htf_4h": true, "vol_band": true},
  "entry": {"mode": "market_next_open"},
  "stop": {"buffer_atr": 0.15, "round_to_tick": true},
  "exit": "<見下表>",
  "costs": {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1}
}
```

出場代號（D29；各模組單獨使用，除表內所列外不加保本或其他出場；都保留初始結構停損）：

| 代號 | 原文 | `exit` 區塊 |
| --- | --- | --- |
| `cur` | 現行近似 | `{"preset": "current", "opposite_signal": {"enabled": true, "tf": "<tf>"}}` |
| `rat` | 不分批只棘輪 | `{"preset": "ratchet_only"}`（保本 1R + 訊號週期筆棘輪） |
| `fx2` | 固定 2R | `{"fixed_r": {"enabled": true, "r": 2.0}}` |
| `fx3` | 固定 3R | `{"fixed_r": {"enabled": true, "r": 3.0}}` |
| `at2` | ATR 追蹤 2 ATR | `{"atr_trail": {"enabled": true, "mult": 2.0, "arm_r": 0.0}}` |
| `at3` | ATR 追蹤 3 ATR | `{"atr_trail": {"enabled": true, "mult": 3.0, "arm_r": 0.0}}` |
| `opp` | 反向訊號 | `{"opposite_signal": {"enabled": true, "tf": "<tf>"}}` |

| # | 名稱 | tf | 出場 | 參加排名 | 表內鄰居 |
| --- | --- | --- | --- | --- | --- |
| 1 | `p1s1_15m_cur` | 15m | cur | 是 | 無 |
| 2 | `p1s1_15m_rat` | 15m | rat | 是 | 無 |
| 3 | `p1s1_15m_fx2` | 15m | fx2 | 是 | fixr 1.6、2.4 |
| 4 | `p1s1_15m_fx3` | 15m | fx3 | 是 | fixr 2.4、3.6 |
| 5 | `p1s1_15m_at2` | 15m | at2 | 是 | atrm 1.6、2.4 |
| 6 | `p1s1_15m_at3` | 15m | at3 | 是 | atrm 2.4、3.6 |
| 7 | `p1s1_15m_opp` | 15m | opp | 是 | 無 |
| 8 | `p1s1_1h_cur` | 1h | cur | 是 | 無 |
| 9 | `p1s1_1h_rat` | 1h | rat | 是 | 無 |
| 10 | `p1s1_1h_fx2` | 1h | fx2 | 是 | fixr 1.6、2.4 |
| 11 | `p1s1_1h_fx3` | 1h | fx3 | 是 | fixr 2.4、3.6 |
| 12 | `p1s1_1h_at2` | 1h | at2 | 是 | atrm 1.6、2.4 |
| 13 | `p1s1_1h_at3` | 1h | at3 | 是 | atrm 2.4、3.6 |
| 14 | `p1s1_1h_opp` | 1h | opp | 是 | 無 |
| 15 | `p1s1_4h_cur` | 4h | cur | 是 | 無 |
| 16 | `p1s1_4h_rat` | 4h | rat | 是 | 無 |
| 17 | `p1s1_4h_fx2` | 4h | fx2 | 是 | fixr 1.6、2.4 |
| 18 | `p1s1_4h_fx3` | 4h | fx3 | 是 | fixr 2.4、3.6 |
| 19 | `p1s1_4h_at2` | 4h | at2 | 是 | atrm 1.6、2.4 |
| 20 | `p1s1_4h_at3` | 4h | at3 | 是 | atrm 2.4、3.6 |
| 21 | `p1s1_4h_opp` | 4h | opp | 是 | 無 |
| 22 | `donchian_1h_n20`（既有 YAML，不改） | 1h | 同 N 反向突破 + 2 ATR 停損；只用前 20 名，不套纏論過濾（D3） | 否（基準） | dcn 16、24 |
| 23 | `donchian_4h_n55`（既有 YAML，不改） | 4h | 同上，N = 55 | 否（基準） | dcn 44、66 |
| 24 | `p1s1_15m_cur_jevref` | 15m | cur；過濾 = S1 硬閘門 + `jev_min: 0.62` | 否（參考列，注意事項第 4 點） | 不跑（D24） |

`description` 由 gen 產生，例如 `S1 1h fx2：硬閘門（4h 方向、波動帶），下一根開盤市價，固定 2R（maker 掛單）`。

### 4.2 S2（參數化；S1 晉級名單代入）

令 `B ∈ PROMOTED(S1)`（0–2 組，來自 `/workspace/cc/ph1.promote.S1.md` 的 `PROMOTED:` 行），`b` = B 去掉 `p1s1_` 的部分（例如 `1h_fx2`）。每個 B 產生 4 列，其中 3 列是新實驗：

| 列 | 名稱 | entry 區塊（其餘全部照抄 B 的 YAML） | 新實驗？ | 表內鄰居（另加 B 本身出場的鄰居） |
| --- | --- | --- | --- | --- |
| 市價 | `B`（沿用 S1 結果，D14） | `{"mode": "market_next_open"}` | 否 | 同 B |
| 限價@收盤 | `p1s2_<b>_lc` | `{"mode": "limit", "limit": {"price": "signal_close", "offset": 0.0, "valid_bars": 4}}` | 是 | limn 3、5 |
| 限價@中點 | `p1s2_<b>_lm` | `{"mode": "limit", "limit": {"price": "defend_frac", "offset": 0.5, "valid_bars": 4}}` | 是 | limn 3、5；limf 0.4、0.6 |
| 等 1 根確認 | `p1s2_<b>_cf1` | `{"mode": "confirm", "confirm": {"bars": 1, "require_close_beyond": true}}` | 是 | cfk 0、2 |

S2 新實驗最多 6 個。S2 候選 = 這 ≤ 8 列（含市價列）。

### 4.3 S3（參數化；S2 晉級名單代入）

令 `B2 ∈ PROMOTED(S2)`（0–2 組；可能是 `p1s1_*` 市價列或 `p1s2_*`），`c` = B2 去掉 `p1s1_` 或 `p1s2_` 前綴（例如 `1h_fx2_lm`、`1h_fx2`）。每個 B2 的列（filters 以外全部照抄 B2）：

| 列 | 名稱 | filters 變更 | 條件 | 表內鄰居（另加 B2 既有參數的鄰居） |
| --- | --- | --- | --- | --- |
| 4h 方向開 | `B2`（沿用，D14） | — | — | 同 B2 |
| 最小停損 1.0 ATR | `p1s3_<c>_ms10a` | `min_stop_atr: 1.0` | — | msa 0.8、1.2 |
| 最小停損 1.3 ATR | `p1s3_<c>_ms13a` | `min_stop_atr: 1.3` | — | msa 1.04、1.56 |
| 最小停損 1% | `p1s3_<c>_ms1p` | `min_stop_pct: 0.01` | — | msp 0.008、0.012 |
| 最小停損 1.5% | `p1s3_<c>_ms15p` | `min_stop_pct: 0.015` | — | msp 0.012、0.018 |
| 4h 方向關 | `p1s3_<c>_no4h` | `htf_4h: false`（波動帶保留） | — | 無新增 |
| 排除傳統金融永續 | `p1s3_<c>_xtf` | `exclude_tradfi: true` | B2 獨立版樣本內交易中 tradfi 幣筆數 > 0 才跑；= 0 就不跑、不佔名額，並在 phase1.md 註明（D15、D41） | 無新增 |
| JEV ≥ 0.55 | `p1s3_<c>_jev055` | `jev_min: 0.55` | 只限 tf = 15m（D16） | jev 0.44、0.66 |
| JEV ≥ 0.62 | `p1s3_<c>_jev062` | `jev_min: 0.62` | 只限 tf = 15m；core_sha 等於已有實驗（例如 B2 = `p1s1_15m_cur` 時就是 `p1s1_15m_cur_jevref`）→ 沿用，不跑 | jev 0.496、0.744 |

S3 新實驗最多 16 個（依目前資料，xtf 一定會跳過，所以實際最多 14）。

### 4.4 備用 10 組（R1–R10）

只能用在：經 issue 裁決（記在 ph1.decisions.md）認定第 4.1–4.3 節某一組的 YAML 寫錯（設定與本計畫不符），必須以新名稱 `<原名>_r1` 重跑同一份「正確」設定。**不得用來新增任何設定**；要新增設定就寫 QUESTION（注意事項第 8 點）。程式 bug 修正後重跑同一設定用 `--rerun`，不佔名額（D20）。

### 4.5 鄰居（不算 60）

依 §3.10 與 §3.9 的觸發規則自動產生，名單記在 manifest 與每輪報告。上限不設，但每一個都要記進 registry（摘要以 NEIGHBOR 開頭）。

---

## 5. 步驟與驗收

### 5.0 通則

- 所有命令在 `/workspace/ChanEdge-research` 執行，Python 一律 `.venv/bin/python`。
- 超過約 2 分鐘的命令用背景執行：`nohup setsid <命令> > research/cache/logs/<名>.log 2>&1 &`，之後用 `tail -n 5 research/cache/logs/<名>.log` 輪詢，直到出現 `# DONE` 或 `# done` 行（每次間隔約 1 分鐘）。不要中途改設計趕時間。
- 開發期間不要用 `research.run` 試跑（會灌 registry）。用 unittest、合成資料或 `--check`。
- 任何一輪開跑後（registry 出現第一個 p1 實驗後）再改 `sim.py` 的模擬語意：先寫 issue，不要自己 `--rerun`。
- 每個 stage 結束前：`git status` 確認只有 research/ 底下的檔案、`research/cache` 沒被加入；commit；把報告寫到流程指定的位置。

### 5.1 prep（注意事項 1–3，以及 S1–S3 需要的全部功能；不跑任何正式實驗）

預估：寫程式 3–5 小時；augment 約 20–40 分鐘；Donchian 重建約 5–15 分鐘。

**步驟 1：效能紀錄搬家（注意事項 1）**
1. `research/validate.py`：刪掉「## 各步驟耗時」與效能段的產生程式，換成一行 `效能與耗時紀錄見 research/out/harness_perf.md（由 research.perf 產生）。`；開頭 5 行格式完全不變（第 5 行仍含「模擬耗時 X 秒」，那是階段 0 寫死的格式）。用 `net_r_ex_funding`（若有）對 baseline。
2. 重新產生：`.venv/bin/python -m research.validate --experiment p0_validate_current_15m`（不寫 registry，覆寫 `harness_validation.md`；這個檔從此只由 validate 產生）。
3. 新增 `research/perf.py`：`.venv/bin/python -m research.perf` 產生 `research/out/harness_perf.md`，內容：
   - `p0_perf_15m_all`：成交數、run.py 內部耗時（json）、`perf.log` 的 bash `real`、門檻 10:00、PASS/FAIL；註明環境沒有 `/usr/bin/time`、驗收者冷快取重量 47.8 秒（階段 0 驗收報告）。
   - 訊號快取建置：小樣本（`signals_build_small.log` 的 3 幣、workers、各幣耗時）、**推估總耗時**、實際總耗時（`signals_build.log` 的 `# done`，註明含機器暫停）。推估法：`est = (Σ小樣本 elapsed / Σ小樣本 w) × Σ全部 w / workers`，w = 該幣 active 範圍（`signals._seg_time_range` 的 lo..hi）內的 15m K 根數，workers 用全量 log 的值（6）。
   - 階段 1 每個實驗的耗時表（讀 `results/*.json` 的 elapsed_s；prep 時只有 2 列）。
   - augment 與 Donchian 重建耗時（讀各自 log）。
4. `research/signals.py`：`build` 加 `--out-dir`（預設 `C.CACHE`）。有 `--symbols` 時，結束後在 log 寫一行 `# estimate full=<n> symbols ≈ <秒> s at workers=<w>`（同上推估法）。另在**現有** `signals_build.log` 末尾追加一行 `# estimate-retro (from signals_build_small.log) ≈ <秒> s at workers=6`（注意事項 1 的「Build log 補上」）。**不要重跑 signals build**。

**步驟 2：程式功能（§3.1–§3.7、§3.11）**
1. `common.py`：§3.1 的常數與函式。
2. `sim.py`：§3.2 過濾鍵與驗證（Donchian `donchian_n ∈ {16, 20, 24, 44, 55, 66}`）；§3.3 aug 合併、`load_market(bi_tf)`、tp 欄；§3.4 進場（`defend_frac`、N/K 以訊號週期計、`min_stop_*`）；§3.5 成本（fixed_r maker）與資金費；§3.6 attempts。`resolved()` 不輸出預設值的新鍵。
3. `run.py`：§3.11 全部（`--neighbor`、`--rerun`、`--check`、60 的算法、attempts 檔、runs.log、摘要）。
4. `donchian.py`：`NS = (16, 20, 24, 44, 55, 66)`。
5. `report.py`：結果檔有 `funding_r` 時多印 `funding=` 平均；其餘不變。
6. `metrics.py`：§3.7、§3.8、§3.9（P1–P3、關卡 A 判定函式）、§3.12。
7. `augment.py`：§3.3。
8. `phase1.py`（介面見步驟 6）。

**步驟 3：快取補件（不是實驗）**
1. `cp research/cache/signals_donchian_1h.parquet research/cache/signals_donchian_1h.p0.parquet`，4h 同樣。然後背景執行 `.venv/bin/python -m research.donchian build`（log：`research/cache/logs/donchian_build.log`，結束要印 `# done`）。
2. 背景執行 `.venv/bin/python -m research.augment build --workers 6`（log：`research/cache/logs/augment.log`）。
3. 產出檢查（寫進報告）：`signals_{tf}_aug` 列數 = 原表；1h/4h `tp_up_end` 非缺值比例；15m 表 `atr15_pct` 與 `atr_pct` 的最大絕對差，以及樣本內在榜訊號中「波動帶判定不同」的筆數（D35，預期 0 或極少；> 1% 就寫 issue）；`bi_events_{1h,4h}` 列數；funding 列數與幣數；Donchian 表的 n 值集合 = {16, 20, 24, 44, 55, 66}。

**步驟 4：單元測試（注意事項 2、3、5；S1 開跑前必須全部通過）**

用 unittest、合成 K 線（`test_sim.py` 的 `make_bars/make_sig/run` 寫法），除特別註明外不讀真實資料。每一項都要有，名稱照寫：

`research/tests/test_htf.py`（2-1：1h/4h 不能偷看未來）
- `test_h1_htf_entry_starts_after_signal_close`：1h 訊號 T = 第 4 根 15m 的 open_time；第 0–3 根（訊號那根 1h 內）放極端高低價（會打到停損與目標）；斷言 entry_time = ot[4]、進場價 = O[4]×(1+1bp)、mfe/mae 只含第 4 根起、沒有在 0–3 根出場。4h 版同樣（第 16 根）。
- `test_h2_htf_signal_time_is_tf_close`（讀快取，快取存在時必須執行）：1h/4h 表每個 time 是 1h/4h 整點、等於某根已收盤 1h/4h K 的 close_time、且 bars_15m 有 open_time == time 的 K（樣本內在榜列）。
- `test_h3_walk_1h_4h_truncation`（讀真實 BTC 1h/4h）：對 3 個截斷點 N，`walk(bars[:N])` 中 time ≤ bars[N-1].close_time 的訊號（id、defending_price）與 bi_events（confirm_time ≤ 截斷點）和 `walk(bars)` 相同。
- `test_h4_bias_uses_closed_4h_only`：合成 bias_4h 表（close_time 00:00 = up、04:00 = down）；`signals._lookup_bias` 在 03:45 → up、03:59:59 → up、04:00 → down。另測 sim 的 1h bias 對齊：1h 收盤 01:00 的 bias 變化只影響 close_time ≥ 01:00 的 15m K。
- `test_h5_htf_filter_and_vol_band`：`select_signals` 的 `htf_4h`（多單 breakout_up 通過、down 擋掉；空單對稱）、`vol_band` 閉區間（等於 0.001、0.03 通過；NaN 擋掉）。
- `test_h6_atr15_pct_at_signal_close`：augment 的 atr15_pct 取 `close_time == T` 那根；把 T 之後的 15m K 改成極端值，結果不變。
- `test_h7_htf_ratchet_uses_tf_bi_at_its_close`：1h new 下降筆事件 confirm_time = 第 k 根 15m 的 close_time；停損只從第 k+1 根起上移。
- `test_h8_htf_tp1_uses_tp_columns`：1h 訊號 `tp_up_end` 與 `last_up_end` 不同時，TP1 用 `tp_up_end`。

`research/tests/test_limit_cost.py`（2-2 限價單、2-3 成本）
- `test_l1_strict_cross_long_short`：多單 low == L 不成交、low < L 成交在 L；空單 high == L 不成交、high > L 成交。
- `test_l2_cancel_after_n_tf_bars`：15m N=2：第 j0+1 根可成交、第 j0+2 根不行；1h N=1：j0..j0+3 有效、j0+4 無效。
- `test_l3_unfilled_not_counted_but_reported`：過期 → trades 沒有這列、attempts status = unfilled、end_time = 最後有效根 open_time；`metrics.summarize` 的 fill_rate = filled/(filled+unfilled)。
- `test_l4_defend_frac_price`：多空都驗 L = close − 0.5×(close − defending)。
- `test_l5_minstop_rejects_before_order`：市價與限價 min_stop 不過 → `minstop_rejected`、不佔用；確認模式 → `abandoned`。
- `test_k1_stop_exits_taker_plus_slippage`：structure / breakeven / ratchet / trail 停損出場，價 = 停損價×(1−1bp)（多單），費率 taker；跳空 → open×(1−1bp)。
- `test_k2_fixed_r_maker_strict`：high == 目標 → 不成交；high > 目標 → 成交在目標價、maker 2bp、無滑價；開盤跳空越過目標 → 成交在目標價、maker。
- `test_k3_tp1_current_stays_taker`：current 的 TP1 仍是 taker + 滑價（數字手算）。
- `test_k4_next_open_exits_taker`：opposite / bias_1h / time_stop 下一根開盤出場 taker + 滑價。
- `test_k5_fee15`：`net_fee15 = gross − 1.5 fee − funding` 手算一致。

`research/tests/test_donchian.py`（2-4）
- `test_d1_breakout_uses_closed_bars_only`：每個 N ∈ NS，在合成序列上：t 的訊號只取決於 t 與之前；改 t 之後的 K 不影響；只取第一根突破。
- `test_d2_entry_next_open`：Donchian 訊號 time = 突破 K 的 close_time → 模擬進場在 open_time == time 的 15m K 開盤 + 滑價。
- `test_d3_rebuilt_tables_keep_20_55`（讀快取）：新表中 n ∈ {20, 55} 的列與 `*.p0.parquet` 完全相同（排序後逐欄）。
- `test_d4_opposite_same_n_only`：反向出場只看同 N 的對向突破。

`research/tests/test_funding.py`（注意事項 3）
- `test_f1_boundaries`：多單在 open_time == F1 的那根開盤進場 → F1 不計；next-open 出場在 open_time == F3 的那根 → F3 要計；中間 F2 要計。
- `test_f2_weight_after_tp1`：TP1 在 open_time == F2 的那根成交 → F2 權重 1；之後的事件權重 0.5。
- `test_f3_sign`：正費率時多單 funding_r > 0、空單 < 0。
- `test_f4_mark_price`：mark = close_time == F 那根的收盤。
- `test_f5_net_definitions`：`net_r = gross − fee − funding`、`net_r_ex_funding = gross − fee`。
- `test_f6_missing_month_flag`：持倉跨過沒有 CSV 的月份 → funding_missing = True。
- `test_f7_calc_time_rounding`：`1693584000001` → 整點。

`research/tests/test_onepos.py`（注意事項 5）
- `test_v1_overlap_skipped_strict`：前一筆 end_time = E；signal_time == E 的訊號跳過、> E 的收下；不同幣互不影響。
- `test_v2_simultaneous_signals`：同時多空 → 全跳過；同方向 → 三類優先。
- `test_v3_rejected_do_not_occupy`：minstop_rejected / invalid_stop 不佔用。
- `test_v4_unfilled_and_abandoned_occupy`：unfilled、abandoned 佔用到各自 end_time。
- `test_v5_only_in_sample`：輸入含 OOS 列時，`metrics.load_is` 與 `one_per_symbol` 的結果完全不含 OOS 列。

`research/tests/test_phase1.py`（設定、registry、gen、鄰居、指標）
- `test_p1_existing_shas_unchanged`：四個既有 YAML 的 config_sha = `422b2b9d5ca3`、`9b64a9e432ea`、`84a0bcbc2647`、`5676294a19f3`。
- `test_p2_new_keys_optional_and_validated`：新鍵可省略；未知鍵仍報錯；`htf_4h/vol_band` 用在 donchian 報錯；`jev_min` 用在 1h 報錯；`min_stop_*` ≤ 0 報錯。
- `test_p3_registry_rules`（暫存 registry）：`__nb_` 名字不算 60；60 個主實驗後第 61 個主實驗被拒、鄰居仍可跑；同名無 `--rerun` 被拒；`--rerun` 同 sha 可、不同 sha 拒；`__nb_` 名字沒加 `--neighbor` 被拒；`--neighbor` 名字沒有 `__nb_` 被拒。
- `test_p4_check_writes_nothing`：`--check` 不改 registry、不改 results（用暫存目錄或合成）。
- `test_p5_gen_s1_matches_plan`：`phase1.gen_specs("S1")` 正好是 §4.1 的 24 個名稱，每個的 tf、exit、filters 與計畫表相同（在測試裡把 §4.1 的表再寫一次當期望值）。
- `test_p6_neighbor_table`：fx2 → 1.6/2.4；fx3 → 2.4/3.6；at3 → 2.4/3.6；lm → limn 3/5 + limf 0.4/0.6；cf1 → K=0 變市價、K=2；ms13a → 1.04/1.56；jev062 → 0.496/0.744；donchian_1h_n20 → 16/24（types 一起改）；cur/rat/opp → 無鄰居。
- `test_p7_quarters_and_gate_a`：合成 v2 交易：6 季中 5 季正 → 季度條件過、4 季正 → 不過；空季算不為正；n = 499 → 筆數不過；PF、淨 R 用原始浮點數比較（0.0799999 不過）；無可測鄰居 → 鄰居條件成立且標記。
- `test_p8_eligibility_ranking`：P1/P2/P3 與排序（同分取 n 多、再取名稱）；符合的只有 1 組時只回傳 1 組。

既有 `test_sim.py`、`test_signals.py`、`test_run_report.py` 必須照樣通過（`test_run_report` 的 60 上限測試若因新算法要調整，只能改呼叫方式，不能刪斷言）。

**步驟 5：回歸（不寫 registry）**
1. `.venv/bin/python -m research.run research/experiments/p0_validate_current_15m.yaml --check` → `CHECK OK`。
2. `.venv/bin/python -m research.run research/experiments/p0_perf_15m_all.yaml --check` → `CHECK OK`。
   （兩者證明新程式在 15m、現行規則、市價這條已驗證路徑上與階段 0 逐筆一致。）

**步驟 6：`research/phase1.py`**

```text
python -m research.phase1 gen S1 [--verify]                 # 寫 22 個 p1s1_*.yaml（JSON 內容）+ manifest；--verify 只比對不寫
python -m research.phase1 gen S2 --promote /workspace/cc/ph1.promote.S1.md
python -m research.phase1 gen S3 --promote /workspace/cc/ph1.promote.S2.md
python -m research.phase1 runround S1|S2|S3 [--workers 6]  # 依 manifest 依序呼叫 run.py（子行程）；跳過沿用列與已有結果者；最後印 "# DONE <round>"
python -m research.phase1 neighbors S1|S2|S3 [--workers 6] [--status]   # 依 §3.9 觸發、§3.10 產生並跑鄰居（run.py --neighbor）；--status 只列缺少的
python -m research.phase1 table S1|S2|S3 [--out PATH]       # 寫 research/out/phase1_S?.md（預設路徑）
python -m research.phase1 gatea [--donchian] [--out PATH]   # 關卡 A 表（S3 受檢組；--donchian 為 S1 的兩組基準）
python -m research.phase1 sanity S1|S2|S3                   # 結構性檢查（§5.2 第 3 步），只印 OK/FAIL 與違規筆數
python -m research.phase1 audit                             # §5.2 第 6 步
python -m research.phase1 final [--promote-dir /workspace/cc] [--out PATH]   # 產生 phase1.md
```

- gen 讀晉級檔的 `PROMOTED:` 行（逗號分隔；`none` 表示 0 組）；沒有這行 → 報錯（執行者寫 issue）。名稱不在上一輪清單 → 報錯。
- gen 檢查每個新 YAML 的 core_sha：等於已有實驗 → 不寫檔，在 manifest 記 `reuse_of`。
- gen 不覆寫已存在且內容不同的 YAML（報錯）。
- manifest 結構：`{"S1": [{"name","tf","exit","entry","filter","ranked","reuse_of"}...], "S2": [... "base"], "S3": [...], "neighbors": {"<主實驗>": [{"param","value","experiment","reuse_of"}]}, "skipped": [{"name","reason"}]}`。
- table 的內容：(a) v2 主表（§3.8 全部單值指標，一列一組，另欄標「參考列／基準／沿用」）；(b) 獨立版主表；(c) v2 各季淨 R 表；(d) 多空表；(e) 分群表；(f) 出場原因表；(g) 鄰居表（每個鄰居的 v2 n、net_r，標沿用）；(h) P1/P2/P3 機械判定與排序（標題寫「機械判定，晉級名單以驗收者的 promote 檔為準」）；(i) 疑似錯誤標記（§3.8 最後一段）；(j) 被跳過的列與原因。數字格式：R 類 `+0.0000`、PF `0.000`、比例 `0.0%`。

**步驟 7：產生 S1 YAML**：`.venv/bin/python -m research.phase1 gen S1`，然後 `--verify`。

**步驟 8：commit**（例：`Phase 1 prep: funding, HTF structure, limit/confirm, one-per-symbol metrics, tests`）。

**prep 驗收（執行者自查，驗收者重跑）**

| # | 指令 | 通過條件 |
| --- | --- | --- |
| P1 | `git diff --name-only main...HEAD -- . ':!research' ':!.gitignore'` | 無輸出 |
| P2 | `.venv/bin/python -m unittest discover -s research/tests -t . -v` | 全部 OK、無 skip；§5.1 步驟 4 列的每個測試名都出現在輸出中 |
| P3 | `.venv/bin/python -m pytest -q` | 全過（數字以終端為準，上次 303 passed） |
| P4 | 步驟 5 兩個 `--check` | 都是 `CHECK OK`，退出碼 0 |
| P5 | `.venv/bin/python -m research.validate --experiment p0_validate_current_15m --out /tmp/hv.md && diff /tmp/hv.md research/out/harness_validation.md && git show 60ccc53:research/out/harness_validation.md \| head -5 \| diff - <(head -5 research/out/harness_validation.md)` | 兩個 diff 都無輸出 |
| P6 | `grep -n "效能關卡\|Elapsed\|各步驟耗時" research/out/harness_validation.md` | 無輸出（只剩指向 harness_perf.md 的一行） |
| P7 | `.venv/bin/python -m research.perf && cat research/out/harness_perf.md` | 有 p0_perf 耗時、小樣本推估、實際總耗時 |
| P8 | `tail -2 research/cache/logs/signals_build.log` | 有 `# estimate-retro` 行 |
| P9 | `git diff 60ccc53 -- research/out/registry.md` 與 `test ! -s research/out/oos_log.md && echo empty` | 無輸出；`empty` |
| P10 | `.venv/bin/python -m research.phase1 gen S1 --verify` | 24 組符合 §4.1 |
| P11 | `.venv/bin/python -m research.phase1 audit` | OK：主實驗 2、鄰居 0 |
| P12 | 步驟 3 第 3 點的產出檢查數字 | 寫在報告；aug 列數相等；Donchian n 集合正確 |
| P13 | `git status --porcelain` 與 `git ls-files research/cache \| wc -l` | 乾淨；0 |

### 5.2 S1（跑 24 組 + 觸發的鄰居；跑完就停）

預估：主實驗約 15–30 分鐘；鄰居約 10–20 分鐘。

1. `nohup setsid .venv/bin/python -m research.phase1 runround S1 --workers 6 > research/cache/logs/S1_run.log 2>&1 &`，輪詢到 `# DONE S1`。
2. `.venv/bin/python -m research.phase1 table S1`（先產生，讓鄰居觸發用的 P1/P2 有數字）。
3. `.venv/bin/python -m research.phase1 sanity S1`，必須 OK：
   - 市價列：所有樣本內交易 `entry_time == signal_time`（違規 0）。
   - 所有交易：`entry_time >= signal_time`、`exit_time >= entry_time`、`r_dist > 0`。
   - `p1s1_15m_cur` 的每筆獨立版交易都能用 `(symbol, type, signal_time)` 在 `p0_perf_15m_all` 找到，且 `net_r_ex_funding` 與 p0 的 `net_r` 最大絕對差 ≤ 1e-9（同一模擬器、訊號是子集）。
   - 樣本內 `funding_missing` 筆數（預期 0；> 0 就列出）。
4. `nohup setsid .venv/bin/python -m research.phase1 neighbors S1 --workers 6 > research/cache/logs/S1_nb.log 2>&1 &`，輪詢到 `# DONE`；`neighbors S1 --status` 缺少數 = 0。
5. 再跑一次 `table S1`（含鄰居）與 `gatea --donchian --out research/out/phase1_S1_donchian_gateA.md`。
6. `.venv/bin/python -m research.phase1 audit` 必須 OK：
   - registry 每一列的名字都有 YAML（主實驗在 `research/experiments/`、鄰居在 `neighbors/`），且 YAML 現在的 config_sha 等於 registry 的 sha。
   - 每個 results 檔都有 registry 列；每個 registry 名字都有 results 檔。
   - registry 資料列數 = `runs.log` 列數。
   - 主實驗不同名字數 ≤ 60；本輪新增的主實驗名稱 ⊆ manifest 該輪清單（不允許清單外）。
   - `oos_log.md` 是 0 位元組。
7. commit（`Phase 1 S1: 24 runs + neighbors`），報告附 S1 v2 主表（淨 R、毛 R、手續費 R、funding_r、PF、筆數）。**不要寫晉級名單，不要跑 S2。**

### 5.3 S2（依 promote.S1 代入；跑完就停）

1. `.venv/bin/python -m research.phase1 gen S2 --promote /workspace/cc/ph1.promote.S1.md`（`PROMOTE_COUNT: 0` 時不會走到這裡）。
2. `runround S2` → `table S2` → `sanity S2`（另加：限價列 `entry_price == entry_reference`、進場費率 maker；確認列 `entry_time >= signal_time + K×TF`）→ `neighbors S2` → `table S2` → `audit` → commit。
3. 不寫晉級名單、不跑 S3。

### 5.4 S3（依 promote.S2 代入；跑完就停）

1. `gen S3 --promote /workspace/cc/ph1.promote.S2.md`。gen 會依 §4.3 的條件自動處理：xtf 的受影響筆數（印出數字，= 0 就記 `skipped`）、非 15m 基底不產生 jev 列、core_sha 相同就沿用。
2. `runround S3` → `table S3` → `sanity S3` → `neighbors S3` → `table S3` → `gatea --out research/out/phase1_S3_gateA.md` → `audit` → commit。
3. 不判定通過名單（由驗收者寫）。

### 5.5 final（不跑新實驗）

1. `.venv/bin/python -m research.phase1 final`，產生 `research/out/phase1.md`；`.venv/bin/python -m research.perf` 更新 harness_perf.md。
2. `phase1.md` 的結構（全部由程式產生；最後一節 `## 執行者備註` 之前加一行 `<!-- generated above; hand-written notes below -->`，只有這行以下可以手寫）：
   - **開頭 5 行（固定格式）**：
     ```
     結論：有候選（K 組通過關卡 A：a, b, c）｜無候選（在 S? 結束，依注意事項第 10 點）
     最佳纏論組 <name>（v2）：淨 R +x.xxxx、PF x.xxx、筆數 n、正季 x/6、手續費×1.5 淨 R +x.xxxx、鄰居 全正｜有負｜無可測
     Donchian 基準（v2）：1h n20 淨 R …、PF …、筆數 …；4h n55 淨 R …、PF …、筆數 …；關卡 A：1h 過｜不過、4h 過｜不過
     改善淨 R 最多的槓桿：<週期｜出場｜進場｜過濾>（Δ淨 R +x.xxxx：<A> → <B>）；其他：…
     實驗用量：主實驗 X / 60（含階段 0 的 2 個）、鄰居 Y 個（不計）；oos_log.md 為空；研究停損判讀：…
     ```
   - 給使用者的摘要（注意事項「階段 1 結束後貼給我」五項）：開頭 5 行；S1 完整 v2 表（淨 R、毛 R、手續費 R、funding_r、PF、筆數）；各輪晉級名單與理由（讀 promote 檔原文）；通過關卡 A 的組與每條門檻的實際數字；纏論最佳組與 Donchian 並排。
   - 全部實驗的表（獨立版與 v2 兩版；含鄰居表）。
   - 通過關卡 A 的最多 3 組 + 穩健性檢查（全部用既有結果計算，不跑新模擬）：鄰居表；各季與各月 v2 淨 R；獨立版 vs v2；多空、分群；去掉 v2 最好的 1% 交易後的淨 R；去掉淨 R 貢獻最大的 3 個幣後的淨 R；手續費 ×1.5 與 ×2 的淨 R；n_cross 與去掉這些交易後的淨 R。
   - 沒有任何一組通過時：明寫「**無候選**」；§3.12 的槓桿表；纏論版與基準策略的比較。不追加實驗。
   - 研究停損判讀（原文：「全部組合都過不了 A（包含 1h、4h 和限價進場）…如果基準趨勢策略能過，改成『趨勢策略為主、纏論當過濾』。基準也不行，就停下來重新想。」）：照實列出 Donchian 的關卡 A 結果；若在 S1 就結束，要寫明「限價進場沒有測到，研究停損條件未完整檢驗」，交使用者判斷（D40）。
   - 註記：傳統金融永續在樣本內從未進前 20 名，S3 的排除檢驗在樣本內無法回答（D15）；資金費資料缺 2026-10（樣本外）；D10 的兩版結論差異；無可測鄰居的組；所有沿用與跳過。
3. commit（`Phase 1: results and conclusion`）。

**final 驗收**：`final --out /tmp/p1.md` 與 commit 版在標記行以上 `diff` 無輸出；開頭 5 行與 promote 檔、gatea 表、table 數字一致；`audit` OK；`oos_log.md` 空；抽 3 組 `--check` OK。

---

## 6. 給驗收者（Opus）

報告只拿來對照，所有數字自己重跑（使用者 t51u 第 3 點）。

**每個 stage 都要做**
1. 範圍：`git diff --name-only main...HEAD -- . ':!research' ':!.gitignore'` 無輸出；`git status` 乾淨；已 commit。
2. 注意事項第 11 點三件事：`test ! -s research/out/oos_log.md`；`python -m research.phase1 audit`（registry 列數 = 實際執行數、每組 YAML 都在 `research/experiments/`、sha 一致）；抽 3 組 `python -m research.run <yaml> --check`（不足 3 組就全抽；S1 建議 15m、1h、4h 各 1 組，至少 1 組是 Donchian 或鄰居）。
3. `python -m research.phase1 table <round> --out /tmp/t.md && diff /tmp/t.md research/out/phase1_<round>.md` 無輸出。
4. 沒有清單外的主實驗（manifest 與 §4 比對）；有 → 寫 `/workspace/cc/ph1.QUESTION.md`。
5. v2 淨 R ≥ +0.5 的組：抽 20 筆逐筆手算（§3.8）。

**prep 另外**：§5.1 的 P1–P13 全部重跑。

**S1、S2 晉級**：自己用 v2 重算 P1–P3（可直接讀 results 與 attempts，用 `research.metrics` 或自寫 pandas）；依 §3.9 排序取最多 2 組，不足不湊。寫 `/workspace/cc/ph1.promote.S1.md`（S2 同理），格式：

```text
# S1 晉級（驗收者判定）
PROMOTED: p1s1_xxx, p1s1_yyy        # 0 組寫 PROMOTED: none
PROMOTE_COUNT: 2
理由：每個候選的 v2 淨 R、手續費×1.5 淨 R、各鄰居淨 R；被排除者的原因（不符 P1/P2/P3 或名次）。
```

**S3**：關卡 A 自己重算（§0.6；v2；附每條實際數字；另列獨立版結果並標出兩版不同處）。寫 `/workspace/cc/ph1.promote.S3.md`：

```text
# S3 關卡 A（驗收者判定）
PASSED_A: a, b, c                   # 依 v2 淨 R 取前 3；沒有寫 PASSED_A: none
PASSED_A_TOTAL: <實際通過總數>
PROMOTE_COUNT: <列出的組數，0–3>
（每組六條門檻的實際數字表）
```

`PROMOTE_COUNT: 0` 時管線會進 final 並寫「無候選」。

---

## 7. 常見錯誤（執行者注意）

- 跑了 `signals build --symbols ...` 沒加 `--out-dir` → 全量快取被覆寫。不要跑。
- 1h/4h 的 TP1 還在用 `last_up_end`（15m 筆）→ 違反 D4。用 `tp_up_end`。
- 1h/4h 的棘輪還在讀 `bi_events_15m` → `load_market(bi_tf=<tf>)`。
- 限價有效根數或確認根數用 15m 根數算 → D5 是訊號週期根數。
- 固定 R 停利還在收 taker + 滑價、或「碰到就成交」→ D7：maker、嚴格穿過、成交在目標價。
- 資金費邊界寫成 `[entry_time, exit_time)` → 是 `(entry_time, exit_time]`（§3.5）。
- net_r 沒扣 funding、或 validate 用了扣 funding 的 net_r 對 baseline。
- v2 用了 OOS 的 attempts，或 `signal_time >= busy_until` 就收（要嚴格大於）。
- 被 min_stop / invalid 擋掉的訊號拿去佔用幣；或 unfilled/abandoned 沒佔用。
- 關卡 A 或晉級用了獨立版數字。
- 把四捨五入後的數字拿去比門檻（例如 0.0799 顯示成 0.080 就算過）。
- 改了 `resolved()` 讓階段 0 的 sha 變了（`test_p1` 會抓到）。
- 執行者自己寫了晉級名單或跑了下一輪。
- 用 `report.py --oos`，或寫任何會輸出樣本外績效的程式。
- 為了過關臨時加過濾、換參數、加實驗。過不了就照實報告。

---

## 附錄 A：原始任務原文（`/workspace/cc/phase1_prompt.md` 節錄，照抄）

### A.1 B 節：階段 1 原始 prompt

```
先讀 docs/agents/README.md 和 research/out/harness_validation.md。用階段 0 的 research/ 工具，不改 src/、config/。全程只看樣本內（2024-01-01 → 2025-06-30），不准用 --oos。

目標：找出扣成本後有優勢的組合。實驗總數上限 60 個，全部要記進 registry.md。

分三輪：
- S1 週期 × 出場（進場固定為下一根開盤市價）：週期 15m、1h、4h；出場用現行近似、不分批只棘輪、固定 2R、固定 3R、ATR 追蹤（2 與 3 ATR）、反向訊號。共 18 組。基準 Donchian 1h、4h 也一起跑。
- S2 取 S1 淨 R 最好的 2 組，換進場方式：市價、限價掛在訊號 K 收盤價、限價掛在收盤價和防守價的中點、等 1 根確認。
- S3 取 S2 最好的 2 組，加過濾：最小停損距離（1.0 / 1.3 ATR、1% / 1.5%）、4h 方向開或關、排除傳統金融永續（XAU、XAG、CL、BZ、股票類）、JEV 分數門檻（只有 15m 能用）。

每組都報：筆數、淨 R、毛 R、PF、勝率、每筆手續費 R、第一根就停損比例、MFE/MAE 中位數、各季淨 R、多空分開、幣種分群。

關卡 A（全部同時成立才算過）：淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500、≥ 70% 的季度為正、手續費 ×1.5 後仍為正、相鄰參數（±20%）同號。

產出 research/out/phase1.md：
- 開頭 5 行結論。
- 全部實驗的表。
- 通過 A 的最多 3 組，附穩健性檢查。
- 若沒有任何一組通過：明確寫「無候選」，列出哪個槓桿讓淨 R 改善最多，以及纏論版和基準策略的比較。不要為了過關再追加實驗。

commit 並 push，不開 PR。
```

（「共 18 組」與 7 種出場 × 3 週期 = 21 的出入，依 D1 全跑 21 組。「commit 並 push」依流程規則 E 改為只 commit。）

### A.2 A 節：關卡與停損條件（節錄）

> 關卡（現在就寫死）
> * A（樣本內，2024-01 → 2025-06，簡化模擬）：要全部同時成立。
>   * 淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500
>   * ≥ 70% 的季度為正
>   * 手續費乘 1.5 倍後仍為正
>   * 相鄰參數同號
> * B（樣本外，2025-07 → 2026-10，只跑一次）：淨 R ≥ +0.05、PF ≥ 1.15、筆數 ≥ 300、≥ 4/6 季為正。
> * C（完整事件回測，兩段都跑）：和簡化模擬差距 ≤ 0.05R；0.5% 風險下 MaxDD ≤ 30%；兩段期末權益都高於期初。
> * D（紙交易 ≥ 10 週或 ≥ 100 筆）：平均 R > 0；滑價和成交率在假設範圍內；對帳無異常。
>
> 停損條件（研究本身的停損）
> * 全部組合都過不了 A（包含 1h、4h 和限價進場）：在合理成本下，纏論買賣點當進場訊號沒有優勢。
>   * 如果基準趨勢策略能過，改成「趨勢策略為主、纏論當過濾」。
>   * 基準也不行，就停下來重新想。
>
> 這只是示意。如果某組設定在回測裡出現每筆 +0.5R、回撤 5%，第一反應應該是懷疑過擬合或程式錯誤，而不是開心。

### A.3 D 節：使用者的階段 1 注意事項（全文）

> 階段 0 的結果很好：對上 100%、相關係數 0.9999。不過要記得，這只證明了「15m、現行規則、市價進場」這一條路徑模擬得準。階段 1 會用到的 1h/4h 訊號、限價進場、新出場規則和 Donchian 基準，都還沒驗過。下面的注意事項大多在補這個缺口。
>
> ## 開跑前（不算進 60 次實驗）
>
> 1. **先修 Opus 提的第一點。** 效能紀錄改寫到 `research/out/harness_perf.md`，`harness_validation.md` 只讓 `research.validate` 產生。Build log 補上用小樣本推估的總耗時。
> 2. **用合成 K 線為新功能補單元測試。** 每項都要有測試，而且要在 S1 開跑前完成：
>    - **1h/4h 不能偷看未來**：訊號時間等於該週期確認 K 的收盤；15m 價格路徑要從那根收盤之後才開始；4h 方向只能用已收盤的 4h。
>    - **限價單**：價格必須嚴格穿過限價才算成交，剛好碰到不算；過了有效根數就取消；被取消的單不算進筆數，但成交率要另外報。
>    - **成本**：停損出場一律 taker 加滑價。只有固定 R 停利是掛單、而且價格嚴格穿過時，才用 maker 費率。
>    - **Donchian 基準**：突破判斷只用已收盤 K，下一根開盤進場。
> 3. **加資金費率。** 1h/4h 的單常持有超過 8 小時，資金費率就不能忽略。每筆加一欄 funding_r（用 vision 的 fundingRate 估算），淨 R 要扣掉它。
>
> ## 讓比較公平
>
> 4. **S1 每個週期都用同一套過濾。** 1h/4h 沒有 JEV 分數，所以 S1 的主比較一律是「只套硬閘門（4h 方向、波動帶），不用 JEV」。15m 加上 JEV ≥ 0.62 另列一行當參考，不參加排名。不然 15m 有 JEV 加持、1h 沒有，比較就失真。
> 5. **關卡 A 以「每幣同時最多一筆」為準。** 每個訊號獨立算的話，同一個幣會有很多筆重疊的單。這些單高度相關，會把筆數灌大、讓季度看起來很穩。請把兩種結果都報出來：
>    - 獨立版
>    - 每幣同時最多一筆版：前一筆還沒出場，後面的訊號就跳過
>
>    關卡 A 的筆數、季度、PF 都用第二種計算。
> 6. **晉級不能只看淨 R 第一名。** S1 → S2、S2 → S3 各取兩組時，候選必須先滿足：淨 R > 0、相鄰參數同號、手續費 ×1.5 後仍不是大幅轉負。符合的不到兩組，就照實只晉級一組或零組，不要硬湊。
> 7. **離散選項的「相鄰參數」要事先定好。** 例如固定 2R 的鄰居是 1.6R 和 2.4R；ATR 追蹤 2.5 的鄰居是 2.0 和 3.0；限價有效根數 N 的鄰居是 N±1。在 S1 開跑前把這份對照表寫進計畫，事後不能改。鄰居測試不算進 60 次。
>
> ## 紀律
>
> 8. **實驗名額要先排好。** S1 是 18 組加 2 組基準，S2 約 8 組，S3 約 20 組。開跑前在 `research/plans/phase1.md` 列出完整清單和每組的設定，留約 10 組備用。超出清單的實驗要先問你。
> 9. **每輪結束都停一次。** S1、S2、S3 各自跑完，Sonnet 都要停下來，由 Opus 對照第 6 點確認晉級名單，再開下一輪。不能三輪一次跑完再挑。
> 10. **只要一次「無候選」，階段 1 就結束。** 任何一輪結束時沒有可晉級的組，就直接寫 `phase1.md` 的「無候選」結論，不再用剩下的名額找補。
> 11. **驗收時 Opus 要多檢查三件事：**
>    - `oos_log.md` 是空的。
>    - registry 的筆數等於實際跑過的實驗數。
>    - 每一組的設定都能在 `research/experiments/` 找到，並且能重跑出相同數字。抽 3 組實際重跑。
>
> ## 階段 1 結束後貼給我
>
> - `phase1.md` 開頭 5 行結論
> - S1 的完整表：每幣最多一筆版，含淨 R、毛 R、手續費 R、funding_r、PF、筆數
> - 各輪的晉級名單和理由
> - 通過關卡 A 的組（如果有），附每一條門檻的實際數字
> - 纏論版最好的一組和 Donchian 基準的並排比較
>
> 我判讀完，再給你階段 2 要注意的地方。

（第 8 點「S2 約 8 組、S3 約 20 組」：本計畫 S2 是 8 列比較、其中 6 組新實驗；S3 每基底 8 種過濾、最多 16 組新實驗；備用 10 組；總數 ≤ 58，見 §4。）
