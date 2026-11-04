"""Phase 1 driver: experiment lists (gen), neighbour tests, tables, sanity checks and audit.

  python -m research.phase1 gen S1 [--verify]
  python -m research.phase1 gen S2 --promote /workspace/cc/ph1.promote.S1.md
  python -m research.phase1 gen S3 --promote /workspace/cc/ph1.promote.S2.md
  python -m research.phase1 runround S1|S2|S3 [--workers 6]
  python -m research.phase1 neighbors S1|S2|S3 [--workers 6] [--status]
  python -m research.phase1 table S1|S2|S3 [--out PATH]
  python -m research.phase1 gatea [--donchian] [--out PATH]
  python -m research.phase1 sanity S1|S2|S3
  python -m research.phase1 audit

YAML files are written as JSON (a YAML subset): research code may not import yaml; C.read_yaml reads them.
Everything here reads in-sample results only.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research import common as C
from research import metrics as M
from research import run as R
from research import sim

MANIFEST = C.EXPERIMENTS / "p1_manifest.json"
NB_DIR = C.EXPERIMENTS / "neighbors"
TFS = ("15m", "1h", "4h")
EXITS = ("cur", "rat", "fx2", "fx3", "at2", "at3", "opp")
EXIT_TEXT = {
    "cur": "現行近似（反向訊號用訊號週期）",
    "rat": "不分批只棘輪（保本 1R + 筆棘輪）",
    "fx2": "固定 2R（maker 掛單）",
    "fx3": "固定 3R（maker 掛單）",
    "at2": "ATR 追蹤 2 ATR",
    "at3": "ATR 追蹤 3 ATR",
    "opp": "只有反向訊號",
}
HARD_GATE = {"htf_4h": True, "vol_band": True}
BASE_FILTERS = {"in_top20": True, "candidate_only": False, "gate_pass": False, "jev_min": None, "max_cost_r": None, "exclude_reemit": False}
COSTS = {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1}
ENTRY_S2 = {
    "lc": {"mode": "limit", "limit": {"price": "signal_close", "offset": 0.0, "valid_bars": 4}},
    "lm": {"mode": "limit", "limit": {"price": "defend_frac", "offset": 0.5, "valid_bars": 4}},
    "cf1": {"mode": "confirm", "confirm": {"bars": 1, "require_close_beyond": True}},
}
ENTRY_TEXT = {"lc": "限價掛在訊號 K 收盤價（N=4）", "lm": "限價掛在收盤價與防守價中點（N=4）", "cf1": "等 1 根確認（收盤須不劣於訊號收盤）"}
S3_FILTERS = {
    "ms10a": ("min_stop_atr", 1.0),
    "ms13a": ("min_stop_atr", 1.3),
    "ms1p": ("min_stop_pct", 0.010),
    "ms15p": ("min_stop_pct", 0.015),
    "no4h": ("htf_4h", False),
    "xtf": ("exclude_tradfi", True),
    "jev055": ("jev_min", 0.55),
    "jev062": ("jev_min", 0.62),
}
S3_TEXT = {
    "ms10a": "最小停損 1.0 ATR", "ms13a": "最小停損 1.3 ATR", "ms1p": "最小停損 1%", "ms15p": "最小停損 1.5%",
    "no4h": "4h 方向關（波動帶保留）", "xtf": "排除傳統金融永續", "jev055": "JEV ≥ 0.55", "jev062": "JEV ≥ 0.62",
}


def exit_block(code: str, tf: str) -> dict:
    return {
        "cur": {"preset": "current", "opposite_signal": {"enabled": True, "tf": tf}},
        "rat": {"preset": "ratchet_only"},
        "fx2": {"fixed_r": {"enabled": True, "r": 2.0}},
        "fx3": {"fixed_r": {"enabled": True, "r": 3.0}},
        "at2": {"atr_trail": {"enabled": True, "mult": 2.0, "arm_r": 0.0}},
        "at3": {"atr_trail": {"enabled": True, "mult": 3.0, "arm_r": 0.0}},
        "opp": {"opposite_signal": {"enabled": True, "tf": tf}},
    }[code]


def s1_yaml(name: str, tf: str, code: str, jev: float | None = None) -> dict:
    flt = {**BASE_FILTERS, **HARD_GATE}
    desc = f"S1 {tf} {code}：硬閘門（4h 方向、波動帶），下一根開盤市價，{EXIT_TEXT[code]}"
    if jev is not None:
        flt["jev_min"] = jev
        desc = f"S1 參考列（不排名）：15m 現行近似，硬閘門 + JEV ≥ {jev}，下一根開盤市價"
    return {
        "name": name,
        "description": desc,
        "signals": {"source": "chan", "tf": tf, "types": ["second_buy", "third_buy", "second_sell", "third_sell"], "donchian_n": None},
        "filters": flt,
        "entry": {"mode": "market_next_open"},
        "stop": {"buffer_atr": 0.15, "round_to_tick": True},
        "exit": exit_block(code, tf),
        "costs": dict(COSTS),
    }


def gen_specs(rnd: str = "S1") -> list[dict]:
    """The 24 S1 rows of plan 4.1 (in order), each with its YAML dict."""
    if rnd != "S1":
        raise ValueError("gen_specs only builds S1 (S2/S3 depend on the promotion files)")
    out = []
    for tf in TFS:
        for code in EXITS:
            name = f"p1s1_{tf}_{code}"
            out.append({"name": name, "tf": tf, "exit": code, "entry": "market", "filter": "hard", "ranked": True, "reuse_of": None, "yaml": s1_yaml(name, tf, code), "existing": False})
    for name, tf in (("donchian_1h_n20", "1h"), ("donchian_4h_n55", "4h")):
        out.append({"name": name, "tf": tf, "exit": "dc", "entry": "market", "filter": "top20", "ranked": False, "reuse_of": None, "yaml": C.read_yaml(C.EXPERIMENTS / f"{name}.yaml"), "existing": True})
    out.append({"name": "p1s1_15m_cur_jevref", "tf": "15m", "exit": "cur", "entry": "market", "filter": "hard+jev0.62", "ranked": False, "reuse_of": None,
                "yaml": s1_yaml("p1s1_15m_cur_jevref", "15m", "cur", jev=0.62), "existing": False})
    return out


# --------------------------------------------------------------------------- neighbours (plan 3.10, fixed table)
def _num(v: float) -> str:
    return f"{v:.6g}".replace(".", "p")


def _scaled(v: float) -> tuple[float, float]:
    return round(v * 0.8, 6), round(v * 1.2, 6)


def neighbor_specs(name: str, y: dict) -> list[dict]:
    """Neighbours of one experiment: one parameter changed at a time. [{code, value, name, yaml}]; no table parameter -> []."""
    out = []

    def add(code, value, mutate):
        z = copy.deepcopy(y)
        mutate(z)
        nm = f"{name}__nb_{code}_{_num(value)}"
        z["name"] = nm
        z["description"] = f"NEIGHBOR of {name}: {code}={_num(value).replace('p', '.')}"
        out.append({"code": code, "value": value, "name": nm, "yaml": z})

    raw_exit = y["exit"]
    fx = raw_exit.get("fixed_r", {})
    if fx.get("enabled"):
        for v in _scaled(fx["r"]):
            add("fixr", v, lambda z, v=v: z["exit"]["fixed_r"].update(r=v))
    at = raw_exit.get("atr_trail", {})
    if at.get("enabled"):
        for v in _scaled(at["mult"]):
            add("atrm", v, lambda z, v=v: z["exit"]["atr_trail"].update(mult=v))
    e = y["entry"]
    if e["mode"] == "limit":
        n = e["limit"]["valid_bars"]
        for v in (n - 1, n + 1):
            add("limn", v, lambda z, v=v: z["entry"]["limit"].update(valid_bars=v))
        if e["limit"]["price"] == "defend_frac":
            for v in _scaled(e["limit"]["offset"]):
                add("limf", v, lambda z, v=v: z["entry"]["limit"].update(offset=v))
    if e["mode"] == "confirm":
        k = e["confirm"]["bars"]
        for v in (k - 1, k + 1):
            if v == 0:
                add("cfk", 0, lambda z: z.update(entry={"mode": "market_next_open"}))
            else:
                add("cfk", v, lambda z, v=v: z["entry"]["confirm"].update(bars=v))
    f = y["filters"]
    for key, code in (("min_stop_atr", "msa"), ("min_stop_pct", "msp"), ("jev_min", "jev")):
        if f.get(key) is not None:
            for v in _scaled(f[key]):
                add(code, v, lambda z, v=v, key=key: z["filters"].update({key: v}))
    sg = y["signals"]
    if sg["source"] == "donchian":
        for v in {20: (16, 24), 55: (44, 66)}.get(sg["donchian_n"], ()):
            add("dcn", v, lambda z, v=v: (z["signals"].update(donchian_n=v, types=[f"dc{v}_long", f"dc{v}_short"])))
    return out


# --------------------------------------------------------------------------- file helpers
def write_yaml(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def core_of(y: dict) -> str:
    return R.core_sha(sim.SimConfig.from_dict(y).resolved())


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"S1": [], "S2": [], "S3": [], "neighbors": {}, "skipped": []}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")


def read_promoted(path: str) -> list[str]:
    for ln in Path(path).read_text().splitlines():
        m = re.match(r"\s*PROMOTED:\s*(.*?)\s*(#.*)?$", ln)
        if m:
            v = m.group(1).strip()
            return [] if v.lower() == "none" or not v else [x.strip() for x in v.split(",") if x.strip()]
    raise SystemExit(f"no PROMOTED: line in {path}")


def existing_core_shas() -> dict[str, str]:
    out = {}
    for p in sorted(C.EXPERIMENTS.glob("*.yaml")) + sorted(NB_DIR.glob("*.yaml")):
        out.setdefault(core_of(C.read_yaml(p)), p.stem)
    return out


def _emit(specs: list[dict], seen: dict[str, str], directory: Path) -> list[dict]:
    """Write the YAML of new specs; a spec whose core_sha already exists is recorded as reuse_of and not written."""
    rows = []
    for s in specs:
        sha = core_of(s["yaml"])
        reuse = seen.get(sha)
        if s.get("existing"):
            reuse = None
        elif reuse is None:
            path = directory / f"{s['name']}.yaml"
            if path.exists() and C.read_yaml(path) != s["yaml"]:
                raise SystemExit(f"{path} exists with different content; refusing to overwrite")
            write_yaml(path, s["yaml"])
            seen[sha] = s["name"]
        else:
            pass
        rows.append({k: v for k, v in s.items() if k != "yaml"} | {"reuse_of": reuse})
    return rows


def gen_s1(verify: bool) -> int:
    specs = gen_specs("S1")
    if verify:
        bad = []
        for s in specs:
            p = C.EXPERIMENTS / f"{s['name']}.yaml"
            if not p.exists() or C.read_yaml(p) != json.loads(json.dumps(s["yaml"])):
                bad.append(s["name"])
        m = load_manifest().get("S1", [])
        if [x["name"] for x in m] != [s["name"] for s in specs]:
            bad.append("manifest S1")
        if bad:
            print("FAIL: mismatch:", ", ".join(bad))
            return 1
        print(f"OK: {len(specs)} S1 groups match plan 4.1")
        return 0
    seen = existing_core_shas()
    rows = _emit(specs, seen, C.EXPERIMENTS)
    m = load_manifest()
    m["S1"] = rows
    save_manifest(m)
    print(f"S1: {len(rows)} groups, {sum(1 for r in rows if not r['existing'])} new YAML files written")
    return 0


def _base_name_parts(name: str) -> str:
    return re.sub(r"^p1s[12]_", "", name)


def gen_s2(promote: str) -> int:
    promoted = read_promoted(promote)
    m = load_manifest()
    known = {x["name"] for x in m["S1"]}
    for b in promoted:
        if b not in known:
            raise SystemExit(f"{b} is not in the S1 list")
    seen = existing_core_shas()
    specs = []
    for b in promoted:
        y0 = C.read_yaml(C.EXPERIMENTS / f"{b}.yaml")
        c = _base_name_parts(b)
        for code, entry in ENTRY_S2.items():
            y = copy.deepcopy(y0)
            y["name"] = f"p1s2_{c}_{code}"
            y["entry"] = copy.deepcopy(entry)
            y["description"] = f"S2 {c}：進場改為{ENTRY_TEXT[code]}；其餘同 {b}"
            specs.append({"name": y["name"], "tf": y["signals"]["tf"], "exit": c, "entry": code, "filter": "hard", "ranked": True, "reuse_of": None, "base": b, "yaml": y, "existing": False})
    rows = _emit(specs, seen, C.EXPERIMENTS)
    m["S2"] = [{"name": b, "base": b, "entry": "market", "reuse_of": b, "ranked": True} for b in promoted] + rows
    save_manifest(m)
    print(f"S2: {len(rows)} new rows from {promoted}")
    return 0


def tradfi_trades(name: str) -> int:
    t, _a = M.load_is(name)
    return int(t["symbol"].map(lambda s: s.split("/")[0] in C.TRADFI_BASES).sum())


def gen_s3(promote: str) -> int:
    promoted = read_promoted(promote)
    m = load_manifest()
    known = {x["name"] for x in m["S2"]}
    for b in promoted:
        if b not in known:
            raise SystemExit(f"{b} is not in the S2 list")
    seen = existing_core_shas()
    specs, skipped = [], []
    for b in promoted:
        y0 = C.read_yaml(C.EXPERIMENTS / f"{b}.yaml")
        c = _base_name_parts(b)
        for code, (key, val) in S3_FILTERS.items():
            nm = f"p1s3_{c}_{code}"
            if code.startswith("jev") and y0["signals"]["tf"] != "15m":
                continue
            if code == "xtf":
                n = tradfi_trades(b)
                print(f"{b}: traditional-finance trades in the base (independent, in-sample) = {n}")
                if n == 0:
                    skipped.append({"name": nm, "reason": "xtf: no in-sample trade of the base is a traditional-finance perpetual (D41)"})
                    continue
            y = copy.deepcopy(y0)
            y["filters"][key] = val
            y["name"] = nm
            y["description"] = f"S3 {c}：過濾 {S3_TEXT[code]}；其餘同 {b}"
            specs.append({"name": nm, "tf": y["signals"]["tf"], "exit": c, "entry": b, "filter": code, "ranked": True, "reuse_of": None, "base": b, "yaml": y, "existing": False})
    rows = _emit(specs, seen, C.EXPERIMENTS)
    m["S3"] = [{"name": b, "base": b, "filter": "base", "reuse_of": b, "ranked": True} for b in promoted] + rows
    m["skipped"] = [x for x in m.get("skipped", []) if not x["name"].startswith("p1s3_")] + skipped
    save_manifest(m)
    print(f"S3: {len(rows)} rows ({sum(1 for r in rows if r['reuse_of'])} reused), skipped {len(skipped)}")
    return 0


# --------------------------------------------------------------------------- results access
def exists_result(name: str) -> bool:
    return (C.CACHE / "results" / f"{name}.attempts.parquet").exists()


def v2_summary(name: str) -> dict:
    t, a = M.load_is(name)
    t2, a2 = M.one_per_symbol(a, t)
    return M.summarize(t2, a2)


def ind_summary(name: str) -> dict:
    t, a = M.load_is(name)
    return M.summarize(t, a[a["status"].isin(M.OCCUPY)])


def round_names(rnd: str) -> list[dict]:
    return load_manifest().get(rnd, [])


def run_cmd(path: Path, workers: int, neighbor: bool = False) -> int:
    cmd = [sys.executable, "-m", "research.run", str(path), "--workers", str(workers)] + (["--neighbor"] if neighbor else [])
    return subprocess.run(cmd, cwd=C.ROOT).returncode


def runround(rnd: str, workers: int) -> int:
    for row in round_names(rnd):
        name = row["name"]
        if row.get("reuse_of") or exists_result(name):
            print(f"skip {name} ({'reuse of ' + row['reuse_of'] if row.get('reuse_of') else 'has results'})", flush=True)
            continue
        rc = run_cmd(C.EXPERIMENTS / f"{name}.yaml", workers)
        if rc != 0:
            print(f"FAILED {name} rc={rc}", flush=True)
            return rc
    print(f"# DONE {rnd}", flush=True)
    return 0


def neighbor_plan(rnd: str) -> list[dict]:
    """Neighbours owed by this round: every ranked/benchmark row with P1 and P2 (plan 3.9); reuse by core_sha."""
    m = load_manifest()
    seen = existing_core_shas()
    plan = []
    for row in round_names(rnd):
        if row.get("filter") == "hard+jev0.62":
            continue
        base = row.get("reuse_of") or row["name"]
        if not exists_result(base):
            continue
        s = v2_summary(base)
        e = M.eligibility(s, None)
        if not (e["P1"] and e["P2"]):
            continue
        for nb in neighbor_specs(base, C.read_yaml(C.EXPERIMENTS / f"{base}.yaml")):
            reuse = seen.get(core_of(nb["yaml"]))
            if reuse is None:
                seen[core_of(nb["yaml"])] = nb["name"]
            plan.append({"main": base, **{k: nb[k] for k in ("code", "value", "name", "yaml")}, "reuse_of": reuse})
    return plan


def neighbors(rnd: str, workers: int, status_only: bool) -> int:
    plan = neighbor_plan(rnd)
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
        m["neighbors"].setdefault(p["main"], [])
        entry = {"param": p["code"], "value": p["value"], "experiment": p["name"], "reuse_of": p["reuse_of"]}
        if entry not in m["neighbors"][p["main"]]:
            m["neighbors"][p["main"]].append(entry)
    if status_only:
        print(f"{rnd}: neighbour tests missing = {missing} of {len(plan)}")
        return 0
    save_manifest(m)
    print(f"# DONE neighbors {rnd}", flush=True)
    return 0


def neighbor_values(main: str) -> list[float]:
    out = []
    for e in load_manifest()["neighbors"].get(main, []):
        out.append(v2_summary(e["reuse_of"] or e["experiment"])["net_r"])
    return out


# --------------------------------------------------------------------------- tables
def fmt_r(x):
    return "n/a" if x != x else f"{x:+.4f}"


def table(rnd: str, out: str | None) -> int:
    rows = [r for r in round_names(rnd) if exists_result(r.get("reuse_of") or r["name"])]
    lines = [f"# Phase 1 {rnd} 結果（只含樣本內；v2 = 每幣同時最多一筆）", ""]
    head = "| 實驗 | 標記 | n | 淨R | 毛R | 手續費R | funding_r | ×1.5淨R | PF | 勝率 | 第一根停損 | MFE中位 | MAE中位 | 正季 | n_cross |"
    sep = "|" + " --- |" * 15
    v2 = {}
    lines += ["## v2 主表（每幣最多一筆）", "", head, sep]
    for r in rows:
        key = r.get("reuse_of") or r["name"]
        s = v2.setdefault(key, v2_summary(key))
        tag = "參考列" if r.get("filter") == "hard+jev0.62" else ("基準" if not r.get("ranked", True) else ("沿用" if r.get("reuse_of") else ""))
        lines.append(f"| {r['name']} | {tag} | {s['n']} | {fmt_r(s['net_r'])} | {fmt_r(s['gross_r'])} | {s['fee_r']:.4f} | {fmt_r(s['funding_r'])} | {fmt_r(s['net_fee15'])} | {s['pf']:.3f} | {s['win']:.1%} | {s['first_bar_stop']:.1%} | {s['mfe_med']:.2f} | {s['mae_med']:.2f} | {s['pos_q']}/6 | {s['n_cross']} |")
    lines += ["", "## 獨立版主表", "", head, sep]
    for r in rows:
        key = r.get("reuse_of") or r["name"]
        s = ind_summary(key)
        lines.append(f"| {r['name']} |  | {s['n']} | {fmt_r(s['net_r'])} | {fmt_r(s['gross_r'])} | {s['fee_r']:.4f} | {fmt_r(s['funding_r'])} | {fmt_r(s['net_fee15'])} | {s['pf']:.3f} | {s['win']:.1%} | {s['first_bar_stop']:.1%} | {s['mfe_med']:.2f} | {s['mae_med']:.2f} | {s['pos_q']}/6 | {s['n_cross']} |")
    lines += ["", "## v2 各季淨 R 總和", "", "| 實驗 | " + " | ".join(C.IS_QUARTERS) + " |", "|" + " --- |" * 7]
    for r in rows:
        s = v2[r.get("reuse_of") or r["name"]]
        lines.append(f"| {r['name']} | " + " | ".join(f"{q['sum']:+.1f}({q['n']})" for q in s["quarters"]) + " |")
    lines += ["", "## v2 多空與分群（n / 淨R）", "", "| 實驗 | long | short | major | core | tradfi | other |", "|" + " --- |" * 7]
    for r in rows:
        s = v2[r.get("reuse_of") or r["name"]]
        cells = [s["long"], s["short"]] + [s["groups"].get(g, {"n": 0, "net_r": math_nan()}) for g in ("major", "core", "tradfi", "other")]
        lines.append(f"| {r['name']} | " + " | ".join(f"{c['n']} / {fmt_r(c['net_r'])}" for c in cells) + " |")
    lines += ["", "## P1 / P2 / P3 機械判定（晉級名單以驗收者的 promote 檔為準）", "", "| 實驗 | P1 淨R>0 | P2 ×1.5淨R≥-0.02 | P3 鄰居 | 可晉級 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        if not r.get("ranked", True):
            continue
        key = r.get("reuse_of") or r["name"]
        nbv = neighbor_values(key)
        e = M.eligibility(v2[key], nbv)
        p3 = "無可測鄰居（成立）" if e["no_neighbor"] else ("全正" if e["P3"] else "有負")
        lines.append(f"| {r['name']} | {e['P1']} | {e['P2']} | {p3} | {e['eligible']} |")
    nbm = load_manifest()["neighbors"]
    if nbm:
        lines += ["", "## 鄰居（v2 n / 淨R）", "", "| 主實驗 | 參數 | 值 | 鄰居實驗 | n | 淨R | 沿用 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for main, lst in nbm.items():
            for e in lst:
                s = v2_summary(e["reuse_of"] or e["experiment"])
                lines.append(f"| {main} | {e['param']} | {e['value']} | {e['experiment']} | {s['n']} | {fmt_r(s['net_r'])} | {e['reuse_of'] or ''} |")
    flagged = [r["name"] for r in rows if v2[r.get("reuse_of") or r["name"]]["net_r"] >= 0.5]
    lines += ["", "## 疑似錯誤標記（v2 淨 R ≥ +0.5）", "", ", ".join(flagged) if flagged else "無"]
    sk = load_manifest().get("skipped", [])
    lines += ["", "## 被跳過的列", ""] + ([f"- {x['name']}：{x['reason']}" for x in sk] if sk else ["無"])
    Path(out or C.OUT / f"phase1_{rnd}.md").write_text("\n".join(lines) + "\n")
    return 0


def math_nan():
    return float("nan")


def gatea(donchian: bool, out: str | None) -> int:
    m = load_manifest()
    names = [x["name"] for x in m["S1"] if x["name"].startswith("donchian_")] if donchian else [x.get("reuse_of") or x["name"] for x in m["S3"]]
    if not donchian:
        names += [x["base"] for x in m["S3"] if x.get("base")]
    names = list(dict.fromkeys(names))
    lines = ["# 關卡 A（v2；獨立版另列）", "", "| 實驗 | 版本 | 淨R≥+0.08 | PF≥1.2 | n≥500 | 正季≥70% | ×1.5淨R>0 | 鄰居同號 | 通過 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for n in names:
        if not exists_result(n):
            continue
        for label, s in (("v2", v2_summary(n)), ("獨立", ind_summary(n))):
            g = M.gate_a(s, neighbor_values(n))
            cell = lambda k, f: f"{f(g[k][0])} {'✓' if g[k][1] else '✗'}"
            nb = ("無可測鄰居 ✓" if g["neighbors_note"] != "tested" else ("全正 ✓" if g["neighbors"][1] else "有負 ✗"))
            lines.append(f"| {n} | {label} | {cell('net_r', fmt_r)} | {cell('pf', lambda x: f'{x:.3f}')} | {cell('n', str)} | {cell('pos_q', lambda x: f'{x}/6')} | {cell('fee15', fmt_r)} | {nb} | {g['pass']} |")
    Path(out or C.OUT / "phase1_gateA.md").write_text("\n".join(lines) + "\n")
    return 0


# --------------------------------------------------------------------------- sanity & audit
def sanity(rnd: str) -> int:
    bad = 0
    for r in round_names(rnd):
        name = r.get("reuse_of") or r["name"]
        if not exists_result(name):
            continue
        t, a = M.load_is(name)
        y = C.read_yaml(C.EXPERIMENTS / f"{name}.yaml") if (C.EXPERIMENTS / f"{name}.yaml").exists() else C.read_yaml(NB_DIR / f"{name}.yaml")
        v = 0
        v += int((t["entry_time"] < t["signal_time"]).sum()) + int((t["exit_time"] < t["entry_time"]).sum()) + int((~(t["r_dist"] > 0)).sum())
        if y["entry"]["mode"] == "market_next_open":
            v += int((t["entry_time"] != t["signal_time"]).sum())
        if y["entry"]["mode"] == "limit":
            v += int((t["entry_price"] != t["entry_reference"]).sum())
        if y["entry"]["mode"] == "confirm":
            k = y["entry"]["confirm"]["bars"]
            v += int((t["entry_time"] < t["signal_time"] + t["tf"].map(C.TF_US).map(lambda x: pd.Timedelta(microseconds=x)) * k).sum())
        miss = int(t["funding_missing"].sum())
        print(f"{'OK  ' if v == 0 else 'FAIL'} {name}: violations={v} funding_missing={miss}")
        bad += v
    print("sanity", "OK" if bad == 0 else f"FAIL ({bad})")
    return 0 if bad == 0 else 1


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
        sha = R.config_sha(sim.SimConfig.from_dict(C.read_yaml(p)).resolved())
        if sha not in reg[n]:
            problems.append(f"{n}: YAML sha {sha} not in registry {sorted(reg[n])}")
        if not (C.CACHE / "results" / f"{n}.parquet").exists():
            problems.append(f"{n}: no results file")
    for p in (C.CACHE / "results").glob("*.json"):
        if p.stem not in reg:
            problems.append(f"{p.stem}: results without registry row")
    rows = [ln for ln in (C.OUT / "registry.md").read_text().splitlines() if ln.startswith("|") and not ln.startswith("| time_utc") and not set(ln) <= {"|", "-", " "}]
    runs = C.CACHE / "logs" / "runs.log"
    n_runs = len(runs.read_text().splitlines()) if runs.exists() else 0
    # phase 0 ran before runs.log existed: its 2 rows are not in runs.log
    p0 = sum(1 for n in reg if n.startswith("p0_"))
    if len(rows) - p0 != n_runs:
        problems.append(f"registry rows {len(rows)} (phase 0: {p0}) != runs.log rows {n_runs}")
    if len(main_names) > R.MAX_EXPERIMENTS:
        problems.append(f"{len(main_names)} main experiments > {R.MAX_EXPERIMENTS}")
    allowed = {r["name"] for rnd in ("S1", "S2", "S3") for r in load_manifest().get(rnd, [])} | {n for n in reg if n.startswith("p0_")}
    for n in main_names:
        if n not in allowed:
            problems.append(f"{n}: not in the manifest lists")
    if (C.OUT / "oos_log.md").stat().st_size != 0:
        problems.append("oos_log.md is not empty")
    for p in problems:
        print("PROBLEM", p)
    print(f"{'OK' if not problems else 'FAIL'}: main experiments {len(main_names)}, neighbours {len(nb_names)}")
    return 0 if not problems else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.phase1")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("round", choices=["S1", "S2", "S3"])
    g.add_argument("--verify", action="store_true")
    g.add_argument("--promote")
    r = sub.add_parser("runround")
    r.add_argument("round", choices=["S1", "S2", "S3"])
    r.add_argument("--workers", type=int, default=6)
    n = sub.add_parser("neighbors")
    n.add_argument("round", choices=["S1", "S2", "S3"])
    n.add_argument("--workers", type=int, default=6)
    n.add_argument("--status", action="store_true")
    t = sub.add_parser("table")
    t.add_argument("round", choices=["S1", "S2", "S3"])
    t.add_argument("--out")
    ga = sub.add_parser("gatea")
    ga.add_argument("--donchian", action="store_true")
    ga.add_argument("--out")
    s = sub.add_parser("sanity")
    s.add_argument("round", choices=["S1", "S2", "S3"])
    sub.add_parser("audit")
    a = p.parse_args(argv)
    if a.cmd == "gen":
        if a.round == "S1":
            return gen_s1(a.verify)
        if not a.promote:
            raise SystemExit("--promote is required for S2/S3")
        return gen_s2(a.promote) if a.round == "S2" else gen_s3(a.promote)
    if a.cmd == "runround":
        return runround(a.round, a.workers)
    if a.cmd == "neighbors":
        return neighbors(a.round, a.workers, a.status)
    if a.cmd == "table":
        return table(a.round, a.out)
    if a.cmd == "gatea":
        return gatea(a.donchian, a.out)
    if a.cmd == "sanity":
        return sanity(a.round)
    return audit()


if __name__ == "__main__":
    sys.exit(main())
