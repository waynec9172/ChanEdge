# Phase 1 裁決紀錄

## 規劃者決定（plan，2026-11-04，Opus）

以下都是寫計畫時就決定的事。沒有任何一條改動關卡數字、樣本切分或 60 上限，所以不寫 QUESTION。細節以 `research/plans/phase1.md` 為準。

- D1 S1 的組數：原文列了 7 種出場（現行近似、不分批只棘輪、固定 2R、固定 3R、ATR 追蹤 2、ATR 追蹤 3、反向訊號），乘上 3 個週期是 21 組。原文寫「共 18 組」，最可能是把 ATR 2/3 算成一種。決定 21 組全跑，再加 2 組 Donchian 基準和 1 組 15m+JEV 參考列，S1 共 24 組。名額仍夠：最多 48 組，加 10 組備用是 58，不到 60。
- D2 60 個名額要算進 registry 裡階段 0 的 2 個實驗（run.py 本來就這樣算）。鄰居測試另外標記，不算在內。
- D3 S1 的硬閘門只有兩條：4h 方向（多單要 bias_4h ∈ {up, breakout_up}，空單要 ∈ {down, breakout_down}）和波動帶（15m ATR(14)/收盤 ∈ [atr_pct_min, atr_pct_max]，數值讀 settings，也就是 [0.001, 0.030]）。三個週期一律用從 15m 全序列算出來的 atr15_pct。不用 candidate、1h 衝突、歷史長度和成本過濾。Donchian 照階段 0 已 commit 的兩個 YAML 跑（donchian_1h_n20、donchian_4h_n55），只用前 20 名幣池，不套纏論過濾。
- D4 1h/4h 的結構元素跟著訊號週期走：反向訊號、棘輪用的筆、TP1 的前高前低、ATR 都用訊號週期的。管理節奏仍然是每根 15m 收盤檢查一次。bias 出場三個週期都用 1h bias，和現行規則一樣。
- D5 限價單的有效根數 N 和確認根數 K 都用「訊號週期的根數」計算。N = 4，K = 1。
- D6 「收盤價和防守價的中點」用防守價（defending_price）算，不用停損價。新增價位規則 defend_frac，offset = 0.5。
- D7 固定 R 停利視為掛在目標價的 maker 限價單：只有嚴格穿過才成交（多單 high > 目標，相等不算），成交價就是目標價（跳空也一樣），收 maker 費、不加滑價。現行近似的 TP1 維持 taker 加滑價（和 baseline 一致）。所有停損類出場一律 taker 加滑價。
- D8 資金費：持倉期間 [held_from, held_to) 內的每次 funding 都計入。funding_r = Σ w × side × rate × mark / R，net_r = gross_r − fee_r − funding_r。另存 net_r_ex_funding 欄位，給 validate 對 baseline 用。實際的計入邊界、權重和 mark 價寫在計畫 §3.5。【補充：補值的資金費事件一律算成本，見 D51、phase1.md §8.7】
- D9 每幣同時最多一筆（v2）：從訊號時間到 end_time 都算佔用這個幣。end_time 是出場時間、限價取消時間或確認放棄時間。新訊號要嚴格晚於 busy_until 才收。同一幣同一時間有多個訊號時：多空都有就全部跳過；同方向就三類優先於二類。被過濾器擋掉的訊號不佔用。
- D10 關卡 A 的六條全部用 v2 計算。獨立版也照樣報。若把淨 R、手續費 ×1.5、鄰居改用獨立版會得到不同結論，就在 phase1.md 標出來，交給使用者判斷。
- D11 樣本內季度 = 2024Q1 到 2025Q2 共 6 季，依 signal_time（UTC）分。分母固定是 6，沒有交易的季算不為正。「≥ 70%」等於至少 5 季為正。
- D12 晉級條件（第 6 點）：P1 v2 淨 R > 0；P2 手續費 ×1.5 後的 v2 淨 R ≥ −0.02R（「大幅轉負」定義為 < −0.02R）；P3 鄰居對照表裡所有鄰居的 v2 淨 R 都 > 0。符合的組依 v2 淨 R 由高到低取最多 2 組，同分取筆數多的。Donchian 和 15m+JEV 參考列不參加晉級。【補充：4h 七組也不參加晉級（D48）；P3 不再有「無可測鄰居」（D45）；S1 正常晉級 0 組時另有 fallback（D46）】
- D13 鄰居對照表見計畫 §3.10，寫死在程式常數裡。只對表內參數做鄰居測試。沿用現行系統、本階段沒有搜尋的參數（TP1 50%/1.5R、保本 1R、波動帶、ATR 週期、ATR 追蹤啟動門檻 0）不測。K = 1 的下鄰 K = 0 就是同設定的市價進場。設定完全相同（core_sha 相同）的結果直接沿用，不重跑。【補充：表新增 sbuf（stop.buffer_atr 0.12/0.18），見 D45、phase1.md §8.2】
- D14 S2 的「市價」列直接沿用 S1 的結果，不重跑，所以 S2 最多新增 6 組。S3 的「4h 方向開」就是基底本身。【補充：走 fallback 時 S2 每基底只有 lc、lm，市價列不是候選，見 D46】
- D15 傳統金融永續的名單寫死成 25 個（XAU XAG XAUT PAXG CL BZ GOOGL INTC MRVL MSTR MU NVDA TSLA SAMSUNG SKHY SKHYNIX SNDK SOXL SOXS CRCL EWY SPCX DRAM KORU SNXX）。這份名單由週末波動和成交量偏低核對過。這些幣在 2024-01 → 2025-06 一天都沒進過前 20 名，所以排除它們在樣本內不會改變任何結果。S3 跑之前先做檢查：基底裡受影響的樣本內交易數為 0，就不跑、不佔名額，並在 phase1.md 註明。要不要在階段 2 排除它們，樣本內資料無法回答，留給使用者決定。【補充：末句已由使用者決定——階段 2 主結果排除這 25 個幣，見 D49、phase1.md §8.6】
- D16 S3 的 JEV 門檻用 0.55 和 0.62，只在 15m 基底上跑。
- D17 最小停損距離：R_dist（含 buffer）/ 訊號週期 ATR ≥ 1.0 或 1.3；R_dist / entry_reference ≥ 1% 或 1.5%。市價和限價在掛單前判定，沒通過就不下單、不佔用。確認模式等確認完才判定，沒通過記為 abandoned。
- D18 關卡 A 的受檢組 = S3 各組加上它們的基底（S2 晉級組）。通過的組依 v2 淨 R 取前 3。Donchian 在 S1 另外檢查關卡 A，只用於研究停損條件的判讀。
- D19 鄰居測試也記進 registry.md，名稱帶 `__nb_`、摘要以 NEIGHBOR 開頭，不算進 60。YAML 放在 research/experiments/neighbors/。
- D20 重跑驗證用 `research.run --check`：在記憶體裡重算並和存檔比對，不寫 registry、不寫結果，只寫 cache/logs/checks.log。要合法重跑同一個實驗名，必須加 `--rerun "<原因>"`，而且只限 issue 裁決同意的修 bug。
- D21 新的設定鍵一律選填，預設值等於舊行為；resolved() 遇到預設值就不輸出這個鍵，所以階段 0 兩個實驗的 config_sha 不變（422b2b9d5ca3、9b64a9e432ea）。
- D22 幣種分群：major = BTC、ETH；core = 樣本內在前 20 名的天數 ≥ 274 天（547 天的 50%）；tradfi = D15 的名單；其餘是 other。
- D23 「第一根就停損」定義為 exit_reason == structure_stop 且 bars_held == 0（第一根 15m）。另外報「第一根訊號週期 K 線內」的比例當參考。
- D24 鄰居測試的觸發條件：符合 P1 和 P2 的組都跑（每一輪都一樣；S1 包含 Donchian，不含 JEV 參考列）。【補充：S1 另對 15m/1h 中 v2 毛 R ≥ +0.05 的組跑 sbuf 鄰居；4h 參考列不跑，見 D46、D48】
- D25 訊號的鍵一律用 (symbol, type, time)，因為 15m 和 1h 的 signal_id 有重複。
- D26 依流程只 commit、不 push。Donchian 鄰居需要 N = 16/24/44/66 的訊號，要重建 Donchian 訊號表。這是快取，不是實驗。

