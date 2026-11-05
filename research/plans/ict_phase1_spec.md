
# ICT P1 詳細實作規格

> 範圍：T1（`research/ict/`）、T2（`sim.py` 三處擴充加歧義計數器）、T3（測試）、`out/ict_funnel.md`。
> 限制：不改 `src/ config/ tests/ docs/ARCHITECTURE.md pyproject.toml`；只用 pandas、pyarrow、numpy 和標準庫；P1 不跑損益、不寫 registry、不寫 `cache/results/`。

## 0. 已核對的事實（實作前提）

- **sim 內部時間單位**：int64 微秒（µs），UTC epoch。
  - `sim._us()` 把 datetime 轉成 `datetime64[us]` 再轉 int64。
  - `C.TF_US["15m"] = 900_000_000`。
  - `Market.bars[sym]["ot"]` 是 µs。
- **訊號表的 `time` 欄**：`datetime64[us, UTC]`（例如 `signals_donchian_4h.parquet`）。sim 用 `int(r.time.value // 1000)` 轉成 µs（`Timestamp.value` 一律是 ns）。
- **進場 K 線**：`j0 = bisect_left(ot, T_us)`（`sim.py:629`），也就是第一根 open_time ≥ T 的 15m K 線。所以事件的 `time` 必須是**決策那根 15m 的 close_time**（= 進場那根的 open_time）。
- **entry_ref 與 stop**：`entry_ref = r.close`（`sim.py:651,666`）。`stop = _tick_round(defending ∓ buffer_atr×atr)`，做空向上取整（`sim.py:643–650`）。
- **sim 讀取的欄位**：`signal_id, tf, type, side, time, close, atr, defending_price, attempt_id`。`level_fail` 只在啟用時讀 `type`；`tp_up_end` 只在欄位存在時讀。
- **Bars**：`C.load_bars_df(sym, tf)` 有 `open_time, close_time (datetime64[us,UTC]), open, high, low, close, volume`。
- **資金費**：`funding.parquet` 欄位是 `symbol, funding_time[us,UTC], rate, interval_h, imputed, basis`。
- **幣數**：`C.union_symbols()` 共 591 個。
- **舊實驗**：`research/experiments/*.yaml` 36 個 + `neighbors/*.yaml` 4 個 = 40 個。registry 的主實驗 36、鄰居 4，`oos_log.md` 是 0 bytes。
- **測試指令**：`.venv/bin/python -m unittest discover -s research/tests -t . -v`。環境沒有 `python`，只有 `.venv/bin/python`。

## 1. 檔案總覽

```
research/ict/__init__.py      空
research/ict/params.py        ICT_VERSION、DEFAULTS、validate()、table_key()
research/ict/swings.py        swing 偵測（含確認時點）
research/ict/fvg.py           FVG 偵測、觸及時間、失效時間
research/ict/htf.py           EMA、4H 多空旗標、對齊
research/ict/state.py         Phase、資料類別、step15()、stepS()（純函數）
research/ict/generate.py      Features 組裝、run_symbol()、EXPERIMENTS、build/count CLI、漏斗報告
research/tests/test_ict_features.py
research/tests/test_ict_state.py
research/tests/test_ict_generate.py
research/tests/test_ict_sim.py
```

快取輸出放在 `research/cache/ict/`（已被 .gitignore 涵蓋）：
- `events_<key>.parquet`
- `setups_<key>.parquet`
- `events_<key>.json`（sidecar）

**不寫** `research/cache/results/`，否則 `phase1b audit` 會報「results without registry row」。

## 2. `params.py`

```python
ICT_VERSION = "ict-p1.0"
DEFAULTS: dict = {
  "version": ICT_VERSION, "setup_tf": "1h", "swing_n": 2, "atr_n": 14, "fvg_k": 0.5,
  "ote_lo": 0.618, "ote_hi": 0.786, "anchor": "causal", "tp2_ext": 0.618, "zone_valid_bars": 24,
  "use_htf": True, "htf_ema": 50,
  "use_expansion": True, "exp_tr_atr": 1.5, "exp_vol_mult": 1.5, "exp_vol_n": 20,
  "use_fresh": True,
  "use_ltf": True, "ltf_bars": 16, "wick_frac": 0.5,
  "use_sweep": True, "sweep_bars": 24,
  "use_session": True, "session_start_h": 7, "session_end_h": 21, "weekdays_only": True,
  "use_funding": True, "funding_block": 0.0005,
  "warmup_until": "2024-01-15",
  "random": None,          # 或 {"seed": int, "match": "ict_L7"}
}
def validate(d: dict) -> dict
def table_key(d: dict) -> str
```

**`validate(d)`**：
- 鍵集合必須**完全等於** `DEFAULTS` 的鍵（不補預設值），否則 `sim.ConfigError`。在函數內 import，避免循環 import。
- 型別檢查：`bool` 不得當 int；數值要有限。
- 範圍：
  - `version == ICT_VERSION`
  - `setup_tf ∈ {"1h","15m"}`
  - `swing_n ≥ 1`，`atr_n ≥ 2`，`fvg_k > 0`
  - `0 < ote_lo < ote_hi < 1`
  - `anchor ∈ {"causal","confirmed"}`
  - `zone_valid_bars`、`ltf_bars`、`sweep_bars`、`exp_vol_n` 都是 ≥ 1 的整數
  - `0 ≤ session_start_h < session_end_h ≤ 24`
  - `funding_block > 0`
  - `warmup_until` 是 ISO 日期字串
  - `random` 是 None，或鍵恰為 `{seed:int, match:str}`
- 回傳淺拷貝。

**`table_key(d)`** = `sha256(json.dumps(validate(d), sort_keys=True, separators=(",",":"))).hexdigest()[:12]`。

因為 `version` 也在 dict 裡，YAML 的 config_sha 會鎖定程式版本。之後改任何生成邏輯都必須升 `ICT_VERSION`。

## 3. `swings.py`

```python
def swings(high: np.ndarray, low: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """回傳 (sh_pivot, sh_price, sl_pivot, sl_price)，皆依 pivot 遞增；確認索引 = pivot + n。"""
```

- **Swing high at i**：`n ≤ i ≤ len−1−n`，`high[i] > high[i−k]`（k=1..n，嚴格），而且 `high[i] ≥ high[i+k]`（k=1..n）。
- **Swing low at i**：`low[i] < low[i−k]`（嚴格），而且 `low[i] ≤ low[i+k]`。
- 要用向量化寫法（`np.lib.stride_tricks.sliding_window_view` 或 shift 比較）。
- **確認時點**：`confirm_idx = pivot + n`，confirmed_at = `close_time[pivot + n]`。只用到 `confirm_idx ≤ k` 的資料就能判定，所以有前綴不變性。

