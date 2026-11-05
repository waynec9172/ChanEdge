
# ICT 階段 1 事先登記檔（T0）

> 路徑：`research/plans/ict_phase1.md`。這份檔案要在任何 ICT 事件表建立、任何 ICT 實驗執行之前 commit。commit 之後只能用「附錄 A 修訂」追加內容，不准改寫本文。
> 依據：`/workspace/ChanEdge-ictsmc-plan.md` 的「定案決策」與「P1 任務」，以及 `research/CLAUDE.md` 的鐵則 1–9。
> 舊計畫 `research/plans/phase1.md`、`phase1b.md` 不動。

## 0. 研究問題與主假設

**H-ICT（主假設，只有一個）**：多空對稱的 ICT/SMC 結構策略在 v2（每個幣同時最多一筆）下，扣除成本與資金費後有正期望值。規則如下：
- 4H 空頭時做空、4H 多頭時做多，規則完全鏡像。
- 1H 用 swing、收盤 BOS、FVG∩OTE 建立 zone。
- 15m 觸區，再等 LTF 觸發後進場。
- 濾網有 sweep、時段、資金費率。

這個假設由實驗 `ict_L7`（完整模型）代表。

**多空對稱**：
- 一條規則寫兩次，一次做空、一次做多，鏡像方式是高↔低、`>`↔`<`、+↔−。
- 資金費率的門檻也鏡像：做空時擋 ≤ −0.05%，做多時擋 ≥ +0.05%。
- 多、空兩個狀態機各自獨立。每個 (symbol, side) 同時最多一個 active setup。
- 多空同時有部位的衝突由 v2 處理：同一時間點出現多空兩個訊號時，兩個都跳過（沿用 `metrics.one_per_symbol`）。
- 額外條件：v2 下多、空兩邊的淨 R 都要 > 0（見關卡 A′）。

## 1. 樣本切分（照原文，不准改）

- IS：2024-01-01 → 2025-06-30。2024-01-15 00:00 UTC 之前的事件因暖機不足一律丟棄，所以 ICT 實際可用的 IS 是 2024-01-15 → 2025-06-30。
- OOS：2025-07-01 → 2026-10-27。每個實驗只看一次，用 `report.py --oos` 與 `oos_log.md` 控管。
- 不做 walk-forward，不做敏感度網格。參數全部在此固定。
- 幣池：每日 top-20（`in_top20`），加上 `delist_rule: true` 和 `exclude_tradfi: true`。最後一項在 IS 不起作用，因為 tradfi 在 IS 從未進過前 20 名，但這樣 OOS 規則從一開始就一致。

## 2. IS 逆風聲明

本地 BTC/USDT 4H 收盤：2024-01-01 約 42,314，2024-12-31 約 92,759，2025-06-30 約 108,310。IS 期間大致是多頭，所以**做空的一側在 IS 屬於逆風**。

事先聲明：
1. 不會因為空單在 IS 表現差，就拿掉空方、只留多方，或事後加上任何行情狀態條件。
2. 「多、空各自 v2 淨 R > 0」這條照樣適用，空方不過就是不過。
3. 如果結果是多方過、空方不過，結論寫成「H-ICT 未通過」，不另立「只做多」的新假設。只做多要另開計畫，而且只能用新資料驗證。

## 3. 參數預設值（全部固定，IS 內不准調）

