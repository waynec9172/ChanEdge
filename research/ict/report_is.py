"""ICT gate A' report (ict_phase1.md section 4), in-sample only.

  python -m research.ict.report_is [NAME ...] [--out PATH] [--registry PATH]

Reads results only through metrics.load_is (which drops every non-IS row right after reading). There is no OOS switch and this module
imports nothing that evaluates OOS conditions. Writes nothing unless --out is given.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

from research import common as C
from research import metrics as M
from research import run as R
from research.ict import stats as S

COOLDOWN_US = 4 * 3600 * 10**6
MANIFEST = C.EXPERIMENTS / "ict" / "ict_manifest.json"
THR = {"net_r": 0.08, "pf": 1.2, "n": 150, "pos_q": 5}
NB_MARK = "__nb_"
NB_SUFFIXES = ("fvgk_0p4", "fvgk_0p6", "sl_0p2", "sl_0p4")


def v2(name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(trades, attempts) of v2 = one_per_symbol with the 4h cooldown, in-sample."""
    t, a = M.load_is(name)
    return M.one_per_symbol(a, t, cooldown_us=COOLDOWN_US)


def neighbor_names(main: str) -> list:
    return [f"{main}{NB_MARK}{s}" for s in NB_SUFFIXES]


def ambiguous_trade_ratio(t: pd.DataFrame) -> float:
    """Share of trades whose path had a stop/target (amb_stop_target) or TP1-on-entry-bar (amb_tp1_entry) ambiguity. Report only."""
    if not len(t) or "amb_stop_target" not in t.columns:
        return math.nan
    return float((t["amb_stop_target"].astype(bool) | t["amb_tp1_entry"].astype(bool)).mean())


def analyse(trades_v2: pd.DataFrame) -> dict:
    """summary + weekly bootstrap lower bound + Sharpe moments of one v2 in-sample trade set."""
    s = M.summarize(trades_v2)
    if len(trades_v2):
        s["boot"] = S.block_bootstrap_lb(trades_v2["net_r"], S.week_index(trades_v2["signal_time"]))
    else:
        s["boot"] = {"lb": math.nan}
    s["sr"] = S.sharpe_moments(trades_v2["net_r"])["sr"] if len(trades_v2) else math.nan
    s["amb"] = ambiguous_trade_ratio(trades_v2)
    return s


def gate_a_prime(s: dict, neighbor_net_r: list | None) -> dict:
    """Gate A' on one `analyse` result. Raw floats, no rounding. Every condition is (value, ok).

    neighbors: the 4 v2 net R values; a missing/short list fails ("missing neighbour results").
    DSR and slippage x3 are report-only and are not in the result's `pass`.
    """
    ok = lambda v, thr: bool(v == v and v >= thr)
    pos = lambda v: bool(v == v and v > 0)
    lb = s["boot"]["lb"]
    nb = list(neighbor_net_r or [])
    res = {
        "n": (s["n"], s["n"] >= THR["n"]),
        "net_r": (s["net_r"], ok(s["net_r"], THR["net_r"])),
        "pf": (s["pf"], ok(s["pf"], THR["pf"])),
        "fee15": (s["net_fee15"], pos(s["net_fee15"])),
        "pos_q": (s["pos_q"], s["pos_q"] >= THR["pos_q"]),
        "neighbors": (nb, len(nb) == len(NB_SUFFIXES) and all(pos(x) for x in nb)),
        "boot_lb": (lb, pos(lb)),
        "long": (s["long"]["net_r"], pos(s["long"]["net_r"])),
        "short": (s["short"]["net_r"], pos(s["short"]["net_r"])),
    }
    res["neighbors_note"] = "tested" if len(nb) == len(NB_SUFFIXES) else "missing neighbour results"
    res["pass"] = all(res[k][1] for k in ("n", "net_r", "pf", "fee15", "pos_q", "neighbors", "boot_lb", "long", "short"))
    return res


