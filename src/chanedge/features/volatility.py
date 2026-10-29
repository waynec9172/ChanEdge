"""Volatility channel. The tent peak is this symbol's own p50, not (min + max) / 2."""

from __future__ import annotations

import math
from collections.abc import Sequence

from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.decision import VolatilityFeatures
from chanedge.domain.enums import RegimeLabel
from chanedge.domain.params import FeatureParams
from chanedge.features.atr import atr_pct
from chanedge.features.mathutil import clamp, ratio, tent

_CENTER_ABSENT = "vol_center_absent"


def percentile(samples: Sequence[float], percent: float) -> float:
    """Linear percentile. samples stay in the order given; this sorts a copy."""
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percent / 100
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (index - lo) * (ordered[hi] - ordered[lo])


def volatility_channel(
    bars: Sequence[Bar],
    signal_index: int,
    signal: ChanSignal | None,
    atr_values: Sequence[float | None],
    atr: float,
    params: FeatureParams,
) -> VolatilityFeatures:
    bar = bars[signal_index]
    pct = atr_pct(atr, bar.close)
    samples = [
        atr_pct(value, bars[index].close)
        for index, value in enumerate(atr_values)
        if index < signal_index and value is not None
    ]
    count = len(samples)
    p10 = p50 = p90 = None
    if count:
        p10 = percentile(samples, 10)
        p50 = percentile(samples, 50)
        p90 = percentile(samples, 90)
    in_band = params.atr_pct_min <= pct <= params.atr_pct_max
    regime = _regime(pct, count, params.min_samples, p10, p50, p90)
    previous = [item.volume for item in bars[max(0, signal_index - params.volume_median_bars) : signal_index]]
    median = _median(previous)
    rel = ratio(bar.volume, median)
    volume_score = clamp(ratio(rel - params.volatility_volume.volume_floor, params.volatility_volume.volume_span), 0.0, 1.0)
    notes: tuple[str, ...] = ()
    if in_band and count >= params.min_samples and p50 is not None and p10 is not None and p90 is not None:
        width = max(p90 - p50, p50 - p10, 1e-6)
        vol_tent = tent(pct, p50, width)
    elif in_band:
        vol_tent = 0.5
        notes = (_CENTER_ABSENT,)
    else:
        vol_tent = 0.0
    weights = params.volatility_volume
    subscore = 0.0 if signal is None else weights.vol_weight * vol_tent + weights.volume_weight * volume_score
    return VolatilityFeatures(
        atr=atr,
        atr_pct=pct,
        atr_pct_min=params.atr_pct_min,
        atr_pct_max=params.atr_pct_max,
        in_band=in_band,
        rel_volume_20=rel,
        volume_20_median=median,
        vol_p10=p10,
        vol_p50=p50,
        vol_p90=p90,
        vol_n=count,
        regime_label=regime,
        subscore=subscore,
        penalty=0.0,
        skip=False,
        notes=notes,
    )


def _regime(
    pct: float,
    count: int,
    min_samples: int,
    p10: float | None,
    p50: float | None,
    p90: float | None,
) -> RegimeLabel:
    if count < min_samples or p10 is None or p50 is None or p90 is None:
        return RegimeLabel.UNKNOWN
    if pct < p10:
        return RegimeLabel.LOW_EXTREME
    if pct < p50:
        return RegimeLabel.LOW_NORMAL
    if pct <= p90:
        return RegimeLabel.HIGH_NORMAL
    return RegimeLabel.HIGH_EXTREME


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2
