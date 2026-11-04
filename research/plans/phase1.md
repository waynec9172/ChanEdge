# Phase 1 計畫：找優勢（只看樣本內）

規劃者：Opus。執行者：Sonnet。日期 2026-11-04。分支 `research/phase1`（由已通過的 `research/phase0` 建立）。工作目錄 `/workspace/ChanEdge-research`。
原始任務：`/workspace/cc/phase1_prompt.md`（A–E 節；相關原文附在本檔附錄 A，照抄）。研究鐵則：`research/CLAUDE.md`。
裁決紀錄：`/workspace/cc/ph1.decisions.md`。**開工前必讀，裁決優先於本計畫的任何敘述**。本計畫中的「D 編號」指該檔的條目。
**§8「補充規則（使用者 2026-11-04 裁示）」優先於本計畫其他各節與 D1–D43**；被它取代的句子在原處標「→ §8.x」，索引見 §8.11。S1 開跑前要先做完 §8.8 的補件。

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
| 相鄰參數（±20%）同號 | §3.10 對照表中這組設定的每一個鄰居，v2 `mean(net_r) > 0`（D12 P3）。~~這組設定沒有任何表內參數時，記為「無可測鄰居」，此條視為成立，並在報告中明列（D30）~~ → §8.2：沒有其他表內參數的組用 sbuf 0.12、0.18 當鄰居；缺鄰居結果算不成立 |

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

**不得修改**：`src/`、`config/`、`tests/`、`docs/`（全部）、`pyproject.toml`、`research/CLAUDE.md`、`research/plans/phase0.md`、本計畫的 §0、§3.10、§4、§8（這些是寫死的清單；§8 是使用者裁示，`research/plans/phase1_decisions.md` 是裁決副本，執行者都不改）。

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
- 資料只到 2026-09（樣本外的 2026-10 沒有）。~~本階段不處理，報告註明，留給階段 2。~~ → §8.7：先從 vision 下載，抓不到就用補值（只扣不加），補值事件與 `funding_missing` 的新意思見 §8.7 B。

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
| n_funding_missing | funding_missing 筆數（→ §8.7：= 資金費補值的受影響筆數，另報 basis = market 的筆數） |
| net_slip3 | `mean(net_r − 2 × slip_r)`（→ §8.1：滑價 ×3 淨 R，參考，不是關卡） |

任何一組 v2 淨 R ≥ +0.5R（使用者原文：「出現每筆 +0.5R、回撤 5%，第一反應應該是懷疑過擬合或程式錯誤」）：在該輪報告標紅「疑似錯誤」，驗收者要抽 20 筆逐筆手算。這不是關卡，不得據此刪改實驗。

### 3.9 晉級規則與關卡 A（注意事項第 6 點、D12、D18、D24、D31）

**晉級條件**（每輪各自判定，用 v2）：

- P1：`net_r > 0`。
- P2：`net_fee15 >= −0.02`（「大幅轉負」= < −0.02R）。
- P3：§3.10 對照表中這組設定的每個鄰居 `net_r > 0`；~~沒有表內參數 → 「無可測鄰居」，P3 成立（D30）。~~ → §8.2：沒有其他表內參數的組用 sbuf 0.12、0.18；缺鄰居結果 → P3 不成立。
- 符合 P1–P3 的組依 v2 net_r 由高到低，同分取 v2 n 多的，再同分取名稱字典序，取最多 2 組。**不到 2 組就照實晉級 1 組或 0 組，不硬湊。**
- Donchian 兩組與 15m+JEV 參考列**不參加晉級**。4h 七組也不參加（→ §8.5）。
- 誰決定：執行者只負責跑實驗、跑鄰居、產生表格（表格可以列 P1–P3 的機械判定），**不寫晉級名單**。驗收者（Opus）自己重算後寫 `/workspace/cc/ph1.promote.S{1,2}.md`（§6）。
- 鄰居觸發（D24）：每一輪，凡是符合 P1 且 P2 的組（S1 含 Donchian、不含 JEV 參考列；S2 含市價列；S3 含基底），執行者都要把它的鄰居跑完。（→ §8.4 第 4 點：S1 另加 v2 毛 R ≥ +0.05 各組的 sbuf 鄰居；→ §8.5：4h 參考列不跑。）
- 推論：S2 的候選包含市價列（就是 S1 晉級組本身，結果與鄰居都相同），所以 S1 有晉級時 S2 不會是 0 組；同理 S3 的受檢組含基底。「無候選」實際上只會發生在 S1 或 S3。（→ §8.4：走 fallback 時市價列不是 S2 候選，S2 也可能無候選。）

**關卡 A**（只在 S3 判定，D18）：受檢組 = S3 各組（含沿用列）＋它們的基底（S2 晉級組）。六條照 §0.6，全部用 v2，同時另列獨立版的六條結果；兩版結論不同就標出來（D10）。通過的組依 v2 net_r 取前 3。Donchian 在 S1 另外檢查關卡 A（只用於研究停損條件的判讀）。

**無候選**（注意事項第 10 點）：任何一輪結束時沒有可晉級的組（S3 是沒有組通過關卡 A），就直接寫 `phase1.md` 的「無候選」結論，不再用剩下的名額找補。（→ §8.4：S1 沒有正常晉級時，先照使用者裁示的限價 fallback 判定；連 fallback 都是 0 組才算 S1 無候選。）

### 3.10 相鄰參數對照表（注意事項第 7 點；寫死，事後不可改）

**→ §8.2（使用者 2026-11-04 裁示，S1 開跑前更新）：本表新增 `sbuf`（`stop.buffer_atr` 0.15 → 0.12、0.18），下方「不測鄰居的參數」段落也已改寫。以 §8.2 的更新版對照表為準。**

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

**不測鄰居的參數**（D13、D30）：訊號週期（15m/1h/4h 不是彼此的鄰居）；出場種類 cur / rat / opp（沒有數值參數）；TP1 50% 與 1.5R 後備、保本 1R、ATR 追蹤啟動門檻 0、ATR 週期 14、停損 buffer（~~纏論 0.15 ATR~~ → §8.2 改為 sbuf 鄰居、Donchian 2 ATR）、波動帶 [0.001, 0.03]——這些沿用現行系統或原文、本階段沒有搜尋；開關類（`htf_4h`、`exclude_tradfi`、`require_close_beyond`）；限價 `signal_close` 的價位（offset 0 的 ±20% 仍是 0，只測 `limn`）；成本參數。

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
- → §8.5：4h 七組是參考列。週期槓桿主值只用 `net(1h,e) − net(15m,e)`，4h − 15m 另列參考；最佳纏論組不含 4h，另列「4h 最佳（參考）」。

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