def rank_candidates(rows: list, k: int = 2) -> list:
    """rows = (name, summary, gate result). Section 7: passing A' only, ict_rand never, net R desc, n desc, name; at most k, no padding."""
    ok = [(n, s) for n, s, g in rows if g["pass"] and n != "ict_rand"]
    ok.sort(key=lambda x: (-x[1]["net_r"], -x[1]["n"], x[0]))
    return [n for n, _ in ok[:k]]


def _f(x, spec="+.4f"):
    return "nan" if x != x else format(x, spec)


def _mark(b):
    return "✓" if b else "✗"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def collect(names: list, registry: Path) -> dict:
    """Load and analyse; the DSR variance uses the SRs of every executed ICT main experiment, N = run.n_main(registry)."""
    out = {}
    for n in names:
        t, _a = v2(n)
        out[n] = {"trades": t, "s": analyse(t)}
    man = load_manifest()
    mains = [r["name"] for r in man["run"]]
    srs = {}
    for n in mains:
        if n in out:
            srs[n] = out[n]["s"]["sr"]
        elif (C.CACHE / "results" / f"{n}.parquet").exists():
            srs[n] = analyse(v2(n)[0])["sr"]
    var = S.var_of_srs(list(srs.values()))
    n_trials = R.n_main(R.read_registry(registry))
    for n in names:
        if NB_MARK in n:
            continue
        out[n]["dsr"] = S.deflated_sharpe(out[n]["trades"]["net_r"], var, n_trials)
    out["_dsr_ctx"] = {"var_sr": var, "n_trials": n_trials, "n_srs": len(srs)}
    return out


def nb_values(data: dict, main: str) -> list:
    vals = []
    for nb in neighbor_names(main):
        if nb in data:
            vals.append(data[nb]["s"]["net_r"])
        elif (C.CACHE / "results" / f"{nb}.parquet").exists():
            vals.append(analyse(v2(nb)[0])["net_r"])
    return vals