## 4. `fvg.py`

```python
def fvgs(high, low, atr, k: float) -> dict[str, np.ndarray]
def first_touch(fvg_side, fvg_lo, fvg_hi, created_ct_us, m15_ot_us, m15_h, m15_l) -> np.ndarray
def kill_time(fvg_side, fvg_lo, fvg_hi, created_idx, s_close, s_ct_us) -> np.ndarray
```

**`fvgs(...)`** 回傳 `{"idx", "side", "lo", "hi", "gap"}`：
- 空頭 FVG（side=−1）at i（i ≥ 2）：`gap = low[i−2] − high[i]`，條件 `gap > k·atr[i]`，而且 `atr[i]` 不是 NaN。`lo = high[i]`，`hi = low[i−2]`。
- 多頭 FVG（+1）：`gap = low[i] − high[i−2] > k·atr[i]`，`lo = high[i−2]`，`hi = low[i]`。
- 建立時點 `created_at = close_time[i]`。比較是嚴格大於，等於不算。

**`first_touch(...)`**：回傳每個 FVG 第一次被觸及的 15m K 線 close_time（µs），沒有就是 `INT64_MAX`。
- 只看 `open_time ≥ created_at` 的 15m K 線。
- 空頭 FVG 的觸及：`h ≥ lo`；多頭：`l ≤ hi`。
- 實作：`searchsorted` 找起點，再往前掃（FVG 數量少，用迴圈即可）。

**`kill_time(...)`**：回傳 FVG 被收盤穿越的 setup K 線 close_time，沒有就是 `INT64_MAX`。
- 空頭：idx 之後第一根 `close > hi` 的 setup K 線；多頭：`close < lo`。

## 5. `htf.py`

```python
def ema(close: np.ndarray, span: int) -> np.ndarray
def htf_flags(h4: pd.DataFrame, n: int, span: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]
def align(src_ct_us: np.ndarray, t_us: np.ndarray) -> np.ndarray
```

**`ema(close, span)`**：等同 `pd.Series(close).ewm(span=span, adjust=False, min_periods=span).mean()`，前 span−1 根是 NaN。

**`htf_flags(h4, n, span)`** 回傳 `(ct_us, bear, bull)`，每根 4H 一列，表示「這根收盤時」的狀態：
- **bear[j]** = (A) 或 (B)：
  - (A)：`confirm_idx ≤ j` 的 swing low 中最後兩個（依確認順序）滿足 後 < 前。
  - (B)：`close[j] < ema[j]`，ema 是 NaN 時視為 False。
- **bull[j]** = 最後兩個已確認 swing high 後 > 前，或 `close[j] > ema[j]`。

**`align(src_ct_us, t_us)`**：`np.searchsorted(src_ct_us, t_us, side="right") − 1`，−1 表示沒有。15m K 線在 close_time t 時，用的是最後一根 close_time ≤ t 的 4H。

## 6. `state.py`（純函數；只用標準庫 dataclasses 和 numpy 讀取）

### 6.1 型別

```python
class Phase(str, Enum):
    IDLE="IDLE"; BOS_CONFIRMED="BOS_CONFIRMED"; ZONE_ARMED="ZONE_ARMED"; IN_ZONE="IN_ZONE"
    TRIGGERED="TRIGGERED"; INVALID="INVALID"

@dataclass(frozen=True)
class Setup:
    setup_id: str; side: int
    bos_s: int; bos_time: int            # setup K 線索引、close_time µs
    a1: float; a1_pivot: int             # 錨點 1 的價格與 pivot 索引
    a0: float | None; a0_s: int | None   # 錨點 0
    fvg_id: int | None; zone_lo: float | None; zone_hi: float | None
    zone_time: int | None                # 第一次建立 zone 的 close_time（有效期的起點）
    zone_eff: int | None                 # 目前 zone 生效起點（重新錨定時更新），觸及只看 open_time ≥ zone_eff 的 K 線
    touch_time: int | None; touch_k: int | None
    flags: tuple                         # (("htf",bool),("exp",bool),("sweep",bool),("fresh",bool|None),...)

@dataclass(frozen=True)
class SideState:
    side: int                            # −1 做空機，+1 做多機
    setup: Setup | None
    phase: Phase                         # 沒有 active setup 時為 IDLE
    last_bos_swing: int                  # 已被 BOS 消耗的最近 swing 的 pivot 索引（避免重複 BOS），初值 −1

@dataclass(frozen=True)
class Transition:
    time: int; setup_id: str; side: int; frm: str; to: str; reason: str

@dataclass(frozen=True)
class Event:
    time: int; side: int; close: float; atr: float; defending: float; tp2: float
    setup: Setup; trigger_kind: str; funding_rate: float; f_session: bool; f_funding: bool
```

`Features`（由 `generate.build_features` 產生）是唯讀物件，各欄位都是 numpy 陣列：
- `m15`：`ot, ct, o, h, l, c`
- `S`（setup TF）：`ot, ct, o, h, l, c, v, atr`、`s_of_ct`（15m 索引 → 在該 ct 收盤的 S 索引，沒有是 −1）
- S 的 swing：`sh_pivot, sh_price, sh_conf, sl_pivot, sl_price, sl_conf`（conf = 確認 S 索引）
- 15m 的 swing：同樣格式，加前綴 `m_`
- FVG：`fvg_idx, fvg_side, fvg_lo, fvg_hi, fvg_ct, fvg_touch, fvg_kill`
- `bigbar[S]`（bool，擴張）及其前綴和 `bigbar_cs`
- `sweep_dn[S]`（bool，空方 sweep：影線穿越當時最後一個已確認 swing high、收盤 ≤ 該價）、`sweep_up[S]`，及各自前綴和
- `h4_idx_of_m15`、`h4_bear`、`h4_bull`
- `fund_t`、`fund_r`（只含 `imputed == False`）
- `last_sh_before[S]`、`last_sl_before[S]`：在 S 開盤時已確認的最後一個 swing 的價格與 pivot

**所有欄位都只能用「確認／建立時點 ≤ 當前 t」的資料。** 前綴測試會驗證這一點。

### 6.2 每根 15m 收盤 t 的處理順序（索引 k）

1. 對每台機器（side −1 與 +1）：`step15(ss, k, F, P) -> (ss, [Transition], Event|None)`
2. 若 `F.s_of_ct[k] ≥ 0`（t 也是 setup K 線的收盤）：`stepS(ss, s, F, P) -> (ss, [Transition])`