→ §8.2、§8.5（使用者 2026-11-04 裁示）：#1、2、7、8、9、14 的「表內鄰居」改為 sbuf 0.12、0.18；#15–21（4h）的「參加排名」改為「否（參考：4h）」，不跑鄰居。其他欄與 YAML 內容不變。

### 4.2 S2（參數化；S1 晉級名單代入）

令 `B ∈ PROMOTED(S1)`（0–2 組，來自 `/workspace/cc/ph1.promote.S1.md` 的 `PROMOTED:` 行），`b` = B 去掉 `p1s1_` 的部分（例如 `1h_fx2`）。每個 B 產生 4 列，其中 3 列是新實驗：

| 列 | 名稱 | entry 區塊（其餘全部照抄 B 的 YAML） | 新實驗？ | 表內鄰居（另加 B 本身出場的鄰居） |
| --- | --- | --- | --- | --- |
| 市價 | `B`（沿用 S1 結果，D14） | `{"mode": "market_next_open"}` | 否 | 同 B |
| 限價@收盤 | `p1s2_<b>_lc` | `{"mode": "limit", "limit": {"price": "signal_close", "offset": 0.0, "valid_bars": 4}}` | 是 | limn 3、5 |
| 限價@中點 | `p1s2_<b>_lm` | `{"mode": "limit", "limit": {"price": "defend_frac", "offset": 0.5, "valid_bars": 4}}` | 是 | limn 3、5；limf 0.4、0.6 |
| 等 1 根確認 | `p1s2_<b>_cf1` | `{"mode": "confirm", "confirm": {"bars": 1, "require_close_beyond": true}}` | 是 | cfk 0、2 |

S2 新實驗最多 6 個。S2 候選 = 這 ≤ 8 列（含市價列）。（→ §8.4 第 6 點：S1 走 fallback 時，每個基底只有 lc、lm 兩列新實驗，市價列只當對照、不是候選，最多 4 個。）

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
- `test_p5_gen_s1_matches_plan`：`phase1.gen_specs("S1")` 正好是 §4.1 的 24 個名稱，每個的 tf、exit、filters 與計畫表相同（在測試裡把 §4.1 的表再寫一次當期望值）。（→ §8.5 第 6 點：4h 七組 ranked = false。）
- `test_p6_neighbor_table`：fx2 → 1.6/2.4；fx3 → 2.4/3.6；at3 → 2.4/3.6；lm → limn 3/5 + limf 0.4/0.6；cf1 → K=0 變市價、K=2；ms13a → 1.04/1.56；jev062 → 0.496/0.744；donchian_1h_n20 → 16/24（types 一起改）；~~cur/rat/opp → 無鄰居~~。（→ §8.2 測試更新：cur/rat/opp → sbuf 0.12/0.18 等。）
- `test_p7_quarters_and_gate_a`：合成 v2 交易：6 季中 5 季正 → 季度條件過、4 季正 → 不過；空季算不為正；n = 499 → 筆數不過；PF、淨 R 用原始浮點數比較（0.0799999 不過）；~~無可測鄰居 → 鄰居條件成立且標記~~。（→ §8.2 測試更新：缺鄰居結果 → 第 6 條不成立並標記。）
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

0. 先做完 §8.8 的補件（使用者 2026-11-04 裁示），A1–A9 全部通過並 commit，才做第 1 步。
1. `nohup setsid .venv/bin/python -m research.phase1 runround S1 --workers 6 > research/cache/logs/S1_run.log 2>&1 &`，輪詢到 `# DONE S1`。
2. `.venv/bin/python -m research.phase1 table S1`（先產生，讓鄰居觸發用的 P1/P2 有數字）。
3. `.venv/bin/python -m research.phase1 sanity S1`，必須 OK：
   - 市價列：所有樣本內交易 `entry_time == signal_time`（違規 0）。
   - 所有交易：`entry_time >= signal_time`、`exit_time >= entry_time`、`r_dist > 0`。
   - `p1s1_15m_cur` 的每筆獨立版交易都能用 `(symbol, type, signal_time)` 在 `p0_perf_15m_all` 找到，且 `net_r_ex_funding` 與 p0 的 `net_r` 最大絕對差 ≤ 1e-9（同一模擬器、訊號是子集）。
   - 樣本內 `funding_missing` 筆數（預期 0；> 0 就列出）。
4. `nohup setsid .venv/bin/python -m research.phase1 neighbors S1 --workers 6 > research/cache/logs/S1_nb.log 2>&1 &`，輪詢到 `# DONE`；`neighbors S1 --status` 缺少數 = 0。（→ §8.2、§8.4 第 4 點：含 cur/rat/opp 的 sbuf 鄰居，以及 15m、1h 中 v2 毛 R ≥ +0.05 各組的 sbuf 鄰居；4h 參考列不跑。）
5. 再跑一次 `table S1`（含鄰居）與 `gatea --donchian --out research/out/phase1_S1_donchian_gateA.md`。
6. `.venv/bin/python -m research.phase1 audit` 必須 OK：
   - registry 每一列的名字都有 YAML（主實驗在 `research/experiments/`、鄰居在 `neighbors/`），且 YAML 現在的 config_sha 等於 registry 的 sha。
   - 每個 results 檔都有 registry 列；每個 registry 名字都有 results 檔。
   - registry 資料列數 = `runs.log` 列數。
   - 主實驗不同名字數 ≤ 60；本輪新增的主實驗名稱 ⊆ manifest 該輪清單（不允許清單外）。
   - `oos_log.md` 是 0 位元組。
7. commit（`Phase 1 S1: 24 runs + neighbors`），報告附 S1 v2 主表（淨 R、毛 R、手續費 R、funding_r、PF、筆數；→ §8.1 加滑價×3 淨 R 參考欄）與 §8.8 第 4 點的 fallback 機械判定表。**不要寫晉級名單，不要跑 S2。**

### 5.3 S2（依 promote.S1 代入；跑完就停）

