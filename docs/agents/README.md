# 給其他 agent 的導覽

這份資料夾幫助你審查或接手 ChanEdge。它不是第三份規格。

纏論謂詞、夾具、榜單、風險與撮合以 `docs/ARCHITECTURE.md` 從「架構設計」標題開始的正文為準。寫程式的步驟以 `docs/IMPLEMENTATION.md` 為準。JEV 的身分、呼叫順序與進場門檻以 [logic.md](logic.md) 為準。架構稿 Overview、§4、§5.3、§5.8 與審查附錄的 JEV 句已改成同一套：預設是本地 `weighted-v1`，`systemone.enabled` 為 true 才走 System One 預檢。兩份若再分叉，以 logic.md 為準。其餘鎖定句子仍以架構稿為準。本資料夾不是另一份交易公式表。

## 先讀哪一份

| 檔案 | 內容 |
| --- | --- |
| [logic.md](logic.md) | 定案後的架構邏輯。先讀這份 |
| [purpose.md](purpose.md) | 這套系統做什麼、Phase 1／2／3 的界線、現在做到哪 |
| [map.md](map.md) | 實際目錄，以及每個套件負責什麼 |
| [review.md](review.md) | 兩種審查怎麼做、回覆格式、測試與命令怎麼跑 |
| [pitfalls.md](pitfalls.md) | 審查或改碼前必須先知道的陷阱。只指向章節，不重抄公式 |

## 兩種工作不要混

規格審查讀架構稿開頭「給審查者」。那一節寫給審文字的人：不要寫程式，不要改倉庫檔案。那裡的「倉庫裡沒有交易程式」是審查說明，不是現在的目錄。

程式審查看 `src/chanedge`，拿實作去對架構稿正文與實作計畫。PR-1 到 PR-12 與 System One 進場路徑已經在樹上。預設旗標仍是關閉。缺模組這件事，只在審規格時不算規格錯誤。

做法、回覆格式與指令在 [review.md](review.md)。

## 現況

狀態是 Draft。日期是 2026-10-28。不要把 `approve` 寫進狀態列。

PR-1 到 PR-12 已完成。System One 進場路徑已接入，`systemone.enabled` 預設仍是 false。2026-10-29 程式審查的 18 項與幾個收尾問題已修正。PR-13（唯讀圖形監控）在使用者要求下已完成：`chanedge monitor` 另開行程，只綁 `127.0.0.1`，只讀 `chart_frames`。使用者沒有明確說要做之前，不要加 `execution/live.py`、不要接 Telegram、不要讓監控綁其他位址或加任何寫入路由。不要把 `paper.yaml` 的旗標打開。

上次在倉庫的 `.venv` 跑完整測試是 277 passed、12.82 秒（Windows）。2026-10-29 修正審查問題並完成 PR-13 之後，在 Linux、Python 3.13 是 303 passed；2026-10-30 再審查修正之後是 308 passed。這些數字只是當時的結果。審查時自己重跑，以終端機輸出為準。

沒有使用者要求時不要 commit。