順序是先 15m 後 setup，所以在 t 建立的 zone 只對 open_time ≥ t 的 K 線有效。setup_tf=15m 時每根都兩步都跑。

**效能**：兩台機器都在 IDLE 時，直接跳到下一個 setup 收盤（`np.flatnonzero(F.s_of_ct ≥ 0)`），不逐根跑 15m。

### 6.3 `stepS`（做空機；做多機在 6.6 鏡像）

- **(a) BOS 偵測**：
  - 取 `confirm ≤ s` 的最後一個 swing low `(p, P)`，條件是 `p > last_bos_swing`。
  - 若 `c_S[s] < P`（嚴格）就是 BOS：`last_bos_swing = p`。等於不算，那是 sweep 或什麼都不是。
  - 目前 phase 是 IN_ZONE：只記 Transition `(…, "IN_ZONE","IN_ZONE","bos_ignored_in_zone")`，不換 setup。
  - 目前 phase 是 BOS_CONFIRMED 或 ZONE_ARMED：舊 setup 標 INVALID，reason `replaced`。
- **(b) 候選檢查**（依序，失敗就在 setups 表記一列，max_phase=`BOS`，附 reason）：
  1. **錨點 1**：取 `confirm ≤ s` 而且 `pivot < s` 的最後一個 swing high pivot ph，`a1 = max(h_S[ph..s])`，`a1_pivot` = 取到最大值的索引（同值取最早）。沒有 ph，或 `a1 ≤ c_S[s]` → `no_anchor1`。
  2. `use_htf` 而且 `not h4_bear[at t]` → `htf_reject`。
  3. `use_expansion` 而且 `bigbar_cs` 在 [a1_pivot, s] 區間總和為 0 → `no_expansion`。
     - `bigbar[j] = TR[j] ≥ exp_tr_atr·atr[j−1]` 或 `v[j] ≥ exp_vol_mult·median(v[j−20..j−1])`。
  4. `use_sweep` 而且 `sweep_dn` 在 [s−sweep_bars+1, s] 區間總和為 0 → `no_sweep`。
  - 全部通過：新 Setup，`phase=BOS_CONFIRMED`，`setup_id=f"{symbol}|{side}|{bos_time}"`，記錄 flags（各條件的實際值，即使該濾網關閉也照算並記錄）。
- **(c) 錨點 0**（phase ∈ {BOS_CONFIRMED, ZONE_ARMED}，而且 setup 不是在本步剛建立的）：
  - **causal**：`m = argmin(l_S[bos_s..s])`，同值取最早。若 `m < s`，候選 a0 = `l_S[m]`。
  - **confirmed**：取 `pivot ≥ bos_s`、`confirm ≤ s` 的 swing low 中價格最低者。
  - 候選 a0 比現有 a0 低（或現有是 None）時：更新 a0，然後 **(d)**。
- **(d) 建 zone／重新錨定**：
  - OTE = `[a0 + ote_lo·(a1−a0), a0 + ote_hi·(a1−a0)]`。
  - 合格 FVG：side=−1，`a1_pivot ≤ idx ≤ s`，`fvg_kill > t`，`fvg_ct ≤ t`。`use_fresh` 時另外要求 `fvg_touch > t`。
  - 交集 = `[max(ote_lo_p, fvg_lo), min(ote_hi_p, fvg_hi)]`，要求 lo < hi。
  - 取交集長度最大者，同長取 `fvg_ct` 較新者。
  - **沒有合格 FVG**：
    - 若關掉新鮮度要求後就會有，reason `stale_fvg`，否則 `zone_empty`，轉 INVALID。
    - 在 ZONE_ARMED 重新錨定時也一樣處理。
  - **成功**：
    - 第一次：`zone_time = t`，`zone_eff = t`，轉 ZONE_ARMED，reason `zone_built`。
    - 重新錨定：zone 更新，`zone_eff = t`，`zone_time` 不變，Transition reason `reanchor`。

### 6.4 `step15`（做空機），依序檢查

phase ∈ {BOS_CONFIRMED, ZONE_ARMED, IN_ZONE} 時：

1. `use_htf` 而且 `not h4_bear[h4_idx_of_m15[k]]`（−1 視為 False）→ INVALID `htf_lost`
2. `c[k] > a1` → INVALID `close_above_anchor1`
3. phase ∈ {ZONE_ARMED, IN_ZONE} 而且 `c[k] > zone_hi` → INVALID `close_above_zone`
4. **ZONE_ARMED**：
   - `ot[k] ≥ zone_eff` 而且 `h[k] ≥ zone_lo` → IN_ZONE，`touch_time = ct[k]`，`touch_k = k`。
     - `use_ltf=false`：立即進入第 6 步，觸發種類 `touch`。
     - `use_ltf=true`：同一根也做第 5 步。
   - 否則若 `ct[k] ≥ zone_time + zone_valid_bars·TF_US[setup_tf]` → INVALID `zone_expired`。檢查順序是先看觸及、再看到期，所以剛好在到期那根觸及仍然有效。
5. **IN_ZONE 而且 use_ltf**：
   - **wick**：`R = h−l > 0`，`h − max(o,c) ≥ wick_frac·R`，而且 `c ≤ l + R/3`。
   - **MSS**：取 15m swing low 中 `m_sl_pivot ≥ touch_k` 而且 `m_sl_conf < k` 的最後一個，條件 `c[k] < price`。確認那根本身不可能收在下方。
   - 兩者都成立時，trigger_kind 記 `mss`。
   - 都沒有，而且 `ct[k] ≥ touch_time + (ltf_bars−1)·900_000_000` → INVALID `no_trigger`。
6. **決策**（T = ct[k]）：
   - `f_session` = `session_start_h ≤ hour(T) < session_end_h`，而且 `weekdays_only ⇒ weekday(T) ≤ 4`（UTC）。
   - `use_session` 而且 not f_session → INVALID `session`。
   - **資金費**：`i = searchsorted(fund_t, T, "right") − 1`；`rate = fund_r[i]`，條件是 `i ≥ 0` 而且 `T − fund_t[i] ≤ 86_400_000_000`，否則 NaN。
     - 做空：`f_funding = not (rate ≤ −funding_block)`，NaN 視為 True。
     - `use_funding` 而且 not f_funding → INVALID `funding`。
   - 通過 → TRIGGERED，產生 Event：
     - `close = c[k]`
     - `atr = S.atr[最後一根 ct ≤ T 的 S]`
     - `defending = a1`
     - `tp2 = a0 − tp2_ext·(a1 − a0)`
   - 然後機器回到 IDLE。

