"""Swing detection. Left side strict, right side non-strict; confirmed at close of bar pivot+n."""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _win


def _pivots(x: np.ndarray, n: int, high: bool) -> np.ndarray:
    m = len(x)
    if m < 2 * n + 1:
        return np.empty(0, dtype=np.int64)
    w = _win(x, 2 * n + 1)  # row r covers pivot r+n
    mid = w[:, n:n + 1]
    left, right = w[:, :n], w[:, n + 1:]
    if high:
        ok = (mid > left).all(axis=1) & (mid >= right).all(axis=1)
    else:
        ok = (mid < left).all(axis=1) & (mid <= right).all(axis=1)
    return np.flatnonzero(ok).astype(np.int64) + n


def swings(high: np.ndarray, low: np.ndarray, n: int):
    """(sh_pivot, sh_price, sl_pivot, sl_price), ascending by pivot. Confirm index = pivot + n."""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    ph = _pivots(high, n, True)
    pl = _pivots(low, n, False)
    return ph, high[ph], pl, low[pl]
