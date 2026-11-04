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

- augment build：done total=114s failed=[]
- donchian build：done total=52s

## 各實驗耗時（results/*.json 的 elapsed_s）

| 實驗 | 訊號數 | 成交數 | elapsed_s |
| --- | --- | --- | --- |
| p0_perf_15m_all | 97680 | 97680 | 13.75 |
| p0_validate_current_15m | 7785 | 7041 | 17.68 |