## 規劃者補充（plan 第 2 次，2026-11-04，Opus）

上一次規劃在寫完 D1–D26 後連線中斷，計畫檔沒有寫出。本次照 D1–D26 寫出 `research/plans/phase1.md`，並補上下列決定。都沒有改動關卡數字、樣本切分或 60 上限，所以不寫 QUESTION。細節以計畫為準（§ 指計畫章節）。

- D27 資金費細節（D8 所說的 §3.5）：計入 `entry_time < F <= exit_time` 的事件（entry_time、exit_time 是進出場那根 15m 的 open_time；等價於 [entry_time+1µs, exit_time+1µs)）。權重 = 出場時間 ≥ F 的腿的比例。mark = close_time == F 那根 15m 的收盤，沒有就用 open_time == F 那根的開盤。calc_time 四捨五入到分鐘。持倉經過沒有 CSV 的月份 → funding_missing = True，該事件當 0，報缺漏筆數。vision 月檔只到 2026-09（樣本外缺 2026-10），本階段不處理，留給階段 2。【補充：末句「本階段不處理」已由使用者裁示取代——先下載、抓不到就補值，見 D50、D51、phase1.md §8.7】
- D28 「手續費 ×1.5」只放大 fee_r（maker/taker 手續費），不放大滑價（已在 gross_r 內）與資金費：net_fee15 = gross_r − 1.5 × fee_r − funding_r。
- D29 S1 出場定義：cur = preset current，反向訊號週期改成訊號週期；rat = preset ratchet_only（保本 1R + 訊號週期筆棘輪）；fx2/fx3 = 只有 fixed_r；at2/at3 = 只有 atr_trail（arm 0，ATR 為進場時的訊號週期 ATR）；opp = 只有反向訊號。除列出的模組外不加保本或其他出場，都保留初始結構停損。15m+JEV 參考列的出場用 cur，過濾 = S1 硬閘門 + jev ≥ 0.62，名稱 p1s1_15m_cur_jevref。
- D30 【已被使用者裁示取代（2026-11-04 17:59）：末句「無可測鄰居（成立）」取消，改見 D45 與 phase1.md §8.2；前半的 ±20%、整數 ±1、限價 offset 規則仍有效】鄰居表補充（§3.10）：連續參數照字面 ±20%（JEV 0.62 → 0.496/0.744，0.55 → 0.44/0.66；最小停損 1.3 ATR → 1.04/1.56）；整數根數 ±1。限價 signal_close 的價位 offset 是 0，±20% 仍是 0，所以只測有效根數 N。~~沒有任何表內參數的設定（例如 cur/rat/opp + 市價 + S1 硬閘門），「相鄰參數同號」與晉級 P3 記為「無可測鄰居（成立）」，並在每輪表與 phase1.md 明列，交使用者判讀。~~
- D31 S2 的候選包含市價列（= S1 晉級組本身）；S3 每個基底跑最多 8 種過濾（ms10a、ms13a、ms1p、ms15p、no4h、xtf、jev055、jev062）。因為市價列與基底都在候選中，「無候選」實際上只會在 S1 或 S3 發生。S3 的 PROMOTE_COUNT = 列出的通過關卡 A 組數（最多 3）。【補充：末句「無候選只會在 S1 或 S3 發生」在走 fallback 時不成立，S2 也可能無候選，見 D46】
- D32 晉級檔格式：S1/S2 寫 `PROMOTED: a, b`（0 組寫 `PROMOTED: none`）與 `PROMOTE_COUNT: n`；S3 寫 `PASSED_A: …`、`PASSED_A_TOTAL: …`、`PROMOTE_COUNT: …`。gen S2/S3 讀 PROMOTED 行。【補充：S1 晉級檔加 MODE 行、PROMOTE_COUNT 含 fallback，見 D47、phase1.md §8.9】
- D33 備用 10 組只能用在：經 issue 裁決認定清單內某組 YAML 寫錯，以 `<原名>_r1` 重跑正確設定。不得用來新增設定（新增要寫 QUESTION）。程式修 bug 重跑同設定用 --rerun，不佔名額。
- D34 樣本歸屬沿用階段 0：看 signal_time。樣本內訊號持有到 2025-07-01 之後的交易照算進樣本內，不截斷，但每組另報筆數 n_cross，final 的穩健性檢查列出去掉這些交易後的淨 R。
- D35 波動帶的 atr15_pct 一律用 data/bars 的 15m 全序列 Wilder ATR(14) / 收盤（bars_15m 快取只有 1 天暖機，不用）。15m 訊號也用它（D3），prep 要報告它與 FeatureBuilder atr_pct 的差異與判定不同的筆數；> 1% 就寫 issue。
- D36 1h/4h 的筆事件用 signals.walk() 在完整已收盤 1h/4h 序列上產生（bi_events_{1h,4h}.parquet）。TP1 前高前低 = confirm_time ≤ t 的最後一條同方向筆終點（套用 replace），存成 signals_{tf}_aug.parquet 的 tp_up_end/tp_down_end；15m 的 tp_*_end 照抄 last_*_end，所以階段 0 結果不變。aug 檔與原表同列數、同順序，合併前逐列斷言 symbol/type/time 相同。
- D37 注意事項 1 的做法：validate.py 拿掉耗時段（開頭 5 行格式不變），重新產生 harness_validation.md；新增 research.perf 產生 harness_perf.md。小樣本推估從既有 signals_build_small.log 回推，追加到 signals_build.log 末尾（`# estimate-retro`），不重跑 signals build（--symbols 會覆寫全量快取）。signals build 加 --out-dir，日後小樣本跑會自動寫 `# estimate`。
- D38 實驗 YAML 由 research.phase1 gen 產生，內容是 JSON（YAML 子集；research 內不准 import yaml，已驗證 C.read_yaml 可讀）。p1_manifest.json 記錄每輪清單、沿用、跳過與鄰居對應，並 commit。
- D39 槓桿改善的定義（§3.12）：v2 淨 R，只看纏論主實驗。週期 = 同出場下 max(1h,4h) − 15m；出場 = 同週期下 max 出場 − cur；進場 = 同基底下 max(限價/確認) − 市價；過濾 = 同基底下 max 過濾 − 基底。各取最大 Δ，四者中最大的就是「改善最多的槓桿」；沒跑到的輪次標「未測」。JEV 參考列只當參考。【補充：4h 是參考列，週期槓桿主值只用 1h，見 D48】
- D40 【已被使用者裁示取代（2026-11-04 17:59）：S1 無組晉級時改跑限價 fallback，判讀文字改見 D46 與 phase1.md §8.4 第 10 點】~~研究停損判讀：若在 S1 就無候選，限價進場沒測到，phase1.md 要明寫「研究停損條件（含限價進場）未完整檢驗」，並照實列出 Donchian 的關卡 A 結果，交使用者判斷，不另跑實驗。~~
- D41 S3 排除傳統金融的「受影響筆數」以基底的獨立版樣本內交易計算；= 0 就不跑、不佔名額、manifest 記 skipped。
- D42 限價有效期與確認等待窗都以時間判定：15m K 的 open_time < T + N（或 K）× 訊號週期。確認窗最後一根必須 close_time == T + K × 週期，缺資料視為 abandoned。
- D43 每幣同時最多一筆（v2）只用樣本內的 attempts 計算，不讀任何樣本外列。佔用類 status = filled / unfilled / abandoned；其他（minstop_rejected、invalid_stop、cost_rejected、no_entry_bar、no_bars）不佔用。新訊號 signal_time 必須嚴格大於 busy_until。


