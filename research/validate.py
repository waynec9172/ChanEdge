"""Fidelity check of the simulator against the baseline trades.parquet. Writes harness_validation.md.

Only fidelity numbers are reported (match ratio, net R agreement). No simulated performance by sample.
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from research import common as C

N_BASELINE_EXPECTED = 5575
MATCH_MIN = 0.80
DIFF_MAX = 0.05


def md_table(df: pd.DataFrame, index: bool = True) -> list[str]:
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return lines


def load_baseline() -> pd.DataFrame:
    b = pd.read_parquet(C.BASELINE_DIR / "trades.parquet")
    for c in ("r_multiple", "qty", "entry_price", "exit_price", "pnl", "fee_quote", "cost_r", "defending_atr"):
        b[c] = pd.to_numeric(b[c])
    b["entry_time"] = pd.to_datetime(b["entry_time"], utc=True).astype("datetime64[us, UTC]")
    b["exit_time"] = pd.to_datetime(b["exit_time"], utc=True).astype("datetime64[us, UTC]")
    return b


def attribute(unmatched: pd.DataFrame, sig: pd.DataFrame) -> tuple[dict, pd.Series]:
    """Classify each unmatched baseline trade by the first failing stage in the signal cache."""
    key = sig.set_index(["symbol", "type", "time"])
    reasons = {"a_no_signal": 0, "b_candidate": 0, "c_gate": 0, "d_jev": 0, "e_cost": 0, "f_other": 0}
    veto_counts: dict[str, int] = {}
    labels = []
    for r in unmatched.itertuples():
        k = (r.symbol, r.signal_type, r.entry_time)
        if k not in key.index:
            reasons["a_no_signal"] += 1
            labels.append("a_no_signal")
            continue
        row = key.loc[k]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        if not bool(row["candidate"]) or bool(row["ambiguous"]):
            reasons["b_candidate"] += 1
            labels.append("b_candidate")
        elif not bool(row["gate_pass"]):
            reasons["c_gate"] += 1
            labels.append("c_gate")
            for code in str(row["veto_codes"]).split(","):
                veto_counts[code] = veto_counts.get(code, 0) + 1
        elif not (row["jev_score"] >= 0.62):
            reasons["d_jev"] += 1
            labels.append("d_jev")
        else:
            side = int(row["side"])
            dist = side * (row["close"] - (row["defending_price"] - side * 0.15 * row["atr"]))
            if dist > 0 and 0.0012 / (dist / row["close"]) > 0.40:
                reasons["e_cost"] += 1
                labels.append("e_cost")
            else:
                reasons["f_other"] += 1
                labels.append("f_other")
    reasons["veto_codes_in_c"] = veto_counts
    return reasons, pd.Series(labels, index=unmatched.index)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.validate")
    p.add_argument("--experiment", required=True)
    p.add_argument("--out", default=str(C.OUT / "harness_validation.md"))
    a = p.parse_args(argv)
    res = pd.read_parquet(C.CACHE / "results" / f"{a.experiment}.parquet")
    meta = json.loads((C.CACHE / "results" / f"{a.experiment}.json").read_text())
    base = load_baseline()
    n_base = len(base)
    if "net_r_ex_funding" in res.columns:  # phase 1 results: baseline r_multiple has no funding, compare without it
        res = res.assign(net_r=res["net_r_ex_funding"])
    sim = res.rename(columns={"exit_reason": "sim_exit", "exit_time": "sim_exit_time"})
    m = base.merge(
        sim[["symbol", "type", "entry_time", "net_r", "gross_r", "fee_r", "sim_exit", "tp1_hit", "sim_exit_time"]],
        left_on=["symbol", "signal_type", "entry_time"],
        right_on=["symbol", "type", "entry_time"],
        how="left",
        validate="many_to_one",
    )
    matched = m[m["net_r"].notna()].copy()
    n_match = len(matched)
    ratio = n_match / n_base
    diff = matched["net_r"] - matched["r_multiple"]
    mean_diff = float(diff.mean())
    mean_abs = float(diff.abs().mean())
    corr = float(np.corrcoef(matched["net_r"], matched["r_multiple"])[0, 1])
    pass_main = ratio >= MATCH_MIN and abs(mean_diff) <= DIFF_MAX
    pass_abs = ratio >= MATCH_MIN and mean_abs <= DIFF_MAX
    modes = json.loads((C.CACHE / "mode.json").read_text())
    sig = pd.read_parquet(C.CACHE / "signals_15m.parquet")
    unmatched = m[m["net_r"].isna()]
    reasons, _labels = attribute(unmatched, sig)
    quant = diff.quantile([0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0])
    conf = pd.crosstab(matched["exit_reason"], matched["sim_exit"])
    same_exit = float((matched["exit_reason"] == matched["sim_exit"]).mean()) if n_match else float("nan")
    base_tp = matched["partial_reason"].fillna("").astype(str).str.len() > 0
    same_tp = float((base_tp == matched["tp1_hit"].astype(bool)).mean()) if n_match else float("nan")
    big = (diff.abs() > 0.05).sum()
    note = "兩種讀法結論相同"
    if pass_main != pass_abs:
        note = f"若改用平均絕對差判定，結論為 {'PASS' if pass_abs else 'FAIL'}（交由使用者決定）"
    verdict = "PASS" if pass_main else "FAIL"
    lines = [
        f"結論：{verdict}（對上 ≥ 80% 且 平均 net R 差 ≤ 0.05）",
        f"對上比例：{n_match} / {n_base} = {ratio:.2%}",
        f"net R 相關係數：r = {corr:.6f}（n = {n_match}）",
        f"平均 net R 差（sim − baseline）：{mean_diff:+.3e} ；平均絕對差：{mean_abs:.3e}",
        f"訊號模式：15m={modes['15m']}，1h={modes['1h']}，4h={modes['4h']}；模擬耗時 {meta['elapsed_s']} 秒；備註：{note}",
        "",
        "# Harness 驗證（模擬器 vs 0.15 baseline）",
        "",
        f"- 實驗：`{a.experiment}`，config_sha `{meta['config_sha']}`，訊號數 {meta['n_signals']}，模擬成交 {meta['n_trades']}。",
        f"- baseline：`{C.BASELINE_DIR.name}`，{n_base} 筆（預期 {N_BASELINE_EXPECTED}）。",
        "- 鍵 = (symbol, signal_type/type, entry_time)；分母是全部真實交易。",
        f"- 判定（原文）：對上比例 ≥ 80% 且 |平均 net R 差| ≤ 0.05。對上比例 {ratio:.2%}，|平均差| {abs(mean_diff):.3e}。",
        f"- 另一讀法（平均絕對差 ≤ 0.05）：mean|diff| = {mean_abs:.3e} → {'PASS' if pass_abs else 'FAIL'}。{note}。",
        f"- |差| > 0.05 的配對數：{int(big)} / {n_match}。出場原因一致率 {same_exit:.2%}；TP1 是否成交一致率 {same_tp:.2%}。",
        "",
        "## 模式比對（signal_mode_check.md 摘要）",
        "",
    ]
    check = (C.OUT / "signal_mode_check.md").read_text().splitlines()
    lines += [ln for ln in check if ln.startswith("|")][:5]
    lines += ["", "## 未對上的 baseline 交易歸因", ""]
    rows = [(k, v) for k, v in reasons.items() if k != "veto_codes_in_c"]
    lines += md_table(pd.DataFrame(rows, columns=["原因", "筆數"]), index=False)
    lines += ["", f"(c) 的 veto_codes 分布：{reasons['veto_codes_in_c']}", "", "## 出場原因混淆表（列 = baseline，欄 = sim，僅對上的配對）", ""]
    lines += md_table(conf)
    lines += ["", "## net R 差值分位數（sim − baseline）", ""]
    lines += md_table(pd.DataFrame({"q": quant.index, "diff": [f"{x:+.3e}" for x in quant.values]}), index=False)
    lines += [
        "",
        "## 已知差異來源",
        "",
        "- baseline 後期權益極小，數量取整（qty_step）帶來 R 雜訊；模擬器用無限可分數量。",
        "- 帳戶與持倉上限（最多 3 倉、同向 2 倉、總名目上限）使 baseline 少做某些單；sim 不設上限，多出的單不影響對上率（分母是 baseline 的單）。",
        "- 反向訊號只看發出當根（sim）；baseline 看視窗內所有 time > 進場決策時間的反向訊號，結果相同除非視窗滾動使舊訊號改變。",
        "- 資金費不計（baseline r_multiple 同樣不含資金費）。",
        "- 手續費、滑價、停損／停利撮合順序與 matcher 相同；停損價用 Decimal 對齊 tick。",
        "",
        "## Donchian 解讀附註",
        "",
        "「Donchian 突破（20/55）」解讀為通道長度 N=20 與 N=55 各自成一組訊號（1h 與 4h 各跑 20 與 55）；"
        "出場用同 N 的反向突破，另加 2 ATR 停損。這是規劃者的解讀。phase 0 不執行這些實驗，只提交 YAML。",
        "",
    ]
    lines += ["## 效能與耗時", "", "效能與耗時紀錄見 research/out/harness_perf.md（由 research.perf 產生）。", ""]
    from pathlib import Path

    Path(a.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:5]))
    print(f"unmatched attribution: {reasons}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