1. `.venv/bin/python -m research.phase1 gen S2 --promote /workspace/cc/ph1.promote.S1.md`（`PROMOTE_COUNT: 0` 時不會走到這裡）。（→ §8.4、§8.9：gen 依 promote 檔的 `MODE:` 行決定列；`MODE: fallback` 時每個基底只有 lc、lm。）
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
     （→ §8.2：第 2 行的鄰居欄只剩「全正｜有負」；→ §8.5：最佳纏論組不含 4h。）
   - 給使用者的摘要（注意事項「階段 1 結束後貼給我」五項）：開頭 5 行；S1 完整 v2 表（淨 R、毛 R、手續費 R、funding_r、PF、筆數；→ §8.1 加滑價×3 淨 R 參考欄，4h 列標參考）；各輪晉級名單與理由（讀 promote 檔原文）；通過關卡 A 的組與每條門檻的實際數字；纏論最佳組與 Donchian 並排。
   - 全部實驗的表（獨立版與 v2 兩版；含鄰居表）。
   - 通過關卡 A 的最多 3 組 + 穩健性檢查（全部用既有結果計算，不跑新模擬）：鄰居表；各季與各月 v2 淨 R；獨立版 vs v2；多空、分群；去掉 v2 最好的 1% 交易後的淨 R；去掉淨 R 貢獻最大的 3 個幣後的淨 R；手續費 ×1.5 與 ×2 的淨 R；n_cross 與去掉這些交易後的淨 R。
   - 沒有任何一組通過時：明寫「**無候選**」；§3.12 的槓桿表；纏論版與基準策略的比較。不追加實驗。
   - 研究停損判讀（原文：「全部組合都過不了 A（包含 1h、4h 和限價進場）…如果基準趨勢策略能過，改成『趨勢策略為主、纏論當過濾』。基準也不行，就停下來重新想。」）：照實列出 Donchian 的關卡 A 結果；~~若在 S1 就結束，要寫明「限價進場沒有測到，研究停損條件未完整檢驗」，交使用者判斷（D40）。~~ → §8.4 第 10 點。
   - 註記：傳統金融永續在樣本內從未進前 20 名，S3 的排除檢驗在樣本內無法回答（D15）；資金費資料缺 2026-10（樣本外）；D10 的兩版結論差異；~~無可測鄰居的組~~；所有沿用與跳過。（→ §8.6：改寫成「階段 2 主結果排除這 25 個幣，含它們的版本另列參考」；→ §8.7：改寫成 2026-10 資金費的下載結果與補值受影響筆數；→ §8.2：不再有無可測鄰居的組。）
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

**S1、S2 晉級**：自己用 v2 重算 P1–P3（可直接讀 results 與 attempts，用 `research.metrics` 或自寫 pandas）；依 §3.9 排序取最多 2 組，不足不湊。寫 `/workspace/cc/ph1.promote.S1.md`（S2 同理），格式：（→ §8.9：**S1 的晉級檔改用 §8.9 的格式**，加 `MODE:` 行；S1 正常晉級 0 組時先判 §8.4 的 fallback，`PROMOTE_COUNT` 包含 fallback 晉級的組數並註明，只有連 fallback 都沒有才寫 0。下面的格式只用於 S2。）

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

`PROMOTE_COUNT: 0` 時管線會進 final 並寫「無候選」。（→ §8.4 第 8、9 點：S1 只有在 fallback 也是 0 組時才寫 0。）

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

---

## 8. 補充規則（使用者 2026-11-04 裁示）

來源：`/workspace/cc/ph1.user_amend.md`（使用者 2026-11-04 17:59 原文，§8.0 全文照抄）。本節由規劃者（Opus）把七條規則轉成可照做的規格；落實時規劃者做的選擇記為 D44–D53（`/workspace/cc/ph1.decisions.md`。本次 commit 時的副本在 `research/plans/phase1_decisions.md`，之後若有新裁決，以 `/workspace/cc/` 那份為準）。

- **優先順序**：本節 > 本計畫其他各節 > D1–D43。被本節取代或補充的舊敘述，已在原處標「→ §8.x」，完整索引見 §8.11。
- **沒有改動**：關卡 A、B 的數字，樣本切分，實驗上限 60，階段 0 驗證門檻。名額核算見 §8.10（最多 58 ≤ 60），所以不寫 QUESTION。
- 本節的程式部分在 **S1 第一個實驗之前**做完（§8.8）。

### 8.0 使用者原文（照抄）

```text
（使用者 2026-11-04 17:59 原文）
## Opus 的四個判斷

**1. 手續費 ×1.5 只放大手續費：可以，但滑價壓力要另外報。**

關卡 A 原文寫的就是「手續費 ×1.5」，照這個判定沒問題。不過 1bp 的滑價對山寨幣的停損出場偏樂觀。建議每組多報一欄「滑價 ×3」的淨 R，只當參考資訊，不當關卡。

**2. 「無可測鄰居就直接算過」：不要這樣，每組都有可測的鄰居。**

所有組都用 `stop_buffer_atr` 0.15，這本身就是一個參數。沒有其他可調參數的組，就用停損緩衝 0.12 和 0.18 當鄰居，一樣要同號才算過。這樣現行規則、反向訊號出場這類組才不會比別組容易過關。鄰居測試照之前說的，不算進 60 次。

**3. 跨過 2025-07-01 的單算樣本內，另外報筆數和拿掉後的淨 R：同意。**

**4. S1 沒有候選時，限價進場等於完全沒測到：這點要現在就決定。**

限價進場主要是省成本，在 1% 停損下每筆約 +0.08R。所以市價版小虧的組，換成限價有可能轉正。我之前說「一次無候選就結束」，在這裡太嚴了。改成以下規則，寫進 phase1.md：

> S1 沒有任何一組通過時，S2 仍然要跑，條件是：取「每幣最多一筆版」裡毛 R ≥ +0.05、而且停損緩衝鄰居同號的組，最多 2 組，只測限價進場。沒有組達到毛 R +0.05，階段 1 才結束。

要求毛 R ≥ +0.05，是因為限價最多只能省下大約這個量級的成本，毛 R 更低的組不可能靠限價轉正。

## 查到的三件事

**4h 湊不到 500 筆：同意不放寬門檻。** 那 7 組 4h 就當參考資訊，不用改分配。

**傳統金融永續：現在就定，階段 2 主結果排除它們。** 它們在樣本內從沒進過前 20 名，但 2026 年的樣本外裡有（XAU、XAG、CL 等都出現過）。沒在樣本內測過的東西，不該算進樣本外的判定。
- 階段 2 的主結果：排除這 25 個幣。
- 包含它們的版本：另列一行，只當參考資訊。
這條現在先寫進 phase1.md，不要等看到樣本外結果再決定。

**資金費率只到 2026-09：會影響階段 2。** 階段 1 用不到，但樣本外一路到 2026-10-27，最後近兩個月沒有資金費率資料。依序處理：
1. 現在已經 11 月初，先試著從 Binance vision 下載 2026-10 的月檔或日檔。
2. 抓不到的話，用規則補：缺資料的月份，每筆單用該幣前 3 個月資金費率絕對值的中位數當成本（只扣，不加）。另外報受影響的筆數。
這條也是現在就寫進計畫。

## 其他
- 補充規則請 Opus 另外 commit 成 phase1.md 的補充段落，再讓 Sonnet 開跑 S1。
```

### 8.1 每組加報「滑價 ×3」淨 R（參考欄，不是關卡）

原文：

> 建議每組多報一欄「滑價 ×3」的淨 R，只當參考資訊，不當關卡。

規格（D44）：