## 使用者裁示（2026-11-04 17:59）與規劃者落實（amend，2026-11-04，Opus）

使用者原文：`/workspace/cc/ph1.user_amend.md`（全文照抄在 `research/plans/phase1.md` §8.0）。七條規則的可照做規格寫在 phase1.md §8.1–§8.7。使用者裁示優先於 D1–D43；被取代的 D30（末句）、D40 已在上方標註，部分受影響的條目標了【補充】。

這次沒有改動關卡數字、樣本切分、60 上限或階段 0 驗證門檻。名額最多 58（fallback 路徑 56），≤ 60，所以不寫 QUESTION。

使用者的七條（摘要；原文以 ph1.user_amend.md 為準）：

- U1 每組多報一欄「滑價 ×3」的淨 R，只當參考，不當關卡（§8.1）。
- U2 取消「無可測鄰居算過」。沒有其他可調參數的組，用停損緩衝 0.12 和 0.18 當鄰居，一樣要同號；鄰居測試不算進 60（§8.2）。取代 D30 末句。
- U3 跨過 2025-07-01 的交易算樣本內，另報筆數和拿掉後的淨 R：照 D34（§8.3）。
- U4 S1 沒有組通過時，取 v2 毛 R ≥ +0.05、停損緩衝鄰居同號的組，最多 2 組，只測限價進場；沒有組達到才結束（§8.4）。取代 D40。
- U5 4h 七組當參考資訊，分配不變（§8.5）。
- U6 階段 2 主結果排除 25 個傳統金融永續，含它們的版本另列參考（§8.6）。決定了 D15 末句。
- U7 資金費缺 2026-10：先試著從 Binance vision 下載月檔或日檔；抓不到就用該幣前 3 個月資金費率絕對值的中位數當成本（只扣不加），另報受影響筆數；在 prep 或階段 2 前做（§8.7）。取代 D27 末句。

