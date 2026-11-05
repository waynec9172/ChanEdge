# ChanEdge

ChanEdge 是一套自用的量化系統：用纏論引擎找 Binance USDⓈ-M USDT 永續成交額前 20 名的買賣點，經硬規則否決與 JEV 評分後，做紙交易、事件回測與稽核日誌。

## 現況

**研究已在 2026-11-05 結案，結論是不交易。** 在這份資料上（樣本內 2024-01-01 → 2025-06-30），研究階段 1 與 1b 共 34 組事先登記的實驗，沒有一組過關卡 A。纏論買賣點當進場，毛 R 全部為負。不進樣本外驗證，不實盤。理由見 [docs/research/decision-2026-11-05.md](docs/research/decision-2026-11-05.md)。

程式照舊可用：資料管線、撮合、回測、紙交易迴圈、日誌，以及唯讀圖形監控（產品 Phase 2，PR-13）。產品 Phase 3（Telegram 與實盤）沒有啟動。

「產品 Phase」和「研究階段」是兩套編號，見 [docs/agents/README.md](docs/agents/README.md) 的「現況」。

## 文件地圖

架構（系統怎麼做）：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：架構稿。行為、數字與鎖定句子以這份為準
- [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)：實作計畫，寫程式的步驟
- [docs/agents/](docs/agents/README.md)：給審查或接手的 agent 的導覽。[logic.md](docs/agents/logic.md)、[purpose.md](docs/agents/purpose.md)、[map.md](docs/agents/map.md)、[review.md](docs/agents/review.md)、[pitfalls.md](docs/agents/pitfalls.md)

研究方法（怎麼驗、什麼算過）：

- [research/README.md](research/README.md)：研究工具索引、研究階段與關卡、怎麼重現
- [research/CLAUDE.md](research/CLAUDE.md)：研究鐵則
- [research/plans/](research/plans/)：各研究階段的事先登記計畫，已凍結

結果（數字以這裡為準）：

- [research/out/phase1.md](research/out/phase1.md)：研究階段 1
- [research/out/phase1b.md](research/out/phase1b.md)：研究階段 1b
- [research/out/registry.md](research/out/registry.md)：每個實驗的執行紀錄

決定：

- [docs/research/decision-2026-11-05.md](docs/research/decision-2026-11-05.md)：為什麼停、留下什麼、怎樣才能重開

## 測試怎麼跑

在倉庫根目錄，用虛擬環境安裝：

```text
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

Windows 的寫法見 [docs/agents/review.md](docs/agents/review.md)。

研究工具的測試另外跑。部分測試要讀本機的 `research/cache/` 與 `data/`，這兩個都不在 git 裡：

```text
.venv/bin/python -m unittest discover -s research/tests -t .
```

最近一次的數字記在 [docs/agents/README.md](docs/agents/README.md) 的「現況」。那只是當時的結果，以自己重跑的終端機輸出為準。
