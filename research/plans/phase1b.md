# Phase 1b 計畫：較長週期的趨勢策略，與纏論結構當過濾器（只看樣本內）

規劃者：Opus。執行者：Sonnet。日期 2026-11-05。分支 `research/phase1b`（由 `research/phase1` 最後一個 commit `73007d9` 建立）。工作目錄 `/workspace/ChanEdge-research`。
原始任務：`/workspace/cc/ph1b_prompt.md`（使用者原文；相關段落照抄在本檔 §0 與附錄 A）。研究鐵則：`research/CLAUDE.md`。前一階段計畫：`research/plans/phase1.md`（本檔沒寫到的通用規格，照它的 §3、§5.0、§7 辦理）。
裁決紀錄：`/workspace/cc/ph1b.decisions.md`。**開工前必讀；裁決優先於本計畫的任何敘述。**

**關卡數字、樣本切分、實驗上限 60、階段 0 驗證門檻一律以原文為準**（§0 逐字照抄）。執行中若覺得其中任何一條要改，或要跑 §5 清單以外的實驗：停下，寫 `/workspace/cc/ph1b.QUESTION.md`，結束本次工作。其他問題或歧義寫 `/workspace/cc/ph1b.issue.md`（背景、選項、你的建議），然後結束本次工作。**不要開始階段 2。全程不准用 `--oos`。**

本計畫分三段，對應管線的三個 stage：**prep**（§6.1）→ **run**（§6.2）→ **final**（§6.3）。每段結束都停下來，由 Opus 驗收（§7）。

---

## 0. 不可改動的條款（原文照抄）

### 0.1 關卡 A（照抄 `research/plans/phase1.md` §0.1）

使用者原始計畫（t50u）：

> * A（樣本內，2024-01 → 2025-06，簡化模擬）：要全部同時成立。
>   * 淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500
>   * ≥ 70% 的季度為正
>   * 手續費乘 1.5 倍後仍為正
>   * 相鄰參數同號

階段 1 prompt：

> 關卡 A（全部同時成立才算過）：淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500、≥ 70% 的季度為正、手續費 ×1.5 後仍為正、相鄰參數（±20%）同號。

使用者注意事項第 5 點：

> 關卡 A 的筆數、季度、PF 都用第二種計算。

（第二種 = 「每幣同時最多一筆版」。D10 規定六條全部用第二種算，獨立版照樣報。）

階段 1b prompt（使用者原文）：

> 研究規則照舊：只看樣本內、不准用 --oos、關卡 A 原文不改、以 v2（每幣同時最多一筆）為準。

> - 關卡 A 原文不變。

### 0.2 樣本切分（照抄 `phase1.md` §0.2）

> 全程只看樣本內（2024-01-01 → 2025-06-30），不准用 --oos。

> 所有關卡數字、樣本切分（樣本內 2024-01 → 2025-06、樣本外 2025-07 → 2026-10）、實驗上限 60，一律原文照抄，不得改動。

研究鐵則 3：「樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27。」
研究鐵則 4：「階段 1 全程不准用 --oos；research/out/oos_log.md 必須保持空的。」（階段 1b 同樣適用。）

### 0.3 實驗上限（照抄 `phase1.md` §0.3）

> 目標：找出扣成本後有優勢的組合。實驗總數上限 60 個，全部要記進 registry.md。

研究鐵則 6：「實驗總數上限 60 個。每次執行都要在 research/out/registry.md 追加一行（時間、實驗名、設定摘要）。」

階段 1b prompt（使用者原文）：

> 實驗（事先登記，總共最多 12 組；累計不得超過 60）：

### 0.4 階段 0 驗證門檻（照抄 `phase1.md` §0.4；本階段要重跑，門檻不得改動）

> 階段 0 的驗證門檻（對上 ≥ 80%、平均 net R 差 ≤ 0.05）

### 0.5 其他照抄條款（照抄 `phase1.md` §0.5）

- 鐵則 1：「不改 src/、config/、tests/、docs/ARCHITECTURE.md（架構稿）、pyproject.toml。可以 import chanedge，新程式全部放 research/。」
- 鐵則 2：「不加任何依賴：只用 pandas、pyarrow（含 numpy）和標準庫。」
- 鐵則 7：「關卡門檻、樣本切分、實驗上限、驗證門檻一律照原文，不准修改。覺得該改就停下來提問。」
- 鐵則 8：「過不了關卡就停下來回報，絕不為了過關調參數或追加實驗。」
- 鐵則 9：「research/cache/ 不 commit（已加進 .gitignore）。」
- 成本（階段 0 原文）：「taker 5bp、maker 2bp、市價單滑價 1bp。」
- 嚴禁前視（階段 0 原文）：「訊號時間是確認 K 收盤，最早下一根開盤進場。」
- 流程：只 commit，不 push、不開 PR、不用 `--no-verify`。不要開始階段 2。

### 0.6 關卡 A 的實作讀法（照抄 `phase1.md` §0.6，不改數字；第 6 列的鄰居定義改用 1b 原文，見表後）

全部用「每幣同時最多一筆版」（v2，§3.7）的**樣本內已成交交易**計算，比較時用原始浮點數，不先四捨五入：

| 條件 | 實作 |
| --- | --- |
| 淨 R ≥ +0.08 | `mean(net_r) >= 0.08`，net_r 已扣手續費與資金費（§3.5） |
| PF ≥ 1.2 | `sum(net_r[net_r>0]) / abs(sum(net_r[net_r<0])) >= 1.2` |
| 筆數 ≥ 500 | v2 已成交筆數 `>= 500`（限價未成交、確認放棄不算筆數） |
| ≥ 70% 的季度為正 | 6 個季度（2024Q1…2025Q2，依 signal_time 的 UTC 日期）。季度淨 R = 該季 v2 交易 net_r 的總和；> 0 為正；沒有交易的季算不為正。`正季數 / 6 >= 0.70`，等於至少 5 季（D11） |
| 手續費 ×1.5 後仍為正 | `mean(gross_r − 1.5 × fee_r − funding_r) > 0`（只放大手續費，不放大滑價與資金費，D28） |
| 相鄰參數（±20%）同號 | 這組設定的每一個鄰居，v2 `mean(net_r) > 0`（D12 P3）。缺鄰居結果算不成立（`phase1.md` §8.2） |

（表內 §3.x、D 編號指 `phase1.md` 與 `/workspace/cc/ph1.decisions.md`。）

**階段 1b 的鄰居**（使用者 1b 原文：「鄰居（不計名額，只在 P1、P2 都成立時才跑）：通道 n ±20%，初始停損 1.6 / 2.4 ATR。」）：每組 4 個鄰居 = 通道 n × 0.8、n × 1.2，以及初始停損 1.6、2.4 ATR（細節 §5.3）。第 6 條 = 這 4 個鄰居的 v2 `mean(net_r)` 全部 > 0；任何一個沒有結果 → 不成立。

### 0.7 P1、P2 與 +0.5R 警示（照抄 `phase1.md` §3.9、§3.8）

> - P1：`net_r > 0`。
> - P2：`net_fee15 >= −0.02`（「大幅轉負」= < −0.02R）。

（P1、P2 一律用 v2。1b 不晉級、不排名，P1、P2 只用來決定要不要跑鄰居。）

> 任何一組 v2 淨 R ≥ +0.5R（使用者原文：「出現每筆 +0.5R、回撤 5%，第一反應應該是懷疑過擬合或程式錯誤」）：在該輪報告標紅「疑似錯誤」，驗收者要抽 20 筆逐筆手算。這不是關卡，不得據此刪改實驗。

### 0.8 關卡 B 與研究停損條件（照抄 `phase1.md` 附錄 A.2；1b 不判定關卡 B）

> 關卡（現在就寫死）
> * A（樣本內，2024-01 → 2025-06，簡化模擬）：要全部同時成立。
>   * 淨 R ≥ +0.08、PF ≥ 1.2、筆數 ≥ 500
>   * ≥ 70% 的季度為正
>   * 手續費乘 1.5 倍後仍為正
>   * 相鄰參數同號
> * B（樣本外，2025-07 → 2026-10，只跑一次）：淨 R ≥ +0.05、PF ≥ 1.15、筆數 ≥ 300、≥ 4/6 季為正。
> * C（完整事件回測，兩段都跑）：和簡化模擬差距 ≤ 0.05R；0.5% 風險下 MaxDD ≤ 30%；兩段期末權益都高於期初。
> * D（紙交易 ≥ 10 週或 ≥ 100 筆）：平均 R > 0；滑價和成交率在假設範圍內；對帳無異常。
>
> 停損條件（研究本身的停損）
> * 全部組合都過不了 A（包含 1h、4h 和限價進場）：在合理成本下，纏論買賣點當進場訊號沒有優勢。
>   * 如果基準趨勢策略能過，改成「趨勢策略為主、纏論當過濾」。
>   * 基準也不行，就停下來重新想。
>
> 這只是示意。如果某組設定在回測裡出現每筆 +0.5R、回撤 5%，第一反應應該是懷疑過擬合或程式錯誤，而不是開心。

### 0.9 階段 1b 的停止條件與過濾判讀（使用者 1b 原文）

> 晉級與關卡：
> - 關卡 A 原文不變。
> - 「纏論過濾有沒有加分」只看同一組有過濾和沒過濾的淨 R 差，當參考，不當關卡。
>
> 停止條件：
> - 12 組裡沒有任何一組過關卡 A：寫 research/out/phase1b.md 的「無候選」結論，並明確建議停止在這份資料上尋找進場優勢。
> - 有組過 A：只停下來回報，等使用者決定是否進入階段 2。不要自動進入。

（本計畫登記 10 組主實驗，另留 2 組備用，見 §5.1。「12 組」= 本階段名額上限內實際跑的全部主實驗。）

### 0.10 「過了 A、沒過 B」的停止條件（使用者原文全文，逐字照抄自 `/workspace/cc/ph1b_prompt.md`）