規劃者落實時的選擇：

- D44 滑價 ×3（U1）：每筆新增 `slip_r` = 實際付出的 1bp 滑價換成 R（市價或確認進場 `O×slip`；每條有滑價的出場腿 `w×raw×slip`；限價進場與 fixed_r maker 腿為 0）。`net_slip3 = mean(net_r − 2×slip_r)`。手續費不重算（差異 < 1e-4R 量級）。出場路徑不讀含滑價的成交價，所以這一欄等於 3bp 重跑的結果，不另跑實驗。不參與 P1–P3、關卡 A、fallback 或排序。
- D45 停損緩衝鄰居（U2）：sbuf 只給「表內參數（含 S2/S3 繼承的）為空」的組；有其他表內參數的組不加。YAML 寫字面值 0.12、0.18（不用 0.15×0.8 算）。初始停損和棘輪停損讀同一個鍵，一起變。同號 = 鄰居 v2 net_r > 0。缺鄰居結果判不成立（不再有空集合算成立）。依目前清單，S1 是 15m、1h 的 cur、rat、opp 六組；S3 的 no4h、xtf 列在 B2 沒有參數時也用。
- D46 限價 fallback（U4）：
  - 觸發 = S1 正常晉級 0 組；有 1 組就不用 fallback 補第 2 個。
  - 候選池 = 15m 與 1h 的 14 組（4h 是參考列，D48）。
  - F1：v2 毛 R ≥ 0.05。
  - F2「停損緩衝鄰居同號」解讀為兩個 sbuf 鄰居的 v2 毛 R > 0。這是和 F1 同一個量；候選的淨 R 通常 ≤ 0，拿淨 R 比同號沒有意義。所有 F1 組都要測 sbuf（含 fx、at）。
  - 排序用 v2 淨 R（沿用原 prompt「取 S1 淨 R 最好的 2 組」），同分取筆數多的，再取名稱字典序；最多 2 組。
  - 原文第二句「沒有組達到毛 R +0.05，階段 1 才結束」當成第一句條件的簡寫：有 F1 組但都不符 F2，也結束。
  - S2 每個基底只產生 lc、lm；市價列只當對照、不是候選（它的 P1–P3 結果不會變），所以 fallback 時 S2 也可能無候選。
  - S1 執行者在 neighbors 步驟就先把所有 F1 組的 sbuf 跑好，驗收者寫 promote 檔前不用回頭補跑。
