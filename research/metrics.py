"""In-sample metrics for phase 1: the one-position-per-symbol version (v2), summary table, gate A, promotion conditions.

Only in-sample rows are ever read: load_is() drops everything that is not sample == "IS" right after reading, and no
function in this module takes an out-of-sample switch.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from research import common as C

OCCUPY = ("filled", "unfilled", "abandoned")
IS_CUT_US = pd.Timestamp("2025-07-01", tz="UTC")
GATE = {"net_r": 0.08, "pf": 1.2, "n": 500, "pos_q_frac": 0.70}
FEE_MULT = 1.5
P2_FLOOR = -0.02


def load_is(name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(trades, attempts) of one experiment, in-sample rows only."""
    res = C.CACHE / "results"
    t = pd.read_parquet(res / f"{name}.parquet")
    a = pd.read_parquet(res / f"{name}.attempts.parquet")
    return t[t["sample"] == "IS"].reset_index(drop=True), a[a["sample"] == "IS"].reset_index(drop=True)


def _priority(typ: str) -> int:
    return 0 if str(typ).startswith("third_") else 1


def one_per_symbol(attempts: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v2: a symbol holds at most one position/order at a time (plan 3.7).

    Occupying attempts (filled / unfilled / abandoned) of one symbol are walked in signal_time order. Several attempts at
    the same time: long and short both present -> all skipped; same side -> third_* beats second_*, then smallest signal_id.
    An attempt is taken only if signal_time > busy_until (strict); then busy_until = its end_time.
    Returns (trades_v2, attempts_v2). Out-of-sample rows are ignored.
    """
    a = attempts[(attempts["sample"] == "IS") & attempts["status"].isin(OCCUPY)]
    keep: list[int] = []
    for _sym, g in a.groupby("symbol", sort=False):
        g = g.sort_values(["signal_time", "attempt_id"], kind="stable")
        busy = None
        for _t, grp in g.groupby("signal_time", sort=True):
            if grp["side"].nunique() > 1:
                continue
            if busy is not None and not _t > busy:
                continue
            pick = min(grp.itertuples(), key=lambda r: (_priority(r.type), r.signal_id))
            keep.append(int(pick.attempt_id))
            busy = pick.end_time
    att2 = a[a["attempt_id"].isin(keep)].sort_values("attempt_id", kind="stable").reset_index(drop=True)
    tr = trades[(trades["sample"] == "IS") & trades["attempt_id"].isin(att2.loc[att2["status"] == "filled", "attempt_id"])]
    return tr.reset_index(drop=True), att2


def pf_of(x: pd.Series) -> float:
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg > 0:
        return pos / neg
    return math.inf if pos > 0 else math.nan


def _block(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"n": 0, "net_r": math.nan, "pf": math.nan}
    return {"n": int(len(t)), "net_r": float(t["net_r"].mean()), "pf": pf_of(t["net_r"])}


def summarize(trades: pd.DataFrame, attempts: pd.DataFrame | None = None) -> dict:
    """All plan 3.8 metrics for one trade set (already restricted to in-sample, v2 or independent)."""
    n = len(trades)
    out: dict = {"n": n}
    if n == 0:
        out.update(net_r=math.nan, gross_r=math.nan, fee_r=math.nan, funding_r=math.nan, net_fee15=math.nan, pf=math.nan,
                   win=math.nan, first_bar_stop=math.nan, first_tf_bar_stop=math.nan, mfe_med=math.nan, mae_med=math.nan,
                   pos_q=0, quarters=[], long=_block(trades), short=_block(trades), groups={}, exit_reasons={}, n_cross=0,
                   n_funding_missing=0, n_funding_market=0, net_slip3=math.nan)
    else:
        net = trades["net_r"]
        stop0 = (trades["exit_reason"] == "structure_stop") & (trades["bars_held"] == 0)
        bpt = trades["tf"].map(C.BARS_PER_TF)
        stop_tf = (trades["exit_reason"] == "structure_stop") & (trades["bars_held"] < bpt)
        q = C.quarter_of_series(trades["signal_time"])
        quarters = []
        for lab in C.IS_QUARTERS:
            x = net[q == lab]
            quarters.append({"q": lab, "n": int(len(x)), "sum": float(x.sum()), "mean": float(x.mean()) if len(x) else math.nan})
        grp = trades["symbol"].map(C.symbol_group)
        out.update(
            net_r=float(net.mean()),
            gross_r=float(trades["gross_r"].mean()),
            fee_r=float(trades["fee_r"].mean()),
            funding_r=float(trades["funding_r"].mean()),
            net_fee15=float((trades["gross_r"] - FEE_MULT * trades["fee_r"] - trades["funding_r"]).mean()),
            pf=pf_of(net),
            win=float((net > 0).mean()),
            first_bar_stop=float(stop0.mean()),
            first_tf_bar_stop=float(stop_tf.mean()),
            mfe_med=float(trades["mfe_r"].median()),
            mae_med=float(trades["mae_r"].median()),
            pos_q=int(sum(1 for x in quarters if x["sum"] > 0)),
            quarters=quarters,
            long=_block(trades[trades["side"] == 1]),
            short=_block(trades[trades["side"] == -1]),
            groups={g: _block(trades[grp == g]) for g in ("major", "core", "tradfi", "other")},
            exit_reasons={k: int(v) for k, v in trades["exit_reason"].value_counts().items()},
            n_cross=int((trades["exit_time"] >= IS_CUT_US).sum()),
            n_funding_missing=int(trades["funding_missing"].sum()),
            n_funding_market=int((trades["n_funding_market"] > 0).sum()) if "n_funding_market" in trades.columns else 0,
            net_slip3=float((net - 2.0 * trades["slip_r"]).mean()) if "slip_r" in trades.columns else math.nan,
        )
    if attempts is not None:
        st = attempts["status"].value_counts()
        f, u, ab = int(st.get("filled", 0)), int(st.get("unfilled", 0)), int(st.get("abandoned", 0))
        out["fill_rate"] = f / (f + u) if (f + u) else math.nan
        out["abandon_rate"] = ab / len(attempts) if len(attempts) else math.nan
        out["n_unfilled"], out["n_abandoned"] = u, ab
    return out


def gate_a(s: dict, neighbor_net_r: list[float] | None) -> dict:
    """Gate A on a v2 summary. Raw floats, no rounding.

    neighbor_net_r = v2 net R of each tabled neighbour. Plan 8.2: there is no "no testable neighbour" case any more; an empty or
    None list means the neighbour results are missing and the sixth condition FAILS (note "missing neighbour results").
    """
    def ok(v, thr):
        return bool(v == v and v >= thr)

    res = {
        "net_r": (s["net_r"], ok(s["net_r"], GATE["net_r"])),
        "pf": (s["pf"], ok(s["pf"], GATE["pf"])),
        "n": (s["n"], s["n"] >= GATE["n"]),
        "pos_q": (s["pos_q"], s["pos_q"] / len(C.IS_QUARTERS) >= GATE["pos_q_frac"]),
        "fee15": (s["net_fee15"], bool(s["net_fee15"] == s["net_fee15"] and s["net_fee15"] > 0)),
    }
    if neighbor_net_r:
        res["neighbors"] = (list(neighbor_net_r), all(x == x and x > 0 for x in neighbor_net_r))
        res["neighbors_note"] = "tested"
    else:
        res["neighbors"] = ([], False)
        res["neighbors_note"] = "missing neighbour results"
    res["pass"] = all(res[k][1] for k in ("net_r", "pf", "n", "pos_q", "fee15", "neighbors"))
    return res


def eligibility(s: dict, neighbor_net_r: list[float] | None) -> dict:
    """Promotion conditions P1-P3 on a v2 summary (plan 3.9, 8.2). Missing neighbour results -> P3 fails."""
    p1 = bool(s["net_r"] == s["net_r"] and s["net_r"] > 0)
    p2 = bool(s["net_fee15"] == s["net_fee15"] and s["net_fee15"] >= P2_FLOOR)
    p3 = bool(neighbor_net_r) and all(x == x and x > 0 for x in neighbor_net_r)
    return {"P1": p1, "P2": p2, "P3": p3, "missing_neighbor": not neighbor_net_r, "eligible": p1 and p2 and p3}


def rank_eligible(items: list[tuple[str, dict, dict]], k: int = 2) -> list[str]:
    """items = (name, v2 summary, eligibility). Highest v2 net R first, then more trades, then name; at most k; never padded."""
    ok = [(n, s) for n, s, e in items if e["eligible"]]
    ok.sort(key=lambda x: (-x[1]["net_r"], -x[1]["n"], x[0]))
    return [n for n, _ in ok[:k]]


F1_GROSS = 0.05


def fallback_s1(items: list[tuple[str, dict, list[float] | None]], k: int = 2) -> dict:
    """Plan 8.4 limit-order fallback (mechanical). items = (name, v2 summary, [v2 gross R of the two sbuf neighbours] or None).

    The caller passes only the candidate pool (15m and 1h ranked main experiments; never 4h, Donchian or the JEV reference).
    F1: mean(gross_r) >= 0.05 (raw float). F2: both sbuf neighbours have v2 mean(gross_r) > 0 (missing -> fails).
    Ranking among F1&F2 by v2 net R desc, then more trades, then name; at most k.
    """
    rows = []
    for name, s, nb in items:
        g = s["gross_r"]
        f1 = bool(g == g and g >= F1_GROSS)
        f2 = bool(nb) and len(nb) == 2 and all(x == x and x > 0 for x in nb)
        rows.append({"name": name, "gross_r": g, "net_r": s["net_r"], "n": s["n"], "F1": f1, "nb_gross": list(nb) if nb else [], "F2": f2, "both": f1 and f2})
    ok = sorted((r for r in rows if r["both"]), key=lambda r: (-r["net_r"], -r["n"], r["name"]))
    return {"rows": rows, "promoted": [r["name"] for r in ok[:k]], "f1_names": [r["name"] for r in rows if r["F1"]]}