| # | 參數 | 預設值 | 落在哪裡 |
|---|---|---|---|
| 1 | Swing 確認（1H、4H、15m） | 左右各 N=2 根。左側嚴格 `>`，右側 `≥`（swing low 鏡像）。確認時點 = 右側第 N 根的 close_time | `signals.ict.swing_n` |
| 2 | ATR | Wilder 14，以 setup TF 計，預設 1H（`donchian.wilder_atr_np`） | `atr_n` |
| 3 | FVG 最小缺口 | 缺口 > 0.5 × ATR（嚴格大於） | `fvg_k` |
| 4 | OTE 區間 | 0.618–0.786，與 FVG 取交集，交集要非空（lo < hi） | `ote_lo`、`ote_hi` |
| 5 | HTF | 空頭：4H 最近兩個已確認 swing low 一個比一個低，**或** 最後一根已收盤 4H 的收盤 < EMA50(4H)。多頭鏡像 | `use_htf`、`htf_ema` |
| 6 | 下殺擴張 | 下殺段（錨點 1 的 pivot 到 BOS 那根）至少一根 setup K 線的 TR ≥ 1.5×ATR[前一根]，或成交量 ≥ 1.5× 前 20 根中位數 | `use_expansion`、`exp_tr_atr`、`exp_vol_mult`、`exp_vol_n` |
| 7 | Sweep | BOS 那根加上前 23 根（共 24 根 setup K 線）內，有一根影線穿越已確認 swing high、收盤 ≤ 該價 | `use_sweep`、`sweep_bars` |
| 8 | FVG 新鮮度 | 只做第一次觸及：zone 建立時，FVG 不能已被任何 15m K 線碰過 | `use_fresh` |
| 9 | Zone 有效期 | 第一次建立後 24 根 setup K 線（重新錨定不重置） | `zone_valid_bars` |
| 10 | LTF 觸發 | 觸區那根算第 1 根，16 根 15m 內出現其一：(a) MSS：收盤跌破觸區後形成的 15m swing low；(b) 上影線 ≥ 50% 全長，且收在下 1/3（含邊界） | `use_ltf`、`ltf_bars`、`wick_frac` |
| 11 | SL | 錨點 1（swing high）+ 0.3×ATR，對齊 tick（做空向上取整） | `stop.buffer_atr: 0.3`、`round_to_tick: true` |
| 12 | TP1 | 1.5R 平 50%，下一根起保本 | `exit.tp1 {fraction 0.5, target r, r_fallback 1.5}`、`exit.breakeven {arm_r 1.5}` |
| 13 | 剩餘部位 | TP2 = OTE 的 −0.618 延伸（`a0 − 0.618×(a1 − a0)`），出場模式為保本 | `tp2_ext`、`exit.row_target` |
| 14 | 時間障礙 | TP1 前，進場後 12 根 15m 內（含進場那根）最有利價沒到 entry_ref − 0.5R（做空），就在第 13 根開盤出場 | `exit.time_barrier {bars 12, min_r 0.5}` |
| 15 | 時段 | 決策時間 T（觸發那根 15m 的 close_time）的 UTC 小時 ∈ [7, 21)，而且是週一到週五 | `use_session` |
| 16 | 資金費率 | 最後一筆 `funding_time ≤ T` 的真實（非補值）費率：做空時 ≤ −0.0005 就擋，做多時 ≥ +0.0005 就擋。超過 24h 沒有資料視為未知，未知就放行 | `use_funding`、`funding_block` |
| 17 | 冷卻 | 平倉後 4 根 1H。生成器不知道平倉時間，所以 P1 不實作；P2 在 v2 用 `busy_until = end_time + 4h` 實作 | P2：`metrics.one_per_symbol(cooldown_us=…)` |
| 18 | 成本 | taker 5bps、maker 2bps、slip 1bps；`max_cost_r: 0.40`。滑價 ×3 只報告 | `costs`、`filters.max_cost_r` |
| 19 | 進場 | `entry.mode: market_next_open`，entry_ref = 決策那根 15m 的收盤 | `entry` |
| 20 | 暖機 | 事件 T < 2024-01-15T00:00Z 一律丟棄 | `warmup_until` |
| 21 | 錨點 0 | 因果臨時錨點：BOS 之後已收盤 setup K 線的最低價，而且創低那根不能是當前這根。之後再創新低就重新錨定 | `anchor: causal` |

P1 不做「HTF 翻多就出場」。

## 4. 關卡 A′（原文，v2、只看 IS，以下全部要達到）

- 淨 R ≥ 0.08/筆
- PF ≥ 1.2
- 手續費 ×1.5 後淨 R 仍 > 0
- 6 個季度中至少 5 個淨 R 合計 > 0
- 4 個鄰居參數組全為正
- 筆數 ≥ 150
- **新增**：以週為單位做 block bootstrap（2000 次、固定 seed），90% 單尾信賴區間下界 > 0。在 150 筆時，這條實際等於要求約 0.115R。
- 多空兩邊的淨 R 各自 > 0
- Deflated Sharpe 和滑價 ×3 只報告、不當關卡。
- 影子單只用來排序濾網，不能拿來過關。

