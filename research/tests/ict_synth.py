"""Synthetic fixtures for the ICT tests (not a test module). Setup TF = 15m unless stated; prices are multiples of 0.25 or short decimals."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from research.ict import generate as G
from research.ict import params as IP
from research.ict import state as ST

START = pd.Timestamp("2024-03-04 00:00", tz="UTC")  # a Monday
STEP_US = 900_000_000
SYMBOL = "SYN/USDT"

FLAT = (100.0, 100.5, 99.5, 100.0)
# bar index: 0..29 flat; 30..42 build a swing high (41) and swing low (37); 43 closes below the swing low (BOS)
SHORT_BASE = (
    [FLAT] * 30
    + [
        (100.0, 101.0, 99.75, 100.75),   # 30
        (100.75, 102.0, 100.5, 101.75),  # 31
        (101.75, 103.0, 101.5, 102.75),  # 32
        (102.75, 104.0, 102.5, 103.5),   # 33 swing high 104
        (103.5, 103.5, 102.0, 102.25),   # 34
        (102.25, 102.5, 100.5, 100.75),  # 35
        (100.75, 101.0, 99.0, 99.25),    # 36
        (99.25, 99.5, 98.0, 98.25),      # 37 swing low 98
        (98.5, 99.5, 98.5, 99.5),        # 38
        (99.5, 100.5, 99.25, 100.25),    # 39
        (100.25, 101.0, 100.0, 100.75),  # 40
        (100.75, 101.5, 100.5, 101.0),   # 41 swing high 101.5
        (101.0, 101.25, 100.25, 100.5),  # 42
        (100.5, 100.5, 97.5, 97.75),     # 43 BOS (close 97.75 < 98); a1 = 101.5
        (97.75, 99.5, 97.5, 97.5),       # 44 bearish FVG [99.5, 100.25]
        (97.5, 97.75, 95.5, 95.75),      # 45 new low 95.5
        (95.75, 96.5, 95.5, 96.25),      # 46 -> a0 = 95.5, zone built
        (96.25, 97.25, 96.0, 97.0),      # 47
        (97.0, 98.5, 96.75, 98.25),      # 48
        (98.25, 99.25, 98.0, 99.0),      # 49
        (99.0, 100.0, 98.75, 99.75),     # 50 touches zone_lo
        (99.75, 99.75, 98.5, 98.75),     # 51
        (98.75, 99.0, 97.5, 97.75),      # 52
    ]
)


def mirror_rows(rows, c=1000.0):
    return [(c - o, c - l, c - h, c - cl) for o, h, l, cl in rows]


def frames(rows, start=START):
    n = len(rows)
    ot = pd.date_range(start, periods=n, freq="15min", tz="UTC").astype("datetime64[us, UTC]")
    a = np.array(rows, dtype=float)
    b15 = pd.DataFrame({
        "open_time": ot, "close_time": ot + pd.Timedelta(minutes=15), "open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3],
        "volume": np.full(n, 100.0),
    })

    def agg(k, freq):
        g = b15.groupby(np.arange(n) // k)
        d = g.agg(open_time=("open_time", "first"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
        d = d[g.size().to_numpy() == k].reset_index(drop=True)
        d["close_time"] = d["open_time"] + pd.Timedelta(freq)
        return d

    return b15, agg(4, "1h"), agg(16, "4h")


def P_for(**over):
    """All filters off, setup_tf 15m; override per test."""
    d = copy.deepcopy(IP.DEFAULTS)
    d.update(setup_tf="15m", use_htf=False, use_expansion=False, use_fresh=False, use_ltf=False, use_sweep=False, use_session=False, use_funding=False)
    d.update(over)
    return IP.validate(d)


def features(rows, P, funding=None, htf=None, start=START):
    b15, b1h, b4h = frames(rows, start)
    F = G.build_features(SYMBOL, b15, b1h, b4h, funding, P)
    if htf is not None:  # force the 4h flags (bear, bull): scalars or per-4h-bar arrays
        for name, v in zip(("h4_bear", "h4_bull"), htf):
            F.__dict__[name] = np.full(len(F.h4_bear), v) if np.isscalar(v) else np.asarray(v, dtype=bool)
    return F


def run(rows, P, funding=None, htf=(True, True), start=START, **kw):
    F = features(rows, P, funding, htf, start)
    ev, tr, info = G.run_symbol(SYMBOL, F, P, **kw)
    return F, ev, tr, info


def reasons(tr, side=None):
    return [(t.frm, t.to, t.reason) for t in tr if side is None or t.side == side]


def final_reasons(tr, side=-1):
    return [t.reason for t in tr if t.side == side and t.to == "INVALID"]


def replace_bar(rows, i, bar):
    r = list(rows)
    r[i] = bar
    return r
