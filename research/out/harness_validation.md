結論：PASS（對上 ≥ 80% 且 平均 net R 差 ≤ 0.05）
對上比例：5575 / 5575 = 100.00%
net R 相關係數：r = 0.999913（n = 5575）
平均 net R 差（sim − baseline）：-2.708e-04 ；平均絕對差：4.702e-04
訊號模式：15m=single，1h=single，4h=single；模擬耗時 17.68 秒；備註：兩種讀法結論相同

# Harness 驗證（模擬器 vs 0.15 baseline）

- 實驗：`p0_validate_current_15m`，config_sha `422b2b9d5ca3`，訊號數 7785，模擬成交 7041。
- baseline：`b78fb5ba0ff45dde_921628697ec40df8_2024-01-01_2026-10-27_2026-10-30T19-33-48`，5575 筆（預期 5575）。
- 鍵 = (symbol, signal_type/type, entry_time)；分母是全部真實交易。
- 判定（原文）：對上比例 ≥ 80% 且 |平均 net R 差| ≤ 0.05。對上比例 100.00%，|平均差| 2.708e-04。
- 另一讀法（平均絕對差 ≤ 0.05）：mean|diff| = 4.702e-04 → PASS。兩種讀法結論相同。
- |差| > 0.05 的配對數：4 / 5575。出場原因一致率 99.91%；TP1 是否成交一致率 100.00%。

## 模式比對（signal_mode_check.md 摘要）

| tf | n_single | n_rolling | sym_diff | rate | 判定 |
| --- | --- | --- | --- | --- | --- |
| 15m | 1309 | 1309 | 0 | 0.0000% | single |
| 1h | 330 | 330 | 0 | 0.0000% | single |
| 4h | 74 | 74 | 0 | 0.0000% | single |

## 未對上的 baseline 交易歸因

| 原因 | 筆數 |
| --- | --- |
| a_no_signal | 0 |
| b_candidate | 0 |
| c_gate | 0 |
| d_jev | 0 |
| e_cost | 0 |
| f_other | 0 |

(c) 的 veto_codes 分布：{}

## 出場原因混淆表（列 = baseline，欄 = sim，僅對上的配對）

| exit_reason | bias_1h | breakeven_adverse | breakeven_stop | opposite_signal | ratchet_stop | structure_stop | zhongshu_fail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bias_1h | 70 | 0 | 0 | 0 | 0 | 0 | 0 |
| breakeven_adverse | 0 | 42 | 1 | 0 | 0 | 0 | 0 |
| breakeven_stop | 0 | 0 | 1403 | 0 | 0 | 3 | 0 |
| opposite_signal | 0 | 0 | 0 | 1217 | 0 | 0 | 0 |
| ratchet_stop | 0 | 0 | 1 | 0 | 449 | 0 | 0 |
| structure_stop | 0 | 0 | 0 | 0 | 0 | 2388 | 0 |
| zhongshu_fail | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## net R 差值分位數（sim − baseline）

| q | diff |
| --- | --- |
| 0.0 | -1.001e+00 |
| 0.01 | -8.041e-05 |
| 0.05 | -7.202e-06 |
| 0.25 | -3.636e-09 |
| 0.5 | +2.498e-15 |
| 0.75 | +3.736e-09 |
| 0.95 | +8.110e-06 |
| 0.99 | +1.190e-04 |
| 1.0 | +5.125e-01 |

## 已知差異來源

- baseline 後期權益極小，數量取整（qty_step）帶來 R 雜訊；模擬器用無限可分數量。
- 帳戶與持倉上限（最多 3 倉、同向 2 倉、總名目上限）使 baseline 少做某些單；sim 不設上限，多出的單不影響對上率（分母是 baseline 的單）。
- 反向訊號只看發出當根（sim）；baseline 看視窗內所有 time > 進場決策時間的反向訊號，結果相同除非視窗滾動使舊訊號改變。
- 資金費不計（baseline r_multiple 同樣不含資金費）。
- 手續費、滑價、停損／停利撮合順序與 matcher 相同；停損價用 Decimal 對齊 tick。

## Donchian 解讀附註

「Donchian 突破（20/55）」解讀為通道長度 N=20 與 N=55 各自成一組訊號（1h 與 4h 各跑 20 與 55）；出場用同 N 的反向突破，另加 2 ATR 停損。這是規劃者的解讀。phase 0 不執行這些實驗，只提交 YAML。

## 效能與耗時

效能與耗時紀錄見 research/out/harness_perf.md（由 research.perf 產生）。