**事先固定的計算細節**（P2 實作時照抄）：
- **v2**：`metrics.one_per_symbol`，加上冷卻 4h（第 3 節第 17 項）。
- **季度**：`C.IS_QUARTERS`，用 `signal_time` 分季。2024Q1 實際只有 01-15 之後的部分。
- **手續費 ×1.5**：沿用 `metrics.summarize` 的 `net_fee15`。
- **Block bootstrap**：
  - 區塊是 UTC 週，週一 00:00 起算（2024-01-01 剛好是週一），共 79 週（最後一週只有 2025-06-30 一天），**空週也算**。
  - 每次有放回地抽 79 週，統計量 = 抽到的交易 net_r 總和 ÷ 筆數。抽到 0 筆時，統計量記為 0。
  - `numpy.random.default_rng(20261105)`，重抽 2000 次；下界 = `np.quantile(stats, 0.10)`，必須 > 0。
- **多空**：`summarize()["long"]["net_r"] > 0`，而且 `["short"]["net_r"] > 0`。

## 5. 實驗清單（24 個，與舊研究共用上限 60：已用 36，剩 24）

共同設定（以下稱「基準 exit」）：
- `filters`：`{in_top20 true, candidate_only false, gate_pass false, jev_min null, max_cost_r 0.4, exclude_reemit false, delist_rule true, exclude_tradfi true}`
- `entry.mode`：`market_next_open`
- `stop`：`{buffer_atr 0.3, round_to_tick true}`
- `exit`：`{tp1 {enabled true, fraction 0.5, target r, r_fallback 1.5}, breakeven {enabled true, arm_r 1.5}, row_target {enabled true}, time_barrier {enabled true, bars 12, min_r 0.5}}`
- `costs`：`{taker 5, maker 2, slippage 1}`
- `signals`：`{source ict, tf 15m, types [ict_long, ict_short], donchian_n null, ict {…}}`

| # | 名稱 | 與 ict_L7 的差異（未列出者 = 第 3 節預設） |
|---|---|---|
| 1 | ict_L0 | 純結構：use_htf/expansion/fresh/ltf/sweep/session/funding 全部 false。觸區那根收盤後，下一根開盤市價進場 |
| 2 | ict_L1 | L0 + use_htf |
| 3 | ict_L2 | L1 + use_expansion |
| 4 | ict_L3 | L2 + use_fresh |
| 5 | ict_L4 | L3 + use_ltf |
| 6 | ict_L5 | L4 + use_sweep |
| 7 | ict_L6 | L5 + use_session |
| 8 | ict_L7 | L6 + use_funding = 完整模型 = **主假設 H-ICT** |
| 9 | ict_loo_htf | L7，use_htf=false |
| 10 | ict_loo_exp | L7，use_expansion=false |
| 11 | ict_loo_fresh | L7，use_fresh=false |
| 12 | ict_loo_ltf | L7，use_ltf=false（觸區即進場） |
| 13 | ict_loo_sweep | L7，use_sweep=false |
| 14 | ict_loo_session | L7，use_session=false |
| 15 | ict_x_trail | L7 事件表。exit：tp1 + breakeven + ratchet（15m 纏論筆結構追蹤，與產品 `_ratchet` 相同），row_target 關閉，time_barrier 開啟 |
| 16 | ict_x_notb | L7，time_barrier 關閉 |
| 17 | ict_rand | 隨機基準：見第 5.1 節。不得晉級 |
| 18 | ict_anchor_conf | L7，anchor=confirmed（錨點 0 必須是已確認的 swing low，確認前被碰到的 FVG 一律不新鮮、直接失效） |
| 19 | ict_setup15m | L7，setup_tf=15m（swing、BOS、FVG、OTE、ATR、zone 有效期、sweep 都改在 15m 計；觸發仍是 15m）。這是獨立假設 |
| 20–24 | ict_rsv1 … ict_rsv5 | 預留。只能經附錄 A 修訂啟用（第 9 節） |

「leave-one-out 去掉 funding」就等於 ict_L6，不重複登記。

### 5.1 隨機基準 ict_rand

- 對每個 (symbol, side, 季度)，取 ict_L7 在該格的事件數 n。在同一格裡，從符合條件的 15m K 線中，無放回均勻抽 n 根，當成決策 K 線。
- 符合條件 = HTF 與 side 同向、in_top20、時段 OK、T ≥ 暖機日。
- defending_price = T 時最近一個已確認、價格在收盤之上的 1H swing high（做多鏡像）；沒有就跳過這根重抽。
- tp2 = `a0 − 0.618×(a1 − a0)`，其中 a0 = 最近 24 根已收盤 1H 的最低價（做多鏡像）。
- 亂數：`default_rng([20261105, zlib.crc32(symbol), 0 if side==-1 else 1])`。
- exit 與 L7 相同。

