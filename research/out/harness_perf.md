# Harness 效能紀錄

本檔只由 `python -m research.perf` 產生；`harness_validation.md` 只由 `research.validate` 產生。

## p0_perf_15m_all（15m 全期、全幣池，門檻 10:00）

- 成交 97680 筆，訊號 97680；run.py 內部耗時 13.75 秒。
- perf.log 的 bash `real` = 0m14.424s（門檻 10:00）→ PASS。環境沒有 `/usr/bin/time`，所以用 bash `time`。
- 階段 0 驗收者冷快取重量：47.8 秒（階段 0 驗收報告）。

## 訊號快取建置

- 小樣本（`signals_build_small.log`）：build 2026-11-03T07:58:09.888854+00:00 symbols=3 modes={'15m': 'single', '1h': 'single', '4h': 'single'} workers=3
  - SOL/USDT sig15=4853 sig1h=1224 sig4h=294 elapsed=608.0s total=608s
  - ETH/USDT sig15=4986 sig1h=1214 sig4h=292 elapsed=620.6s total=621s
  - BTC/USDT sig15=4938 sig1h=1204 sig4h=280 elapsed=621.6s total=622s
- 推估總耗時（小樣本回推，公式見 phase1.md §5.1）：estimate-retro (from signals_build_small.log, 3 symbols) full=591 symbols ~ 19770 s at workers=6
- 實際總耗時（`signals_build.log`）：done total=61423s failed=[]（log 時間含機器暫停期間，非純運算時間）。

## 階段 1 補件耗時

- augment build：done total=28s failed=[]
- donchian build：done total=52s

## 各實驗耗時（results/*.json 的 elapsed_s）

| 實驗 | 訊號數 | 成交數 | elapsed_s |
| --- | --- | --- | --- |
| donchian_1h_n20 | 31358 | 31355 | 13.63 |
| donchian_4h_n55 | 4084 | 4081 | 10.93 |
| p0_perf_15m_all | 97680 | 97680 | 13.75 |
| p0_validate_current_15m | 7785 | 7041 | 17.68 |
| p1s1_15m_at2 | 41181 | 41181 | 11.84 |
| p1s1_15m_at3 | 41181 | 41181 | 11.79 |
| p1s1_15m_cur | 41181 | 41181 | 14.18 |
| p1s1_15m_cur_jevref | 10828 | 10828 | 13.33 |
| p1s1_15m_fx2 | 41181 | 41181 | 11.86 |
| p1s1_15m_fx3 | 41181 | 41181 | 11.52 |
| p1s1_15m_opp | 41181 | 41181 | 11.76 |
| p1s1_15m_rat | 41181 | 41181 | 12.69 |
| p1s1_1h_at2 | 9096 | 9096 | 9.61 |
| p1s1_1h_at3 | 9096 | 9096 | 9.73 |
| p1s1_1h_cur | 9096 | 9096 | 10.7 |
| p1s1_1h_fx2 | 9096 | 9096 | 9.55 |
| p1s1_1h_fx3 | 9096 | 9096 | 9.98 |
| p1s1_1h_opp | 9096 | 9096 | 10.11 |
| p1s1_1h_rat | 9096 | 9096 | 9.98 |
| p1s1_4h_at2 | 2401 | 2401 | 9.9 |
| p1s1_4h_at3 | 2401 | 2401 | 9.52 |
| p1s1_4h_cur | 2401 | 2401 | 10.17 |
| p1s1_4h_fx2 | 2401 | 2401 | 8.8 |
| p1s1_4h_fx3 | 2401 | 2401 | 9.54 |
| p1s1_4h_opp | 2401 | 2401 | 9.43 |
| p1s1_4h_rat | 2401 | 2401 | 9.79 |