def render(data: dict, mains: list) -> str:
    G = {n: gate_a_prime(data[n]["s"], nb_values(data, n)) for n in mains}
    ctx = data["_dsr_ctx"]
    L = ["# ICT 關卡 A′ 報表（只含樣本內；v2 = 每幣最多一筆 + 冷卻 4h）", "",
         f"- bootstrap：週區塊，{S.BOOT_N} 次，seed {S.BOOT_SEED}，90% 單尾下界（{S.IS_WEEKS} 週，空週也算）",
         f"- DSR：N = {ctx['n_trials']}（registry 主實驗數），V[SR] 取 {ctx['n_srs']} 個已執行 ICT 主實驗的樣本變異數 = {_f(ctx['var_sr'], '.6f')}；只報告",
         "", "## 1. 關卡 A′", "",
         "| 實驗 | 筆數≥150 | 淨R≥0.08 | PF≥1.2 | ×1.5淨R>0 | 正季≥5/6 | 鄰居全正 | 週bootstrap下界>0 | 多>0 | 空>0 | 通過 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for n in mains:
        g = G[n]
        cell = lambda k, spec="+.4f": f"{_mark(g[k][1])} {_f(g[k][0], spec) if isinstance(g[k][0], float) else g[k][0]}"
        nbtxt = f"{_mark(g['neighbors'][1])} {g['neighbors_note']}" if g["neighbors_note"] != "tested" else f"{_mark(g['neighbors'][1])} " + "/".join(_f(x, "+.3f") for x in g["neighbors"][0])
        L.append(f"| {n} | {cell('n')} | {cell('net_r')} | {_mark(g['pf'][1])} {_f(g['pf'][0], '.3f')} | {cell('fee15')} | {cell('pos_q')}/6 | {nbtxt} | {cell('boot_lb')} | {cell('long')} | {cell('short')} | **{'PASS' if g['pass'] else 'FAIL'}** |")
    L += ["", "## 2. 報告用（不當關卡）", "",
          "| 實驗 | 毛R | 手續費R | funding_r | 勝率 | 滑價×3 淨R | DSR | SR | SR0 | 模糊路徑比例 | 首根停損比例 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for n in mains:
        s, d = data[n]["s"], data[n]["dsr"]
        L.append(f"| {n} | {_f(s['gross_r'])} | {_f(s['fee_r'], '.4f')} | {_f(s['funding_r'])} | {_f(s['win'], '.3f')} | {_f(s['net_slip3'])} | {_f(d['dsr'], '.3f')} | {_f(d['sr'], '.4f')} | {_f(d['sr0'], '.4f')} | {_f(s['amb'], '.3f')} | {_f(s['first_bar_stop'], '.3f')} |")
    L += ["", "## 3. 多空分邊（v2）", "", "| 實驗 | 空 n | 空 淨R | 空 PF | 多 n | 多 淨R | 多 PF |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for n in mains:
        s = data[n]["s"]
        L.append(f"| {n} | {s['short']['n']} | {_f(s['short']['net_r'])} | {_f(s['short']['pf'], '.3f')} | {s['long']['n']} | {_f(s['long']['net_r'])} | {_f(s['long']['pf'], '.3f')} |")
    L += ["", "## 4. 季度（v2；n / 合計 net R）", "", "| 實驗 | " + " | ".join(C.IS_QUARTERS) + " |", "| --- |" + " --- |" * len(C.IS_QUARTERS)]
    for n in mains:
        qs = {q["q"]: q for q in data[n]["s"]["quarters"]}
        L.append(f"| {n} | " + " | ".join((f"{qs[q]['n']} / {qs[q]['sum']:+.2f}" if q in qs else "—") for q in C.IS_QUARTERS) + " |")
    L += ["", "## 5. 鄰居（v2 淨 R）", ""]
    any_nb = False
    for n in mains:
        vals = [(nb, data[nb]["s"]) for nb in neighbor_names(n) if nb in data]
        if vals:
            any_nb = True
            L.append(f"- {n}: " + "、".join(f"{nb.split(NB_MARK)[1]} {_f(s['net_r'])} (n={s['n']})" for nb, s in vals))
    if not any_nb:
        L.append("- （沒有鄰居結果）")
    cands = rank_candidates([(n, data[n]["s"], G[n]) for n in mains])
    L += ["", "## 6. 判定", ""]
    if "ict_L7" in G:
        L.append("- ict_L7（H-ICT）：" + ("通過關卡 A′" if G["ict_L7"]["pass"] else "**未通過關卡 A′ → 結論：H-ICT 未通過**") + f"（v2 筆數 {data['ict_L7']['s']['n']}）")
    if "ict_rand" in G and G["ict_rand"]["pass"]:
        L.append("- **紅旗**：ict_rand 通過關卡 A′，不能晉級，需回報。")
    L.append("- 依第 7 節排序的晉級候選（≤ 2，不補位，ict_rand 除外）：" + (", ".join(cands) if cands else "無"))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.ict.report_is")
    p.add_argument("names", nargs="*", help="main experiment names (default: every registered ICT main experiment that has results)")
    p.add_argument("--out", default=None)
    p.add_argument("--registry", default=str(C.OUT / "registry.md"))
    a = p.parse_args(argv)
    man = load_manifest()
    mains = a.names or [r["name"] for r in man["run"] if (C.CACHE / "results" / f"{r['name']}.parquet").exists()]
    if not mains:
        print("no ICT results found", file=sys.stderr)
        return 2
    for n in mains:
        if not (C.CACHE / "results" / f"{n}.parquet").exists():
            print(f"no results for {n}", file=sys.stderr)
            return 2
    neighbours = [nb for n in mains for nb in neighbor_names(n) if (C.CACHE / "results" / f"{nb}.parquet").exists()]
    data = collect(mains + neighbours, Path(a.registry))
    md = render(data, mains)
    if a.out:
        Path(a.out).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