- D47 S1 晉級檔（U4）：加一行 `MODE: normal|fallback|none`。`PROMOTE_COUNT` 包含 fallback 晉級的組數，並在同一行註明 fallback；只有正常與 fallback 都是 0 組才寫 0。管線用 `grep … | tail -1` 讀數字，所以 `PROMOTE_COUNT` 這個字串全檔只出現一次。gen S2 缺 MODE 行就報錯。三種寫法見 phase1.md §8.9。
- D48 4h 參考列（U5）：照跑、照報，ranked = false；不晉級、不進 fallback、不跑鄰居。§3.12 的週期槓桿主值只用 1h，4h 另列參考；最佳纏論組不含 4h。
- D49 階段 2 排除傳統金融（U6）：把同一次樣本外結果事後拆成兩版，不另跑。in_top20 是固定的每日榜單、v2 每幣獨立，所以結果等於 `exclude_tradfi: true`，也不違反「樣本外只跑一次」。
- D50 資金費下載（U7）：
  - 只補 2025-07 到 2026-10 之間本機缺檔的 (幣, 月)。
  - 先抓月檔；月檔沒有再抓日檔（先用 BTCUSDT 探測一次，404 就全部跳過）。
  - 只做月份層級：日檔不齊，整個月改用補值。
  - 檔案放 `research/cache/vision_dl/`，驗證 sha256 與內容，不寫入 `data/`（data 連到主工作樹的資料夾）。
  - 網路不通不算失敗，直接走補值。