> 若某組在樣本內通過關卡 A，但在樣本外（2025-07-01 → 2026-10-27）沒通過關卡 B：
> 1. 該組判定不成立，不得因為樣本外結果修改它的任何參數再重跑。
> 2. 樣本外這段資料視為已用掉。之後任何新設定或新策略都不能再用這段資料當驗證依據，只能當樣本內的一部分。
> 3. 下一輪的樣本外，只能用 2026-10-28 之後新產生的資料，也就是往後的紙交易或前推資料。至少累積 ≥ 300 筆或 ≥ 6 個月再判定，以先到者為準。
> 4. 要寫一份 decision 文件，記錄樣本內和樣本外的數字並排比較，以及「樣本外已用掉」這件事。
> 5. 這種情況下不准進入階段 3。

使用者附註（原文）：「現在沒有任何組過 A，所以這條暫時用不到，但請先寫進計畫。」本階段不跑樣本外，這條只登記，供階段 2 使用；final 的 `phase1b.md` 要原文附上（§6.3）。

---

## 1. 已查明的事實（規劃者已驗證，執行者直接採用；數字不同就寫 issue）

| 項目 | 事實 |
| --- | --- |
| registry | 26 列、26 個主實驗（階段 0 的 2 個 + 階段 1 S1 的 24 個），鄰居 0。`runs.log` 24 行（階段 0 早於 runs.log）。`oos_log.md` 0 位元組。`python -m research.phase1 audit` → `OK: main experiments 26, neighbours 0`。 |
| 名額 | 已用 26 / 60。本階段最多 12 → 累計最多 38 ≤ 60，不需要 QUESTION。 |
| 平線段（下架）掃描 | 用 `data/bars/binanceusdm/<BASE>/USDT/15m.parquet`（`is_closed` 列、依 open_time 排序），條件 `high == low == close 且 volume == 0`、連續 ≥ 96 列：聯集 591 幣中有 **111 段、111 幣**。103 段一直延續到資料結尾；**8 段之後又恢復交易（重新上架）**：AERGO（2025-03-27 09:15 → 2025-04-15 23:45）、AIA（2025-12-11 → 2026-01-19）、CTK（2024-04-01 → 2025-04-29）、CVC（2023-10-01 00:00 起，即資料第一列 → 2025-05-15）、LIT（2025-01-31 → 2025-12-22）、MAVIA（2024-12-16 → 2025-03-25）、PUMP（2025-06-13 → 2025-07-09）、SLP（2024-05-15 → 2025-07-22）。延續到結尾、且在 2025-07-01 以前開始的有 28 段（和階段 1 驗收報告的 28 個一致）。CVC 那段從第一列開始，沒有「平線前的最後一根正常 K」。18 段內部有時間缺口。所有平線 K 的 open 也等於 close；每段只有一個價格。 |
| 平線與前 20 名重疊 | 重新上架後進過前 20 名、而且在樣本內的：**AERGO**（2025-04-17 起 8 天）、**CTK**（2025-06-30，1 天）。其餘重新上架後的前 20 名都在樣本外（PUMP 2025-07-13 起 104 天、MAVIA 2025-10-27、LIT 2025-12-31、AIA 2026-01-21、CVC 2026-09-14；SLP 沒有）。下架當天仍在前 20 名的：ALPACA、BNX 各 2 天，DAM、NFP、ZKJ 各 1 天。 |
| bars 快取 | `research/cache/bars_15m.parquet` 只有 symbol、open_time、OHLC，**沒有 volume**，不能用來偵測平線；每幣只從第一段在榜起點前 1 天開始。偵測一律讀 `data/bars`。 |
| 資金費 | 4 個非 ASCII 幣名（龙虾、牛来、我踏马来了、币安人生）只缺 **2026-10**（`funding_fetch.log` 的 4 行 `UnicodeEncodeError`；其他月份 data/ 裡都有）。全部屬樣本外。`funding_fetch.log` 末行 `# done dl_monthly=488 dl_daily=0 missing=912`；日檔不可用。`funding_months.parquet` 在 2024-01 … 2025-07 共有 27 個 imputed (幣, 月)（2024-01：1、2025-07：26），其餘 local。 |
| 1d 聚合 | 聯集 591 幣的全序列 15m 以 UTC 日期切日：434,416 天，其中 431 天不滿 96 根（幾乎都是上市第一天或資料最後一天），夾在中間的只有 8 天（8 個幣）。 |
| Donchian 表 | `signals_donchian_1h.parquet` 2,769,425 列、`signals_donchian_4h.parquet` 676,742 列，n ∈ {16, 20, 24, 44, 55, 66}；另有 `.p0.parquet` 備份（只有 20、55）。在榜列：1h 142,851、4h 34,371；需要的 (幣, 4h 時段) 共 39,738 個。訊號定義（`research/donchian.py`）：收盤突破前 N 根最高/最低，只取第一根；time = 突破 K 的 close_time；defending = close；停損 = close ∓ 2.0 × 該週期 ATR(14)（取整到 tick）；反向出場 = 同 N 的未過濾反向突破，時間嚴格晚於進場那根 15m 的 open_time，下一根 15m 開盤出場（taker + 滑價）。 |
| 4h 纏論結構 | `bias_4h.parquet` 1,191,493 列、591 幣，是每根 4h 收盤時對「最近 500 根已收盤 4h K」做 `snapshot` 的 `structure_bias`（`signals.bias_series`）。一次 4h snapshot（500 根）約 6 ms；BTC 4h 全序列 walk 0.13 秒。中樞（`Zhongshu`）只追加不刪，`snapshot.zhongshus` 的最後一個就是最新的中樞（`src/chanedge/chanlun/zhongshu.py`）。 |
| 既有測試的限制 | `test_phase1.py::test_p2` 斷言「`htf_4h`、`vol_band` 用在 donchian 要報錯」→ Donchian 的纏論過濾**必須用新鍵**，不能放寬 `htf_4h`。`test_p1` 斷言四個既有 YAML 的 sha 不變。`test_donchian.py::test_d1` 迭代 `donchian.NS`。 |
| 基準（階段 1，舊規則） | v2：donchian_1h_n20 淨 R −0.0053、PF 0.992、n 6434；donchian_4h_n55 淨 R −0.0674、PF 0.916、n 961（`research/out/phase1.md`）。 |
| 環境 | 8 核、15 GB RAM。git 沒有 user.email：commit 用 `git -c user.name="Wayne" -c user.email="waynec9172@gmail.com" commit ...`，訊息結尾加 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`（或流程指定的署名行）。pre-commit hook 擋 src/ config/ tests/ docs/ARCHITECTURE.md pyproject.toml。 |

---

## 2. 規劃者決定（E 編號；E1–E5 屬下架規則，要先經 issue 裁決，見 §6.1 步驟 0）

| # | 決定 | 理由 |
| --- | --- | --- |
| E1 | 下架規則做成選填的設定鍵 `filters.delist_rule`（bool，預設 false）。`false` 時行為與現在逐位元相同，`resolved()` 不輸出它，所以階段 0、1 的 26 個 sha 都不變。**階段 1b 的每個主實驗與鄰居都必須是 `true`**（gen、audit、測試三處強制，§4.8）。往後階段的計畫也要沿用（final 註記）。 | 規則一改，設定的 sha 就跟著變，結果與設定一一對應；舊結果仍可 `--check` 重現。使用者說兩組 Donchian 基準「在新規則下重算（算進名額）」，正好是「同設定 + 規則開 → 新 sha → 新名字 → 佔名額」。 |
| E2 | 平線段偵測照使用者原文：`high == low == close` 且 `volume == 0`（完全相等），連續 ≥ 96 列（依列順序，不看時間缺口）。下架點 = 平線段第一列的前一列。平線段從第一列開始 → 沒有下架點，只禁訊號。 | 原文寫「連續 ≥ 96 根」；資料裡平線段內有缺口的 18 段，缺口不該把一段拆成兩段。 |
| E3 | **重新上架（8 段）**：建議 A = 照 1b prompt 原文「平線期間…不產生訊號、不能進場」，只禁平線期間，重新上架後照常。選項 B = 照使用者說明段「平線開始之後，這個幣不再產生任何訊號」，第一個下架點之後永遠不再交易。**由 issue 裁決**。樣本內只差在 AERGO、CTK（§1）。 | prompt 是給規劃者的正式指示；兩句話在「永久下架」時意思相同，只有重新上架時不同，而使用者寫的時候沒有考慮到重新上架。A 比較貼近字面；差異很小，照實報。 |
| E4 | 強制平倉的細節（§4.1 E）：在下架點那根先照常做排隊出場、停損、停利，仍持有才在收盤平倉；價格 = 收盤 × (1 − side × 3 × 滑價)、taker；出場那一腿的時間 = 下架點那根的 open_time（與 `end_of_data` 同慣例，資金費邊界照 `phase1.md` §3.5）。 | 撮合順序沿用階段 0；收盤平倉沿用既有的資料結束平倉慣例。 |
| E5 | **不改 `funding.parquet` 的補值邏輯**。「平線期間不計資金費」由模擬器保證：規則開時，任何持倉都在下架點收盤前平掉，平線期間沒有持倉，也就不會被扣資金費。 | 改補值會讓舊實驗的資金費變動，又不影響新規則下的任何交易。 |
| E6 | 非 ASCII 修正：只把 URL 的路徑段 percent-encode；zip 成員名檢查與本機存檔名照舊用原字串。已下載過的檔直接沿用（log 記 `cached`），不重抓。 | 最小改動；重抓 488 個已驗證過的檔沒有意義。 |
| E7 | 「反向 n/2 通道」取 `n // 2`：20 → 10、55 → **27**、16 → 8、24 → 12、44 → 22、66 → 33。鄰居改 n 時，出場通道跟著 `n // 2` 變。 | 通道長度要整數；`n // 2` 是唯一不帶額外參數的寫法。原文是「n/2」，出場綁定 n。 |
| E8 | 出場的反向通道突破用 Donchian 表中 `n = n // 2`、方向相反的**第一根突破**訊號（未過濾：不看前 20 名、不看下架），時間嚴格晚於進場那根 15m 的 open_time，下一根 15m 開盤出場。 | 進場那根突破 K 的收盤一定高於 n//2 通道下緣，所以進場後第一次跌破通道的那根一定是「第一根突破」，用既有的 first-breakout 表等價於逐根檢查。 |
| E9 | 「纏論當過濾」的四組沿用**基準的出場**（同 N 反向突破 + 2 ATR 停損），對照組就是新規則重算的兩組基準。 | 原文寫「Donchian 1h n20 與 4h n55」，指的是階段 1 那兩組基準；1h n20 不在純趨勢清單裡，所以只有基準可以當它的「沒過濾」版本。四組都用同一種出場，淨 R 差才只反映過濾。 |
| E10 | 「4h 纏論方向同向」：訊號時間 T 時，最後一根 close_time ≤ T 的 4h K 的 `structure_bias`（最近 500 根已收盤 4h K 的 snapshot，與 `bias_4h.parquet` 同一算法）。多單要 `up` 或 `breakout_up`，空單要 `down` 或 `breakout_down`（與階段 1 的 `htf_4h` 相同）；沒有值 → 不通過。新鍵 `dc_bias_4h`。 | 與階段 1 硬閘門同一定義；用新鍵，不碰既有測試。 |
| E11 | 「突破點不在 4h 中樞區間內」：突破點 = 訊號 K 收盤價（`close`）。中樞 = 同一個 4h snapshot 的 `zhongshus` 最後一個（最新的中樞，不論是否已結束）。在區間內 = `zd ≤ close ≤ zg`（閉區間）→ 不進場。snapshot 沒有任何中樞 → 通過（沒有區間可以落在裡面），另報筆數。多空同一規則。新鍵 `dc_not_in_zs4h`。 | 「4h 中樞區間」最直接的讀法是「目前最新的那個中樞」；它和方向過濾用同一個 snapshot，不偷看未來。 |
| E12 | 1d K：15m 依 open_time 的 UTC 日期分組（UTC 00:00 切日），open = 第一根 open、high = 最高、low = 最低、close = 最後一根 close、volume = 加總；open_time = 當日 00:00、close_time = 次日 00:00。有任何一根 15m 的日子都產生一根 1d K（不滿 96 根的另計數報告）。1d ATR = 1d 序列的 Wilder ATR(14)。 | 原文「1d K 由 15m 聚合，UTC 00:00 切日」。不完整的日子極少（§1），丟掉反而會讓通道視窗跳日。 |
| E13 | Donchian 表的 n 集合：1h 不變 {16, 20, 24, 44, 55, 66}（**1h 表不重建**）；4h 與 1d 用 NS_ALL = {8, 10, 12, 16, 20, 22, 24, 27, 33, 44, 55, 66}。 | 4h、1d 的純趨勢組要 n 與 n//2；1h 只用同 N 出場，不需要新 n。不動 1h 表就不會影響 1h 的舊實驗。 |
| E14 | 10 組主實驗 + 2 組備用（只能照 `phase1.md` §4.4 的方式用在裁決認定的 YAML 錯誤）。 | 使用者清單是 2 + 4 + 4 = 10 組，上限 12。 |
| E15 | 階段 0 驗證用 `research.validate --delist`：在記憶體裡把 `p0_validate_current_15m` 的設定加上 `delist_rule: true` 重新模擬，對 baseline 比對，寫 `research/out/harness_validation_delist.md`；不寫 registry、不寫結果檔（和 `--check` 一樣不算實驗）。原本的 `harness_validation.md` 不動，並證明預設路徑重新產生後完全相同。 | 「重跑階段 0 的驗證」是保真度檢查，不是績效實驗，只輸出對上率與差值；保留階段 0 的原紀錄。 |
| E16 | 階段 1 的 26 個結果檔不重跑。`research.phase1 audit` 在 1b 之後會把 `p1b_*` 判成「不在 manifest」→ 改用 `research.phase1b audit`（它同時認 p1 與 p1b 的清單）。 | 階段 1 已結束；重跑會灌 registry。 |

