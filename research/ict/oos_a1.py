"""ICT OOS pass conditions (ict_phase1.md amendment A1.1). Pure functions on DataFrames.

This module has NO loader and no CLI: it never touches a results file. It may only be fed OOS rows that came out of the
existing `research.report --oos` mechanism (which writes oos_log.md first, once per name). Nothing in research/ict imports it
by default, and report_is.py must not import it.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from research import common as C
from research import metrics as M
from research.ict import stats as S

COOLDOWN_US = 4 * 3600 * 10**6
PERIODS = ("2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3+")
THR = {"net_r": 0.05, "pf": 1.15, "n": 100, "pos_periods": 3, "side_n": 30}


def period_of(signal_time: pd.Series) -> pd.Series:
    """OOS period by signal_time; 2026-07-01 .. 2026-10-27 are all '2026Q3+'. Outside 2025-07-01.. -> NaN."""
    t = pd.to_datetime(signal_time, utc=True)
    q = t.dt.year.astype(str) + "Q" + t.dt.quarter.astype(str)
    q = q.where(~((t.dt.year == 2026) & (t.dt.quarter >= 3)), "2026Q3+")
    return q.where(q.isin(PERIODS))


def v2_oos(attempts: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same v2 as the IS gate (metrics.one_per_symbol with the 4h cooldown) on OOS rows, TRADFI_BASES excluded.

    metrics.one_per_symbol only sees sample == 'IS', so OOS rows are relabelled on copies first.
    """
    def prep(df):
        d = df[df["sample"] == "OOS"].copy()
        d = d[~d["symbol"].str.split("/").str[0].isin(C.TRADFI_BASES)]
        d["sample"] = "IS"
        return d

    return M.one_per_symbol(prep(attempts), prep(trades), cooldown_us=COOLDOWN_US)


def evaluate(t: pd.DataFrame) -> dict:
    """A1.1 on v2 OOS trades `t`. verdict: PASS / FAIL / INSUFFICIENT (n < 100, or either side n < 30)."""
    n = len(t)
    s = M.summarize(t) if n else None
    per = period_of(t["signal_time"]) if n else pd.Series([], dtype=object)
    sums = {p: float(t.loc[per == p, "net_r"].sum()) if n else 0.0 for p in PERIODS}
    cnts = {p: int((per == p).sum()) if n else 0 for p in PERIODS}
    best = max(PERIODS, key=lambda p: sums[p])
    rest = t[(per != best) & per.notna()] if n else t
    rest_mean = float(rest["net_r"].mean()) if len(rest) else math.nan
    nl = int((t["side"] == 1).sum()) if n else 0
    ns = int((t["side"] == -1).sum()) if n else 0
    net_l = float(t.loc[t["side"] == 1, "net_r"].mean()) if nl else math.nan
    net_s = float(t.loc[t["side"] == -1, "net_r"].mean()) if ns else math.nan
    pos = lambda v: bool(v == v and v > 0)
    c = {
        "net_r": (s["net_r"] if s else math.nan, bool(s and s["net_r"] >= THR["net_r"])),
        "pf": (s["pf"] if s else math.nan, bool(s and s["pf"] >= THR["pf"])),
        "n": (n, n >= THR["n"]),
        "pos_periods": (sum(1 for p in PERIODS if sums[p] > 0), sum(1 for p in PERIODS if sums[p] > 0) >= THR["pos_periods"]),
        "drop_best": (rest_mean, pos(rest_mean)),
        "sides": ((net_l, net_s), pos(net_l) and pos(net_s)),
        "fee15": (s["net_fee15"] if s else math.nan, bool(s and pos(s["net_fee15"]))),
    }
    insufficient = n < THR["n"] or nl < THR["side_n"] or ns < THR["side_n"]
    allok = all(v[1] for v in c.values())
    out = {"cond": c, "period_sum": sums, "period_n": cnts, "best_period": best, "n_long": nl, "n_short": ns}
    out["verdict"] = "INSUFFICIENT" if insufficient else ("PASS" if allok else "FAIL")
    return out


def bootstrap_report(t: pd.DataFrame) -> dict:
    """Report-only weekly block bootstrap on OOS v2 trades (weeks counted from Monday 2025-06-30, through 2026-10-27)."""
    origin = pd.Timestamp("2025-06-30", tz="UTC")  # Monday
    n_weeks = int((pd.Timestamp("2026-10-27", tz="UTC") - origin).days // 7) + 1
    if not len(t):
        return {"lb": math.nan}
    return S.block_bootstrap_lb(t["net_r"], S.week_index(t["signal_time"], origin), n_weeks=n_weeks)