## 6. 鄰居（4 個，不計入 60）

對 ict_L7（若別的候選通過其他 A′ 條件，也對它做同樣 4 個擾動）：

| 名稱 | 變動 |
|---|---|
| ict_L7__nb_fvgk_0p4 | signals.ict.fvg_k = 0.4 |
| ict_L7__nb_fvgk_0p6 | signals.ict.fvg_k = 0.6 |
| ict_L7__nb_sl_0p2 | stop.buffer_atr = 0.2 |
| ict_L7__nb_sl_0p4 | stop.buffer_atr = 0.4 |

- YAML 放在 `research/experiments/neighbors/`，description 以 `NEIGHBOR of ict_L7: ` 開頭。
- 用 `run.py --neighbor` 執行。
- 判定：4 個鄰居的 v2 淨 R 全部 > 0。

## 7. 預算、晉級與 DSR 的 N

- 主實驗總數 = 36（舊）+ 本表實際執行數，最多 60（`run.MAX_EXPERIMENTS`）。重跑用 `--rerun`，不算新名字。
- **晉級 OOS**：最多 2 個。
  - 候選：通過全部 A′ 的實驗，ict_rand 除外。
  - 排序：v2 淨 R 由大到小，再看筆數多，再看名稱。
  - 不補位：通過的不足 2 個，就只晉級通過的那些。
- **DSR 的 N** = 報告當下 `run.n_main(read_registry(registry.md))`，也就是舊 36 個加上已執行的 ICT 主實驗，全部跑完時 N = 60。
- **DSR 公式**（Bailey & López de Prado）：
  - SR 為每筆 net_r 的 mean/std(ddof=1)，用 v2、IS。
  - V[SR] 取所有已執行 ICT 主實驗 SR 的樣本變異數。
  - `SR0 = sqrt(V)·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e)))`，γ = 0.5772156649。
  - `DSR = Φ((SR−SR0)·sqrt(T−1)/sqrt(1 − skew·SR + (kurt−1)/4·SR²))`。
  - 只報告，不當關卡。

## 8. 盲測筆數 < 150 的停止規則

- 盲測數 = P1 `generate count` 產出的 ict_L7 IS 事件數，多空合計。條件是：在 in_top20、exclude_tradfi、delist_rule、暖機丟棄之後，在任何模擬、任何損益之前。
- **≥ 150**：可以進 P2。
- **< 150**：停下來回報。只剩兩條路，二選一，由使用者決定：
  - (a) 改走事先登記的 ict_setup15m。它有自己的同一條 ≥ 150 盲測門檻與自己的 OOS。
  - (b) 另開 top-50 計畫，需要新的資料流程。
  - **不准放寬任何濾網或參數**，也不准用影子單過關。
- 提醒：v2 筆數 ≤ 事件數。如果事件 ≥ 150 但 P2 的 v2 筆數 < 150，A′ 的筆數條件就不過，也沒有補救。

## 9. 預留名額規則（ict_rsv1–5）

- 只能用附錄 A 的「修訂」啟用。修訂要寫日期、名稱、與 L7 的差異、理由，在執行前 commit。
- 不准在看過任何 OOS 結果後啟用。
- 不准拿第 3 節的數值參數做網格（例如 fvg_k 0.3）。
- 啟用後計入 60 與 DSR 的 N。

## 10. OOS 規則

1. P1 與 P2 全程不准用 `--oos`；`research/out/oos_log.md` 保持 0 bytes。
2. 只有晉級的候選（≤ 2）可以看 OOS。看之前先由 `report.py --oos` 自動寫 `oos_log.md`；每個名字一次，看完不准改參數、不准追加實驗。
3. OOS 主結果排除 `TRADFI_BASES`（YAML 已經設了 `exclude_tradfi: true`）。
4. **OOS 通過條件（待使用者確認，T0 commit 前定案）**：
   - 建議：v2 淨 R ≥ +0.05、PF ≥ 1.15、筆數 ≥ 100、OOS 季度（2025Q3–2026Q4，6 季）中 ≥ 4 季為正、多空各自淨 R > 0。
   - 筆數不足 100 時只做描述，判為「不足」，不算通過。
5. 通過 A′ 和 OOS 之後，才做產品整合（`src/chanedge/ict/`）。

## 附錄 A：修訂紀錄

（空）