---

## 3. 檔案總覽

新增（全部在 research/）：

```text
research/
  phase1b.py                       # gen / runall / neighbors / table / gatea / sanity / regress / compare-base / audit / final
  experiments/
    p1b_*.yaml                     # 10 組（prep 產生，JSON 內容）
    p1b_manifest.json              # 清單、對照、鄰居
    neighbors/p1b_*__nb_*.yaml     # 只在 P1、P2 都成立時產生
  tests/
    test_delist.py                 # 下架規則（合成 K 線）
    test_phase1b.py                # 設定鍵、sha、gen、鄰居、過濾差、1d、通道出場、纏論過濾
  out/
    harness_validation_delist.md   # 新規則下的階段 0 驗證（research.validate --delist 產生）
    phase1b_run.md                 # run 的表（phase1b table 產生）
    phase1b_gateA.md               # 關卡 A 表（phase1b gatea 產生）
    phase1b.md                     # 最終結論（phase1b final 產生）
  plans/
    phase1b_decisions.md           # final 時把 /workspace/cc/ph1b.decisions.md 原樣複製進來
```

修改：`research/common.py`、`research/sim.py`、`research/run.py`、`research/augment.py`、`research/donchian.py`、`research/validate.py`、`research/tests/test_funding.py`、`research/tests/test_donchian.py`（只加測試）。既有測試只能在必要時改呼叫方式，不得刪斷言。

**不得修改**：`src/`、`config/`、`tests/`、`docs/`、`pyproject.toml`、`research/CLAUDE.md`、`research/plans/phase0.md`、`research/plans/phase1.md`、`research/plans/phase1_decisions.md`、本計畫（執行者不改）、`research/experiments/` 裡既有的 27 個檔（26 個 YAML + `p1_manifest.json`）、`research/out/harness_validation.md`、`research/out/phase1*.md`。

---

## 4. 規格

### 4.1 下架幣規則（模擬語意變更；**先走 issue 裁決，§6.1 步驟 0**）

**A. 偵測**（`.venv/bin/python -m research.augment build --only delist`，寫 `research/cache/delist.parquet`，log 追加到 `research/cache/logs/augment.log`）

1. 對每個聯集幣讀 `data/bars/.../15m.parquet` 的 `open_time, high, low, close, volume, is_closed`，只留 `is_closed`，依 open_time 排序。
2. 平線 K = `high == low == close and volume == 0`。平線段 = 連續平線 K 的最長區段（依列順序）；長度 ≥ 96 列才算。
3. 每段一列：`symbol, run_start`（第一根平線 K 的 open_time）`, run_end`（最後一根的 open_time）`, n_bars, delist_bar`（平線前最後一根正常 K 的 open_time；段從第一列開始就是 NaT）`, delist_close, to_end`（段是否延續到最後一列）`, has_gap`（段內是否有不是 15 分鐘的間隔）。
4. log 最後兩行：`# delist runs=<n> symbols=<n> to_end=<n> relist=<n> to_end_start_before_2025-07-01=<n> no_delist_bar=<n> with_gap=<n>` 與 `# done ...`。期望值見 §1（111、111、103、8、28、1、18），不同就寫 issue。

**B. 開關**：`filters.delist_rule`（E1）。chan 與 donchian 都可以用。`sim.load_market()` 在 `delist.parquet` 存在時載入成 `Market.delist = {symbol: (run_start_us[], run_end_us[], delist_us[])}`（沒有下架點填 −1）；設定開了規則而檔案不存在 → 報錯。

**C. 訊號**（規則開時，在 `select_signals` 裡做，屬訊號層：不產生 attempt、不佔用）

- 選項 A（建議）：訊號時間 T 落在某段的 `[run_start, run_end + 15 分鐘]`（閉區間）→ 剔除。包含 T = run_start（在下架點收盤發出的訊號，下一根已經是平線，不能進場）。
- 選項 B：T ≥ 該幣第一個「有下架點的段」的 run_start → 剔除；另外照 A 剔除沒有下架點的段。
- 剔除數記在 `counters["delist_filtered"]`，`run.py` 的 meta json 會帶出來。

**D. 進場防線**：成交那根 15m（jf）的 open_time 落在任何段的 `[run_start, run_end]` → attempt 狀態 `delisted_no_entry`，不產生交易、**不佔用**（v2 照 OCCUPY 規則略過）。市價進場在 C 之後不會發生；這條是給限價、確認模式的防線，照樣要測。

**E. 強制平倉**（規則開時）

1. 進場後，找第一個 `delist_us >= ot[jf]` 的下架點，對應 `market.bars` 中 open_time 相等的那一列 d。下架點在快取 K 線裡找不到 → 報錯（不應發生，發生就寫 issue）。
2. 走到 j = d 那根時，照常依序做：(1) 前一根排隊的下一根開盤出場、(2) 停損、(3) 停利。做完仍持有 → **在 d 的收盤強制平倉**，不做 (4) 收盤檢視。
3. 成交價 = `Cl[d] × (1 − side × 3 × slip)`；費率 taker；`exit_reason = "delisted"`；這一腿的時間 = `ot[d]`；`exit_time = ot[d]`；`bars_held = d − jf`。
4. `slip_r` 的這一腿 = `w × Cl[d] × 3 × slip`（實際付出的滑價）。`net_slip3` 公式不變（參考欄；這一腿會被算成 9 倍滑價，量級可忽略，報告註明）。
5. MFE/MAE 含 d 那根。資金費照 `phase1.md` §3.5：`entry_time < F <= exit_time`，所以 F ≤ ot[d] 計入，之後都不計。
6. attempts：`filled`，`end_time = ot[d]`。
7. 規則關時完全不走這段程式（回歸測試 §6.1 B4、B12 要證明）。

