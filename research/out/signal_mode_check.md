# 訊號模式比對（單次走訪 vs 滾動視窗）

幣：BTC/USDT, ETH/USDT, SOL/USDT；期間 2024-03-01 00:00 → 2024-06-01 00:00 UTC（close_time 閉區間）。
鍵 = (symbol, tf, type, time, round(defending_price, 8))。差異率 = |單次 △ 滾動| / |滾動|，三幣合併。
判定：差異率 > 0.02 的週期改用 rolling，否則 single（每個週期各自判定）。

| tf | n_single | n_rolling | sym_diff | rate | 判定 |
| --- | --- | --- | --- | --- | --- |
| 15m | 1309 | 1309 | 0 | 0.0000% | single |
| 1h | 330 | 330 | 0 | 0.0000% | single |
| 4h | 74 | 74 | 0 | 0.0000% | single |

## 不一致樣本（每週期前 20 筆）

| tf | 來源 | symbol | type | time | defending |
| --- | --- | --- | --- | --- | --- |
