"""Fair value gaps: detection, first 15m touch, close-through kill time."""

from __future__ import annotations

import numpy as np

INT64_MAX = np.iinfo(np.int64).max


def fvgs(high, low, atr, k: float) -> dict:
    high = np.asarray(high, float)
    low = np.asarray(low, float)
    atr = np.asarray(atr, float)
    n = len(high)
    if n < 3:
        z = np.empty(0)
        return {"idx": np.empty(0, np.int64), "side": np.empty(0, np.int64), "lo": z, "hi": z.copy(), "gap": z.copy()}
    i = np.arange(2, n)
    a = atr[2:]
    with np.errstate(invalid="ignore"):
        bear_gap = low[:-2] - high[2:]
        bull_gap = low[2:] - high[:-2]
        bear = ~np.isnan(a) & (bear_gap > k * a)
        bull = ~np.isnan(a) & (bull_gap > k * a)
    idx = np.r_[i[bear], i[bull]]
    side = np.r_[np.full(bear.sum(), -1, np.int64), np.full(bull.sum(), 1, np.int64)]
    lo = np.r_[high[2:][bear], high[:-2][bull]]
    hi = np.r_[low[:-2][bear], low[2:][bull]]
    gap = np.r_[bear_gap[bear], bull_gap[bull]]
    o = np.argsort(idx, kind="stable")
    return {"idx": idx[o].astype(np.int64), "side": side[o], "lo": lo[o], "hi": hi[o], "gap": gap[o]}


def first_touch(fvg_side, fvg_lo, fvg_hi, created_ct_us, m15_ot_us, m15_h, m15_l) -> np.ndarray:
    """close_time (us) of the first 15m bar with open_time >= created and (bear: h >= lo; bull: l <= hi); INT64_MAX if none."""
    out = np.full(len(fvg_side), INT64_MAX, dtype=np.int64)
    for q in range(len(fvg_side)):
        j0 = int(np.searchsorted(m15_ot_us, created_ct_us[q], side="left"))
        if fvg_side[q] == -1:
            hit = np.flatnonzero(m15_h[j0:] >= fvg_lo[q])
        else:
            hit = np.flatnonzero(m15_l[j0:] <= fvg_hi[q])
        if len(hit):
            out[q] = int(m15_ot_us[j0 + hit[0]]) + 900_000_000
    return out


def kill_time(fvg_side, fvg_lo, fvg_hi, created_idx, s_close, s_ct_us) -> np.ndarray:
    """close_time (us) of the first setup bar after idx closing through the gap (bear: close > hi; bull: close < lo)."""
    out = np.full(len(fvg_side), INT64_MAX, dtype=np.int64)
    for q in range(len(fvg_side)):
        j0 = int(created_idx[q]) + 1
        if fvg_side[q] == -1:
            hit = np.flatnonzero(s_close[j0:] > fvg_hi[q])
        else:
            hit = np.flatnonzero(s_close[j0:] < fvg_lo[q])
        if len(hit):
            out[q] = int(s_ct_us[j0 + hit[0]])
    return out
