"""4H trend flags and alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.ict.swings import swings


def ema(close: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(np.asarray(close, float)).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def _last_two_flag(conf: np.ndarray, price: np.ndarray, m: int, lower: bool) -> np.ndarray:
    """flag[j] = the last two swings with conf <= j satisfy (lower: later < earlier; else later > earlier)."""
    out = np.zeros(m, dtype=bool)
    if len(conf) < 2:
        return out
    cmp = (price[1:] < price[:-1]) if lower else (price[1:] > price[:-1])  # cmp[q]: swings q (earlier), q+1 (later)
    cnt = np.searchsorted(conf, np.arange(m), side="right")  # swings confirmed at bar j
    ok = cnt >= 2
    out[ok] = cmp[cnt[ok] - 2]
    return out


def htf_flags(h4: pd.DataFrame, n: int, span: int):
    c = h4["close"].to_numpy(float)
    ct = h4["close_time"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy().astype("int64")
    m = len(c)
    ph, pp, pl, pq_ = swings(h4["high"].to_numpy(float), h4["low"].to_numpy(float), n)
    e = ema(c, span)
    with np.errstate(invalid="ignore"):
        below = c < e
        above = c > e
    bear = _last_two_flag(pl + n, pq_, m, True) | below
    bull = _last_two_flag(ph + n, pp, m, False) | above
    return ct, bear, bull


def align(src_ct_us: np.ndarray, t_us: np.ndarray) -> np.ndarray:
    return np.searchsorted(src_ct_us, t_us, side="right") - 1