**F. 報告**：每組報 v2 與獨立版的 `delisted` 出場筆數（表上一欄）與 `delist_filtered`（meta）。

### 4.2 非 ASCII 幣名 percent-encode，重抓資金費率

1. `augment.py` 新增 `vision_url(kind, sym, period) -> str`：`f"{VISION}/{kind}/fundingRate/{quote(sym, safe='')}/{quote(f'{sym}-fundingRate-{period}', safe='')}.zip"`（`urllib.parse.quote`）。`_fetch_one` 改用它；CHECKSUM 網址 = 它 + `.CHECKSUM`。`validate_funding_zip` 的成員名仍是未編碼的 `<sym>-fundingRate-<period>.csv`；存檔路徑仍用未編碼字串。ASCII 幣名產生的網址必須和現在逐字相同。
2. 快取沿用（E6）：`vision_dl/monthly/<sym>/<sym>-fundingRate-<M>.csv` 已存在 → 不連網，log 行寫 `<SYM> <M> dl_monthly cached`，計入 dl_monthly；日檔同理。`# done` 行加 `cached=<n>`。
3. 執行順序：`.venv/bin/python -m research.augment fetch-funding` → `.venv/bin/python -m research.augment build --only funding`。其他行為（目標月份、補值、market 中位數）一律不改（E5）。
4. 驗收數字：4 個非 ASCII 幣的 2026-10 那 4 行不得再有 `UnicodeEncodeError`（結果是 `dl_monthly` 或照實的 404/驗證失敗都可以，照實報）；`augment.log` 的 sources 計數；2024-01 … 2025-07 的 imputed (幣, 月) 數（§1 是 27；有變就列出）。

### 4.3 1d K 線與 Donchian 表重建

1. `common.py`：`TF_US["1d"] = 86_400_000_000`、`BARS_PER_TF["1d"] = 96`、`TF_DELTA["1d"] = 1 天`；新增 `DONCHIAN_TFS = ("1h", "4h", "1d")`。`TFS` 不改（仍是 15m/1h/4h，chan 用）。
2. `donchian.py`：
   - `NS_ALL = (8, 10, 12, 16, 20, 22, 24, 27, 33, 44, 55, 66)`、`NS_BY_TF = {"1h": (16, 20, 24, 44, 55, 66), "4h": NS_ALL, "1d": NS_ALL}`；`NS = NS_ALL`（`test_d1` 迭代它）。
   - `daily_bars(df15) -> DataFrame`：E12。輸入是 `C.load_bars_df(symbol, "15m")`（全序列）。輸出欄 `open_time, close_time, open, high, low, close, volume, n15`。
   - `signals_for(symbol, tf, rank_map)`：tf = 1d 時 K 線來自 `daily_bars`；其餘照舊。n 迴圈改用 `NS_BY_TF[tf]`。
   - `build --tf <清單>`（**必填**，沒給就報錯；本階段只用 `--tf 4h,1d`，**不重建 1h**）。開始前把 `signals_donchian_4h.parquet` 複製成 `signals_donchian_4h.p1.parquet`（已存在就不覆寫）。另寫 `research/cache/bars_1d.parquet`（含 symbol）。log `research/cache/logs/donchian_build.log` 追加每個 tf 的列數、n 集合，1d 另記 `incomplete_days=<n> mid_series=<n>`（§1：431、8），最後 `# done`。
3. `sim.py`：`SimConfig` 允許 `signals.tf = "1d"`（只限 donchian）；`donchian_n` 必須在 `NS_BY_TF[tf]`；`DONCHIAN_NS` 改成 `NS_ALL`。`load_signal_table` 讀 `signals_donchian_1d.parquet`。
4. 檢查（寫進報告，並由測試 §6.1 涵蓋）：新 4h 表中 n ∈ {16, 20, 24, 44, 55, 66} 的列與 `.p1` 備份完全相同（依 symbol、type、time 排序後逐欄）；4h、1d 的 n 集合 = NS_ALL；1d 表每個 time 都是 UTC 00:00；1h 表的 md5 在 prep 前後不變。

### 4.4 新出場 `donchian_exit`（反向 n/2 通道突破）

1. 設定：`"exit": {"donchian_exit": {"enabled": true, "n": <m>}}`。只限 source = donchian；m 必須在 `NS_BY_TF[tf]`；不能和 `opposite_signal.enabled = true` 同時用。
2. **不放進 `EXIT_MODULES`**（那會讓每個設定的 resolved 多一塊、所有 sha 都變）。做法：`resolve_exit` 接受這個鍵另外處理；回傳的 exit dict 只有在 enabled 時才含 `donchian_exit`。
3. 機制（E8）：比照 `opposite_times`，取 Donchian 表中同 tf、`n == m`、方向與持倉相反的列（未過濾）的時間；進場後第一個嚴格晚於 `ot[jf]` 的時間 → 那根 15m 收盤時排隊，下一根 15m 開盤出場，taker + 滑價，`exit_reason = "channel_exit"`。其餘（停損、資金費、下架）照舊。
4. `run.summarize` 的出場標籤寫 `dcx<m>`。

### 4.5 纏論過濾（Donchian 專用）與 aug 表

1. 新選填過濾鍵（預設 false，`resolved()` 不輸出預設值；只限 source = donchian 且 tf ∈ {1h, 4h}）：`dc_bias_4h`（E10）、`dc_not_in_zs4h`（E11）。`htf_4h` 照舊只限 chan（既有測試）。
2. `.venv/bin/python -m research.augment build --only dcaug [--workers 6]` 寫 `research/cache/signals_donchian_{1h,4h}_aug.parquet`：**列數與列順序和對應的 Donchian 表完全相同**，欄 `symbol, type, time, bias4_snap, zs4_zg, zs4_zd, zs4_count`。只算 `in_top20` 的列，其餘填 None/NaN。
3. 算法：每幣讀 `signals.closed_bars("4h", symbol)`；對每個 T，`end = bisect_right(closes4h, T)`，`window = bars4h[max(0, end − 500):end]`，`snap = signals.snapshot(engine, window, "4h")`（以 `closes4h[end − 1]` 為鍵快取）；`bias4_snap = snap.structure_bias.value`；有中樞時取 `snap.zhongshus[-1]` 的 zg、zd，`zs4_count = len(snap.zhongshus)`；end = 0 → 全部空值。
4. 自我檢查：每個在榜列的 `bias4_snap` 必須等於 `signals._lookup_bias(bias_4h.parquet 該幣, T)`。log 末尾報 `# dcaug rows=<n> bias_mismatch=<n> no_bias=<n> no_zs=<n>`。**bias_mismatch > 0 就寫 issue，不往下做。**
5. `select_signals`：設定用到這兩個鍵時合併 aug（先斷言列數相同、`symbol/type/time` 逐列相等）；aug 不存在 → 報錯。`dc_bias_4h`：多單 `bias4_snap ∈ {up, breakout_up}`、空單 `∈ {down, breakout_down}`，空值擋掉。`dc_not_in_zs4h`：`zs4_count == 0` 或 `not (zs4_zd <= close <= zs4_zg)` 才通過。
6. `run.summarize` 的過濾標籤：`delist`、`bias4h`、`nozs4h`。

### 4.6 設定鍵與 sha 不變

新增的鍵全部是選填、預設值不輸出：`filters.delist_rule`、`filters.dc_bias_4h`、`filters.dc_not_in_zs4h`、`exit.donchian_exit`。測試要證明：registry 26 列的每個 YAML，現在算出的 config_sha 都等於 registry 記的 sha（不只四個）。

### 4.7 `research.validate --delist`（E15）

- `--delist`：讀 `research/experiments/<experiment>.yaml`，在記憶體把 `filters.delist_rule` 設成 true，`load_market` → `select_signals` → `simulate`，用這份交易（`net_r_ex_funding` 當 net_r，和現在一樣）對 baseline 比對；meta（config_sha、訊號數、成交數、耗時）用這次的。不寫 registry、不寫 results。
- 預設輸出 `research/out/harness_validation_delist.md`；開頭 5 行格式與 `harness_validation.md` 相同（第 1 行 `結論：PASS|FAIL（…）`）。內文加一節「下架規則影響」：sim 交易中 `delisted` 出場筆數、`delist_filtered` 訊號數、對上的配對中 sim 出場是 `delisted` 的筆數、因下架剔除而對不上的 baseline 筆數。**只報保真度與筆數，不報任何分段績效。**
- 不加 `--delist` 時行為完全不變。

### 4.8 `research/phase1b.py`

```text
python -m research.phase1b gen [--verify]           # 寫 §5.2 的 10 個 YAML（JSON 內容）+ p1b_manifest.json；--verify 只比對不寫
python -m research.phase1b runall [--kind base] [--workers 6]   # 依 manifest 呼叫 research.run（子行程）；已有結果的跳過；最後印 "# DONE run"
python -m research.phase1b neighbors [--workers 6] [--status]   # §5.3：P1 且 P2 的組才產生並跑鄰居；--status 只列缺少數
python -m research.phase1b table [--out PATH]       # 預設 research/out/phase1b_run.md
python -m research.phase1b gatea [--out PATH]       # 預設 research/out/phase1b_gateA.md（10 組；v2 與獨立版）
python -m research.phase1b sanity                   # §6.2 R3，只印 OK/FAIL 與違規數
python -m research.phase1b regress                  # §6.1 B12，只印 OK/FAIL 與列數
python -m research.phase1b compare-base             # §6.1 B14，只印 OK/FAIL 與筆數
python -m research.phase1b audit                    # §6.1 B15
python -m research.phase1b final [--promote /workspace/cc/ph1b.promote.run.md] [--out PATH]   # 產生 research/out/phase1b.md
```

