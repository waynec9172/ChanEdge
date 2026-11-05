# research/：研究工具索引

這個資料夾回答一個問題：纏論買賣點當進場訊號，扣掉成本之後有沒有優勢。研究已在 2026-11-05 結案，答案是在這份資料上沒有。判讀與決定在 [docs/research/decision-2026-11-05.md](../docs/research/decision-2026-11-05.md)。

本檔只是索引。規則以 [CLAUDE.md](CLAUDE.md) 為準，計畫以 `plans/` 為準，數字以 `out/` 為準。計畫檔是事先登記的紀錄，已凍結，不再改。

## 研究工具是什麼

研究工具是一套獨立的簡化模擬器。它 import `chanedge`，用產品的纏論引擎產生訊號，但不改 `src/`、`config/`、`tests/` 與架構稿，只用 pandas、pyarrow 與標準庫。

做法是先把全部訊號算一次存進快取，再用模擬器快速跑很多組進場、出場與過濾的組合。研究階段 0 先證明模擬器和產品回測對得上，之後的結果才算數。

## 研究階段與關卡

這裡的「研究階段」和架構稿 §11 的「產品 Phase 1／2／3」是兩套東西。產品 Phase 講系統做到哪，研究階段講策略驗到哪。

| 研究階段 | 做什麼 | 關卡 | 結果 |
| --- | --- | --- | --- |
| 0 | 訊號快取、模擬器，對產品回測做逐筆驗證 | 驗證門檻：對上 ≥ 80%、平均 net R 差 ≤ 0.05 | PASS，5575 / 5575（`out/harness_validation.md`） |
| 1 | 樣本內。纏論買賣點 × 週期 × 出場，加 Donchian 基準 | A | 無候選，S1 後結束（`out/phase1.md`） |
| 1b | 樣本內。Donchian 趨勢策略，與纏論結構當過濾器 | A | 無候選，建議停止（`out/phase1b.md`） |
| 2 | 樣本外，每組只跑一次 | B | 沒有進入 |
| 3 | 過了 B 之後的驗證：完整事件回測與紙交易驗證 | C、D | 沒有進入 |

關卡原文在 `plans/phase1.md` 附錄 A.2。關卡 A 以 v2（每幣同時最多一筆）為準。

## 檔案

| 路徑 | 內容 |
| --- | --- |
| [CLAUDE.md](CLAUDE.md) | 研究鐵則：不改產品程式、不加依賴、樣本切分、`--oos` 限制、實驗上限 60、`cache/` 不 commit |
| `plans/phase0.md`、`phase1.md`、`phase1b.md` | 各研究階段的事先登記計畫。§0 是照抄的原文條款 |
| `plans/phase1_decisions.md`、`phase1b_decisions.md` | 執行中的裁決副本 |
| `out/harness_validation.md`、`harness_validation_delist.md` | 研究階段 0 的驗證，以及加下架規則後的重驗 |
| `out/phase1.md`、`phase1_S1.md`、`phase1_S1_donchian_gateA.md` | 研究階段 1 的結論與表 |
| `out/phase1b.md`、`phase1b_run.md`、`phase1b_gateA.md` | 研究階段 1b 的結論與表 |
| `out/registry.md` | 每次正式執行一列。主實驗 36 個、鄰居 4 個 |
| `out/oos_log.md` | 使用 `--oos` 的紀錄。保持空的 |
| `out/harness_perf.md`、`signal_mode_check.md` | 效能紀錄、訊號模式比對 |
| `experiments/` | 每個實驗的設定檔（內容是 JSON），`neighbors/` 是鄰居，`*_manifest.json` 是清單 |
| `signals.py`、`donchian.py`、`augment.py` | 建訊號快取、Donchian 訊號表、補件（高週期筆、資金費、下架段、纏論過濾欄） |
| `sim.py`、`run.py`、`metrics.py`、`report.py` | 模擬器、執行一個實驗、指標與關卡 A、報表 |
| `validate.py`、`perf.py` | 研究階段 0 的驗證與效能 |
| `phase1.py`、`phase1_final.py`、`phase1b.py` | 研究階段 1、1b 的產生、批次執行、表、稽核、結論 |
| `tests/` | 研究工具的單元測試（`unittest`） |
| `cache/` | 快取與結果檔。在 `.gitignore`，不在 git 裡 |

## 怎麼重現

`research/cache/` 不在 git 裡。訊號快取、Donchian 表、補件、資金費與每個實驗的結果檔（`cache/results/`）都在那裡。新的 clone 沒有它，要先重建，而且需要本機的 `data/`（K 線、榜單、vision 檔）。

重建順序與指令照計畫的步驟走，不要自己改順序：

1. 訊號快取與 Donchian 表：`plans/phase0.md` 步驟 8。全量訊號建置約要 17 小時。
2. 研究階段 1 的補件：`plans/phase1.md` §5.1 與 §8.7。
3. 研究階段 1b 的資料步驟：`plans/phase1b.md` §6.1 步驟 2。

注意：

- `python -m research.signals build` 不加 `--out-dir`、只給 `--symbols` 時，會把全量快取覆寫成少數幾個幣（`plans/phase1.md` §1）。
- 實驗結果檔要重新產生時，不要寫進 `out/registry.md`。`research.run` 有 `--registry` 參數，可以指到暫存檔。同名實驗已在 registry 時，`research.run` 會拒絕重跑（`plans/phase1.md` §3.11）。
- 不要用 `--oos`。`out/oos_log.md` 要保持空的。

## 核對指令

在倉庫根目錄、有 `research/cache/` 時執行：

```text
python -m unittest discover -s research/tests -t .
python -m research.phase1b audit
python -m research.run research/experiments/<名字>.yaml --check
```

- `audit` 檢查 registry、設定檔、結果檔與 `oos_log.md`。預期 `OK: main experiments 36, neighbours 4`。
- `--check` 在記憶體重算一個實驗，和結果檔比對，印 `CHECK OK` 或 `CHECK FAIL`。不寫 registry，不印績效。鄰居要加 `--neighbor`。
- 沒有快取時，`audit` 會因為找不到結果檔而失敗。
