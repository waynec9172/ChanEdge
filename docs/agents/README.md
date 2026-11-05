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

程式審查看 `src/chanedge`，拿實作去對架構稿正文與實作計畫。PR-1 到 PR-13 與 System One 進場路徑已經在樹上。預設旗標仍是關閉。缺模組這件事，只在審規格時不算規格錯誤。

做法、回覆格式與指令在 [review.md](review.md)。

## 現況

更新日期 2026-11-05。架構稿與實作計畫的狀態列仍是 Draft。不要把 `approve` 寫進狀態列。

**研究已結案，結論是不交易。** 在這份資料上（Binance USDⓈ-M 成交額前 20 名，樣本內 2024-01-01 → 2025-06-30）找進場優勢，研究階段 1 的 24 組與研究階段 1b 的 10 組事先登記實驗，沒有一組過關卡 A。纏論買賣點當進場，毛 R 全部為負，扣手續費之前就沒有優勢。Donchian 趨勢策略、以及把纏論結構當過濾器，也都沒過。依事先寫好的停止條件，不進研究階段 2（樣本外），不進研究階段 3，不實盤。理由在 [../research/decision-2026-11-05.md](../research/decision-2026-11-05.md)，數字在 `research/out/phase1.md` 與 `research/out/phase1b.md`。

「階段」有兩套，不要混用：

- 產品 Phase 1／2／3 是架構稿 §11：紙交易 MVP、唯讀圖形監控、Telegram 與實盤。產品 Phase 1 與產品 Phase 2（PR-13）的程式已在樹上。產品 Phase 3 沒有開始。
- 研究階段 0／1／1b／2／3 在 `research/`：工具驗證、樣本內關卡 A、樣本外關卡 B、之後的完整回測與紙交易驗證。研究停在 1b。

程式：PR-1 到 PR-13 已完成。System One 進場路徑已接入，`systemone.enabled` 預設仍是 false。`chanedge monitor` 另開行程，只綁 `127.0.0.1`，只讀 `chart_frames`。

使用者沒有明確要求之前：

- 不開新實驗，不用 `--oos`，`research/out/oos_log.md` 保持空的。樣本外 2025-07-01 → 2026-10-27 還沒用過，要留著。
- 不加 `execution/live.py`，不接 Telegram，不打開 `paper.yaml` 的旗標，不讓監控綁其他位址或加寫入路由。
- 不為了配合研究結論去改架構稿的鎖定句子。研究結論是「這套進場在這份資料上沒有優勢」，不是規格寫錯。

測試：2026-11-05 在 main `5c8c818`、Linux、Python 3.13，`pytest -q` 是 312 passed；`python -m unittest discover -s research/tests -t .` 是 Ran 101 tests OK（要有本機的 `research/cache/` 與 `data/`）。這些數字只是當時的結果。審查時自己重跑，以終端機輸出為準。

沒有使用者要求時不要 commit。
