"""Benchmark strategy signals: Donchian close-breakouts on 1h / 4h, N in {20, 55}.

Long signal at bar t: close[t] > max(high[t-N..t-1]) and close[t-1] <= max(high[t-N-1..t-2]).
Short is symmetric on lows. Only the first breakout bar fires. Time = close_time of bar t.
Stop distance is set by the simulator (stop.buffer_atr = 2.0 with defending_price = close).
"""

from __future__ import annotations

import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from research import common as C

NS = (20, 55)


def wilder_atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Same recursion as chanedge.features.atr.wilder_atr; first value at index `period`."""
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    prev_close = close[:-1]
    tr = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)])
    out[period] = tr[:period].mean()
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i - 1]) / period
    return out


def breakouts(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    h = pd.Series(high)
    lo = pd.Series(low)
    hh = h.rolling(n).max().shift(1).to_numpy()  # max(high[t-n..t-1])
    ll = lo.rolling(n).min().shift(1).to_numpy()
    c = pd.Series(close)
    up = (c.to_numpy() > hh) & ~(c.shift(1).to_numpy() > pd.Series(hh).shift(1).to_numpy())
    dn = (c.to_numpy() < ll) & ~(c.shift(1).to_numpy() < pd.Series(ll).shift(1).to_numpy())
    # first bars (NaN comparisons) are False; the previous-bar test must be valid, so require its window too
    up &= ~np.isnan(pd.Series(hh).shift(1).to_numpy())
    dn &= ~np.isnan(pd.Series(ll).shift(1).to_numpy())
    return up, dn


def signals_for(symbol: str, tf: str, rank_map: dict) -> pd.DataFrame:
    df = C.load_bars_df(symbol, tf)
    if df.empty:
        return pd.DataFrame()
    high, low, close = (df[c].to_numpy(float) for c in ("high", "low", "close"))
    atr = wilder_atr_np(high, low, close)
    close_time = df["close_time"]
    frames = []
    for n in NS:
        up, dn = breakouts(high, low, close, n)
        for side, mask, label in ((1, up, "long"), (-1, dn, "short")):
            idx = np.flatnonzero(mask)
            if not len(idx):
                continue
            t = close_time.iloc[idx].reset_index(drop=True)
            days = C.universe_dates(t)
            keep = (days >= C.HISTORY_START) & (days <= C.HISTORY_END)
            sel = idx[keep.to_numpy()]
            if not len(sel):
                continue
            t = close_time.iloc[sel].reset_index(drop=True)
            days = C.universe_dates(t)
            ranks = np.array([rank_map.get((d, symbol), np.nan) for d in days], dtype=float)
            frames.append(
                pd.DataFrame(
                    {
                        "signal_id": [f"dc{n}|{symbol}|{tf}|{x.isoformat()}|{label}" for x in t],
                        "symbol": symbol,
                        "tf": tf,
                        "type": f"dc{n}_{label}",
                        "side": np.int64(side),
                        "time": t,
                        "close": close[sel],
                        "defending_price": close[sel],
                        "prior_extreme": np.nan,
                        "zs_zg": np.nan,
                        "zs_zd": np.nan,
                        "atr": atr[sel],
                        "bias_4h": None,
                        "bias_1h": None,
                        "universe_date": days.to_numpy(),
                        "rank": ranks,
                        "in_top20": ~np.isnan(ranks),
                        "reemit": False,
                        "last_up_end": np.nan,
                        "last_down_end": np.nan,
                        "n": n,
                    }
                )
            )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build() -> None:
    uni = C.load_universe()
    rank_map = {(d, s): r for d, s, r in zip(uni["date"], uni["symbol"], uni["rank"])}
    C.CACHE.mkdir(parents=True, exist_ok=True)
    for tf in ("1h", "4h"):
        frames = [signals_for(s, tf, rank_map) for s in C.union_symbols()]
        frames = [f for f in frames if len(f)]
        out = pd.concat(frames, ignore_index=True).sort_values(["time", "symbol"]).reset_index(drop=True)
        out["time"] = out["time"].astype("datetime64[us, UTC]")
        out.to_parquet(C.CACHE / f"signals_donchian_{tf}.parquet")
        print(tf, len(out))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        print("usage: python -m research.donchian build")