1. 模擬器每筆交易新增欄位 `slip_r`，意思是「這筆交易實際付出的滑價（1bp 那一份）換算成 R」：
   - 進場項：市價進場與確認後進場是 `O[jf] × slip`；限價進場是 0。
   - 出場項：每一條有套滑價的腿（所有停損類、下一根開盤出場、`current` 的 TP1、資料結束）是 `w × raw × slip`。raw 是套滑價前的價格（停損價、跳空時的 open、TP1 目標價或 open、最後收盤）。`fixed_r` 的 maker 腿是 0。
   - `slip_r = (進場項 + Σ 出場項) / R_dist`，一定 ≥ 0。等價寫法：`[side × (p_entry − O[jf]) + Σ w × side × (raw − p)] / R_dist`。
   - slip = `costs.slippage_bps / 1e4`（本階段 1bp）。
2. 指標 `net_slip3 = mean(net_r − 2 × slip_r)`。意思是把每一條有滑價的腿從 1bp 改成 3bp（多付 2 倍）。
   - 手續費不重算。手續費以成交價計，差異約是 taker 費率 × 2bp，量級 < 1e-4R，忽略。
   - 出場路徑不變：停損、停利、保本、追蹤都以 entry_reference 和 K 線價位判定，不讀含滑價的成交價；`max_cost_r` 本階段都是 null。所以用 3bp 重跑會得到同樣的出場，這一欄等於 3bp 重跑的淨 R，不必另跑實驗。
3. 報在：每輪表的 v2 主表與獨立版主表（每一列，含 Donchian、參考列）；`gatea` 表（欄名「滑價×3 淨 R（參考，不是關卡）」）；`phase1.md` 的 S1 完整表、纏論最佳組與 Donchian 的並排比較。鄰居表不用加。
4. **不參與任何判定**：P1–P3、關卡 A、§8.4 的 fallback、排序都不看 `net_slip3`。
5. 欄位順序：trades 在 `funding_missing` 之後依序追加 `slip_r`、`n_funding_imputed`（§8.7），然後才是 `sample`。`--check` 只比雙方都有的欄，所以階段 0 的結果檔不受影響。
6. 測試 `research/tests/test_limit_cost.py::test_k6_slip_r_and_slip3`：
   - (a) 市價進場 + 結構停損：slip_r 手算 = (O×1bp + stop×1bp) / R；跳空停損時用 open。
   - (b) 限價進場 + fixed_r 出場：slip_r = 0。
   - (c) `current` 有 TP1：TP1 腿以權重 0.5 計入。
   - (d) 同一組合成資料改用 `slippage_bps: 3` 重跑：每筆的 exit_time、exit_reason 完全相同，`net_r` 與 1bp 版的 `net_r − 2 × slip_r` 絕對差 < 1e-4。

### 8.2 相鄰參數：每組都要有可測的鄰居（取消 D30 的「無可測鄰居算過」）

原文：

> 所有組都用 `stop_buffer_atr` 0.15，這本身就是一個參數。沒有其他可調參數的組，就用停損緩衝 0.12 和 0.18 當鄰居，一樣要同號才算過。這樣現行規則、反向訊號出場這類組才不會比別組容易過關。鄰居測試照之前說的，不算進 60 次。

規格（D45）：

1. 「表內參數」指下表中 `sbuf` 以外的代號：fixr、atrm、limn、limf、cfk、msa、msp、jev、dcn。一組設定的表內參數 = 它自己用到的，加上繼承的（S2 列繼承基底 B 的出場參數，S3 列繼承 B2 的全部表內參數），照 §3.10、§4.2、§4.3 原規則。
2. 表內參數為空的組，鄰居 = `sbuf` 0.12 與 0.18 兩個。表內參數不為空的組照舊，**不加** sbuf。（§8.4 的 fallback 另有規定，那是 fallback 的條件，不是 P3 的鄰居。）
3. 「同號」= 每個鄰居 v2 `mean(net_r) > 0`，用在晉級 P3 與關卡 A 第 6 條，和其他鄰居一樣。
   - **不再有「無可測鄰居（成立）」**。程式裡刪掉這個分支。
   - 任何一組缺了必要的鄰居結果：P3 與關卡 A 第 6 條記「缺鄰居結果」，判為**不成立**。執行者要補跑到 `neighbors <輪> --status` 的缺少數 = 0。
4. 會用 sbuf 的組（依目前清單）：
   - S1：`p1s1_15m_cur`、`p1s1_15m_rat`、`p1s1_15m_opp`、`p1s1_1h_cur`、`p1s1_1h_rat`、`p1s1_1h_opp`。4h 的 cur/rat/opp 是參考列（§8.5），不跑鄰居。`p1s1_15m_cur_jevref` 有 jev 參數而且是參考列，照 D24 不跑。
   - S2：市價列就是 B 本身，鄰居同 B。`lc`、`lm`、`cf1` 列有 limn、limf、cfk，不加 sbuf。
   - S3：B2 沒有表內參數時，`no4h`、`xtf` 兩列（它們本身也沒有表內參數）用 sbuf。ms*、jev* 列有自己的參數，不加。
   - Donchian：有 dcn，不加 sbuf（Donchian 的 2 ATR 停損照舊不測）。
5. YAML：照抄原組，只把 `stop.buffer_atr` 改成字面值 `0.12` 或 `0.18`。直接寫這兩個數，不要用 0.15 × 0.8 去算，免得浮點尾數讓 sha 和名稱對不上。
   - 名稱：`<原名>__nb_sbuf_0p12`、`<原名>__nb_sbuf_0p18`。
   - description：`NEIGHBOR of <原名>: stop.buffer_atr=0.12`（0.18 同理）。
   - 模擬器的初始結構停損與棘輪停損都讀這個鍵（`sim.py` 的 `buffer` 與 `entry_buffer`），所以鄰居兩者一起變。這是同一個參數，照這樣做。
6. 不算進 60。命名、registry、沿用規則照 §3.10、§3.11、D19。
7. 觸發照 D24（符合 P1 且 P2 的組才跑），另加 §8.4 第 4 點的 fallback 觸發。

**更新版相鄰參數對照表**（取代 §3.10 的表；§3.10 的其他規則、數值格式、沿用照舊）：

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
| **`sbuf`** | **`stop.buffer_atr`** | **表內參數為空的纏論組（第 2 點）；§8.4 的 fallback 候選** | **0.15** | **0.12、0.18** |

**更新版「不測鄰居的參數」**（取代 §3.10 同名段落）：訊號週期（15m/1h/4h 不是彼此的鄰居）；出場種類 cur/rat/opp 本身（沒有數值參數，改由 sbuf 代表，見第 2 點）；TP1 50% 與 1.5R 後備、保本 1R、ATR 追蹤啟動門檻 0、ATR 週期 14、Donchian 停損 buffer 2 ATR、波動帶 [0.001, 0.03]；開關類（`htf_4h`、`exclude_tradfi`、`require_close_beyond`）；限價 `signal_close` 的價位（offset 0 的 ±20% 仍是 0，只測 `limn`）；成本參數。纏論停損 buffer 0.15 不再列在這裡：第 2 點的組與 fallback 候選要測它，其他組不測。

