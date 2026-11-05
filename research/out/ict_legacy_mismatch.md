# A1.2 mismatch 唯讀調查
scope: funding_months dl_monthly=492 imputed=909; funding_fetch.log dl_monthly(含 cached)=492; log⊇months.dl=True

## donchian_1h_n20
rows trades old=31355 new=31355; attempts old=31358 new=31358; samples old={'IS': 16631, 'OOS': 14723, nan: 1} new={'IS': 16631, 'OOS': 14723, None: 1}
IS trades: rows old=16631 new=16631 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=16631 new=16631 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=14724 new=14724 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'net_r': 2, 'funding_r': 2, 'funding_missing': 2, 'n_funding_imputed': 2}
OOS trades differing rows = 2
OOS attempts: rows old=14727 new=14727 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## donchian_4h_n55
rows trades old=4081 new=4081; attempts old=4084 new=4084; samples old={'IS': 2139, 'OOS': 1942} new={'IS': 2139, 'OOS': 1942}
IS trades: rows old=2139 new=2139 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=2139 new=2139 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=1942 new=1942 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'net_r': 1, 'funding_r': 1, 'funding_missing': 1, 'n_funding_imputed': 1}
OOS trades differing rows = 1
OOS attempts: rows old=1945 new=1945 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_at2
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_at3
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_cur
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_fx2
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_fx3
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_opp
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## p1s1_15m_rat
rows trades old=41181 new=41181; attempts old=41181 new=41181; samples old={'IS': 22816, 'OOS': 18365} new={'IS': 22816, 'OOS': 18365}
IS trades: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
IS attempts: rows old=22816 new=22816 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[] identical=True
OOS trades: rows old=18365 new=18365 only_old=0 only_new=0 cols_only_old=[] cols_only_new=[]
OOS trades diff columns (name: cells) = {'funding_missing': 1}
OOS trades differing rows = 1
OOS attempts: rows old=18365 new=18365 only_old=0 only_new=0 diff_cols={} cols_only_old=[] cols_only_new=[]
OOS differing rows: n_symbols=1 symbols=['龙虾/USDT']
OOS differing rows signal_time months=['2026-10']
(b) trade path columns identical (all non-funding cols, plus same row set & attempts) = True
(c) only funding-related cols differ = True; identity dnet_r == -dfunding_r = True
(d) signal-month (symbol,month) pairs=1; all in dl_monthly scope=True; all in dl_monthly∪imputed scope=True
(d) holding-period variant (>=1 held month of the symbol in scope): dl_monthly=True; dl_monthly∪imputed=True

## 判定
(a) IS 列完全相同: True
(b) 交易路徑欄相同: True
(c) 只有資金費相關欄位不同且恆等式成立: True
(d) 差異 (symbol,月份) 落在 dc5f54a 資金費重建範圍(持倉月份口徑，dl_monthly): True；嚴格以 signal 月份口徑: True

## 結論（繁體中文）

9 個 FAIL 的實驗，IS 列（trades 與 attempts，全部欄位）與重算結果完全相同，(a) 成立。OOS 列的列集合、attempt_id、所有交易路徑欄（進出場時間、價格、停損、gross_r、費用、滑價、exit_reason 等）也都相同，(b) 成立。

OOS 的差異只出現在資金費相關欄位，而且全部集中在 symbol 龍蝦（龙虾/USDT）、signal_time 2026-10 的少數幾列：donchian_1h_n20 有 2 列、donchian_4h_n55 有 1 列，差異欄位是 net_r、funding_r、funding_missing、n_funding_imputed。p1s1_15m_* 七個實驗各 1 列，只有 funding_missing 不同，net_r 與 funding_r 都沒變。Δnet_r == −Δfunding_r 在容差 1e-9 內成立（p1s1 的情況是兩邊的差都為 0），(c) 成立。

龙虾/USDT 2026-10 這個 (symbol, 月份) 是 dc5f54a 修正 URL 百分比編碼後，才由 funding_fetch 以 dl_monthly 補下載的資料。它在 funding_months.parquet 的 source 為 dl_monthly，也出現在 funding_fetch.log 的 dl_monthly 紀錄中。依 signal 月份與持倉月份兩種口徑檢查，差異都落在重建範圍內，(d) 成立。

四條全部成立，依 A1.2 可結案，不修、不重跑，不需要二分 ff744a9..4e0784d，可進 P2。結案後續是 P2 起舊實驗驗收改為「只比 IS 全部 OK，另附這 9 個 OOS 資金費漂移白名單」。

注意：這次只動 funding_missing 與（在 donchian 兩個實驗）資金費相關欄位。donchian_1h_n20 有 1 列 sample 為空值（NaN/None），新舊相同，我的 OOS 篩選（sample != "IS"）把它算進 OOS，與列數對得起來。