- 指標全部重用 `research.metrics`（`load_is`、`one_per_symbol`、`summarize`、`gate_a`、`eligibility`）。只讀 `sample == "IS"` 的列。不得新增任何讀樣本外的參數。
- gen：每個 YAML 的 `filters.delist_rule` 必須是 true；core_sha 等於已有實驗就報錯（10 組彼此與舊實驗都不同）。不覆寫內容不同的既有檔。
- manifest：`{"run": [{"name","kind":"base|tr|filter","tf","n","exit":"same_n|half","exit_n","filter":null|"bias4h"|"nozs4h","control":null|<base 名>}], "neighbors": {"<主實驗>": [{"param":"dcn|stop","value","experiment","reuse_of"}]}, "skipped": []}`。
- neighbors：觸發 = 該組 v2 `eligibility(...)["P1"] and ["P2"]`。鄰居 YAML 照 §5.3；core_sha 等於已有結果就沿用不跑；每個都用 `research.run --neighbor`。
- table 內容：(a) v2 主表（`phase1.py` 的 17 欄，再加「下架平倉」欄 = exit_reason 為 delisted 的筆數）；(b) 獨立版主表；(c) v2 各季淨 R；(d) v2 多空與分群；(e) 出場原因分布；(f) 纏論過濾淨 R 差（§4.9）；(g) 鄰居表（觸發才有）；(h) P1/P2 機械判定與鄰居觸發；(i) 疑似錯誤標記（v2 淨 R ≥ +0.5）；(j) 下架剔除訊號數與 `dc_not_in_zs4h` 的「無中樞而通過」筆數。數字格式同 `phase1.py`（R `+0.0000`、PF `0.000`、比例 `0.0%`）。
- audit（必須全部成立才印 OK）：registry 每列都有 YAML（主實驗在 `research/experiments/`、鄰居在 `neighbors/`），現在的 config_sha 等於 registry 的 sha；每個 registry 名字都有結果檔，每個結果 json 都有 registry 列；registry 資料列數 − 階段 0 的 2 列 = `runs.log` 列數；主實驗不同名字數 ≤ 60；主實驗名字 ⊆ `p1_manifest.json` 的 S1–S3 ∪ `p1b_manifest.json` 的 run ∪ 階段 0；**每個 `p1b_` 開頭的 registry 名字（含鄰居），YAML 的 `filters.delist_rule` 都是 true**；`oos_log.md` 0 位元組。印 `OK: main experiments <n>, neighbours <n>`。

### 4.9 指標、關卡 A、過濾差

- v2 與獨立版指標照 `phase1.md` §3.7、§3.8（含 `net_slip3` 參考欄、資金費受影響筆數）。
- 關卡 A：§0.6，10 組全部判定（含兩組基準），v2 為準，獨立版另列；兩版結論不同要標出（D10）。
- P1、P2：§0.7，只用來決定是否跑鄰居。
- 纏論過濾淨 R 差（參考，不是關卡）：`Δ = v2 net_r(過濾組) − v2 net_r(對照組)`，另列獨立版 Δ、兩組的 v2 n、v2 毛 R 差。四列：1h n20 方向、1h n20 中樞外、4h n55 方向、4h n55 中樞外。
- 「最佳組」（final 第 2 行）：有過 A 的取 v2 淨 R 最高的通過組；沒有就取 10 組中 v2 淨 R 最高者（同分取 n 多、再取名稱）。

---

## 5. 實驗清單（事先登記；寫死，事後不可改）

### 5.1 名額

| 區段 | 數量 | 累計 |
| --- | --- | --- |
| 階段 0、1（已在 registry） | 26 | 26 |
| 1b 基準重算（prep 跑） | 2 | 28 |
| 1b 純趨勢 + 纏論過濾（run 跑） | 8 | 36 |
| 1b 備用（只能照 `phase1.md` §4.4：裁決認定 YAML 寫錯，以 `<原名>_r1` 重跑同一份正確設定） | 2 | 38 ≤ 60 |

鄰居不算名額（§5.3）。

### 5.2 10 組主實驗

共同設定（所有 `p1b_*`）：

```json
{
  "signals": {"source": "donchian", "tf": "<tf>", "types": ["dc<N>_long", "dc<N>_short"], "donchian_n": <N>},
  "filters": {"in_top20": true, "candidate_only": false, "gate_pass": false, "jev_min": null, "max_cost_r": null, "exclude_reemit": false, "delist_rule": true},
  "entry": {"mode": "market_next_open"},
  "stop": {"buffer_atr": 2.0, "round_to_tick": true},
  "exit": "<見下表>",
  "costs": {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1}
}
```

出場：`same_n` = `{"opposite_signal": {"enabled": true, "tf": "<tf>"}}`（與舊基準 YAML 相同：同 N 反向突破）；`half` = `{"donchian_exit": {"enabled": true, "n": <N // 2>}}`。

| # | 名稱 | 類別 | tf | N | 出場 | 額外過濾 | 對照（過濾差） | 何時跑 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `p1b_base_1h_n20` | 基準重算（= `donchian_1h_n20` + 下架規則） | 1h | 20 | same_n | — | — | prep |
| 2 | `p1b_base_4h_n55` | 基準重算（= `donchian_4h_n55` + 下架規則） | 4h | 55 | same_n | — | — | prep |
| 3 | `p1b_tr_4h_n20` | 純趨勢 | 4h | 20 | half（10） | — | — | run |
| 4 | `p1b_tr_4h_n55` | 純趨勢 | 4h | 55 | half（27） | — | — | run |
| 5 | `p1b_tr_1d_n20` | 純趨勢 | 1d | 20 | half（10） | — | — | run |
| 6 | `p1b_tr_1d_n55` | 純趨勢 | 1d | 55 | half（27） | — | — | run |
| 7 | `p1b_base_1h_n20_bias` | 纏論過濾：4h 方向同向 | 1h | 20 | same_n | `dc_bias_4h: true` | `p1b_base_1h_n20` | run |
| 8 | `p1b_base_4h_n55_bias` | 纏論過濾：4h 方向同向 | 4h | 55 | same_n | `dc_bias_4h: true` | `p1b_base_4h_n55` | run |
| 9 | `p1b_base_1h_n20_nozs` | 纏論過濾：不在 4h 中樞內 | 1h | 20 | same_n | `dc_not_in_zs4h: true` | `p1b_base_1h_n20` | run |
| 10 | `p1b_base_4h_n55_nozs` | 纏論過濾：不在 4h 中樞內 | 4h | 55 | same_n | `dc_not_in_zs4h: true` | `p1b_base_4h_n55` | run |

- #1、#2：除 name、description 與 `delist_rule` 外和舊 YAML 相同。測試要證明：把 `delist_rule` 拿掉後的 core_sha 等於 `donchian_1h_n20`、`donchian_4h_n55` 的 core_sha。
- description 由 gen 產生，例如 `1b 純趨勢 4h N=55：收盤突破，初始停損 2 ATR，反向 27 通道突破出場，前 20 名，下架規則`。

### 5.3 鄰居（不算名額；只在 P1、P2 都成立時才跑）

| 主實驗 | 通道 n ±20%（代號 `dcn`） | 初始停損（代號 `stop`） |
| --- | --- | --- |
| #1、#7、#9（1h N=20） | 16、24（types 改成 `dc16_*`/`dc24_*`；出場仍是同 N 反向） | 1.6、2.4 |
| #2、#8、#10（4h N=55） | 44、66（同上） | 1.6、2.4 |
| #3、#5（N=20，half） | 16（出場 8）、24（出場 12） | 1.6、2.4 |
| #4、#6（N=55，half） | 44（出場 22）、66（出場 33） | 1.6、2.4 |

- 一次只改一個參數；過濾鍵、`delist_rule` 照抄。`stop.buffer_atr` 直接寫字面值 `1.6`、`2.4`。
- 名稱：`<主實驗>__nb_dcn_16`、`__nb_dcn_24`、`__nb_dcn_44`、`__nb_dcn_66`、`__nb_stop_1p6`、`__nb_stop_2p4`。description：`NEIGHBOR of <主實驗>: signals.donchian_n=16 (exit n=8)` 或 `NEIGHBOR of <主實驗>: stop.buffer_atr=1.6`。YAML 放 `research/experiments/neighbors/`。
- 不測的參數：ATR 週期 14、成本、前 20 名、下架規則、過濾開關、週期（1h/4h/1d 不是彼此的鄰居）。

### 5.4 不跑的東西（照原文）

只做空、只做多、其他週期或 N、其他出場、限價進場、任何樣本外結果：都不在清單內，要跑就寫 QUESTION（使用者原文：「不要因為 1h at2 空單 +0.02、4h at2 空單 +0.05 就去試『只做空』。那是在 24 組結果裡事後挑出來的，屬於資料探勘。」）。

---

## 6. 步驟與驗收

### 6.0 通則

- 所有命令在 `/workspace/ChanEdge-research`，Python 一律 `.venv/bin/python`。
- 超過約 2 分鐘的命令用背景執行：`nohup setsid <命令> > research/cache/logs/<名>.log 2>&1 &`，之後每隔約 1 分鐘 `tail -n 5 research/cache/logs/<名>.log`，直到出現 `# done` / `# DONE`。
- 開發期間不要用 `research.run` 試跑（會灌 registry）；用 unittest、合成資料或 `--check`。
- **絕不**：`report.py --oos`、`--oos`、`signals build`（會覆寫 17 小時的快取）、`donchian build` 不帶 `--tf`、對舊實驗 `--rerun`。
- 每個 stage 結束前：`git status` 確認只動了 research/ 底下的檔、`research/cache` 沒被加入；commit；報告寫到流程指定位置（`/workspace/cc/ph1b.<stage>.report.<r>.md`），附命令輸出與實際數字。

### 6.1 prep（下架規則、資金費修正、階段 0 驗證、兩組基準重算；不跑其他實驗）

預估：寫程式 3–5 小時；資料步驟約 30 分鐘；兩組基準約 1 分鐘。