**測試更新**（`research/tests/test_phase1.py`）：

- `test_p6_neighbor_table`：原本「cur/rat/opp → 無鄰居」改成「cur/rat/opp（15m、1h）→ sbuf 0.12、0.18」。另加：fx2 → 只有 fixr 1.6、2.4（沒有 sbuf）；lc（基底 cur）→ 只有 limn 3、5；S3 no4h（B2 = cur 市價列）→ sbuf；S3 ms13a（B2 = cur）→ 只有 msa；sbuf 鄰居 YAML 的 `stop.buffer_atr` 正好是 0.12、0.18。其他原斷言保留。
- `test_p7_quarters_and_gate_a`：「無可測鄰居 → 鄰居條件成立且標記」改成「缺鄰居結果 → 第 6 條不成立並標記」。其他原斷言保留。

### 8.3 跨過 2025-07-01 的交易：照 D34，不改

原文：

> **3. 跨過 2025-07-01 的單算樣本內，另外報筆數和拿掉後的淨 R：同意。**

規格：照 D34 與 §3.1、§3.8、§5.5，沒有新規則。

- 樣本內訊號的交易，持有到 2025-07-01 之後照算樣本內，不截斷。
- 每組報 `n_cross`（§3.8）。
- final 的穩健性檢查列出去掉這些交易後的 v2 淨 R（§5.5）。

### 8.4 S1 沒有組晉級時：限價進場 fallback（取代 D40）

原文：

> S1 沒有任何一組通過時，S2 仍然要跑，條件是：取「每幣最多一筆版」裡毛 R ≥ +0.05、而且停損緩衝鄰居同號的組，最多 2 組，只測限價進場。沒有組達到毛 R +0.05，階段 1 才結束。

> 要求毛 R ≥ +0.05，是因為限價最多只能省下大約這個量級的成本，毛 R 更低的組不可能靠限價轉正。

規格（D46、D47）：

1. **觸發**：驗收者依 §3.9 判定 S1 的正常晉級（P1–P3）是 0 組。正常晉級有 1 組以上，就不用 fallback，也不拿 fallback 補第 2 個名額。
2. **候選池**：S1 參加排名的纏論主實驗，也就是 15m 與 1h 的 14 組。4h 七組是參考列（§8.5）；Donchian、JEV 參考列照舊不參加。
3. **條件**（全部用 v2、樣本內、原始浮點數比較）：
   - F1：`mean(gross_r) >= 0.05`。gross_r 已含滑價，不含手續費與資金費（§3.5）。
   - F2：這組的 sbuf 0.12 與 0.18 兩個鄰居，v2 `mean(gross_r) > 0`。「同號」指和這組在同一個量（毛 R；F1 已要求它 > 0）上同號。
   - 所有 F1 組都要測 sbuf，包括 fx/at 這種有其他參數的組。它們原本的 fixr/atrm 鄰居在 fallback 裡不看。
   - 不再看 P1–P3（就是因為都不符合才走到這裡），也不看 net_slip3。
4. **S1 執行者要預先跑好**：S1 的 `neighbors` 步驟除了 D24 的觸發，另外對候選池中 v2 `gross_r >= 0.05` 的每一組都跑 sbuf 0.12 與 0.18（不論 P1、P2；core_sha 相同就沿用）。這樣驗收者寫 promote 檔時不用回頭補跑。`neighbors S1 --status` 要把這些也算進「應有」。
5. **選組**：符合 F1 與 F2 的組，依 v2 `mean(net_r)` 由高到低（同分取 v2 n 多的，再同分取名稱字典序），取最多 2 組。只有 1 組就照實取 1 組；0 組就照第 9 點結束。排序用淨 R，沿用原 prompt「取 S1 淨 R 最好的 2 組」；限價省下的成本大致相同，市價淨 R 較高的組比較接近轉正。
6. **S2（fallback）只測限價進場**：
   - 每個 fallback 基底 B 只產生 2 列新實驗：`p1s2_<b>_lc`、`p1s2_<b>_lm`（設定照 §4.2）。不產生 `cf1`。
   - 市價列 B 只列在表上當對照，**不是 S2 候選**。它已經不符合 S1 的 P1–P3，結果也不會變。
   - S2 候選 = 這些 lc、lm 列。晉級照 §3.9 的 P1–P3。鄰居照 §4.2：limn、limf，加上 B 的出場參數 fixr/atrm（若有）。lc、lm 有表內參數，不加 sbuf。
   - fallback 的 S2 新實驗最多 4 個。
7. S2 晉級 ≥ 1 組 → S3 照 §4.3 跑，基底就是這些 lc/lm 列。S2 晉級 0 組 → 在 S2「無候選」，進 final。
8. **晉級檔 `/workspace/cc/ph1.promote.S1.md`**（驗收者寫，格式見 §8.9）：
   - `PROMOTE_COUNT` 要**包含 fallback 晉級的組數**，並在同一行註明是 fallback。
   - **只有連 fallback 都沒有組時，才寫 `PROMOTE_COUNT: 0`**。
   - 管線用 `grep -o 'PROMOTE_COUNT: *[0-9]*' … | tail -1` 讀數字，所以 `PROMOTE_COUNT` 這個字串在檔案裡只能出現一次（理由段不要再寫這個字），數字要緊接在冒號和空格後面。
9. **階段 1 在 S1 結束的條件**：正常晉級 0 組，而且 fallback 也 0 組（沒有組達到毛 R +0.05，或達到的組 sbuf 鄰居毛 R 不是全正）。這時 promote.S1 寫 `PROMOTED: none`、`MODE: none`、`PROMOTE_COUNT: 0`。
10. **final 的研究停損判讀**（取代 D40 與 §5.5 對應句）：
    - 在 S1 結束：寫明「S1 無組符合晉級條件；限價 fallback 也無組符合」。列出每個 F1 組和它兩個 sbuf 鄰居的 v2 毛 R；沒有 F1 組就寫「沒有任何一組 v2 毛 R ≥ +0.05」。再寫「限價進場沒有實際模擬；依使用者裁示，毛 R 低於 +0.05 的組不可能靠限價轉正」。照實列出 Donchian 的關卡 A 結果，交使用者判斷。
    - 走 fallback 後在 S2 或 S3 結束：寫明「限價進場只在 fallback 組上測過（列名稱）；確認進場（cf1）沒有測」。
    - 正常路徑：照 §5.5。
11. manifest：S2 的每列加 `"fallback": true|false`。`gen S2` 依 promote 檔的 `MODE:` 行決定產生哪些列（§8.8 第 4 點）。

### 8.5 4h 七組：只當參考資訊，分配不變