### 6.5 失效原因總表（多空共用字串）

| 類別 | reason |
|---|---|
| BOS 層 | `no_anchor1`、`htf_reject`、`no_expansion`、`no_sweep` |
| setup 層 | `replaced`、`htf_lost`、`close_above_anchor1`、`zone_empty`、`stale_fvg`、`close_above_zone`、`zone_expired`、`no_trigger`、`session`、`funding` |
| 結束 | `end_of_data`（資料結束時仍 active） |

### 6.6 做多鏡像（side=+1）

- 高↔低：BOS 用 swing high 且 `c > P`；錨點 1 = 最近 swing low 起算的 min low；錨點 0 = BOS 後 max high。
- OTE：`[a0 − ote_hi·(a0−a1), a0 − ote_lo·(a0−a1)]`；FVG 用多頭；sweep 用 `sweep_up`。
- 失效：`c < a1`、`c < zone_lo`。觸及：`l ≤ zone_hi`。
- wick：`min(o,c) − l ≥ wick_frac·R`，而且 `c ≥ h − R/3`。MSS：收盤 > 觸區後的 15m swing high。
- `tp2 = a0 − tp2_ext·(a1 − a0)`（同一公式，代入後就是往上延伸）。
- 資金費擋 `rate ≥ +funding_block`。HTF 用 `h4_bull`。
- reason 字串相同；`close_above_*` 在做多時表示 close_below，字串照用並在報表註明。

## 7. `generate.py`

### 7.1 函數

```python
EXPERIMENTS: tuple[tuple[str, str, str], ...]   # (name, kind, diff_text)，19 個 + 5 個 rsv（kind="reserved"，沒有 dict）
NEIGHBORS: tuple[tuple[str, str], ...]          # 4 個 (name, diff_text)
def ict_params(name: str) -> dict               # 依第 5 節由 DEFAULTS 套差異；鄰居同樣支援
def experiment_dict(name: str) -> dict          # 完整 SimConfig dict（第 5 節共同設定 + 差異）
def build_features(symbol, b15, b1h, b4h, funding, P) -> Features
def run_symbol(symbol, F, P, stop_at_us: int | None = None, state=None) -> tuple[list[Event], list[Transition], dict]
def symbol_job(args) -> dict                    # args=(symbol, [(key, P)], rank_by_date, fund_arrays)
def build(keys_params: list[tuple[str, dict]], workers: int, force: bool) -> dict[str, Path]
def count(workers: int, out: Path, names=LADDER + ("ict_setup15m",)) -> int
def funnel_markdown(per_variant: dict) -> str   # 純函數，只吃計數用的 frame
def main(argv=None) -> int
```

- `run_symbol` 傳入的 `state` 若非 None，就從該 `(SideState, SideState)` 接續執行；回傳的 dict 含 `"state"`。
- `symbol_job` 讀一次 bars，依 (setup_tf, swing_n, fvg_k) 共用 Features，再跑每個 variant。
- `build` 用 `Pool(workers, maxtasksperchild=1)` 加 `imap_unordered`，幣依 15m 根數由大到小排序。
  - 合併後依 `["time","symbol","side"]` stable sort。
  - 寫出 `events_<key>.parquet`、`setups_<key>.parquet`、`events_<key>.json`。
  - sidecar 內容：`{key, params, ict_version, n_symbols, rows, built_utc, elapsed_s}`。
  - 已存在而且 sidecar 的 params 相同時跳過，除非 `--force`。
- 隨機基準需要 match 對象的事件表，在 build 時先建好它。

### 7.2 事件表 schema（`events_<key>.parquet`，一列 = 一個進場事件）

| 欄 | dtype | 單位／語意 |
|---|---|---|
| signal_id | str | `ict\|<key>\|<symbol>\|<short\|long>\|<time ISO>`，唯一 |
| symbol | str | 例如 `BTC/USDT` |
| tf | str | 固定 `15m`（sim 用 `C.TF_US[tf]`） |
| type | str | `ict_short` / `ict_long` |
| side | int64 | −1 / +1 |
| time | datetime64[us, UTC] | 決策那根 15m 的 **close_time**（= 進場那根的 open_time）。sim 以 `time.value//1000` 換成 µs |
| close | float64 | 決策那根的收盤，即 entry_ref |
| atr | float64 | setup TF（預設 1H）Wilder ATR14，取最後一根 close_time ≤ time 的值，價格單位 |
| defending_price | float64 | 錨點 1（做空是 swing high 區段的最高價，做多是最低價） |
| tp2 | float64 | `a0 − tp2_ext·(a1 − a0)` |
| a0 | float64 | 事件當時的錨點 0 |
| zone_lo, zone_hi, fvg_lo, fvg_hi | float64 | 價格 |
| setup_id | str | 對應 setups 表 |
| bos_time, zone_time, touch_time, fvg_time | datetime64[us, UTC] | 各階段時點 |
| trigger_kind | str | `touch` / `mss` / `wick` |
| f_htf, f_expansion, f_sweep, f_fresh, f_session, f_funding | bool | 各條件的**實際值**（濾網關閉時也算） |
| f_ltf | bool | 是否由 LTF 觸發（use_ltf=false 時為 False） |
| funding_rate | float64 | NaN = 未知 |
| universe_date | object(date) | `C.universe_dates(time)` |
| rank | float64 | NaN = 不在榜 |
| in_top20 | bool | `~isnan(rank)` |
| sample | object | `C.sample_of_series(time)`：`IS` / `OOS` / None |

規則：
- 不輸出 `T < warmup_until` 的列，在 setups 表記 `warmup_dropped`。
- 不輸出 `universe_date` 超出 `C.HISTORY_START..HISTORY_END` 的列。

### 7.3 setups 表（`setups_<key>.parquet`，一列 = 一次 BOS 候選）

| 欄 | 說明 |
|---|---|
| setup_id | |
| symbol, side | |
| bos_time | datetime64[us, UTC] |
| max_phase | str：`BOS`、`BOS_CONFIRMED`、`ZONE_ARMED`、`IN_ZONE`、`TRIGGERED` |
| reason | str 或 None（TRIGGERED 時為 None 或 `warmup_dropped`） |
| end_time | 結束時點 |
| n_reanchor | int |
| signal_id | 有事件時填入 |
| in_top20_at_bos | bool |
| sample | 依 bos_time |

### 7.4 CLI