**步驟 0：下架規則的 issue（先做，做完才能改任何程式）**

1. 讀 `/workspace/cc/ph1b.decisions.md`。如果檔案不存在，或裡面沒有標題含「下架幣處理」的裁決：寫 `/workspace/cc/ph1b.issue.md`，然後**結束本次工作**（不要改程式、不要 commit）。內容：
   - 背景：使用者要求的下架規則（附錄 A.2 原文）屬模擬語意變更，照流程先裁決再改；本計畫 §4.1 是規格。
   - 待裁決點：(1) 重新上架的處理，選項 A / B（E3、§4.1 C），附 §1 的 8 段清單與樣本內只影響 AERGO、CTK 的事實；(2) 確認 E1（設定鍵、預設 false、1b 一律 true）；(3) 確認 E4（撮合順序、出場時間慣例、3 倍滑價只用在這一腿、slip_r 記實付）；(4) 確認 E5（不改補值，平線期間由模擬器保證沒有持倉）；(5) 確認 E2 的偵測細節。
   - 建議：A，其餘照計畫。
   - 請裁決者在 `/workspace/cc/ph1b.decisions.md` 的標題寫「下架幣處理」，逐點寫明決定。
2. 有裁決後照裁決做；裁決與本計畫不同處以裁決為準，並在報告列出。

**步驟 1：程式（§4.1–§4.8）**

`common.py`、`sim.py`、`run.py`（summarize 標籤、meta 的 `delist_filtered`）、`augment.py`（delist、dcaug、URL 編碼與快取沿用）、`donchian.py`、`validate.py`、`phase1b.py`。

**步驟 2：資料（全部背景執行，log 在 `research/cache/logs/`）**

1. `md5sum research/cache/signals_donchian_1h.parquet > research/cache/logs/p1b_md5_before.txt`
2. `.venv/bin/python -m research.augment fetch-funding`（log `funding_fetch.log`）→ `.venv/bin/python -m research.augment build --only funding`
3. `.venv/bin/python -m research.augment build --only delist`
4. `.venv/bin/python -m research.donchian build --tf 4h,1d`（先自動備份 `.p1`）
5. `.venv/bin/python -m research.augment build --only dcaug --workers 6`

**步驟 3：單元測試（合成 K 線，除註明外不讀真實資料；名稱照寫）**

`research/tests/test_delist.py`
- `test_x1_detect_runs`：95 根平線不算、96 根算；volume > 0 不算平線；下架點 = 段前一列；段從第一列開始 → 沒有下架點；段後恢復交易 → 偵測到 run_end、`to_end = False`；段內有時間缺口仍算同一段。
- `test_x2_forced_close_at_delist_close`：多單持有到下架點 → 出場價 = 收盤 × (1 − 3bp)、taker、`exit_reason = delisted`、`exit_time = ot[d]`、slip_r 含 3bp 那一腿；空單對稱；F ≤ ot[d] 的資金費計入、之後不計。
- `test_x3_stop_in_delist_bar_wins`：下架點那根盤中觸停損 → `structure_stop`，不是 delisted。
- `test_x4_pending_exit_at_delist_open`：前一根收盤排隊的出場在下架點那根開盤成交，不是 delisted。
- `test_x5_signals_in_flat_filtered`：T = run_start、T 在段內、T = run_end + 15 分鐘 → 剔除；T = run_start − 15 分鐘 → 保留；重新上架後的訊號依裁決（A 保留、B 剔除）。
- `test_x6_rule_off_identical`：同一組合成資料，`delist_rule` 關時結果與不帶下架資料完全相同。
- `test_x7_entry_in_flat_not_occupying`：限價單在平線段內成交 → `delisted_no_entry`、沒有交易、`metrics.one_per_symbol` 不佔用。

`research/tests/test_phase1b.py`
- `test_b1_all_registry_shas_unchanged`：registry 26 列每個 YAML 現在的 config_sha = registry 的 sha。
- `test_b2_new_keys_validation`：`delist_rule` 型別；`dc_bias_4h`、`dc_not_in_zs4h` 只限 donchian 1h/4h（chan、1d 報錯）；`donchian_exit` 只限 donchian、n 要在 `NS_BY_TF[tf]`、不能與 opposite_signal 同開；`tf = "1d"` 只限 donchian；新鍵預設值不出現在 resolved。
- `test_b3_gen_matches_plan`：`gen_specs()` 正好是 §5.2 的 10 個名稱，tf、N、出場、exit_n、過濾、對照與計畫表相同（在測試裡把表再寫一次）；每個 `delist_rule` 都是 true；#1、#2 去掉 `delist_rule` 後 core_sha = 舊基準。
- `test_b4_neighbor_specs`：`p1b_tr_4h_n55` → dcn 44（exit 22）、66（exit 33）、stop 1.6、2.4；`p1b_base_1h_n20_bias` → dcn 16、24（types 一起改、`dc_bias_4h` 保留、出場仍 opposite_signal）、stop 1.6、2.4；YAML 的 `buffer_atr` 正好是 1.6、2.4。
- `test_b5_half_channel_exit`：合成 4h 序列：多單在第一根收盤跌破前 m 根最低點的 4h K 之後的下一根 15m 開盤出場、`channel_exit`、taker + 滑價；`n // 2`：55 → 27。
- `test_b6_daily_bars_utc`：跨兩天的合成 15m → 1d 的 OHLC、volume、n15、open_time 00:00、close_time 次日 00:00；1d 訊號 time = 次日 00:00、進場在 open_time == 該時間的 15m 開盤。
- `test_b7_dc_filters`：`dc_bias_4h` 多單 up/breakout_up 通過、down 擋、None 擋，空單對稱；`dc_not_in_zs4h`：close = zd、= zg → 擋（閉區間），區間外通過，`zs4_count = 0` 通過。
- `test_b8_dcaug_no_lookahead`（讀真實 BTC 4h）：取 3 個 T，`bias4_snap`、`zs4_*` 等於只用 close_time ≤ T 的 4h K 做 snapshot 的結果；把 T 之後的 4h K 截掉重算，值不變。
- `test_b9_filter_delta`：合成 v2 摘要的 Δ 計算與符號。

`research/tests/test_funding.py` 新增 `test_f11_url_percent_encoded`：`币安人生USDT` 的網址全是 ASCII、含 `%E5%B8%81%E5%AE%89%E4%BA%BA%E7%94%9F`；`BTCUSDT` 的網址與修改前逐字相同；成員名檢查仍用原字串。

`research/tests/test_donchian.py` 新增 `test_d8_rebuilt_4h_keeps_old_n`（讀快取）：新 4h 表 n ∈ {16, 20, 24, 44, 55, 66} 的列與 `.p1` 完全相同；4h、1d 的 n 集合 = NS_ALL。

**步驟 4：回歸與階段 0 驗證**

1. `research.run` 對 `p0_validate_current_15m.yaml`、`p0_perf_15m_all.yaml` 做 `--check`（規則關的路徑沒變）。
2. `.venv/bin/python -m research.phase1b regress`：`donchian_1h_n20`、`donchian_4h_n55`、`p1s1_1h_cur` 三個舊設定（規則關）在記憶體重算，**只比樣本內列**，與結果檔逐欄相同（數值 ≤ 1e-9）。印 `REGRESS OK <name> rows=<n>`。
3. `.venv/bin/python -m research.validate --experiment p0_validate_current_15m --out /tmp/hv.md && diff /tmp/hv.md research/out/harness_validation.md`（預設路徑完全不變）。
4. `.venv/bin/python -m research.validate --experiment p0_validate_current_15m --delist`（寫 `research/out/harness_validation_delist.md`）。

**步驟 5：產生 YAML、跑兩組基準**

1. `.venv/bin/python -m research.phase1b gen`，再 `gen --verify`。
2. `.venv/bin/python -m research.phase1b runall --kind base --workers 6`（registry +2）。
3. `.venv/bin/python -m research.phase1b compare-base`：對 `donchian_1h_n20 → p1b_base_1h_n20`、`donchian_4h_n55 → p1b_base_4h_n55`，**只看樣本內**，依 signal_id 對照：新訊號集合 ⊆ 舊集合，少掉的都是下架剔除（落在平線段內）；兩邊都有的交易，除了新版 `exit_reason = delisted` 的列以外，所有欄（不含 attempt_id）逐欄相同。印各項筆數與 `COMPARE OK|FAIL`。
4. `.venv/bin/python -m research.phase1b table --out /tmp/p1b_prep.md`，把兩組基準的 v2 列（新）與 `phase1.md` 的舊列並排貼進報告。

**步驟 6：commit**（`Phase 1b prep: delist rule, funding URL fix, 1d Donchian, channel exit, chan filters, rebuilt baselines`）。

**prep 驗收（執行者自查，驗收者全部重跑）**

