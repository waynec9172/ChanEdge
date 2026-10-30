# 目的

ChanEdge 是一套自用的量化系統。結構由纏論引擎負責。硬規則負責否決。JEV 是 TypeSafe System One 的品質評估器，不是自製的 Joint Evidence Valuation。角色、呼叫順序與 `0.62` 門檻寫在 [logic.md](logic.md)。標的是 Binance USDⓈ-M 的 USDT 本位永續。交易池是每天凍結一次的成交額前 20 名。每個幣種獨立決策，共用一個帳戶。

產品句子、前 20 名的算法、進出場與預設數字都在架構稿。鎖定清單在開頭「已鎖定，不要重開」，決策表在 §4，目標與非目標在 §3。審查時去對那些章節。本檔不另列一份門檻表，避免和正文分出兩個數字。

## 三個階段

Phase 1 的產品範圍是紙交易、事件回測、稽核日誌，以及把 `ChartFrame` 寫進 SQLite。完成定義在架構稿 §11.1，對照句在實作計畫「做完 Phase 1 的對照」。Phase 1 不送實盤單，不開繪圖埠，不接 Telegram。System One 進場路徑已在樹上，預設 `systemone.enabled` 仍是 false。

Phase 2 從 PR-13 開始，是唯讀圖形監控。畫面只讀已經寫好的幀，不呼叫 `ChanEngine`，沒有下單路由。PR-13 已完成：`chanedge monitor` 啟動另一個行程 `python -m chanedge.monitor`，只綁 `127.0.0.1`，經 `journal/reader.py` 以唯讀連線讀 `chart_frames`，只接受 GET／HEAD。測試在 `tests/monitor/test_reads_frames.py`。

Phase 3 才是 Telegram 與實盤。告警事件與實盤進入條件在 §11.3。組合根遇到 `mode=live` 直接失敗，而且失敗在讀取 API 金鑰之前。倉庫裡沒有可送單的 `execution/live.py`。

## 現在樹上有什麼

狀態列在架構稿與實作計畫的開頭。兩邊都寫著 PR-1 到 PR-12 已完成，以及 System One 進場路徑已接入、預設旗標仍關閉。那兩行是進度，不是新的交易規則。

已完成的能力，按套件看 [map.md](map.md)：

- 設定載入與 `config_hash`
- 領域型別與 id
- 行情、榜單、缺口、小數推估
- 日誌結構
- 纏論引擎，含二買、三買與對稱賣點
- 六通道特徵、JEV 評分、硬閘門、風險
- 管線、撮合、回測
- CLI、紙交易迴圈、重啟後從帳簿還原
- System One 進場路徑（預檢、映射、JSONL、`jev-warm`）。預設關閉，`paper.yaml` 沒有打開

紙交易與回測走同一份 `run_pipeline`、同一份 `match_bar`。回測不睡 `close_wait_seconds`，也不寫 `PIPELINE_TIMEOUT`。差異清單在 [pitfalls.md](pitfalls.md)。

## 這套系統不做的事

非目標的全文在 §3.2。審查時最常被加回來、但 Phase 1 明確不做的有：實盤單、第二家交易所、跨幣種相關性、向量化回測當成交真相、把 czsc／chan.py／chanlun-pro 放進依賴、HFT、做市、網格、加碼、同一商品多筆獨立持倉、完整特徵序列線段、資金費率收付與強平。`trades.parquet` 的 `funding_estimate_quote` 不進現金，也不進決策。
