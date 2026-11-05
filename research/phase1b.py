"""Phase 1b driver: 10 pre-registered Donchian experiments (trend, 1d, Chan-structure filters) under the delist rule.

  python -m research.phase1b gen [--verify]
  python -m research.phase1b runall [--kind base] [--workers 6]
  python -m research.phase1b neighbors [--workers 6] [--status]
  python -m research.phase1b table [--out PATH]
  python -m research.phase1b gatea [--out PATH]
  python -m research.phase1b sanity
  python -m research.phase1b regress
  python -m research.phase1b compare-base
  python -m research.phase1b relist-report
  python -m research.phase1b audit

YAML files are written as JSON (a YAML subset). Everything here reads in-sample results only: no function takes an
out-of-sample switch (metrics.load_is drops every non-IS row right after reading).
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import common as C
from research import metrics as M
from research import phase1 as P1
from research import run as R
from research import sim

MANIFEST = C.EXPERIMENTS / "p1b_manifest.json"
NB_DIR = C.EXPERIMENTS / "neighbors"
P1_MANIFEST = C.EXPERIMENTS / "p1_manifest.json"
BASE_FILTERS = {"in_top20": True, "candidate_only": False, "gate_pass": False, "jev_min": None, "max_cost_r": None, "exclude_reemit": False}
COSTS = {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1}
NB_STOPS = (1.6, 2.4)
NB_N = {20: (16, 24), 55: (44, 66)}

# (name, kind, tf, n, exit, filter, control)   plan 5.2 -- fixed, do not edit after registration
RUN = (
    ("p1b_base_1h_n20", "base", "1h", 20, "same_n", None, None),
    ("p1b_base_4h_n55", "base", "4h", 55, "same_n", None, None),
    ("p1b_tr_4h_n20", "tr", "4h", 20, "half", None, None),
    ("p1b_tr_4h_n55", "tr", "4h", 55, "half", None, None),
    ("p1b_tr_1d_n20", "tr", "1d", 20, "half", None, None),
    ("p1b_tr_1d_n55", "tr", "1d", 55, "half", None, None),
    ("p1b_base_1h_n20_bias", "filter", "1h", 20, "same_n", "bias4h", "p1b_base_1h_n20"),
    ("p1b_base_4h_n55_bias", "filter", "4h", 55, "same_n", "bias4h", "p1b_base_4h_n55"),
    ("p1b_base_1h_n20_nozs", "filter", "1h", 20, "same_n", "nozs4h", "p1b_base_1h_n20"),
    ("p1b_base_4h_n55_nozs", "filter", "4h", 55, "same_n", "nozs4h", "p1b_base_4h_n55"),
)
OLD_BASE = {"p1b_base_1h_n20": "donchian_1h_n20", "p1b_base_4h_n55": "donchian_4h_n55"}
FILTER_KEY = {"bias4h": "dc_bias_4h", "nozs4h": "dc_not_in_zs4h"}
FILTER_TEXT = {"bias4h": "纏論過濾：只在 4h 纏論方向同向時進場", "nozs4h": "纏論過濾：突破點不在 4h 中樞區間內才進場"}


# --------------------------------------------------------------------------- specs
def exit_block(mode: str, tf: str, n: int) -> dict:
    if mode == "same_n":
        return {"opposite_signal": {"enabled": True, "tf": tf}}
    return {"donchian_exit": {"enabled": True, "n": n // 2}}


def make_yaml(name: str, kind: str, tf: str, n: int, ex: str, flt: str | None) -> dict:
    filters = {**BASE_FILTERS, "delist_rule": True}
    if flt:
        filters[FILTER_KEY[flt]] = True
    xt = f"同 N={n} 反向突破出場" if ex == "same_n" else f"反向 {n // 2} 通道突破出場"
    head = {"base": "1b 基準重算", "tr": "1b 純趨勢", "filter": f"1b {FILTER_TEXT.get(flt, '')}"}[kind]
    return {
        "name": name,
        "description": f"{head} {tf} N={n}：收盤突破，初始停損 2 ATR，{xt}，前 20 名，下架規則",
        "signals": {"source": "donchian", "tf": tf, "types": [f"dc{n}_long", f"dc{n}_short"], "donchian_n": n},
        "filters": filters,
        "entry": {"mode": "market_next_open"},
        "stop": {"buffer_atr": 2.0, "round_to_tick": True},
        "exit": exit_block(ex, tf, n),
        "costs": dict(COSTS),
    }


def gen_specs() -> list[dict]:
    out = []
    for name, kind, tf, n, ex, flt, ctl in RUN:
        out.append(
            {
                "name": name, "kind": kind, "tf": tf, "n": n, "exit": ex, "exit_n": n // 2 if ex == "half" else None,
                "filter": flt, "control": ctl, "yaml": make_yaml(name, kind, tf, n, ex, flt),
            }
        )
    return out


def neighbor_specs(name: str, y: dict) -> list[dict]:
    """Plan 5.3: channel n -20% / +20% (exit n follows n // 2 for half exits) and initial stop 1.6 / 2.4 ATR; one change at a time."""
    out = []
    sg = y["signals"]
    half = "donchian_exit" in y["exit"]

    def add(code, tag, value, mutate, text):
        z = copy.deepcopy(y)
        mutate(z)
        nm = f"{name}__nb_{code}_{tag}"
        z["name"] = nm
        z["description"] = f"NEIGHBOR of {name}: {text}"
        out.append({"code": code, "value": value, "name": nm, "yaml": z})

    for v in NB_N[sg["donchian_n"]]:
        def mut(z, v=v):
            z["signals"]["donchian_n"] = v
            z["signals"]["types"] = [f"dc{v}_long", f"dc{v}_short"]
            if half:
                z["exit"]["donchian_exit"]["n"] = v // 2

        add("dcn", str(v), v, mut, f"signals.donchian_n={v}" + (f" (exit n={v // 2})" if half else ""))
    for v in NB_STOPS:
        add("stop", f"{v}".replace(".", "p"), v, lambda z, v=v: z["stop"].update(buffer_atr=v), f"stop.buffer_atr={v}")
    return out


# --------------------------------------------------------------------------- files
def write_yaml(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"run": [], "neighbors": {}, "skipped": []}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")


def manifest_rows(specs: list[dict]) -> list[dict]:
    return [{k: v for k, v in s.items() if k != "yaml"} for s in specs]


def existing_core_shas(skip: set[str] = frozenset()) -> dict[str, str]:
    out = {}
    for p in sorted(C.EXPERIMENTS.glob("*.yaml")) + sorted(NB_DIR.glob("*.yaml")):
        if p.stem in skip:
            continue
        out.setdefault(P1.core_of(C.read_yaml(p)), p.stem)
    return out


def gen(verify: bool) -> int:
    specs = gen_specs()
    for s in specs:
        if s["yaml"]["filters"]["delist_rule"] is not True:
            raise SystemExit(f"{s['name']}: delist_rule must be true")
    cores = [P1.core_of(s["yaml"]) for s in specs]
    if len(set(cores)) != len(cores):
        raise SystemExit("two of the 10 experiments have the same core_sha")
    own = {s["name"] for s in specs}
    seen = existing_core_shas(skip=own)
    for s, c in zip(specs, cores):
        if c in seen:
            raise SystemExit(f"{s['name']} has the same settings as the existing experiment {seen[c]}")
    if verify:
        bad = []
        for s in specs:
            p = C.EXPERIMENTS / f"{s['name']}.yaml"
            if not p.exists() or C.read_yaml(p) != json.loads(json.dumps(s["yaml"])):
                bad.append(s["name"])
        if load_manifest().get("run") != json.loads(json.dumps(manifest_rows(specs))):
            bad.append("manifest run")
        if bad:
            print("FAIL: mismatch:", ", ".join(bad))
            return 1
        print(f"OK: {len(specs)} groups match plan 5.2")
        return 0
    for s in specs:
        p = C.EXPERIMENTS / f"{s['name']}.yaml"
        if p.exists() and C.read_yaml(p) != json.loads(json.dumps(s["yaml"])):
            raise SystemExit(f"{p} exists with different content; refusing to overwrite")
        write_yaml(p, s["yaml"])
    m = load_manifest()
    m["run"] = manifest_rows(specs)
    save_manifest(m)
    print(f"gen: {len(specs)} YAML files written")
    return 0


# --------------------------------------------------------------------------- results access
def exists_result(name: str) -> bool:
    return (C.CACHE / "results" / f"{name}.attempts.parquet").exists()


def v2_summary(name: str) -> dict:
    return P1.v2_summary(name)


def ind_summary(name: str) -> dict:
    return P1.ind_summary(name)


def run_cmd(path: Path, workers: int, neighbor: bool = False) -> int:
    cmd = [sys.executable, "-m", "research.run", str(path), "--workers", str(workers)] + (["--neighbor"] if neighbor else [])
    return subprocess.run(cmd, cwd=C.ROOT).returncode


def runall(kind: str | None, workers: int) -> int:
    for row in load_manifest()["run"]:
        name = row["name"]
        if kind and row["kind"] != kind:
            continue
        if exists_result(name):
            print(f"skip {name} (has results)", flush=True)
            continue
        rc = run_cmd(C.EXPERIMENTS / f"{name}.yaml", workers)
        if rc != 0:
            print(f"FAILED {name} rc={rc}", flush=True)
            return rc
    print("# DONE run", flush=True)
    return 0


def neighbor_plan() -> list[dict]:
    """Neighbours owed: every main experiment with results whose v2 summary has P1 and P2 (plan 5.3)."""
    seen = existing_core_shas()
    plan = []
    for row in load_manifest()["run"]:
        name = row["name"]
        if not exists_result(name):
            continue
        e = M.eligibility(v2_summary(name), None)
        if not (e["P1"] and e["P2"]):
            continue
        for nb in neighbor_specs(name, C.read_yaml(C.EXPERIMENTS / f"{name}.yaml")):
            c = P1.core_of(nb["yaml"])
            reuse = seen.get(c)
            if reuse is None:
                seen[c] = nb["name"]
            elif reuse == nb["name"]:
                reuse = None
            plan.append({"main": name, **{k: nb[k] for k in ("code", "value", "name", "yaml")}, "reuse_of": reuse})
    return plan


def neighbors(workers: int, status_only: bool) -> int:
    plan = neighbor_plan()
    m = load_manifest()
    missing = 0
    for p in plan:
        if p["reuse_of"] is None and not exists_result(p["name"]):
            missing += 1
            if not status_only:
                write_yaml(NB_DIR / f"{p['name']}.yaml", p["yaml"])
                if run_cmd(NB_DIR / f"{p['name']}.yaml", workers, neighbor=True) != 0:
                    print(f"FAILED {p['name']}", flush=True)
                    return 1
        entry = {"param": p["code"], "value": p["value"], "experiment": p["name"], "reuse_of": p["reuse_of"]}
        lst = m["neighbors"].setdefault(p["main"], [])
        if entry not in lst:
            lst.append(entry)
    if status_only:
        print(f"neighbour tests missing = {missing} of {len(plan)}" + ("  (未觸發：沒有組同時符合 P1 與 P2)" if not plan else ""))
        return 0
    save_manifest(m)
    print("# DONE neighbors", flush=True)
    return 0


def neighbor_values(main: str, key: str = "net_r") -> list[float]:
    return [v2_summary(e["reuse_of"] or e["experiment"])[key] for e in load_manifest()["neighbors"].get(main, [])]


# --------------------------------------------------------------------------- filter delta
def filter_delta(filt: dict, ctl: dict, filt_ind: dict | None = None, ctl_ind: dict | None = None) -> dict:
    """Delta = v2 net R (filtered) - v2 net R (control). Reference only, not a gate."""
    out = {
        "delta": filt["net_r"] - ctl["net_r"],
        "n_filter": filt["n"],
        "n_control": ctl["n"],
        "gross_delta": filt["gross_r"] - ctl["gross_r"],
    }
    if filt_ind is not None and ctl_ind is not None:
        out["delta_ind"] = filt_ind["net_r"] - ctl_ind["net_r"]
    return out


# --------------------------------------------------------------------------- tables
fmt_r = P1.fmt_r


def n_delisted(name: str, v2: bool) -> int:
    t, a = M.load_is(name)
    if v2:
        t, a = M.one_per_symbol(a, t)
    return int((t["exit_reason"] == "delisted").sum())


def main_row(name: str, tag: str, s: dict, v2: bool) -> str:
    return P1.main_row({"name": name}, s, tag).rstrip(" |") + f" | {n_delisted(name, v2)} |"


def table(out: str | None) -> int:
    man = load_manifest()
    rows = [r for r in man["run"] if exists_result(r["name"])]
    tags = {"base": "基準重算", "tr": "純趨勢", "filter": "纏論過濾"}
    head = ("| 實驗 | 標記 | n | 淨R | 毛R | 手續費R | funding_r | ×1.5淨R | 滑價×3淨R（參考，不是關卡；delisted 腿近似） | PF | 勝率 | 第一根停損 | MFE中位 | MAE中位 | 正季 | n_cross | "
            "資金費受影響筆數(含market) | 下架平倉 |")
    sep = "|" + " --- |" * 18
    lines = ["# Phase 1b 結果（只含樣本內；v2 = 每幣同時最多一筆）", ""]
    v2 = {r["name"]: v2_summary(r["name"]) for r in rows}
    ind = {r["name"]: ind_summary(r["name"]) for r in rows}
    lines += ["## v2 主表（每幣最多一筆）", "", head, sep]
    lines += [main_row(r["name"], tags[r["kind"]], v2[r["name"]], True) for r in rows]
    lines += ["", "## 獨立版主表", "", head, sep]
    lines += [main_row(r["name"], "", ind[r["name"]], False) for r in rows]
    lines += ["", "## v2 各季淨 R 總和", "", "| 實驗 | " + " | ".join(C.IS_QUARTERS) + " |", "|" + " --- |" * 7]
    for r in rows:
        lines.append(f"| {r['name']} | " + " | ".join(f"{q['sum']:+.1f}({q['n']})" for q in v2[r["name"]]["quarters"]) + " |")
    lines += ["", "## v2 多空與分群（n / 淨R）", "", "| 實驗 | long | short | major | core | tradfi | other |", "|" + " --- |" * 7]
    for r in rows:
        s = v2[r["name"]]
        cells = [s["long"], s["short"]] + [s["groups"].get(g, {"n": 0, "net_r": float("nan")}) for g in ("major", "core", "tradfi", "other")]
        lines.append(f"| {r['name']} | " + " | ".join(f"{c['n']} / {fmt_r(c['net_r'])}" for c in cells) + " |")
    lines += ["", "## v2 出場原因分布", "", "| 實驗 | 分布 |", "| --- | --- |"]
    for r in rows:
        lines.append(f"| {r['name']} | {dict(sorted(v2[r['name']]['exit_reasons'].items()))} |")
    lines += ["", "## 纏論過濾淨 R 差（v2，參考，不是關卡；Δ = 過濾組 − 對照組）", "",
              "| 過濾組 | 對照組 | Δ 淨R(v2) | Δ 淨R(獨立) | v2 n（過濾 / 對照） | Δ 毛R(v2) |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["control"] and r["control"] in v2:
            d = filter_delta(v2[r["name"]], v2[r["control"]], ind[r["name"]], ind[r["control"]])
            lines.append(f"| {r['name']} | {r['control']} | {fmt_r(d['delta'])} | {fmt_r(d['delta_ind'])} | {d['n_filter']} / {d['n_control']} | {fmt_r(d['gross_delta'])} |")
    lines += ["", "## P1 / P2 機械判定（只用來決定要不要跑鄰居）", "", "| 實驗 | P1 淨R>0 | P2 ×1.5淨R≥-0.02 | 觸發鄰居 |", "| --- | --- | --- | --- |"]
    for r in rows:
        e = M.eligibility(v2[r["name"]], None)
        lines.append(f"| {r['name']} | {e['P1']} | {e['P2']} | {e['P1'] and e['P2']} |")
    nbm = man["neighbors"]
    lines += ["", "## 鄰居（v2 n / 淨R / 毛R）", ""]
    if nbm:
        lines += ["| 主實驗 | 參數 | 值 | 鄰居實驗 | n | 淨R | 毛R | 沿用 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for main, lst in nbm.items():
            for e in lst:
                s = v2_summary(e["reuse_of"] or e["experiment"])
                lines.append(f"| {main} | {e['param']} | {e['value']} | {e['experiment']} | {s['n']} | {fmt_r(s['net_r'])} | {fmt_r(s['gross_r'])} | {e['reuse_of'] or ''} |")
    else:
        lines.append("未觸發（沒有組同時符合 P1 與 P2，或尚未跑鄰居）")
    flagged = [r["name"] for r in rows if v2[r["name"]]["net_r"] >= 0.5]
    lines += ["", "## 疑似錯誤標記（v2 淨 R ≥ +0.5）", "", ", ".join(flagged) if flagged else "無"]
    lines += ["", "## 下架剔除與中樞過濾說明", "", "| 實驗 | delist_filtered（meta） | 訊號數 | zs4_count=0 而通過的筆數（v2 已成交） |", "| --- | --- | --- | --- |"]
    for r in rows:
        meta = json.loads((C.CACHE / "results" / f"{r['name']}.json").read_text())
        nz = "—"
        if r["filter"] == "nozs4h":
            nz = str(no_zs_pass(r))
        lines.append(f"| {r['name']} | {meta['counters'].get('delist_filtered', 0)} | {meta['n_signals']} | {nz} |")
    Path(out or C.OUT / "phase1b_run.md").write_text("\n".join(lines) + "\n")
    return 0


def dc_table(tf: str) -> pd.DataFrame:
    """Donchian table rows (signal_id, side, close) with the dcaug columns, same row order."""
    base = pd.read_parquet(C.CACHE / f"signals_donchian_{tf}.parquet", columns=["signal_id", "side", "close"])
    aug = pd.read_parquet(C.CACHE / f"signals_donchian_{tf}_aug.parquet", columns=sim.DC_AUG_COLS)
    return pd.concat([base, aug], axis=1).set_index("signal_id")


def no_zs_pass(r: dict) -> int:
    t, a = M.load_is(r["name"])
    t2, _a2 = M.one_per_symbol(a, t)
    d = dc_table(r["tf"])
    x = d.reindex(t2["signal_id"])
    return int((x["zs4_count"] == 0).sum())


def gatea(out: str | None) -> int:
    man = load_manifest()
    lines = ["# 關卡 A（v2；獨立版另列）", "",
             "| 實驗 | 版本 | 淨R≥+0.08 | PF≥1.2 | n≥500 | 正季≥70% | ×1.5淨R>0 | 鄰居同號 | 通過 | 滑價×3淨R（參考，不是關卡） |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in man["run"]:
        n = r["name"]
        if not exists_result(n):
            continue
        for label, s in (("v2", v2_summary(n)), ("獨立", ind_summary(n))):
            nbv = neighbor_values(n)
            g = M.gate_a(s, nbv)
            cell = lambda k, f: f"{f(g[k][0])} {'✓' if g[k][1] else '✗'}"
            if g["neighbors_note"] != "tested":
                e = M.eligibility(v2_summary(n), None)
                nb = "未觸發（P1/P2 不成立）✗" if not (e["P1"] and e["P2"]) else "缺鄰居結果 ✗"
            else:
                nb = "全正 ✓" if g["neighbors"][1] else "有負 ✗"
            lines.append(f"| {n} | {label} | {cell('net_r', fmt_r)} | {cell('pf', lambda x: f'{x:.3f}')} | {cell('n', str)} | {cell('pos_q', lambda x: f'{x}/6')} | {cell('fee15', fmt_r)} | {nb} | {g['pass']} | {fmt_r(s['net_slip3'])} |")
    Path(out or C.OUT / "phase1b_gateA.md").write_text("\n".join(lines) + "\n")
    return 0


# --------------------------------------------------------------------------- sanity
def delist_runs() -> pd.DataFrame:
    return pd.read_parquet(C.CACHE / "delist.parquet")


def sanity() -> int:
    man = load_manifest()
    dl = delist_runs()
    runs = {s: g for s, g in dl.groupby("symbol")}
    names = [(r["name"], r) for r in man["run"] if exists_result(r["name"])]
    for lst in man["neighbors"].values():
        for e in lst:
            nm = e["reuse_of"] or e["experiment"]
            if exists_result(nm):
                names.append((nm, None))
    bad_total = 0
    for name, r in names:
        t, a = M.load_is(name)
        y = C.read_yaml(C.EXPERIMENTS / f"{name}.yaml") if (C.EXPERIMENTS / f"{name}.yaml").exists() else C.read_yaml(NB_DIR / f"{name}.yaml")
        v = {}
        v["order"] = int((t["entry_time"] != t["signal_time"]).sum()) + int((t["exit_time"] < t["entry_time"]).sum()) + int((~(t["r_dist"] > 0)).sum())
        if y["signals"]["tf"] == "1d":
            tt = t["signal_time"].dt.tz_convert("UTC")
            v["utc_midnight"] = int(((tt.dt.hour != 0) | (tt.dt.minute != 0)).sum())
        allowed = ({"structure_stop", "channel_exit", "delisted", "end_of_data"} if "donchian_exit" in y["exit"]
                   else {"structure_stop", "opposite_signal", "delisted", "end_of_data"})
        v["exit_reasons"] = int((~t["exit_reason"].isin(allowed)).sum())
        in_flat = cross = bad_delisted = 0
        for sym, g in t.groupby("symbol"):
            rr = runs.get(sym)
            if rr is None:
                bad_delisted += int((g["exit_reason"] == "delisted").sum())
                continue
            for x in rr.itertuples():
                in_flat += int(((g["entry_time"] >= x.run_start) & (g["entry_time"] <= x.run_end)).sum())
                if pd.notna(x.delist_bar):
                    cross += int(((g["entry_time"] <= x.delist_bar) & (g["exit_time"] > x.delist_bar)).sum())
            dpts = set(rr["delist_bar"].dropna())
            bad_delisted += int(((g["exit_reason"] == "delisted") & ~g["exit_time"].isin(dpts)).sum())
        v["entry_in_flat"], v["cross_delist"], v["delisted_off_point"] = in_flat, cross, bad_delisted
        if r is not None and r["filter"]:
            d = dc_table(r["tf"])
            x = d.reindex(t["signal_id"])
            if r["filter"] == "bias4h":
                up = x["bias4_snap"].isin(sim.BIAS_UP) & (x["side"] == 1)
                dn = x["bias4_snap"].isin(sim.BIAS_DOWN) & (x["side"] == -1)
                v["filter"] = int((~(up | dn)).sum())
            else:
                inside = (x["zs4_count"] > 0) & (x["zs4_zd"] <= x["close"]) & (x["close"] <= x["zs4_zg"])
                v["filter"] = int(inside.sum())
            _tc, ac = M.load_is(r["control"])
            v["subset_of_control"] = int((~a["signal_id"].isin(set(ac["signal_id"]))).sum())
        n_bad = sum(v.values())
        bad_total += n_bad
        print(f"{'OK  ' if n_bad == 0 else 'FAIL'} {name}: {v}")
    print("sanity", "OK" if bad_total == 0 else f"FAIL ({bad_total})")
    return 0 if bad_total == 0 else 1


# --------------------------------------------------------------------------- regress / compare-base
def regress() -> int:
    bad = 0
    for name in ("donchian_1h_n20", "donchian_4h_n55", "p1s1_1h_cur"):
        cfg = sim.SimConfig.from_dict(C.read_yaml(C.EXPERIMENTS / f"{name}.yaml"))
        if cfg.filters["delist_rule"]:
            print(f"REGRESS FAIL {name}: delist_rule is on")
            bad += 1
            continue
        _sig, trades, attempts, _cnt = R.compute(cfg, 6)
        old_t = pd.read_parquet(C.CACHE / "results" / f"{name}.parquet")
        old_a = pd.read_parquet(C.CACHE / "results" / f"{name}.attempts.parquet")
        okt, w1, n1 = R.compare_frames(old_t[old_t["sample"] == "IS"], trades[trades["sample"] == "IS"])
        oka, w2, n2 = R.compare_frames(old_a[old_a["sample"] == "IS"], attempts[attempts["sample"] == "IS"])
        if okt and oka:
            print(f"REGRESS OK {name} rows={int((trades['sample'] == 'IS').sum())} attempts={int((attempts['sample'] == 'IS').sum())} max_abs_diff={max(w1, w2):.3e}")
        else:
            print(f"REGRESS FAIL {name}: {n1} {n2}")
            bad += 1
    return 0 if bad == 0 else 1


def compare_base() -> int:
    dl = sim.load_delist()
    bad = 0
    for new, old in OLD_BASE.items():
        ot, oa = M.load_is(old)
        nt, na = M.load_is(new)
        sig_old, sig_new = set(oa["signal_id"]), set(na["signal_id"])
        missing = oa[~oa["signal_id"].isin(sig_new)]
        extra = sig_new - sig_old
        in_flat = 0
        for x in missing.itertuples():
            rs, re_, _d = dl.get(x.symbol, ((), (), ()))
            T = int(x.signal_time.value // 1000)
            in_flat += any(a <= T <= b + 900_000_000 for a, b in zip(rs, re_))
        m = ot.merge(nt, on="signal_id", suffixes=("_o", "_n"))
        dmask = m["exit_reason_n"] == "delisted"
        cols = [c for c in ot.columns if c in nt.columns and c not in ("attempt_id", "signal_id")]
        diffs = 0
        for c in cols:
            a, b = m[f"{c}_o"][~dmask], m[f"{c}_n"][~dmask]
            if pd.api.types.is_float_dtype(a):
                same = (a == b) | (a.isna() & b.isna()) | ((a - b).abs() <= 1e-9)
            else:
                same = (a == b) | (a.isna() & b.isna())
            diffs += int((~same).sum())
        ok = len(extra) == 0 and in_flat == len(missing) and diffs == 0
        bad += not ok
        print(f"{old} -> {new}: signals old={len(sig_old)} new={len(sig_new)} removed={len(missing)} removed_in_flat={in_flat} new_not_in_old={len(extra)}; "
              f"trades old={len(ot)} new={len(nt)} common={len(m)} delisted_exits={int(dmask.sum())} differing_cells_outside_delisted={diffs}")
    print("COMPARE", "OK" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 1


def relist_report() -> int:
    """Post-hoc statistics required by decision 1793825540: in-sample trades entered after a relisting (would be dropped under option B)."""
    d = delist_runs()
    rel = d[~d["to_end"] & d["delist_bar"].notna()]
    for new in OLD_BASE:
        for label, v2 in (("v2", True), ("獨立", False)):
            t, a = M.load_is(new)
            if v2:
                t, a = M.one_per_symbol(a, t)
            for sym, g in rel.groupby("symbol"):
                first = g["run_start"].min()
                x = t[(t["symbol"] == sym) & (t["signal_time"] > g["run_end"].max())]
                if len(x):
                    print(f"{new} {label} {sym}: relisted after {g['run_end'].max()} (first flat run from {first}); in-sample trades after relisting n={len(x)} net_r_sum={x['net_r'].sum():+.4f}  [選項 B 會剔除]")
    return 0


# --------------------------------------------------------------------------- audit
def audit() -> int:
    reg = R.read_registry(C.OUT / "registry.md")
    problems = []
    main_names = [n for n in reg if R.NB_MARK not in n]
    nb_names = [n for n in reg if R.NB_MARK in n]
    for n in reg:
        p = (NB_DIR if R.NB_MARK in n else C.EXPERIMENTS) / f"{n}.yaml"
        if not p.exists():
            problems.append(f"{n}: no YAML at {p.relative_to(C.ROOT)}")
            continue
        y = C.read_yaml(p)
        sha = R.config_sha(sim.SimConfig.from_dict(y).resolved())
        if sha not in reg[n]:
            problems.append(f"{n}: YAML sha {sha} not in registry {sorted(reg[n])}")
        if n.startswith("p1b_") and y["filters"].get("delist_rule") is not True:
            problems.append(f"{n}: filters.delist_rule is not true")
        if not (C.CACHE / "results" / f"{n}.parquet").exists():
            problems.append(f"{n}: no results file")
    for p in (C.CACHE / "results").glob("*.json"):
        if p.stem not in reg:
            problems.append(f"{p.stem}: results without registry row")
    rows = [ln for ln in (C.OUT / "registry.md").read_text().splitlines() if ln.startswith("|") and not ln.startswith("| time_utc") and not set(ln) <= {"|", "-", " "}]
    runs = C.CACHE / "logs" / "runs.log"
    n_runs = len(runs.read_text().splitlines()) if runs.exists() else 0
    p0 = sum(1 for n in reg if n.startswith("p0_"))
    if len(rows) - p0 != n_runs:
        problems.append(f"registry rows {len(rows)} (phase 0: {p0}) != runs.log rows {n_runs}")
    if len(main_names) > R.MAX_EXPERIMENTS:
        problems.append(f"{len(main_names)} main experiments > {R.MAX_EXPERIMENTS}")
    p1m = json.loads(P1_MANIFEST.read_text())
    allowed = {r["name"] for rnd in ("S1", "S2", "S3") for r in p1m.get(rnd, [])} | {r["name"] for r in load_manifest().get("run", [])} | {n for n in reg if n.startswith("p0_")}
    for n in main_names:
        if n not in allowed:
            problems.append(f"{n}: not in the manifest lists")
    if (C.OUT / "oos_log.md").stat().st_size != 0:
        problems.append("oos_log.md is not empty")
    for p in problems:
        print("PROBLEM", p)
    print(f"{'OK' if not problems else 'FAIL'}: main experiments {len(main_names)}, neighbours {len(nb_names)}")
    return 0 if not problems else 1


MARK = "<!-- generated above; hand-written notes below -->"


def final(promote: str | None, out: str | None) -> int:
    """Plan 6.3: assemble phase1b.md from in-sample results only (no new experiments, no --oos)."""
    import re
    man = load_manifest()
    rows = [r for r in man["run"] if exists_result(r["name"])]
    names = [r["name"] for r in rows]
    v2 = {n: v2_summary(n) for n in names}
    ind = {n: ind_summary(n) for n in names}
    ok = {}
    for n in names:
        nbv = neighbor_values(n)
        ok[n] = (M.gate_a(v2[n], nbv), M.gate_a(ind[n], nbv))
    passed = [n for n in sorted(names, key=lambda x: -v2[x]["net_r"]) if ok[n][0]["pass"]]
    cnt = len(passed)
    if promote and Path(promote).exists():
        m = re.findall(r"PASS_A_COUNT: *([0-9]+)", Path(promote).read_text())
        if m and int(m[-1]) != cnt:
            print(f"MISMATCH PASS_A_COUNT promote={m[-1]} computed={cnt}")
            return 1
    reg = R.read_registry(C.OUT / "registry.md")
    n_main = sum(1 for n in reg if R.NB_MARK not in n)
    n_nb = sum(1 for n in reg if R.NB_MARK in n)
    n1b = sum(1 for n in reg if n.startswith("p1b_") and R.NB_MARK not in n)
    best = max(names, key=lambda x: v2[x]["net_r"])
    b = v2[best]
    nbv = neighbor_values(best)
    e = M.eligibility(b, None)
    nbtxt = "未觸發（P1/P2 不成立）" if not (e["P1"] and e["P2"]) else ("全正" if nbv and all(x > 0 for x in nbv) else "有負")
    ob = {k: v2_summary(o) for k, o in OLD_BASE.items()}
    bs = {k: v2[k] for k in OLD_BASE}
    gp = lambda n: "過" if ok[n][0]["pass"] else "不過"
    d = {}
    for r in rows:
        if r["control"]:
            d[r["name"]] = filter_delta(v2[r["name"]], v2[r["control"]], ind[r["name"]], ind[r["control"]])["delta"]
    sgn = lambda x: f"{x:+.4f}"
    head = [
        "結論：" + ("無候選（10 組事先登記實驗都沒過關卡 A）；建議停止在這份資料上尋找進場優勢" if cnt == 0 else f"有候選（{cnt} 組過關卡 A：{', '.join(passed)}）；只回報，等使用者決定是否進入階段 2"),
        f"最佳組 {best}（v2）：淨 R {sgn(b['net_r'])}、PF {b['pf']:.3f}、筆數 {b['n']}、正季 {ok[best][0]['pos_q'][0]}/6、手續費×1.5 淨 R {sgn(ok[best][0]['fee15'][0])}、鄰居 {nbtxt}",
        f"基準重算（v2，下架規則）：1h n20 淨 R {sgn(bs['p1b_base_1h_n20']['net_r'])}、PF {bs['p1b_base_1h_n20']['pf']:.3f}、筆數 {bs['p1b_base_1h_n20']['n']}；4h n55 淨 R {sgn(bs['p1b_base_4h_n55']['net_r'])}、PF {bs['p1b_base_4h_n55']['pf']:.3f}、筆數 {bs['p1b_base_4h_n55']['n']}"
        f"（舊規則 1h {sgn(ob['p1b_base_1h_n20']['net_r'])}、4h {sgn(ob['p1b_base_4h_n55']['net_r'])}）；關卡 A：1h {gp('p1b_base_1h_n20')}、4h {gp('p1b_base_4h_n55')}",
        f"纏論過濾淨 R 差（v2，參考，不是關卡）：1h n20 方向 Δ{sgn(d['p1b_base_1h_n20_bias'])}、中樞外 Δ{sgn(d['p1b_base_1h_n20_nozs'])}；4h n55 方向 Δ{sgn(d['p1b_base_4h_n55_bias'])}、中樞外 Δ{sgn(d['p1b_base_4h_n55_nozs'])}",
        f"實驗用量：主實驗 {n_main} / 60（階段 0：2、階段 1：24、階段 1b：{n1b}）、鄰居 {n_nb} 個（不計）；oos_log.md 為空；未使用 --oos；未開始階段 2",
    ]
    L = head + [""]
    L += ["# Phase 1b 結果與結論（只含樣本內；v2 = 每幣同時最多一筆）", ""]
    L += ["## 1. 範圍", "",
          "- 只用樣本內（2024-01-01 → 2025-06-30），沒有使用 --oos，`oos_log.md` 為空；關卡 A 全部以 v2 為準，獨立版另列。",
          "- 下架規則（裁決 1793825540）：15m 平線 K（high=low=close 且 volume=0）連續 ≥ 96 根為一段；段內訊號剔除、不能成交進場；持倉在下架點收盤以 taker 加 3 倍滑價強制平倉（`delisted`）。",
          "- 資金費修正：4 個非 ASCII 幣名（币安人生、我踏马来了、牛来、龙虾）2026-10 的月檔以 URL percent-encode 重新下載成功，補值邏輯不變。",
          "- 重新上架（裁決選項 A）：只禁平線期間，重新上架後照常產生訊號與進場。", ""]
    tab = C.OUT / "phase1b_run.md"
    tmp = Path("/tmp/_p1b_tab.md")
    table(str(tmp))
    tabtxt = tmp.read_text()
    sec = {}
    cur = None
    for ln in tabtxt.splitlines():
        if ln.startswith("## "):
            cur = ln[3:]
            sec[cur] = []
        elif cur:
            sec[cur].append(ln)
    L += ["## 2. 完整 v2 表（淨 R、毛 R、手續費 R、funding_r、PF、筆數）", ""] + sec["v2 主表（每幣最多一筆）"] + ["", "### 獨立版（參考，另列）", ""] + sec["獨立版主表"] + [""]
    L += ["### v2 多空與分群（n / 淨R；僅報告）", ""] + sec["v2 多空與分群（n / 淨R）"] + [""]
    L += ["## 3. 關卡 A（v2 為準；獨立版另列，兩版不同的格標 ※）", "",
          "| 實驗 | 版本 | 淨R≥+0.08 | PF≥1.2 | n≥500 | 正季≥70%（≥5/6） | ×1.5淨R>0 | 鄰居同號 | 通過 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    ck = lambda g, k: "✓" if g[k][1] else "✗"
    for n in names:
        g2, gi = ok[n]
        e2 = M.eligibility(v2[n], None)
        nbs = "未觸發（P1/P2 不成立）✗" if not (e2["P1"] and e2["P2"]) else ("全正 ✓" if g2["neighbors"][1] else "有負 ✗")
        for lab, g, s_ in (("v2", g2, v2[n]), ("獨立", gi, ind[n])):
            diff = lambda k: " ※" if lab == "獨立" and g[k][1] != g2[k][1] else ""
            L.append(f"| {n} | {lab} | {s_['net_r']:+.4f} {ck(g, 'net_r')}{diff('net_r')} | {s_['pf']:.3f} {ck(g, 'pf')}{diff('pf')} | {s_['n']} {ck(g, 'n')}{diff('n')} | {g['pos_q'][0]}/6 {ck(g, 'pos_q')}{diff('pos_q')} | {g['fee15'][0]:+.4f} {ck(g, 'fee15')}{diff('fee15')} | {nbs} | {g['pass']} |")
    L += ["", "鄰居（只有同時 P1、P2 成立的組才跑；不計名額）：", ""] + sec["鄰居（v2 n / 淨R / 毛R）"] + [""]
    if passed:
        L += ["### 通過關卡 A 的組（每條門檻實際數字）", ""]
        for n in passed:
            g = ok[n][0]
            L.append(f"- {n}：淨 R {g['net_r'][0]:+.4f}、PF {g['pf'][0]:.3f}、筆數 {g['n'][0]}、正季 {g['pos_q'][0]}/6、×1.5 淨 R {g['fee15'][0]:+.4f}、鄰居 {neighbor_values(n)}")
    else:
        L += ["通過關卡 A 的組：無（0 組），所以沒有「每條門檻實際數字」要另列；10 組的實際數字見上表。", ""]
    L += ["## 4. 纏論過濾淨 R 差（參考，不是關卡）", ""] + sec["纏論過濾淨 R 差（v2，參考，不是關卡；Δ = 過濾組 − 對照組）"] + [""]
    L += ["## 5. 下架規則與資金費修正的影響", "",
          "兩組基準新舊並排（v2；舊 = 階段 1 無下架規則）：", "", "| 組 | 規則 | n | 淨R | 毛R | PF | 正季 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for k, o in OLD_BASE.items():
        for lab, s_ in (("新（v2）", v2[k]), ("舊（v2）", ob[k]), ("新（獨立）", ind[k]), ("舊（獨立）", ind_summary(o))):
            L.append(f"| {k} | {lab} | {s_['n']} | {s_['net_r']:+.4f} | {s_['gross_r']:+.4f} | {s_['pf']:.3f} | {sum(1 for q in s_['quarters'] if q['sum'] > 0)}/6 |")
    L += ["", "下架剔除訊號數與 delisted 出場筆數：", ""] + sec["下架剔除與中樞過濾說明"] + ["", "`harness_validation_delist.md` 前 5 行：", "", "```"]
    L += (C.OUT / "harness_validation_delist.md").read_text().splitlines()[:5] + ["```", ""]
    L += ["## 6. 停止條件判讀", "", "使用者原文：", "",
          "> - 12 組裡沒有任何一組過關卡 A：寫 research/out/phase1b.md 的「無候選」結論，並明確建議停止在這份資料上尋找進場優勢。",
          "> - 有組過 A：只停下來回報，等使用者決定是否進入階段 2。不要自動進入。", ""]
    if cnt == 0:
        L += [f"本階段 10 組事先登記的主實驗（另有 4 個鄰居，不計名額）v2 都沒有通過關卡 A（PASS_A_COUNT: {cnt}）。**無候選。**", "",
              "**建議停止在這份資料上尋找進場優勢。** ChanEdge 的資料管線、撮合、紙交易與日誌可以保留，改接其他策略想法。", ""]
    else:
        L += [f"PASS_A_COUNT: {cnt}。只回報，等使用者決定是否進入階段 2；未開始階段 2。", ""]
    L += ["**過了 A、沒過 B 的停止條件（事先登記，供階段 2 使用；使用者原文）：**", "",
          "> 若某組在樣本內通過關卡 A，但在樣本外（2025-07-01 → 2026-10-27）沒通過關卡 B：",
          "> 1. 該組判定不成立，不得因為樣本外結果修改它的任何參數再重跑。",
          "> 2. 樣本外這段資料視為已用掉。之後任何新設定或新策略都不能再用這段資料當驗證依據，只能當樣本內的一部分。",
          "> 3. 下一輪的樣本外，只能用 2026-10-28 之後新產生的資料，也就是往後的紙交易或前推資料。至少累積 ≥ 300 筆或 ≥ 6 個月再判定，以先到者為準。",
          "> 4. 要寫一份 decision 文件，記錄樣本內和樣本外的數字並排比較，以及「樣本外已用掉」這件事。",
          "> 5. 這種情況下不准進入階段 3。", ""]
    L += ["## 7. 注意事項", "",
          "- E7：反向通道取 `n // 2`（20→10、55→27、16→8、24→12）。",
          "- E9：纏論過濾組沿用基準的出場（同 N 反向突破 + 2 ATR 停損），對照組是新規則重算的基準。",
          "- E11：中樞 = 同一 4h snapshot 最新的中樞，`zd ≤ close ≤ zg` 視為在區間內；沒有中樞而通過的筆數：1h n20 nozs 222、4h n55 nozs 0（v2 已成交）。",
          "- E12：1d K 以 UTC 日切；不滿 96 根 15m 的日子 431 天（其中序列中段 8 天）。",
          "- 重新上架（選項 A）影響筆數（IS，重新上架後進場；選項 B 會剔除）：1h n20 v2 AERGO 4 筆 / +5.4459R、CTK 1 筆 / +1.5493R；獨立 AERGO 12 / +5.6219R、CTK 1 / +1.5493R；4h n55 AERGO 1 筆 / −0.7589R（v2、獨立相同）。post-hoc 統計，未據此改設定。",
          "- `net_slip3` 在 delisted 腿是近似（該腿本身已用 3 倍滑價）。",
          "- 備用 2 組未使用。",
          "- 往後階段的新實驗也必須開 `filters.delist_rule: true`（裁決 E1）。",
          f"- 沒有任何一組 v2 淨 R ≥ +0.5，不需要「疑似錯誤」抽查。獨立版 p1b_tr_4h_n55 的 +0.0894 來自同幣重疊持倉（13 筆 > 20R 的單合計 +562R），v2 為 −0.0302；以 v2 為準。", "",
          MARK, "## 執行者備註", "", "（無）", ""]
    L += ["## 8. 全部表（`phase1b table` 內容）", "", tabtxt.rstrip(), ""]
    Path(out or C.OUT / "phase1b.md").write_text("\n".join(L))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.phase1b")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--verify", action="store_true")
    r = sub.add_parser("runall")
    r.add_argument("--kind", choices=["base", "tr", "filter"])
    r.add_argument("--workers", type=int, default=6)
    n = sub.add_parser("neighbors")
    n.add_argument("--workers", type=int, default=6)
    n.add_argument("--status", action="store_true")
    t = sub.add_parser("table")
    t.add_argument("--out")
    ga = sub.add_parser("gatea")
    ga.add_argument("--out")
    for c in ("sanity", "regress", "compare-base", "relist-report", "audit"):
        sub.add_parser(c)
    f = sub.add_parser("final")
    f.add_argument("--promote")
    f.add_argument("--out")
    a = p.parse_args(argv)
    if a.cmd == "gen":
        return gen(a.verify)
    if a.cmd == "runall":
        return runall(a.kind, a.workers)
    if a.cmd == "neighbors":
        return neighbors(a.workers, a.status)
    if a.cmd == "table":
        return table(a.out)
    if a.cmd == "gatea":
        return gatea(a.out)
    if a.cmd == "sanity":
        return sanity()
    if a.cmd == "regress":
        return regress()
    if a.cmd == "compare-base":
        return compare_base()
    if a.cmd == "relist-report":
        return relist_report()
    if a.cmd == "final":
        return final(a.promote, a.out)
    return audit()


if __name__ == "__main__":
    sys.exit(main())