| # | 指令 | 通過條件 |
| --- | --- | --- |
| B0 | `grep -c "下架幣處理" /workspace/cc/ph1b.decisions.md` | ≥ 1；報告列出裁決內容與實作對應 |
| B1 | `git diff --name-only main...HEAD -- . ':!research' ':!.gitignore'` | 無輸出 |
| B2 | `git diff --name-only 73007d9 HEAD -- research/plans/phase1.md research/plans/phase1_decisions.md research/out/harness_validation.md research/CLAUDE.md research/experiments/p1_manifest.json`；以及 `git diff --name-only --diff-filter=MD 73007d9 HEAD -- research/experiments` | 都無輸出 |
| B3 | `.venv/bin/python -m unittest discover -s research/tests -t . -v` | 全部 OK、無 skip；§6.1 步驟 3 的每個測試名都出現 |
| B4 | `.venv/bin/python -m pytest -q` | 全過 |
| B5 | `… research.run research/experiments/p0_validate_current_15m.yaml --check` 與 `… p0_perf_15m_all.yaml --check` | 都是 `CHECK OK`，退出碼 0 |
| B6 | 步驟 4 第 3 點 | diff 無輸出 |
| B7 | `head -5 research/out/harness_validation_delist.md` | 第 1 行以 `結論：PASS` 開頭；報告寫對上比例、平均差、平均絕對差，以及「下架規則影響」各筆數。FAIL → 寫 issue，不得改門檻或規則 |
| B8 | `tac research/cache/logs/funding_fetch.log \| sed '/# fetch-funding start/q' \| grep -c UnicodeEncodeError`（只看最後一次執行）；`tail -1 research/cache/logs/funding_fetch.log`；`grep "# sources" research/cache/logs/augment.log \| tail -1` | 0；有 `# done`；4 個非 ASCII 幣 2026-10 的結果、各 source 計數、2024-01…2025-07 的 imputed 數寫進報告 |
| B9 | `grep "# delist" research/cache/logs/augment.log \| tail -1` | 等於 §1 的期望值（111、111、103、8、28、1、18） |
| B10 | `tail -4 research/cache/logs/donchian_build.log`；`md5sum -c research/cache/logs/p1b_md5_before.txt` | 4h、1d 的 n 集合 = NS_ALL；1d `incomplete_days=431 mid_series=8`；`# done`；1h 表 md5 不變（`OK`） |
| B11 | `grep "# dcaug" research/cache/logs/augment.log \| tail -1` | `bias_mismatch=0`；其餘數字寫進報告 |
| B12 | `.venv/bin/python -m research.phase1b regress` | 三行都是 `REGRESS OK` |
| B13 | `.venv/bin/python -m research.phase1b gen --verify` | 10 組符合 §5.2 |
| B14 | `.venv/bin/python -m research.phase1b compare-base` | `COMPARE OK`；下架剔除數、delisted 出場數寫進報告 |
| B15 | `.venv/bin/python -m research.phase1b audit` | `OK: main experiments 28, neighbours 0` |
| B16 | `tail -3 research/out/registry.md`；`test ! -s research/out/oos_log.md && echo empty` | 最後 2 列是 `p1b_base_1h_n20`、`p1b_base_4h_n55`，摘要含 `delist`；`empty` |
| B17 | `git status --porcelain`；`git ls-files research/cache \| wc -l` | 乾淨；0 |

### 6.2 run（8 組 + 條件式鄰居；跑完就停，不進階段 2）

預估：主實驗約 5–10 分鐘；鄰居視觸發而定。

1. `nohup setsid .venv/bin/python -m research.phase1b runall --workers 6 > research/cache/logs/p1b_run.log 2>&1 &`，輪詢到 `# DONE run`（已有結果的兩組基準會跳過）。
2. `.venv/bin/python -m research.phase1b table`（先產生，讓 P1/P2 有數字）。
3. `.venv/bin/python -m research.phase1b sanity` 必須 OK：
   - 所有樣本內交易：`entry_time == signal_time`（市價）、`exit_time >= entry_time`、`r_dist > 0`。
   - 下架：沒有任何交易的 entry_time 落在平線段 `[run_start, run_end]`；凡是在某個下架點收盤時仍持有的交易，`exit_reason == "delisted"` 且 `exit_time == delist_bar`。
   - 1d：每個 signal_time 都是 UTC 00:00。
   - 出場原因：half 組只會是 `structure_stop / channel_exit / delisted / end_of_data`；same_n 組只會是 `structure_stop / opposite_signal / delisted / end_of_data`。
   - 過濾組：每筆交易用 aug 重查都符合它的過濾（方向同向；收盤不在 [zd, zg]）。
   - 過濾組的樣本內訊號集合 ⊆ 對照組的訊號集合。
4. `nohup setsid .venv/bin/python -m research.phase1b neighbors --workers 6 > research/cache/logs/p1b_nb.log 2>&1 &`，輪詢到 `# DONE`；`neighbors --status` 缺少數 = 0（沒有組符合 P1 且 P2 時，應有數就是 0，照實報「未觸發」）。
5. 再跑 `table`，再跑 `gatea`。
6. `audit` 必須 OK。
7. commit（`Phase 1b run: 8 pre-registered runs + neighbours`）。報告附 v2 主表（淨 R、毛 R、手續費 R、funding_r、PF、筆數、正季、×1.5 淨 R、滑價×3 淨 R 參考）、P1/P2 與鄰居觸發、纏論過濾差表、gatea 表。**不要寫關卡 A 的通過名單（由驗收者寫），不要進階段 2。**

**run 驗收（執行者自查，驗收者重跑）**

| # | 指令 | 通過條件 |
| --- | --- | --- |
| R1 | `tail -2 research/cache/logs/p1b_run.log` | `# DONE run`，沒有 `FAILED` |
| R2 | `.venv/bin/python -m research.phase1b audit` | `OK: main experiments 36, neighbours <Y>`；Y = 觸發組數 × 4（扣掉沿用） |
| R3 | `.venv/bin/python -m research.phase1b sanity` | `sanity OK` |
| R4 | `.venv/bin/python -m research.phase1b neighbors --status` | 缺少數 = 0 |
| R5 | `.venv/bin/python -m research.phase1b table --out /tmp/t.md && diff /tmp/t.md research/out/phase1b_run.md`；gatea 同理 | 無輸出 |
| R6 | 主實驗名字 vs §5.2 | registry 新增的主實驗正好是 §5.2 的 10 個（沒有清單外；有 → 寫 QUESTION） |
| R7 | `test ! -s research/out/oos_log.md && echo empty` | `empty` |
| R8 | 抽 3 組 `.venv/bin/python -m research.run <yaml> --check`（建議 1 組 tr 1d、1 組過濾、1 組基準；有鄰居就其中 1 組換成鄰居，鄰居要加 `--neighbor`） | 都是 `CHECK OK` |
| R9 | v2 淨 R ≥ +0.5 的組 | 有就標「疑似錯誤」，驗收者抽 20 筆手算 |
| R10 | `git status --porcelain`；`git ls-files research/cache \| wc -l` | 乾淨；0 |

### 6.3 final（不跑新實驗）

1. `.venv/bin/python -m research.phase1b final --promote /workspace/cc/ph1b.promote.run.md`，產生 `research/out/phase1b.md`。`PASS_A_COUNT` 以驗收者的 promote 檔為準；程式另外自己算一次，兩者不同就寫 issue。
2. `cp /workspace/cc/ph1b.decisions.md research/plans/phase1b_decisions.md`。
3. 可選：`.venv/bin/python -m research.perf` 更新 harness_perf.md。
4. `phase1b.md` 結構（全部由程式產生；`## 執行者備註` 前一行加 `<!-- generated above; hand-written notes below -->`，只有這行以下可以手寫）：
   - **開頭 5 行（固定格式）**：
     ```
     結論：無候選（10 組事先登記實驗都沒過關卡 A）；建議停止在這份資料上尋找進場優勢｜有候選（K 組過關卡 A：a, b）；只回報，等使用者決定是否進入階段 2
     最佳組 <name>（v2）：淨 R +x.xxxx、PF x.xxx、筆數 n、正季 x/6、手續費×1.5 淨 R +x.xxxx、鄰居 全正｜有負｜未觸發（P1/P2 不成立）
     基準重算（v2，下架規則）：1h n20 淨 R …、PF …、筆數 …；4h n55 淨 R …、PF …、筆數 …（舊規則 1h …、4h …）；關卡 A：1h 過｜不過、4h 過｜不過
     纏論過濾淨 R 差（v2，參考，不是關卡）：1h n20 方向 Δ…、中樞外 Δ…；4h n55 方向 Δ…、中樞外 Δ…
     實驗用量：主實驗 X / 60（階段 0：2、階段 1：24、階段 1b：Z）、鄰居 Y 個（不計）；oos_log.md 為空；未使用 --oos；未開始階段 2
     ```
     （「舊規則」數字由程式從 `donchian_1h_n20`、`donchian_4h_n55` 的結果算，不寫死。）
   - §1 範圍：只用樣本內、沒用 --oos、v2 為準；下架規則與資金費修正一句話摘要；重新上架依裁決的處理。
   - §2 給使用者的完整 v2 表：10 組一列一組，欄 = 實驗 | 類別 | n | 淨R | 毛R | 手續費R | funding_r | PF | 勝率 | 正季 | ×1.5淨R | 滑價×3淨R(參考) | 多單淨R | 空單淨R | 下架平倉。
   - §3 關卡 A：10 組的 v2 六條實際數字（✓/✗），獨立版另列，兩版不同標出；鄰居表（有觸發才有）。
   - §4 纏論過濾淨 R 差（§4.9 四列；註明「參考，不是關卡」）。
   - §5 下架規則與資金費修正的影響：兩組基準新舊並排（v2 與獨立版的 n、淨 R、毛 R、PF、正季）；下架剔除訊號數、delisted 出場筆數；`harness_validation_delist.md` 的前 5 行；資金費重抓結果（4 個非 ASCII 幣 2026-10）。
   - §6 停止條件判讀：照抄 §0.9 原文；依 PASS_A_COUNT 寫結論。無候選時寫明「建議停止在這份資料上尋找進場優勢；ChanEdge 的資料管線、撮合、紙交易與日誌可以保留，改接其他策略想法」（使用者原文的建議）。有候選時寫明「只回報，等使用者決定是否進入階段 2；未開始階段 2」。兩種情況都原文附上 §0.10「過了 A、沒過 B」的停止條件，標明「事先登記，供階段 2 使用」。
   - §7 注意事項：E7（n//2 = 27）、E9（過濾組用基準出場）、E11（中樞定義與「無中樞而通過」筆數）、E12（1d 不完整日數）、重新上架的處理與 AERGO/CTK 影響筆數、`net_slip3` 在 delisted 腿的近似、備用 2 組是否使用、往後階段的實驗也要開 `delist_rule`（E1）。
   - §8 全部表（`phase1b table` 的內容原樣附上）。
