# 怎麼審查、怎麼用

先分清你在做哪一種。兩種的通過標準不一樣。

## 規格審查

對象是 `docs/ARCHITECTURE.md` 的文字，加上核對 `docs/IMPLEMENTATION.md` 有沒有把架構稿寫成兩種實作。

從架構稿第一行讀到「給審查者」結束。依那一節的 12 項逐條核對，不要只看前幾節。清單不複製到這裡，避免和正文分叉。

這一節的工作規則：

- 不要寫程式，不要改 `C:\Users\wayne\ChanEdge` 裡的檔案。
- 「倉庫裡沒有交易程式。不要因為找不到模組就判規格錯誤。」這句只在規格審查成立。缺檔、缺測試、PR 還沒做，都不是規格錯誤。
- 不要重寫全文，不要改風格，不要提議另一套交易哲學。
- 開頭「已鎖定，不要重開」裡的句子若和正文衝突，記成問題。不要為了改風格或改數字去重開它們。
- 實作計畫和架構稿不一致時，問題記在實作計畫。
- 狀態維持 Draft。日期維持 2026-10-28。不要把 `approve` 寫進狀態列。

回覆：

- 有問題就列清單。每條包含嚴重度（critical / major / minor）、章節、引用的原文、問題、建議改法。
- 沒有問題才寫 `approve`，並用幾句話說明核對過哪些高風險段落。
- critical：沒有這條就會算錯進出場、前視、或無法唯一實作。
- major：Phase 1 會做出兩種都說得通的行為。
- minor：不影響 Phase 1 交易結果的缺口。
- 勾完清單本身不是 `approve`，也不表示可以開始改檔或開下一個 PR。

使用者若是要這份審查稿本身，交出完整的 `docs/ARCHITECTURE.md`，不要用本資料夾代替。

## 程式審查

對象是 `src/chanedge` 與 `tests/`。對照的是架構稿從「架構設計」起的正文，以及實作計畫裡該 PR 的「怎麼寫」。不要拿開頭那句「沒有交易程式」來要求把模組刪掉，也不要拿狀態表的「規格撰寫時沒有交易程式」當成現況。

做法：

1. 讀 [purpose.md](purpose.md) 與 [map.md](map.md)，確認這個套件該擁有什麼。
2. 打開該套件、它的測試，以及實作計畫裡對應的 PR 節。
3. 行為和數字以架構稿正文為準。實作計畫若寫出第二種行為，記在實作計畫。
4. 跑下面的 pytest。沒跑過就不要寫通過。
5. 一次只審或只改使用者點名的那個 PR。PR-13 已完成。監控只讀幀，不要替它加寫入路由或改綁其他位址。

回覆仍用 critical / major / minor。每條要有：嚴重度、架構稿或實作計畫的章節、正文原句、對上的檔案與行為、問題、建議改法。`approve` 只在你跑過相關測試、而且說明核對了哪些高風險路徑時才寫。

不要把審查用的暫存腳本留在倉庫。不要為了審查去改鎖定句子、JEV 分數、硬閘門行為或 `RiskManager` 的簽名。

## 測試怎麼跑

工作目錄必須是倉庫根目錄。從 `C:\Users\wayne` 跑 pytest 會掃到使用者目錄，然後停住。

```text
Set-Location C:\Users\wayne\ChanEdge ; .\.venv\Scripts\python.exe -m pytest -q
```

只跑一個目錄時，把路徑接在 `-q` 後面，例如 `tests/app`。

作者機器的注意事項：

- 虛擬環境是 `C:\Users\wayne\ChanEdge\.venv`。不要裝進系統 Python。
- `requires-python` 是 `>=3.12`。作者本機是 Python 3.14、pytest 9.2.0。
- PowerShell 5.1 沒有 `&&`。串命令用 `;`。
- 終端機裡沒有 `grep`、`head`、`tail`、`sed`、`awk`、`find`。搜尋用編輯器或代理自己的搜尋。
- 工具的工作區常常是 `C:\Users\wayne`。搜尋與讀檔要用 ChanEdge 的絕對路徑，否則會掃到整個使用者目錄。
- 開檔用 UTF-8。
- 架構稿與實作計畫很長。不要假設某一行號是檔尾。行號會隨修訂移動，章節標題比行號可靠。

## 命令怎麼叫

入口在 `pyproject.toml`：

```text
chanedge = "chanedge.app.cli:main"
```

從倉庫根目錄用虛擬環境裡的執行檔。旗標掛在子命令上，所以順序是命令在前、旗標在後。

```text
.\.venv\Scripts\chanedge.exe download --config config/default.yaml
.\.venv\Scripts\chanedge.exe universe --config config/default.yaml
.\.venv\Scripts\chanedge.exe universe --reconstruct --config config/default.yaml
.\.venv\Scripts\chanedge.exe backtest --config config/default.yaml --overlay config/paper.yaml
.\.venv\Scripts\chanedge.exe paper --config config/paper.yaml --once
```

共用旗標是 `--config`（預設 `config/default.yaml`）、`--overlay`、`--root`（預設 `.`）、`--vision`、`--end`。`paper` 另有 `--once`。`universe` 另有 `--reconstruct`。

`download`、`universe --reconstruct`、`backtest`、`jev-warm` 只讀本機檔，連不到交易所市場清單時在 stderr 警告，改用 vision CSV 推估規格。只有 `paper` 在讀不到市場清單時直接失敗。

`backtest` 另有 `--resume <報告目錄>`。迴圈只載入在場幣種（榜上、持倉、掛單、影子單）的 K 線，每個週期只留引擎窗口加約 30 天，離場的幣種會釋放。每 96 根 15m（一天）在報告目錄寫一次 `checkpoint.pkl`（進度、broker 狀態、journal 的 rowid 標記）。程序中斷後用同樣的 `--config`/`--overlay`/`--root`/`--vision` 加 `--resume data/reports/<目錄>` 接著跑：journal 先截回檢查點，再從下一根開始，`--end` 可省略，會沿用原本的。設定或版本不同時會拒絕續跑。跑完會刪除 `checkpoint.pkl`。輸出和不中斷的一次跑完逐位元相同。`checkpoint.pkl` 是 pickle，只續跑本程式自己寫的目錄。報告庫用 `synchronous=OFF`：程序被殺可以續跑，但主機斷電可能損壞 journal，這時重跑。

`backtest` 要放行進場必須加 `--overlay config/paper.yaml`：`default.yaml` 的 `safety.kill_switch` 是 true，回測照樣套用，所有進場都會被 `KILL_SWITCH` 否決，報告會沒有成交。這時命令會在 stderr 印警告。

`main` 抓住例外，印出 `str(exc)`，回傳 1。`mode=live` 在組裝之前就失敗。`universe.mode` 為 `pin` 時，`download`、`universe`、`backtest` 回傳 1。紙交易才使用 pin 清單。

各命令的行為表在實作計畫 PR-12，不要在這裡再寫一份。
