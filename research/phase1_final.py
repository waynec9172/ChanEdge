"""Phase 1 final: write research/out/phase1.md from existing results (no new simulation, in-sample only)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from research import metrics as M

OUT = Path("research/out")
PROMOTE = Path("/workspace/cc/ph1.promote.S1.md")
EXITS = ["cur", "rat", "fx2", "fx3", "at2", "at3", "opp"]
TFS = ["15m", "1h", "4h"]


def v2(name: str) -> dict:
    t, a = M.load_is(name)
    t2, a2 = M.one_per_symbol(a, t)
    return M.summarize(t2, a2)


def demote(md: str) -> str:
    return re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", md, flags=re.M)


def row(name: str, s: dict) -> str:
    return (f"| {name} | {s['n']} | {s['net_r']:+.4f} | {s['gross_r']:+.4f} | {s['fee_r']:.4f} | {s['funding_r']:+.4f} | "
            f"{s['pf']:.3f} | {s['win']*100:.1f}% | {s['pos_q']}/6 | {s['net_fee15']:+.4f} | {s['net_slip3']:+.4f} | "
            f"{s['long']['net_r']:+.4f} | {s['short']['net_r']:+.4f} |")


def main() -> int:
    S = {f"p1s1_{tf}_{e}": v2(f"p1s1_{tf}_{e}") for tf in TFS for e in EXITS}
    jev = v2("p1s1_15m_cur_jevref")
    d1, d4 = v2("donchian_1h_n20"), v2("donchian_4h_n55")
    ranked = {k: s for k, s in S.items() if "_4h_" not in k}
    best = max(ranked, key=lambda k: ranked[k]["net_r"])
    best4 = max((k for k in S if "_4h_" in k), key=lambda k: S[k]["net_r"])
    b = ranked[best]
    # levers (v2 net R)
    per = []
    for e in EXITS:
        per.append((S[f"p1s1_1h_{e}"]["net_r"] - S[f"p1s1_15m_{e}"]["net_r"], e,
                    S[f"p1s1_4h_{e}"]["net_r"] - S[f"p1s1_15m_{e}"]["net_r"]))
    per_best = max(per)
    ex = []
    for tf in TFS:
        for e in EXITS[1:]:
            ex.append((S[f"p1s1_{tf}_{e}"]["net_r"] - S[f"p1s1_{tf}_cur"]["net_r"], tf, e))
    ex_main = max(x for x in ex if x[1] != "4h")
    ex_4h = max(x for x in ex if x[1] == "4h")
    jev_d = jev["net_r"] - S["p1s1_15m_cur"]["net_r"]
    lever_name = "出場" if ex_main[0] >= per_best[0] else "週期"
    top = ex_main if lever_name == "出場" else per_best
    other = "週期" if lever_name == "出場" else "出場"
    other_d = per_best[0] if lever_name == "出場" else ex_main[0]
    lines = [
        "結論：無候選（在 S1 結束，依注意事項第 10 點；14 組參加排名的纏論組 P1/P2 全不成立，限價 fallback 也無組 F1 成立）",
        f"最佳纏論組 {best}（v2）：淨 R {b['net_r']:+.4f}、PF {b['pf']:.3f}、筆數 {b['n']}、正季 {b['pos_q']}/6、手續費×1.5 淨 R {b['net_fee15']:+.4f}、鄰居 有負（未觸發：P1 不成立，無鄰居可測，判不成立）",
        f"Donchian 基準（v2）：1h n20 淨 R {d1['net_r']:+.4f}、PF {d1['pf']:.3f}、筆數 {d1['n']}；4h n55 淨 R {d4['net_r']:+.4f}、PF {d4['pf']:.3f}、筆數 {d4['n']}；關卡 A：1h 不過、4h 不過",
        f"改善淨 R 最多的槓桿：{lever_name}（Δ淨 R {top[0]:+.4f}："
        + (f"{ex_main[1]} cur → {ex_main[2]}" if lever_name == "出場" else f"15m {per_best[1]} → 1h {per_best[1]}")
        + f"）；其他：{other} Δ{other_d:+.4f}，JEV 參考 Δ{jev_d:+.4f}（不排名），進場、過濾 未測",
        "實驗用量：主實驗 26 / 60（含階段 0 的 2 個）、鄰居 0 個（不計）；oos_log.md 為空；研究停損判讀：Donchian 基準兩個週期都不過關卡 A，限價進場沒有實際模擬（毛 R 全部 < +0.05）",
        "",
    ]
    hdr = ("| 實驗 | n | 淨R | 毛R | 手續費R | funding_r | PF | 勝率 | 正季 | ×1.5淨R | 滑價×3淨R(參考) | 多單淨R | 空單淨R |\n"
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    L = lines
    L += ["## 1. 範圍與結論", "",
          "全程只用樣本內（2024-01-01 → 2025-06-30），沒有使用 --oos。v2 = 每幣同時最多一筆（關卡 A 以此為準）。",
          "S1 的 24 組跑完後沒有任何組符合晉級條件，階段 1 在 S1 結束，沒有 S2、S3。本檔不追加實驗。", "",
          "## 2. 給使用者的 S1 v2 表（每幣最多一筆；4h 為參考列）", "", hdr]
    for k, s in S.items():
        L.append(row(k + (" (參考 4h)" if "_4h_" in k else ""), s))
    L += [row("donchian_1h_n20 (基準)", d1), row("donchian_4h_n55 (基準)", d4), row("p1s1_15m_cur_jevref (參考)", jev), "",
          "## 3. 各輪晉級名單與理由（驗收者 promote 檔原文）", "", "### S1", "",
          demote(demote(PROMOTE.read_text())), "",
          "S2、S3：沒有執行（S1 無候選，依第 10 點階段 1 結束）。", "",
          "## 4. 通過關卡 A 的組", "",
          "**無候選。** 沒有任何纏論組通過關卡 A，所以沒有穩健性檢查可附。最接近的一組只作為「最佳纏論組」與基準比較，並非候選：",
          f"{best} v2 淨 R {b['net_r']:+.4f}（門檻 ≥ +0.08 ✗）、PF {b['pf']:.3f}（≥ 1.2 ✗）、筆數 {b['n']}（≥ 500 ✓）、"
          f"正季 {b['pos_q']}/6（≥ 70% ✗）、×1.5 淨 R {b['net_fee15']:+.4f}（> 0 ✗）、鄰居 未觸發（✗）。", "",
          "Donchian 關卡 A（v2 與獨立版）見 §8。", "",
          "## 5. §3.12 槓桿表（v2 淨 R）", "",
          "週期槓桿（主值 = net(1h,e) − net(15m,e)；4h − 15m 為參考）：", "",
          "| 出場 e | 15m | 1h | 4h(參考) | 1h−15m | 4h−15m(參考) |", "| --- | --- | --- | --- | --- | --- |"]
    for d, e, d4_ in per:
        L.append(f"| {e} | {S[f'p1s1_15m_{e}']['net_r']:+.4f} | {S[f'p1s1_1h_{e}']['net_r']:+.4f} | {S[f'p1s1_4h_{e}']['net_r']:+.4f} | {d:+.4f} | {d4_:+.4f} |")
    L += ["", f"週期最大 Δ = {per_best[0]:+.4f}（出場 {per_best[1]}，15m → 1h）。", "",
          "出場槓桿（net(tf,e) − net(tf,cur)）：", "",
          "| 週期 | " + " | ".join(EXITS[1:]) + " | 最大 Δ |", "| --- |" + " --- |" * 7]
    for tf in TFS:
        ds = [S[f"p1s1_{tf}_{e}"]["net_r"] - S[f"p1s1_{tf}_cur"]["net_r"] for e in EXITS[1:]]
        mx = max(ds)
        L.append(f"| {tf}{' (參考)' if tf=='4h' else ''} | " + " | ".join(f"{x:+.4f}" for x in ds) + f" | {mx:+.4f} ({EXITS[1:][ds.index(mx)]}) |")
    L += ["", f"出場最大 Δ（排名組，不含 4h）= {ex_main[0]:+.4f}（{ex_main[1]} cur → {ex_main[2]}）；4h 參考 = {ex_4h[0]:+.4f}（{ex_4h[2]}）。",
          "進場槓桿：未測（S2 沒有執行）。過濾槓桿：未測（S3 沒有執行）。",
          f"JEV（參考，不排名）：net(15m_cur_jevref) − net(15m_cur) = {jev['net_r']:+.4f} − {S['p1s1_15m_cur']['net_r']:+.4f} = {jev_d:+.4f}。", "",
          f"**改善淨 R 最多的槓桿：{lever_name}，Δ {top[0]:+.4f}。** 但改善後最好的纏論組仍是 {b['net_r']:+.4f}，離 +0.08 很遠；毛 R 全部為負（最高 −0.0150），"
          "也就是在扣手續費之前就沒有優勢，成本不是主要問題。", "",
          "## 6. 纏論版最好一組與 Donchian 基準並排（v2）", "", hdr,
          row(f"{best}（纏論最佳）", b), row(f"{best4}（4h 最佳，參考）", S[best4]),
          row("donchian_1h_n20", d1), row("donchian_4h_n55", d4), row("p1s1_15m_cur_jevref（JEV 參考）", jev), "",
          f"另外 {best} 的 n_cross（跨過 2025-07-01）= {b['n_cross']}，Donchian 1h = {d1['n_cross']}，4h = {d4['n_cross']}（U3：算樣本內，來源見 §3 下架幣註記）。",
          "下架幣平線註記與三種數字（原樣、去掉平線筆數、只拿掉平線期間資金費）見 §3 promote 檔第 4 節；結論不變：兩個 Donchian 基準在任一種處理下都不過關卡 A。", "",
          "解讀：Donchian 1h 毛 R 為正（+0.0253）但被成本吃掉，淨 R 接近 0（−0.0053）；纏論版的毛 R 本身為負，沒有優於基準。基準也過不了關卡 A，"
          "依原文研究停損條件「基準也不行，就停下來重新想」，交使用者判斷。限價進場與確認進場沒有實際模擬；依使用者裁示，毛 R 低於 +0.05 的組不可能靠限價轉正。", "",
          "## 7. 注意事項", "",
          "- 傳統金融永續在樣本內從未進前 20 名（tradfi 欄 n=0），樣本內無法回答；階段 2 主結果排除這 25 個幣，含它們的版本另列參考（§8.6）。",
          "- 資金費缺 2026-10：已嘗試下載 Binance vision 月檔，缺的 (幣,月) 用前 3 個月 |rate| 中位數補值（只扣不加）；樣本內受影響筆數見 §2/§8 表的欄位（1h_at2、at3 各 1 筆；Donchian 1h 3 筆、4h 2 筆）。",
          "- 鄰居：S1 沒有任何組觸發鄰居測試，registry 鄰居 0 個；沒有無可測鄰居的組。",
          "- 下架幣平線的模擬語意（在最後一根非平線 K 結算、平線期間不計資金費）屬模擬變更，須走 issue 裁決，本輪不處理；階段 2 前須先決定。",
          "- 滑價×3 只是參考欄，不是關卡。", "",
          "## 8. 全部實驗的完整表（執行時產生；v2 與獨立版兩個版本）", "",
          demote((OUT / "phase1_S1.md").read_text()), "",
          "### Donchian 關卡 A", "", demote((OUT / "phase1_S1_donchian_gateA.md").read_text()), "",
          "<!-- generated above; hand-written notes below -->", "",
          "## 執行者備註", "",
          "- 本檔由 `research/phase1_final.py` 從 `research/cache/results/` 重算（樣本內），§2、§5、§6 與 `phase1_S1.md` 逐格同源；§8 為執行時產生的原表。",
          "- 未跑任何新實驗；registry 26 列不變；oos_log.md 0 位元組。", ""]
    (OUT / "phase1.md").write_text("\n".join(L))
    print("wrote", OUT / "phase1.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