原文：

> **4h 湊不到 500 筆：同意不放寬門檻。** 那 7 組 4h 就當參考資訊，不用改分配。

規格（D48）：

1. `p1s1_4h_cur`、`_rat`、`_fx2`、`_fx3`、`_at2`、`_at3`、`_opp` 照 §4.1 跑，仍是 S1 的 24 組之一，名額不變。每張表照樣列出，標「參考（4h）」。§4.1 表 #15–21 的「參加排名」改為「否（參考：4h，§8.5）」；manifest 寫 `ranked: false`。
2. 不參加 S1 晉級，也不在 §8.4 的 fallback 候選池；不觸發鄰居（同 JEV 參考列）。
3. 關卡 A 的門檻不改（筆數 ≥ 500 照舊）。4h 組不會走到 S3，所以不判關卡 A。表上照樣列 v2 筆數，讓使用者看到差多少。
4. §3.12：週期槓桿的主值改成 `net(1h,e) − net(15m,e)`，另列一欄「4h − 15m（參考）」。「改善最多的槓桿」只用主值比較。最佳纏論組（§3.12 最後一點、開頭第 2 行）從參加排名的組裡取，不含 4h；另列一行「4h 最佳（參考）」。
5. Donchian 4h n55 不受影響：照舊是基準，照舊單獨檢查關卡 A（D18）。
6. 測試：`test_p5_gen_s1_matches_plan` 的期望表把 4h 七組的 ranked 改成 false。

### 8.6 階段 2：主結果排除 25 個傳統金融永續

原文：

> **傳統金融永續：現在就定，階段 2 主結果排除它們。** 它們在樣本內從沒進過前 20 名，但 2026 年的樣本外裡有（XAU、XAG、CL 等都出現過）。沒在樣本內測過的東西，不該算進樣本外的判定。
> - 階段 2 的主結果：排除這 25 個幣。
> - 包含它們的版本：另列一行，只當參考資訊。
> 這條現在先寫進 phase1.md，不要等看到樣本外結果再決定。

規格（D49；本階段不寫任何樣本外程式，只把規則記下來給階段 2）：

1. 名單 = `common.TRADFI_BASES`（D15 的 25 個），以 `symbol.split("/")[0]` 比對。
2. 階段 2 的關卡 B 判定（淨 R、PF、筆數、季度，全部 v2）只用 base 不在名單內的交易。另列一行「含傳統金融永續（參考）」，用全部交易，不參加判定。
3. 做法：把同一次樣本外執行的結果事後拆成兩版，不另跑實驗，所以不違反「樣本外只跑一次」。in_top20 用的是固定的每日榜單、v2 每個幣分開算，所以事後去掉這些幣，結果等於設定 `exclude_tradfi: true`。受檢組本身若已經是 `exclude_tradfi: true`，兩版相同，照實註明。
4. 階段 1 不受影響（樣本內這些幣從沒進過前 20 名，§1）。D15 末句「要不要在階段 2 排除它們…留給使用者決定」已由這條決定。final 的註記改寫成這條規則。

### 8.7 資金費率缺 2026-10：先下載，抓不到就照規則補

原文：

> **資金費率只到 2026-09：會影響階段 2。** 階段 1 用不到，但樣本外一路到 2026-10-27，最後近兩個月沒有資金費率資料。依序處理：
> 1. 現在已經 11 月初，先試著從 Binance vision 下載 2026-10 的月檔或日檔。
> 2. 抓不到的話，用規則補：缺資料的月份，每筆單用該幣前 3 個月資金費率絕對值的中位數當成本（只扣，不加）。另外報受影響的筆數。

**時機**：在 §8.8 的 S1 前補件做（建議）；最晚在階段 2 開始前完成。這條只動資料快取和資金費計算；樣本內月份都有資料時，樣本內結果不變（§8.8 的 A 表要證明）。

規格（D50、D51）：

**A. 下載（新命令 `.venv/bin/python -m research.augment fetch-funding`）**

1. 目標：聯集幣（和 `build_funding` 同一份）的每個 (幣, 月份 M)，M ∈ 2025-07 … 2026-10，條件是該幣在 M 有任何 15m K，而且本機 `data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-<YYYY-MM>.csv` 不存在。預期幾乎都是 2026-10。
2. 月檔：`https://data.binance.vision/data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-<YYYY-MM>.zip`，以及同名的 `.zip.CHECKSUM`。
3. 日檔：先用 `https://data.binance.vision/data/futures/um/daily/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-10-01.zip` 探測一次。404 就整個跳過日檔（log 記 `# daily not available`）。可用時，對月檔 404 的 (幣, M)，逐日抓 M 的第 1 天到「該幣在 M 的最後一根 15m K 那天」。**全部日子都抓到才算這個月有資料**；缺任何一天，整個月走 B 的補值（只做月份層級，不做日層級拼接），log 記缺幾天。
4. 下載檔是不受信任的資料：
   - 放在新的空目錄 `research/cache/vision_dl/`（`monthly/<SYM>/`、`daily/<SYM>/`）。
   - 只用標準庫 `urllib.request`（timeout 30 秒、最多重試 2 次、依序或最多 4 個並行、User-Agent 寫 `ChanEdge-research`，不帶任何個人資訊）和 `zipfile`。
   - 驗證：zip 的 sha256 = CHECKSUM 檔第一欄；zip 只有一個成員，檔名正好是 `<SYM>-fundingRate-<YYYY-MM>.csv`（日檔是 `-<YYYY-MM-DD>.csv`），不含路徑；pandas 讀出的欄位正好是 `calc_time, funding_interval_hours, last_funding_rate`；所有 calc_time 都在該月（日）內。任一項不符就當作沒抓到，log 記原因。
   - 不執行、不 import 任何下載內容。**不寫入 `data/`**：`data` 是指向 `/workspace/ChanEdge/data` 的連結，主工作樹也在用，保持原樣。
5. log：`research/cache/logs/funding_fetch.log`。每 (幣, 月) 一行 `<SYM> <M> local|dl_monthly|dl_daily|missing <原因>`，最後一行 `# done dl_monthly=<n> dl_daily=<n> missing=<n>`。網路完全不通也不算失敗：全部記 missing，走 B。

**B. 合併與補值（`.venv/bin/python -m research.augment build --only funding`）**

