"""ICT P2 statistics: weekly block bootstrap and Deflated Sharpe (ict_phase1.md sections 4 and 7). Pure functions on arrays."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

BOOT_SEED = 20261105
BOOT_N = 2000
BOOT_Q = 0.10  # 90 % one-sided lower bound
WEEK_ORIGIN = pd.Timestamp("2024-01-01", tz="UTC")  # a Monday
IS_WEEKS = 79  # 2024-01-01 .. 2025-06-30, last week holds one day (2025-06-30)
EULER_GAMMA = 0.5772156649
_ND = NormalDist()


def week_index(signal_time: pd.Series, origin: pd.Timestamp = WEEK_ORIGIN) -> np.ndarray:
    """UTC week number counted from `origin` (Monday 00:00), by signal_time."""
    t = pd.to_datetime(signal_time, utc=True)
    return ((t - origin).dt.days // 7).to_numpy(dtype=np.int64)


def block_bootstrap_lb(net_r, weeks, n_weeks: int = IS_WEEKS, n_boot: int = BOOT_N, seed: int = BOOT_SEED, q: float = BOOT_Q) -> dict:
    """Weekly block bootstrap of the mean net R per trade.

    Blocks are UTC weeks, empty weeks included. Each replicate draws n_weeks weeks with replacement (one
    `default_rng(seed).integers(0, n_weeks, (n_boot, n_weeks))` call); statistic = sum of net_r over the drawn weeks / number of
    trades in them (0 when no trade was drawn). Lower bound = np.quantile(stats, q); the gate needs it > 0.
    """
    x = np.asarray(net_r, dtype=float)
    w = np.asarray(weeks, dtype=np.int64)
    if len(x) != len(w):
        raise ValueError("net_r and weeks differ in length")
    if len(w) and (w.min() < 0 or w.max() >= n_weeks):
        raise ValueError("a trade falls outside the week grid")
    sums = np.bincount(w, weights=x, minlength=n_weeks).astype(float)
    cnts = np.bincount(w, minlength=n_weeks).astype(float)
    idx = np.random.default_rng(seed).integers(0, n_weeks, size=(n_boot, n_weeks))
    s, c = sums[idx].sum(axis=1), cnts[idx].sum(axis=1)
    stats = np.divide(s, c, out=np.zeros_like(s), where=c > 0)
    return {"lb": float(np.quantile(stats, q)), "mean": float(stats.mean()), "n_boot": n_boot, "seed": seed, "q": q, "n_weeks": n_weeks}


def sharpe_moments(net_r) -> dict:
    """Per-trade SR = mean/std(ddof=1), plus skewness and (non-excess) kurtosis of the same sample."""
    x = np.asarray(net_r, dtype=float)
    n = len(x)
    if n < 3:
        return {"n": n, "sr": math.nan, "skew": math.nan, "kurt": math.nan}
    sd = x.std(ddof=1)
    if not sd > 0:
        return {"n": n, "sr": math.nan, "skew": math.nan, "kurt": math.nan}
    m = x.mean()
    sd0 = x.std(ddof=0)
    z = (x - m) / sd0
    return {"n": n, "sr": float(m / sd), "skew": float((z**3).mean()), "kurt": float((z**4).mean())}


def expected_max_sr(var_sr: float, n_trials: int) -> float:
    """SR0 = sqrt(V) * ((1-g) * Phi^-1(1-1/N) + g * Phi^-1(1-1/(N*e)))."""
    if not (var_sr == var_sr and var_sr >= 0) or n_trials < 2:
        return math.nan
    g = EULER_GAMMA
    return math.sqrt(var_sr) * ((1 - g) * _ND.inv_cdf(1 - 1 / n_trials) + g * _ND.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(net_r, var_sr: float, n_trials: int) -> dict:
    """Bailey & Lopez de Prado DSR. Report-only. var_sr = sample variance of the SRs of all executed ICT main experiments;
    n_trials = run.n_main(registry) at report time."""
    mo = sharpe_moments(net_r)
    sr0 = expected_max_sr(var_sr, n_trials)
    out = {"sr": mo["sr"], "sr0": sr0, "n_trials": n_trials, "T": mo["n"], "skew": mo["skew"], "kurt": mo["kurt"], "dsr": math.nan}
    if mo["sr"] != mo["sr"] or sr0 != sr0:
        return out
    den = 1 - mo["skew"] * mo["sr"] + (mo["kurt"] - 1) / 4 * mo["sr"] ** 2
    if not den > 0:
        return out
    out["dsr"] = float(_ND.cdf((mo["sr"] - sr0) * math.sqrt(mo["n"] - 1) / math.sqrt(den)))
    return out


def var_of_srs(srs) -> float:
    """Sample variance (ddof=1) of the SRs; NaN SRs are dropped; fewer than 2 -> NaN."""
    v = np.asarray([s for s in srs if s == s], dtype=float)
    return float(v.var(ddof=1)) if len(v) >= 2 else math.nan