- D51 資金費補值（U7）：
  - 補值費率 = 該幣在 M−3 到 M−1 三個日曆月內真實事件 |rate| 的中位數。三個月都沒有資料時，改用同一個窗內全部聯集幣的中位數（basis = market），另外報。
  - 事件時間從月初 00:00 UTC 起，間隔用最後一筆真實事件的 interval（沒有就用 8 小時）。
  - 補值事件不乘 side，多空都扣。
  - funding_missing 改成「受影響」旗標，另新增 n_funding_imputed。
  - 樣本內外的缺月都適用（樣本內預期 0）。
  - 原文「每筆單用…當成本」解讀為：每個資金費時點都用這個費率算成本。算法和真實資金費相同，只是費率換成補值，而且符號固定為成本。
- D52 時機：§8 的程式補件在 S1 第一個實驗之前做完（S1 階段開頭，phase1.md §8.8）。prep 開工時 §8 還不存在，所以 prep 驗收不因 §8 沒做而判不過；S1 驗收要重跑 §8.8 的 A1–A9。資金費（§8.7）建議同時做，最晚在階段 2 開始前完成。
- D53 名額：正常路徑 ≤ 2 + 24 + 6 + 16 + 10 = 58，fallback 路徑 ≤ 2 + 24 + 4 + 16 + 10 = 56。鄰居不計，兩者都 ≤ 60，不寫 QUESTION。