```
.venv/bin/python -m research.ict.generate build (--exp NAME[,NAME…] | --all) [--workers 6] [--force]
.venv/bin/python -m research.ict.generate count [--workers 6] [--out research/out/ict_funnel.md] [--rebuild]
.venv/bin/python -m research.ict.generate key --exp NAME      # 只印 table_key
```

- `count` = 對 `ict_L0..ict_L7` 和 `ict_setup15m` 做 build（`--rebuild` 時加 force），再寫漏斗報告。
- `count` **不得** import 或呼叫 `sim.simulate` / `sim.simulate_symbol`。
- `count` 只呼叫 `sim.SimConfig.from_dict(experiment_dict(n))` 和 `sim.select_signals(cfg, types.SimpleNamespace(delist=sim.load_delist()))`。這樣在 in_top20、exclude_tradfi、日期範圍、delist 上，套用的規則與 P2 完全相同。
- 結束時印一行：`ICT COUNT L7_IS=<n> verdict=<PASS|STOP>`。

## 8. `sim.py` 擴充（精確位置與保證舊 sha 不變的方法）

### 8.1 `SimConfig.from_dict`（`sim.py:118–209`）

- **L123**：改成 `_check_keys("signals", sig, {"source","tf","types","donchian_n","ict"}, {"source","tf","types","donchian_n"})`。
- **L124**：允許 `"ict"`，錯誤訊息改成 `chan, donchian or ict`。
- **L130 之後**，加一個 `elif sig["source"] == "ict":` 分支：
  - `tf` 必須是 `"15m"`。
  - `types` 非空，而且是 `{"ict_long","ict_short"}` 的子集。
  - `donchian_n is None`。
  - `"ict" in sig`；`sig = {**sig, "ict": ict_params.validate(sig["ict"])}`。
  - 非 ict 時若出現 `"ict"` → ConfigError。
  - 原本的 `else:`（donchian 分支）要改成 `elif source == "donchian"`。
- **L192 之後**（`ex = resolve_exit(...)` 之後）：
  - 若 source == ict：`ex["opposite_signal"]["enabled"]` → ConfigError；`ex["tp1"]["enabled"] and ex["tp1"]["target"] != "r"` → ConfigError；`fixed_r` 與 `row_target` 同時開 → ConfigError。
  - 若 `"row_target" in ex` 而 source != ict → ConfigError。
- **L203**：`signals=dict(sig)` 不變。舊設定沒有 `ict` 鍵，所以 `resolved()` 的輸出逐字相同。

### 8.2 `resolve_exit`（`sim.py:225–264`）

比照 L233 的 `donchian_exit`：

```python
tb = raw.pop("time_barrier", None); rt = raw.pop("row_target", None)
allowed = set(EXIT_MODULES) | {"preset","donchian_exit","time_barrier","row_target"}   # 改 L228
...（原流程）...
if tb is not None:
    _check_keys("exit.time_barrier", tb, {"enabled","bars","min_r"}, {"enabled"})
    _expect(..., "enabled", tb["enabled"], "bool")
    if tb["enabled"]:
        # 缺 bars 或 min_r → ConfigError
        # bars: int ≥ 1；min_r: num > 0
        out["time_barrier"] = {"enabled": True, "bars": tb["bars"], "min_r": tb["min_r"]}
if rt is not None:
    _check_keys("exit.row_target", rt, {"enabled"}); _expect(..., "bool")
    if rt["enabled"]:
        out["row_target"] = {"enabled": True}
```

- `pop` 必須在 `extra` 檢查之前，或者把這兩個鍵加進 `allowed`。
- `{"enabled": false}` 等同不寫，與 `donchian_exit` 的行為一致。
- `EXIT_MODULES`、`PRESETS` 都不動，所以舊設定的 `exit` dict 逐字相同。

### 8.3 `load_signal_table`（`sim.py:354–386`）

在 L357 前加入：

```python
if source == "ict":
    from research.ict import params as IP
    key = IP.table_key(cfg.signals["ict"])
    p = C.CACHE / "ict" / f"events_{key}.parquet"
    meta = p.with_suffix(".json")
    if not p.exists():
        raise FileNotFoundError(f"{p.name} missing (run python -m research.ict.generate build --exp …)")
    if json.loads(meta.read_text())["params"] != IP.validate(cfg.signals["ict"]):
        raise ValueError(f"{p.name}: sidecar params differ")
    return pd.read_parquet(p)
```

`select_signals`（`sim.py:389–432`）不必改：
- L395 只有 donchian 才看 `n`。
- in_top20、exclude_tradfi、日期範圍、delist 都是通用的。

`opposite_times` 不改：ict 禁止 opposite_signal，而且沒有 `donchian_exit`，所以回傳 `{}`。

### 8.4 `simulate_symbol`（`sim.py:555–982`）

- **L612–613 附近**：
  ```python
  tbC = ex.get("time_barrier")
  rowC = ex.get("row_target")
  track_amb = cfg.signals["source"] == "ict"
  ```
- **L608 的 cnt**：`if track_amb: cnt.update(amb_stop_target=0, amb_tp1_entry=0, row_target_invalid=0)`。非 ict 時 cnt 的鍵集合不變。
- **每筆交易開始時（L801 之後）**：
  - `amb1 = amb2 = tp2_done = False`
  - `tp2 = float(r.tp2) if rowC else nan`
  - 若 rowC，而且 `not (tp2 == tp2 and side*(tp2 − entry_ref) > 0)`：`tp2 = nan`，`cnt["row_target_invalid"] += 1`。
- **停損觸發（L846 的 `if raw is not None:` 區塊，break 之前）**：
  - 若 track_amb：當該 K 線的區間也碰到任何一個未完成的目標，`amb1 = True`。
  - 目標：TP1（未完成）`side==-1: l_ <= tp_price` / `side==1: h_ >= tp_price`；或 tp2（非 NaN）同理。
- **TP1 成交處（L868–873）**：若 track_amb 而且該根也碰到 entry_ref 的不利側（做空 `h_ >= entry_ref`，做多 `l_ <= entry_ref`），`amb2 = True`。
- **row_target**：在 L873 之後、`if not hit and fix_price` 之前插入，與 TP1 在同一個 `if not (maker_entry and j == jf)` 區塊內：
  ```python
  if rowC and tp2 == tp2:
      raw2 = (o_ if o_ <= tp2 else (tp2 if l_ <= tp2 else None)) if side == -1 else (o_ if o_ >= tp2 else (tp2 if h_ >= tp2 else None))
      if raw2 is not None:
          legs.append((rem, raw2*(1 - side*slip), taker, ot[j], rem*raw2*slip))
          exit_bar, exit_reason, rem, tp2_done = j, "row_target", 0.0, True
          break
  ```
  同一根先成交 TP1 再成交 TP2；TP2 在 TP1 之前觸及時，`rem` 全部出場。
