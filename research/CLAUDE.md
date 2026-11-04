# research/ 鐵則（research/* 分支）

1. 不改 src/、config/、tests/、docs/ARCHITECTURE.md（架構稿）、pyproject.toml。可以 import chanedge，新程式全部放 research/。
2. 不加任何依賴：只用 pandas、pyarrow（含 numpy）和標準庫。
3. 樣本切分固定：樣本內 2024-01-01 → 2025-06-30；樣本外 2025-07-01 → 2026-10-27。
4. 階段 1 全程不准用 --oos；research/out/oos_log.md 必須保持空的。
5. 樣本外每組只跑一次，跑完不准改參數、不准追加實驗。
6. 實驗總數上限 60 個。每次執行都要在 research/out/registry.md 追加一行（時間、實驗名、設定摘要）。
7. 關卡門檻、樣本切分、實驗上限、驗證門檻一律照原文，不准修改。覺得該改就停下來提問。
8. 過不了關卡就停下來回報，絕不為了過關調參數或追加實驗。
9. research/cache/ 不 commit（已加進 .gitignore）。
