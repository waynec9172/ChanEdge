# ChanEdge

ChanEdge 是一個個人研究專案：把纏論（Chan theory）的買賣點寫成程式，套在 Binance USDⓈ-M USDT 永續合約成交額前 20 名上，看它能不能成為有優勢的進場訊號。倉庫裡有完整的資料管線、纏論引擎、事件回測、紙交易迴圈、稽核日誌與唯讀圖形監控，以及一套事先登記、可重現的研究流程。

> **這不是可以拿來交易的策略。** 研究的結論是：在這份資料上，沒有找到扣成本後的可交易優勢。

## 想回答的問題

**纏論買賣點當進場訊號，扣掉手續費、滑價與資金費之後，有沒有優勢？**

為了避免「看完結果再挑參數」，所有實驗都事先登記、規則寫死：

- 樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27（保留不動）。
- 關卡 A（樣本內，全部同時成立才算過）：淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500、6 季中至少 5 季為正、手續費 ×1.5 後仍為正、相鄰參數（±20%）同號。
- 以「每幣同時最多一筆」（v2）為準；實驗總數上限 60。
- 研究用模擬器先和產品回測逐筆比對：5575 / 5575 筆一致，net R 相關係數 0.999913，確認數字不是模擬器的錯。

## 結果

研究在 **2026-11-05 結案**，沒有任何一組通過關卡 A，因此沒有動用樣本外資料，也沒有實盤。

- **研究階段 1（纏論買賣點進場）**：24 組全部沒過。各組**毛 R（扣成本前）全部為負**；淨 R 最好的 `p1s1_1h_cur` 為 −0.1017、PF 0.733。
- **研究階段 1b（Donchian 趨勢為主、纏論當過濾）**：10 組全部沒過。最好的 `p1b_tr_4h_n20` 淨 R +0.0105（門檻 +0.08）、PF 1.020（門檻 1.2）、筆數 1926、正季 2/6。
- **纏論過濾沒有加分**：四個加了纏論過濾的組淨 R 仍全為負（−0.0322、−0.0168、−0.0397、−0.0352）。
- 實驗用量 36 / 60，樣本外未使用。

限制：結論只限這份資料（Binance 成交額前 20 名、上述期間）與事先登記的參數，不代表「纏論在任何市場都沒用」。詳見 [結案決定](docs/research/decision-2026-11-05.md)。

## 目前面對的問題

- **進場本身沒有優勢**：纏論買賣點在扣成本之前就是負期望值，調成本或出場規則救不回來。
- **趨勢基準也很弱**：最好的趨勢組離關卡還很遠，且只有 2/6 季為正，不穩定。
- **樣本外只有一次機會**：保留的樣本外資料必須等到有策略先過關卡 A 才能用；新的樣本外檢驗只能用 2026-10-28 之後的資料（至少 300 筆或 6 個月）。
- **資料面的細節**：下架幣（長時間零成交的平線 K）、非 ASCII 幣名的資料抓取等，都需要特別處理才不會汙染結果。

## 現況

程式照舊可用：資料管線、撮合、回測、紙交易、日誌與唯讀監控（產品 Phase 2）。**產品 Phase 3（Telegram 與實盤）沒有啟動，在有策略通過關卡之前也不會啟動。**

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