- **收盤檢討（L892 的 `elif timeC…` 之後）**：
  ```python
  elif tbC is not None and not tp_done and (j - jf + 1) == tbC["bars"] and side * (best - entry_ref) < tbC["min_r"] * R:
      pending = "time_barrier"
  ```
  `best` 已含進場那根的區間（L809、L824–833）。
- **L949–981 的 rows.append**：tuple 尾端加上 `+ ((amb1, amb2, tp2_done) if track_amb else ())`。迴圈結束後，若 track_amb：`cnt["amb_stop_target"] += amb1`，`cnt["amb_tp1_entry"] += amb2`。
- 歧義比例（`ambiguous_trade_ratio` 與其 PnL 占比）在 P2 由 trade 欄計算，P1 只提供欄位和計數器。

### 8.5 `_COLS` 與 `simulate`（`sim.py:985`、`1024–1069`）

- 新增 `_ICT_COLS = ["amb_stop_target", "amb_tp1_entry", "tp2_hit"]`。
- L1049 改成 `df = pd.DataFrame(rows, columns=_COLS + _ICT_COLS if cfg.signals["source"] == "ict" else _COLS)`。

### 8.6 `run.py`（小改，不影響 sha）

- `_exit_label`（L85–98）：`time_barrier` → `f"tb{v['bars']}"`，`row_target` → `"tp2"`。
- `summarize`（L143–148）：ict 時在 `src=ict` 後面加上 ` ict=<table_key>`。
- `compute` 不改：ict 會走 `bi_tf="15m"`，供 `ict_x_trail` 的 ratchet 使用。

### 8.7 舊 config_sha 不變的保證

- 只新增可選鍵，未出現時不進 `resolved()`。
- `EXIT_MODULES`、`PRESETS`、`_FILTER_DEFAULTS`、`_FILTER_OPTIONAL` 都不改。
- 非 ict 的 trade 欄位與計數器鍵集合不變。
- 由測試 x01、x02、x09 和 40 個 `--check` 驗證。

## 9. 測試清單（`research/tests/test_ict_*.py`，unittest，合成資料為主）

### test_ict_features.py

- **i01_swing_confirm_time**：`h=[1,2,5,3,4,1,1]`、`l=h−0.5`、n=2 → sh_pivot 含 2、price 5.0，確認索引 4。`swings(h[:4], l[:4], 2)` 不含 pivot 2；`swings(h[:5], …)` 含。
- **i02_swing_ties**：`h=[1,5,5,3,2,1]` → pivot 只有 1（左嚴格、右可相等），不含 2。swing low 鏡像同樣成立。
- **i03_swing_n**：n=1 與 n=3 的確認索引 = pivot+n。
- **i04_fvg_boundary**：
  - `low[i−2] − high[i] == k·atr[i]` → 0 個。
  - 多 1e-9 → 1 個，`lo == high[i]`、`hi == low[i−2]`。
  - `atr` 是 NaN → 0 個。
  - 多頭鏡像。
- **i05_fvg_touch_kill**：
  - 第一根 open ≥ created 而且 `h ≥ lo` 的 15m K 線，其 close_time 等於 `first_touch` 的值。
  - created 那根 open < created，不算觸及。
  - `kill_time` = 第一根 `close > hi` 的 setup K 線。
- **i06_htf_alignment**：4H close_time 04:00 → `align` 對 15m ct 04:00 回傳該根，對 03:45 回傳前一根。EMA 的前 49 根是 NaN；ema 是 NaN 而且沒有兩個 swing 時，`bear == False`。
- **i07_htf_either**：只有低點降低成立時 bear True；只有 close < EMA 成立時也 True；兩者都不成立時 False。

### test_ict_state.py

用合成的 1H/15m/4H 建構器 `mk(b15_rows)`，由 15m 聚合成 1H/4H。

- **s01_bos_needs_close**：收盤 == swing low → 沒有 BOS；收盤 < swing low → 有一個 Transition 到 `BOS_CONFIRMED`。
- **s02_sweep_vs_bos**：
  - 影線 > swing high、收盤 == 該價 → `sweep_dn` True，而且做多機沒有 BOS。
  - 收盤 > 該價 → `sweep_dn` False，做多機有 BOS。
- **s03_causal_anchor**：BOS 後 b+1 創新低。
  - b+1 收盤時 `a0 is None`。
  - b+2 收高時 `a0 == l_S[b+1]`。
  - b+3 再創低時，b+4 收盤出現 reason `reanchor`，而且 `zone_time` 不變。
- **s04_freshness**：FVG 在 zone 建立前被一根 15m 碰到。
  - use_fresh=True → INVALID `stale_fvg`。
  - use_fresh=False → `zone_built`。
  - anchor=confirmed 版本也一樣是 `stale_fvg`。
- **s05–s16 各條失效路徑**（各自一個最小情境，斷言 setups 表 reason 剛好等於該字串、沒有事件）：
  - `no_anchor1`、`htf_reject`、`no_expansion`、`no_sweep`、`replaced`、`htf_lost`、`close_above_anchor1`、`zone_empty`、`close_above_zone`。
  - `zone_expired`：第 24 根 setup 收盤前那根觸及 → 有效；晚一根 → expired。
  - `no_trigger`：第 16 根 15m 觸發 → 有事件；第 17 根 → `no_trigger`。
  - `session`：T=21:00 擋、T=07:00 放、週六擋。
  - `funding`：做空在 −0.0005 擋、−0.00049 放；做多在 +0.0005 擋；資料超過 24h → 放行而且 `funding_rate` 是 NaN。
- **s17_ltf_boundaries**：
  - 上影線剛好 0.5R、收盤剛好在 `l + R/3` → 觸發 `wick`。
  - 影線 0.5R − 1e-9 → 不觸發。
  - MSS 在確認後下一根收破 → 觸發 `mss`；確認那根不觸發。
- **s18_touch_order**：zone 在 t 建立，結束於 t 的那根 15m 即使 `h ≥ zone_lo` 也不算觸及。
- **s19_long_mirror**：
  - 把一段做空情境套上 `x → 1000 − x`（high/low 互換、open/close 映射、資金費取負號）。價格都用 0.25 的倍數。
  - 原資料做空事件的 `(time, trigger_kind, reason 序列)` 等於鏡像資料做多事件的對應值。
  - `close'`、`defending'`、`tp2'` 和 1000 − 原值的差 ≤ 1e-9。