5. commit（`Phase 1b: results and conclusion`）。報告要貼出 `phase1b.md` 開頭 5 行與 §2 完整 v2 表（使用者要求「全部完成後回報 phase1b.md 的前 5 行結論和完整的 v2 表」）。

**final 驗收**

| # | 指令 | 通過條件 |
| --- | --- | --- |
| F1 | `.venv/bin/python -m research.phase1b final --promote /workspace/cc/ph1b.promote.run.md --out /tmp/p1b.md` 後，比對兩檔在標記行以上的部分 | `diff` 無輸出 |
| F2 | `head -5 research/out/phase1b.md` | 格式照 §6.3；數字與 gatea 表、table、promote 檔一致；第 1 行與 PASS_A_COUNT 一致 |
| F3 | `grep -c "樣本外這段資料視為已用掉" research/out/phase1b.md`；`grep -c "12 組裡沒有任何一組過關卡 A" research/out/phase1b.md` | 都 ≥ 1 |
| F4 | `diff /workspace/cc/ph1b.decisions.md research/plans/phase1b_decisions.md` | 無輸出 |
| F5 | `.venv/bin/python -m research.phase1b audit`；`test ! -s research/out/oos_log.md && echo empty` | OK、主實驗數同 run 階段；`empty` |
| F6 | 抽 3 組 `--check` | 都是 `CHECK OK` |
| F7 | `git status --porcelain`；`git diff --name-only main...HEAD -- . ':!research' ':!.gitignore'` | 乾淨；無輸出 |

---

## 7. 給驗收者（Opus）

報告只拿來對照，所有數字自己重跑、自己算（使用者：「驗收由你自己重算」）。

**每個 stage 都要做**：範圍（§6.1 B1、B2）；`oos_log.md` 為空；`phase1b audit`；registry 筆數 = 實際跑過的實驗數；每組設定都在 `research/experiments/`（鄰居在 `neighbors/`）；累計主實驗 ≤ 60；抽 3 組 `--check`（不足 3 組就全抽）。

**prep**：B0–B17 全部重跑。另外：
- 確認 `ph1b.decisions.md` 有「下架幣處理」裁決，且程式照裁決實作（特別是重新上架的選項）。讀 `sim.py` 的強制平倉段，對照 §4.1 E 的撮合順序。
- 自己重跑兩組基準：`research.run research/experiments/p1b_base_1h_n20.yaml --check`、`p1b_base_4h_n55` 同樣，都要 `CHECK OK`。
- 用自寫 pandas 從 `delist.parquet` 與兩組基準的樣本內交易重查：沒有交易跨過下架點；delisted 出場價 = 下架點收盤 × (1 ∓ 3bp)。
- 下架規則有合成 K 線測試（test_delist.py 七項）且通過。

**run**：R1–R10 全部重跑。然後**自己**用 v2 重算 10 組的關卡 A（§0.6 六條，原始浮點數；鄰居條件用 §5.3 的 4 個鄰居，沒跑就是不成立），寫 `/workspace/cc/ph1b.promote.run.md`：

```text
# 階段 1b 關卡 A（驗收者判定）
PASSED_A: none                      # 有通過就列名稱，依 v2 淨 R 由高到低，逗號分隔
PASS_A_COUNT: 0
（10 組 v2 六條門檻的實際數字表；獨立版另列並標出兩版不同處；P1/P2 與鄰居觸發情形；纏論過濾淨 R 差（參考））
```

`PASS_A_COUNT` 這個字串全檔只能出現一次，數字緊接在冒號和空格後面（管線用 `grep -o 'PASS_A_COUNT: *[0-9]*' | tail -1` 讀）。有清單外的主實驗被跑 → 寫 `/workspace/cc/ph1b.QUESTION.md`。

**final**：F1–F7 全部重跑；開頭 5 行逐項對照自己算的數字；PASS_A_COUNT = 0 時第 1 行必須是「無候選…建議停止在這份資料上尋找進場優勢」，> 0 時必須是「只回報，等使用者決定是否進入階段 2」，而且沒有任何階段 2 的動作。

---

## 8. 常見錯誤（執行者注意）

- 在 issue 裁決前就改 `sim.py` 的下架語意。
- 用 `bars_15m.parquet`（沒有 volume）偵測平線。
- 強制平倉放在停損之前；或把 3 倍滑價用在其他腿。
- `delist_rule` 做成預設 true，或讓 resolved() 輸出 false → 26 個舊 sha 全變（`test_b1` 會抓到）。
- 把 `donchian_exit` 加進 `EXIT_MODULES` → 所有 sha 都變。
- 放寬 `htf_4h` 給 Donchian（會打破 `test_p2`）；要用 `dc_bias_4h`。
- 出場通道用 `round(55 / 2) = 28`；正確是 `55 // 2 = 27`。
- 出場的反向通道訊號套了前 20 名或下架過濾（出場訊號一律未過濾）。
- 中樞或方向用到 T 之後才收盤的 4h K；或用 walk 的全序列結果代替 500 根 snapshot。
- `donchian build` 沒帶 `--tf` 重建了 1h 表，或沒先備份 4h 表。
- 1d K 用本機時區切日，或丟掉不完整的日子。
- 過濾組改用 half 出場（E9：過濾組用基準出場）。
- `regress`、`compare-base` 或任何新命令印出樣本外的列或績效。
- 執行者自己寫關卡 A 通過名單，或在 final 之前就寫結論。
- 為了過關臨時加過濾、換參數、加實驗；跑只做空、只做多。過不了就照實報告。
- 開始任何階段 2 的工作。

---

## 附錄 A：使用者原文（`/workspace/cc/ph1b_prompt.md` 節錄，照抄）

### A.1 給 Opus 寫計畫的 prompt（text 區塊全文）

```text
先讀 research/CLAUDE.md、research/plans/phase1.md、research/out/phase1.md。研究規則照舊：只看樣本內、不准用 --oos、關卡 A 原文不改、以 v2（每幣同時最多一筆）為準。

背景：階段 1 結論是無候選。纏論 14 組毛 R 全部為負，判定纏論買賣點當進場沒有優勢。Donchian 1h n20 是唯一毛 R 為正的組（+0.025），但淨 R 約 0。依停損條件「基準也不行，就停下來重新想」，進入階段 1b：用小規模、事先登記的實驗，檢查較長週期的趨勢策略，以及纏論結構當過濾器有沒有加分。

開跑前先做（照 issue 流程裁決，屬於模擬語意變更）：
1. 下架幣處理：
   - 偵測：連續 ≥ 96 根 15m 的 high = low = close 而且成交量為 0，平線開始前的最後一根正常 K 視為下架點。
   - 持倉在下架點那根收盤強制平倉，用 taker 手續費加 3 倍滑價。
   - 平線期間不計資金費，也不產生訊號、不能進場。
2. 修好非 ASCII 幣名的 URL percent-encode，重新抓資金費率。
3. 重跑階段 0 的驗證，必須仍然通過；兩組 Donchian 基準在新規則下重算（算進名額）。

實驗（事先登記，總共最多 12 組；累計不得超過 60）：
- 純趨勢，初始停損 2 ATR，出場是反向 n/2 通道突破：
  - Donchian 4h n20、4h n55
  - 1d n20、1d n55（1d K 由 15m 聚合，UTC 00:00 切日）
- 纏論當過濾：
  - Donchian 1h n20 與 4h n55，各自只在 4h 纏論方向（structure_bias）同向時進場
  - 同樣兩組，改成「突破點不在 4h 中樞區間內」才進場
- 鄰居（不計名額，只在 P1、P2 都成立時才跑）：通道 n ±20%，初始停損 1.6 / 2.4 ATR。

晉級與關卡：
- 關卡 A 原文不變。
- 「纏論過濾有沒有加分」只看同一組有過濾和沒過濾的淨 R 差，當參考，不當關卡。

停止條件：
- 12 組裡沒有任何一組過關卡 A：寫 research/out/phase1b.md 的「無候選」結論，並明確建議停止在這份資料上尋找進場優勢。
- 有組過 A：只停下來回報，等使用者決定是否進入階段 2。不要自動進入。

寫 research/plans/phase1b.md 給 Sonnet 執行，驗收由你自己重算。全部完成後回報 phase1b.md 的前 5 行結論和完整的 v2 表。
```

### A.2 下架幣規則（使用者說明段原文）

> ### 1. 下架幣的平線 K 線：現在就寫成規則，之後一律套用
>
> 1. **偵測**：一個幣的 15m K 從某根起連續 ≥ 96 根（1 天）high = low = close 而且成交量為 0，就把平線開始前的最後一根正常 K 當成下架點。
> 2. **持倉**：下架點那根收盤強制平倉，用 taker 手續費加 3 倍滑價。平線期間不計資金費。
> 3. **訊號**：平線開始之後，這個幣不再產生任何訊號，也不能進場。
> 4. 修好非 ASCII 幣名的 URL 編碼（percent-encode），重新抓資金費率。
> 5. 修完後重跑階段 0 的驗證，必須仍然通過。2 組 Donchian 基準要在新規則下重算，這 2 組算進實驗名額。
>
> 這屬於模擬語意的變更，照你們的流程，用 issue 記錄裁決後再改。

### A.3 使用者的判讀與下一步（原文節錄）

> - **不要做的事**：不要因為 1h at2 空單 +0.02、4h at2 空單 +0.05 就去試「只做空」。那是在 24 組結果裡事後挑出來的，屬於資料探勘。

> - **如果這一輪也沒有任何組過 A**，我會建議停止在這份資料上找進場優勢。ChanEdge 現有的資料管線、撮合、紙交易和日誌都可以留著，改接其他策略想法。你也要有心理準備：「這個市場用這類方法賺不到錢」本身就是一個合理的結論。

> 先修下架幣的處理，再跑這 12 組。結果出來，把 `phase1b.md` 的前 5 行和 v2 表貼給我。