1. 來源依序：`data/` 的 CSV（local）→ `vision_dl` 的月檔（dl_monthly）→ 日檔（dl_daily）。同一 (幣, 月) 只取第一個有的來源。`funding_months.parquet` 加欄 `source`（local / dl_monthly / dl_daily / imputed）與 `basis`（只有 imputed 列有值：own / market）。
2. 範圍：該幣第一根到最後一根 15m K 之間、沒有任何來源的月份，樣本內外都算。這些 (幣, M) 照下面補：
   - 補值費率 `imp = median(|rate|)`，取該幣在 M 之前 3 個日曆月（M−3、M−2、M−1，以 funding_time 判定）內的**真實**事件，不含補出來的事件。`basis = own`。
   - 這 3 個月都沒有真實事件（例如 M 才上市）：改用同一個窗內**所有聯集幣**真實事件的 `median(|rate|)`，`basis = market`，另外報這種月份數與受影響筆數。
   - 補值事件的時間：`F = M 的 00:00 UTC + k × h 小時`（k = 0, 1, …），F 早於下個月 00:00，而且 F ≤ 該幣最後一根 15m 的 close_time。h = 該幣在 M 之前最後一筆真實事件的 `funding_interval_hours`；沒有就用 8。
   - 寫進 `funding.parquet`：`rate = imp`、`interval_h = h`，新欄 `imputed = True`（真實事件是 False）。
3. 模擬器（`sim.funding_for_trade`）：真實事件照 §3.5（`w × side × rate × mark / R`）。**補值事件一律算成本**：`w × imp × mark / R`，不乘 side，多空都扣，永遠 ≥ 0（「只扣，不加」）。計入邊界、權重、mark 價照 §3.5。
4. 每筆欄位：
   - `funding_missing`：持倉區間 `(entry_time, exit_time]` 經過任何 source 為 imputed（或完全沒有資料）的月份 → True。意思從「有缺漏、當 0」改成「受影響、用了補值」。
   - 新欄 `n_funding_imputed`：計入的補值事件數。
5. 報告：每組 v2 與獨立版都報「受影響筆數」，也就是 `funding_missing` 為 True 的筆數（§3.8 的 `n_funding_missing`），另報其中 basis = market 的筆數。`augment.log` 末尾報各 source 的 (幣, 月) 數。
6. 測試（`research/tests/test_funding.py`，合成資料，不連網）：
   - `test_f8_imputed_events_cost_only`：補值事件讓多單、空單的 funding_r 都 > 0；真實事件照舊依 side 有正有負。
   - `test_f9_impute_prior3_median_and_schedule`：07–09 月有真實費率、10 月缺 → imp = 07–09 月 |rate| 的中位數；事件時間依最後一筆真實事件的 interval_h（4h 與 8h 各一例）；3 個月都沒有 → 用全市場中位數並記 basis = market；補值不會拿補值來算。
   - `test_f10_fetch_validation`：用本機合成的 zip 測 `fetch-funding` 的驗證函式：CHECKSUM 不符、成員名不符、含路徑、欄位不符、calc_time 不在該月 → 全部拒收。
   - 既有的 `test_f6_missing_month_flag` 保留（意思照第 4 點）。

### 8.8 執行者：S1 開跑前補件（不跑任何正式實驗）

prep 開工時本節還不存在，所以本節不是 prep 的通過條件。**S1 階段的第一件事是把本節做完**（prep 已經做了的部分只要驗證），全部通過、commit 之後，才開始 §5.2 的第 1 步。在 registry 出現第一個 p1 實驗以前做的修改，不受 §5.0「開跑後改 sim 要先寫 issue」限制。

1. `sim.py`：§8.1 的 `slip_r`；§8.7 B 第 3、4 點的補值事件與欄位。
2. `augment.py`：§8.7 A（`fetch-funding`）與 B（來源合併、補值、`source`/`basis`/`imputed` 欄）。然後依序執行 `fetch-funding`、`augment build --only funding`。
3. `metrics.py`：
   - `summarize` 加 `net_slip3`、受影響筆數（含 basis = market 的筆數）。
   - P3 與關卡 A 第 6 條刪掉「無可測鄰居」分支（§8.2 第 3 點）。
   - 新增 `fallback_s1(...)`：回傳 §8.4 第 3、5 點的機械判定（候選池、F1、F2、排序、前 2 組）。
4. `phase1.py`：
   - 鄰居表照 §8.2；S1 的鄰居觸發另加 §8.4 第 4 點；`neighbors --status` 跟著算。
   - `gen S1`：4h 七組 `ranked: false`（只改 manifest，YAML 內容不變）。
   - `gen S2`：讀 promote 檔的 `MODE:` 行。`normal` → 每個基底 lc、lm、cf1；`fallback` → 每個基底只有 lc、lm，manifest 標 `fallback: true`，市價列標「對照，非候選」；缺 `MODE:` 行或值不是 normal / fallback → 報錯（執行者寫 issue）。
   - `table`：v2 與獨立版主表加「滑價×3 淨 R（參考）」欄；4h 列標「參考（4h）」；(h) 的 P1/P2/P3 機械判定不再有「無可測」；S1 表另加 (k)「fallback 機械判定（只在正常晉級 0 組時使用；以驗收者 promote 檔為準）」：候選池 14 組各自的 v2 毛 R、F1、兩個 sbuf 鄰居的 v2 毛 R、F2、排序。
   - `gatea`：加「滑價×3 淨 R（參考，不是關卡）」欄；鄰居條件不再有「無可測」。
   - `final`：§8.4 第 10 點、§8.5 第 4 點、§8.6 第 4 點、§8.7 的報告文字；開頭第 2 行的鄰居欄只剩「全正｜有負」。
5. 測試：§8.1 第 6 點、§8.2 的測試更新、§8.5 第 6 點、§8.7 B 第 6 點。另加：
   - `test_phase1.py::test_p9_promote_mode_parsing`：normal / fallback / 缺行 / 錯值；fallback 只產生 lc、lm。
   - `test_phase1.py::test_p10_fallback_s1`：F1 邊界用原始浮點數（0.0499999 不過、0.05 過）；F2 要兩個 sbuf 都 > 0；同分排序規則；最多 2 組；候選池不含 4h、Donchian、JEV 參考列。
6. commit：`Phase 1 prep: user amendments (slip x3, stop-buffer neighbours, limit fallback, 4h reference, funding fill)`。

**補件驗收**（執行者自查；S1 驗收者全部重跑）：

| # | 指令 | 通過條件 |
| --- | --- | --- |
| A1 | `.venv/bin/python -m unittest discover -s research/tests -t . -v` | 全部 OK、無 skip；本節列的每個新測試名都出現在輸出中 |
| A2 | `.venv/bin/python -m pytest -q` | 全過 |
| A3 | `.venv/bin/python -m research.run research/experiments/p0_validate_current_15m.yaml --check` 與 `… p0_perf_15m_all.yaml --check` | 都是 `CHECK OK`，退出碼 0 |
| A4 | `.venv/bin/python -m research.phase1 gen S1 --verify` | 24 組符合 §4.1，4h 七組 ranked = false |
| A5 | `tail -1 research/cache/logs/funding_fetch.log`；`tail -3 research/cache/logs/augment.log` | 都有 `# done`；各 source 的 (幣, 月) 數寫進報告 |
| A6 | 讀 `research/cache/funding_months.parquet`：2024-01 … 2025-07 中 source = imputed 的 (幣, 月) | 數目寫進報告。預期 0；> 0 就列出幣與月（照 §8.7 補值，不算失敗） |
| A7 | `git diff 60ccc53 -- research/out/registry.md`；`test ! -s research/out/oos_log.md && echo empty` | 無輸出；`empty` |
| A8 | `.venv/bin/python -m research.phase1 audit` | OK：主實驗 2、鄰居 0 |
| A9 | `find data/futures/um/monthly/fundingRate -newer research/plans/phase1_decisions.md -type f \| wc -l`；`git status --porcelain`；`git ls-files research/cache \| wc -l` | 0；乾淨；0 |