- **s20_pure_step**：同一個 `(state, k)` 呼叫兩次，輸出相等，而且輸入的 state 物件未被改動（frozen 加上 `==` 比對）。

### test_ict_generate.py

- **g01_prefix_invariance**：
  - 資料：合成隨機漫步（seed 7，15m 共 6000 根），加上 cache 存在時的 `BTC/USDT` 2024-02-01..2024-04-30（不存在時 skipTest）。
  - 對 20 個隨機切點 t：`run_symbol(features(bars ≤ t))` 的事件，等於 `run_symbol(features(full), stop_at_us=t)` 的事件，也等於 full 結果中 `time ≤ t` 的事件，逐欄相等。
  - 兩者在 t 的 `state` 也相等。
- **g02_incremental_equals_batch**：每 97 根做一次 `pickle.loads(pickle.dumps(state))` 再接續執行，事件表與 transitions 和一次跑完完全相同。
- **g03_deterministic**：`symbol_job` 跑兩次，`pd.testing.assert_frame_equal` 通過；`signal_id` 唯一。
- **g04_schema**：events 的欄位名稱、順序、dtype 等於 7.2 節；`time.dt.tz == UTC`，unit 是 us。
- **g05_warmup**：所有事件 `time ≥ 2024-01-15T00:00Z`；setups 表有 `warmup_dropped` 計數。
- **g06_params_key**：
  - 任一鍵改值 → `table_key` 改變。
  - 少一鍵或多一鍵 → ConfigError。
  - `version` 不等於 `ICT_VERSION` → ConfigError。
- **g07_registration_matches_plan**：
  - 解析 `research/plans/ict_phase1.md` 第 5 節表格（名稱欄），等於 `[n for n,_,_ in EXPERIMENTS]`，共 24 個（含 5 個 rsv）。
  - 第 6 節 4 個名稱等於 `NEIGHBORS`。
  - 19 個非 rsv 和 4 個鄰居的 `experiment_dict` 都能通過 `SimConfig.from_dict`。
  - 名稱都不在 registry 裡。
  - 36 + 24 == `run.MAX_EXPERIMENTS`。
- **g08_random_counts**：小型 fixture 上，`ict_rand` 每個 (symbol, side, quarter) 的列數等於 match 對象的列數；seed 固定，兩次結果相同。
- **g09_count_no_pnl**：
  - `mock.patch("research.sim.simulate", side_effect=AssertionError)` 和 `simulate_symbol` 同樣處理。
  - `funnel_markdown(fixture)` 的 fixture 含 OOS 列，輸出不含 `2025Q3`、`2025-07`、`net`、`R`（損益字樣）。

### test_ict_sim.py

- **x01_old_40_shas_unchanged**：
  - `experiments/*.yaml` 共 36 個，`neighbors/*.yaml` 共 4 個。
  - 每個 `config_sha(SimConfig.from_dict(y).resolved())` 都在 `read_registry()[name]` 裡。
  - 總數 == 40。
- **x02_defaults_untouched**：
  - `resolve_exit({}) == copy.deepcopy(EXIT_MODULES)`。
  - `"time_barrier" not in`、`"row_target" not in`。
  - `resolve_exit({"time_barrier":{"enabled":False}}) == resolve_exit({})`。
  - test_sim 的 `BASE_CFG` 的 resolved 沒有 `ict` 鍵。
- **x03_config_validation**：以下各自 `assertRaises(ConfigError)`：
  - ict 缺 `signals.ict`；tf=1h；types 含 `second_buy`。
  - chan 帶 `ict` 鍵；chan 開 row_target。
  - ict 開 opposite_signal；ict 的 tp1 target=prior_swing；ict 同時開 fixed_r 和 row_target。
  - time_barrier bars=0 / 1.5 / min_r=0 / 缺 min_r。
- **x04_time_barrier_fires**：
  - 做空 close=100、defending=103、atr=2、tick 0.01 → stop=103.6、R=3.6。
  - 12 根 FLAT（low ≥ 98.21）。
  - 結果：`exit_reason=="time_barrier"`，`bars_held==12`，`exit_time == ot[jf+12]`，出場價 = `O[jf+12]·(1+slip)`。
- **x05_time_barrier_not_fired**：
  - 第 11 根 low == 98.2（= 100 − 0.5×3.6，剛好到）→ 不觸發。
  - TP1 先成交 → 不觸發。
  - `bars=12` 時，第 13 根以後不再判斷。
- **x06_hand_reconciliation**（手算對帳；也可由 generate 的合成事件產生同一列）：
  - 做空，`close=100`、`defending=103`、`atr=2`、`tp2=92`、buffer 0.3、tick 0.01；exit 用基準 exit。
  - 進場那根：(99.9, 100.2, 99.0, 99.5)；第 2 根：(99.5, 99.6, 94.0, 94.5)；第 3 根：(94.5, 94.8, 91.5, 92.2)。
  - 斷言：
    - `stop_initial == 103.6`，`r_dist == 3.6`（±1e-9）
    - `entry_price == 99.89001`
    - TP1 價 94.6 → 成交 94.60946；TP2 成交 92.0092
    - `exit_reason == "row_target"`，`tp1_hit` True，`tp2_hit` True
    - `gross_r == 1.8279666666666698`
    - `fee_r == 0.026833241666666712`
    - `net_r_ex_funding == 1.801133425000003`（places=9）
- **x07_tp1_tp2_same_bar**：同一根 low 跨過 94.6 與 92 → 兩段都在該根成交，`bars_held == 0` 或 1（依進場根），exit_reason `row_target`。
- **x08_ambiguity**：
  - 同一根 `h ≥ stop` 而且 `l ≤ tp1` → `exit_reason=="structure_stop"`，`amb_stop_target` True，`cnt["amb_stop_target"] == 1`。
  - TP1 那根 `h ≥ 100` → `amb_tp1_entry` True。
- **x09_non_ict_unchanged**：chan 設定下，cnt 的鍵集合 == 舊的 9 個鍵；每列 tuple 長度 == `len(_COLS)`；`simulate()` 的 columns == `_COLS + ["sample"]`。
- **x10_row_target_invalid**：`tp2 ≥ entry_ref`（做空）→ 忽略，`cnt["row_target_invalid"] == 1`，交易照常。
- **x11_table_sidecar_mismatch**：sidecar 的 params 被改 → `load_signal_table` 丟出 ValueError；檔案不存在 → FileNotFoundError。

## 10. 漏斗報告 `research/out/ict_funnel.md`

由 `generate count` 產生；只計數、只看 IS、不含任何價格結果或損益欄。

```
# ICT P1 盲測漏斗（只計數、只 IS、無損益）

- 產生：`.venv/bin/python -m research.ict.generate count --workers 6`，<UTC 時間>，ICT_VERSION=ict-p1.0，耗時 <s> 秒，幣數 591
- 範圍：IS 2024-01-15 → 2025-06-30（2024-01-01 → 01-14 暖機丟棄）
- 事件計數口徑：sim.select_signals 之後（in_top20、exclude_tradfi、delist_rule、日期範圍），未模擬

## 1. 各階計數（多空合計；括號內為 short/long）
| 階 | 實驗 | key | BOS 候選 | setup 成立 | zone 建立 | 觸區 | 事件（原始） | 事件（篩選後） | ≥150 |
| L0 | ict_L0 | … | … | … | … | … | … | 1234 (600/634) | — |
| …  |
| L7 | ict_L7 | … | … | … | … | … | … | N (s/l) | 是/否 |
| 15m | ict_setup15m | … | … |

## 2. 季度分佈（篩選後事件，short/long）
| 實驗 | 2024Q1* | 2024Q2 | 2024Q3 | 2024Q4 | 2025Q1 | 2025Q2 |
（* 2024Q1 只含 01-15 之後）

## 3. 失效原因（依 bos_time 屬 IS 的 setups）
| reason | L0 | L1 | … | L7 | 15m |
（列出 6.5 節全部 reason 加上 warmup_dropped、end_of_data，0 也列）

## 4. 每幣分佈（L7 篩選後事件）
最多 / 中位數 / 0 事件的幣數

## 5. 判定
ict_L7 IS 事件數 = N。N ≥ 150 → 「盲測門檻通過，可進 P2」；N < 150 → 「停止：依 ict_phase1.md 第 8 節回報，只能改走 ict_setup15m 或另開 top-50 計畫」。
```

- 季度用 `C.quarter_of_series`。
- 計數口徑：BOS 與 setup 依 `bos_time` 的 sample；事件依 `time` 的 sample。
- 任何 `sample != "IS"` 的列在 `funnel_markdown` 入口就先丟掉。

## 11. 驗收（全部在 repo 根目錄執行）

| # | 指令 | 期望 |
|---|---|---|
| A1 | `.venv/bin/python -m unittest discover -s research/tests -t . -v` | 全部 OK、無 skip（cache 存在時）；第 9 節每個測試名都出現 |
| A2 | `for f in research/experiments/*.yaml; do .venv/bin/python -m research.run "$f" --check --workers 6; done 2>&1 \| tee /tmp/ict_chk.log; for f in research/experiments/neighbors/*.yaml; do .venv/bin/python -m research.run "$f" --neighbor --check --workers 6; done 2>&1 \| tee -a /tmp/ict_chk.log; grep -c '^CHECK OK' /tmp/ict_chk.log; grep -c 'CHECK FAIL' /tmp/ict_chk.log` | `40`，然後 `0` |
| A3 | `.venv/bin/python -m research.phase1b regress` | 3 行 `REGRESS OK` |
| A4 | `.venv/bin/python -m research.phase1b audit` | 最後一行 `OK: main experiments 36, neighbours 4` |
| A5 | `wc -c research/out/oos_log.md`；`grep -c '\| ict_' research/out/registry.md`；`git diff --exit-code research/out/registry.md` | `0`；`0`；exit 0 |
| A6 | `ls research/cache/results/ \| grep -c '^ict_'` | `0` |
| A7 | `time .venv/bin/python -m research.ict.generate count --workers 6 --rebuild` | real ≤ 30:00；印出 `ICT COUNT L7_IS=<n> verdict=…`；產生 `research/out/ict_funnel.md` |
| A8 | `git status --porcelain src config tests docs/ARCHITECTURE.md pyproject.toml` | 空 |
| A9 | `grep -nE 'net_r\|gross\|pf\b' research/out/ict_funnel.md` | 無輸出 |

A7 超過 30 分鐘時，可以做的優化只有兩種：
- 把 IDLE 時的跳躍改得更積極。
- 每個幣只從「第一個 active segment 起點 − 60 天」開始跑，但要另加前綴測試，證明切點之後的結果相同。

不准減少 variant，不准改任何參數。

## 12. 交給 P2 的事（P1 不做）

- 寫 24 + 4 個 YAML（`research/ict/` 加上 gen 子命令）。
- `phase1b.audit` 的 allowed 清單加入 ICT manifest。
- `metrics.one_per_symbol(cooldown_us=4*3600*10**6)`，預設 0，舊行為不變。
- weekly block bootstrap、DSR、`ambiguous_trade_ratio`、關卡 A′ 報表。
- 執行順序：先 L7 加鄰居，再跑其餘實驗。

---

兩份檔案我都還沒寫進 repo，只用文字輸出。這個 session 沒有寫檔工具，所以 plan 檔也沒建。

**需要你決定的一件事**：ict_phase1.md 第 10 節第 4 點的 OOS 通過條件。定案決策沒有規定 ICT 的 OOS 通過條件，我只寫了建議值：v2 淨 R ≥ +0.05、PF ≥ 1.15、筆數 ≥ 100、6 季中 ≥ 4 季為正、多空各自 > 0。T0 commit 之前要請你確認。

我也替這些沒寫清楚的細節先選了做法：

- **冷卻**：生成器不知道平倉時間，所以「平倉後 4 根 1H」延到 P2，在 v2 用 `cooldown_us` 實作。
- **一個幣一個 setup**：改成每個 (symbol, side) 各一個 active setup。多空同時出現時交給 v2 處理，兩個都跳過。
- **觸區後出現新 BOS**：setup 進入 IN_ZONE 之後，新的 BOS 不會換掉它。
- **Zone 有效期**：重新錨定時不重置，從第一次建 zone 起算。
- **資金費率缺資料**：超過 24h 沒有資料時放行。
- **隨機基準的 TP2 錨點**：a0 取最近 24 根已收盤 1H 的最低價（做多取最高價）。

**我在 repo 裡核對過的事實**：

- **時間單位**：sim 內部是 int64 微秒。事件的 `time` 要存成 `datetime64[us, UTC]`，值等於決策那根 15m 的 close_time，sim 會在下一根開盤進場。
- **舊 40 個實驗**：36 個主實驗加 4 個鄰居 YAML。跑鄰居的 `--check` 一定要加 `--neighbor`，否則 `run.py` 會直接拒絕。
- **預算**：36 + 24 剛好等於上限 60。
- **快取位置**：ICT 的事件表不能放進 `cache/results/`，否則 `phase1b audit` 會報錯。