### 8.9 給驗收者（Opus）：S1 晉級檔與各輪補充

1. S1：先照 §3.9 判定正常晉級（候選池 = 15m 與 1h 的 14 組；P3 用 §8.2 的鄰居）。
   - ≥ 1 組 → `MODE: normal`。
   - 0 組 → 自己用 v2 重算 §8.4 第 3、5 點（F1、F2、排序）。有符合的 → `MODE: fallback`。
   - 也沒有 → `MODE: none`、`PROMOTE_COUNT: 0`。
2. `/workspace/cc/ph1.promote.S1.md` 的三種寫法（取代 §6 的 S1 格式；`PROMOTE_COUNT` 這個字串全檔只出現一次，理由段不要再寫它）：

   正常：

   ```text
   # S1 晉級（驗收者判定）
   PROMOTED: p1s1_<a>, p1s1_<b>
   MODE: normal
   PROMOTE_COUNT: 2
   理由：每個候選的 v2 淨 R、手續費×1.5 淨 R、各鄰居淨 R；被排除者的原因（不符 P1/P2/P3 或名次）。
   ```

   fallback：

   ```text
   # S1 晉級（驗收者判定）
   PROMOTED: p1s1_<a>
   MODE: fallback
   PROMOTE_COUNT: 1（fallback 晉級 1 組：S1 無組符合 P1–P3，依 phase1.md §8.4 只測限價進場）
   理由：正常晉級為 0 的原因；候選池 14 組各自的 v2 毛 R、F1、兩個 sbuf 鄰居的 v2 毛 R、F2、排序。
   ```

   連 fallback 都沒有：

   ```text
   # S1 晉級（驗收者判定）
   PROMOTED: none
   MODE: none
   PROMOTE_COUNT: 0
   理由：正常晉級為 0 的原因；fallback 為 0 的原因（列出 F1 組與 sbuf 鄰居毛 R，或寫沒有任何一組 v2 毛 R ≥ +0.05）。
   ```

3. S2 驗收（走 fallback 時）：確認只產生了 lc、lm（沒有 cf1），市價列沒有被當成候選；S2 晉級照 §3.9。S2 的 promote 檔照 §6 的格式，不需要 `MODE:` 行。
4. 每輪驗收另查：主表與 gatea 表有滑價×3 欄；4h 列標參考、沒有進晉級或 fallback；鄰居完整（含 sbuf）且 `neighbors <輪> --status` 缺少數 = 0；沒有「無可測鄰居」字樣。
5. S1 驗收另外把 §8.8 的 A1–A9 全部重跑。

### 8.10 名額核算（不寫 QUESTION 的依據）

| 路徑 | 階段 0 | S1 | S2 | S3 | 備用 | 合計 |
| --- | --- | --- | --- | --- | --- | --- |
| 正常 | 2 | 24 | ≤ 6 | ≤ 16 | 10 | ≤ 58 |
| fallback | 2 | 24 | ≤ 4 | ≤ 16 | 10 | ≤ 56 |

- 兩條路徑互斥（fallback 只在 S1 正常晉級 0 組時走）。
- sbuf 與其他鄰居不算進 60（§8.2 第 6 點）。滑價×3、資金費補值、傳統金融拆兩版都不是實驗。
- 都 ≤ 60，所以不寫 `/workspace/cc/ph1.QUESTION.md`。

### 8.11 被取代或補充的既有敘述（索引）

| 位置 | 原敘述 | 現在 |
| --- | --- | --- |
| §0.6 鄰居列、§3.9 P3、D30 末句 | 沒有表內參數 → 「無可測鄰居」，算成立 | 取消；用 sbuf 鄰居，缺結果算不成立（§8.2） |
| §3.10 對照表與「不測鄰居的參數」段 | 沒有 sbuf；纏論停損 buffer 不測 | §8.2 的更新版 |
| §4.1 表 #1、2、7、8、9、14 的「表內鄰居」 | 無 | sbuf 0.12、0.18（§8.2） |
| §4.1 表 #15–21 的「參加排名」與「表內鄰居」 | 是；cur/rat/opp 無、其他有 | 否（參考：4h），不跑鄰居（§8.5） |
| §3.9「不參加晉級」、D12 | Donchian 與 JEV 參考列 | 再加 4h 七組（§8.5） |
| §3.9 鄰居觸發、§5.2 第 4 步、D24 | 符合 P1 且 P2 才跑 | 另加 F1 組的 sbuf（§8.4 第 4 點） |
| §3.9「推論…只會在 S1 或 S3」、§3.9「無候選」、D31 末句 | S2 不會是 0 組；S1 無候選就結束 | S1 先看 fallback；fallback 時 S2 也可能無候選（§8.4） |
| §4.2、D14 | 每個基底 3 列新實驗，市價列是候選 | fallback 時只有 lc、lm，市價列不是候選（§8.4 第 6 點） |
| §5.3 第 1 步、§6 晉級檔格式、D32 | `PROMOTED`、`PROMOTE_COUNT` | S1 加 `MODE:`；`PROMOTE_COUNT` 含 fallback（§8.4 第 8 點、§8.9） |
| §5.5 研究停損判讀、D40 | S1 結束就寫「限價進場沒有測到」 | §8.4 第 10 點 |
| §3.5 末點、§5.5 註記、D27 末句 | 2026-10 資金費本階段不處理 | §8.7 |
| §3.8 指標、§5.2 第 7 步、§5.5 S1 表 | — | 加 net_slip3（參考）與資金費受影響筆數（§8.1、§8.7） |
| §3.12、§5.5 開頭第 2 行、D39 | 週期含 4h；鄰居欄可寫「無可測」 | 週期主值只用 1h、4h 另列參考；鄰居欄只剩「全正｜有負」（§8.5、§8.2） |
| §5.5 註記、D15 末句 | 階段 2 要不要排除傳統金融留給使用者 | 已定：主結果排除（§8.6） |
| §5.1 `test_p5`、`test_p6`、`test_p7` | — | 照 §8.5 第 6 點、§8.2 測試更新 |
