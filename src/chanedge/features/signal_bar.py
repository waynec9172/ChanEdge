"""Signal-bar channel. The short formula is its own weights, not the long formula negated."""

from __future__ import annotations

from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.decision import SignalBarFeatures
from chanedge.domain.enums import Side
from chanedge.domain.params import FeatureParams
from chanedge.features.mathutil import ratio


def signal_bar_channel(bar: Bar, signal: ChanSignal | None, side: Side, params: FeatureParams) -> SignalBarFeatures:
    span = bar.high - bar.low
    if span > 0:
        close_location = (bar.close - bar.low) / span
        body = abs(bar.close - bar.open) / span
        upper = (bar.high - max(bar.open, bar.close)) / span
        lower = (min(bar.open, bar.close) - bar.low) / span
    else:
        close_location = 0.5
        body = 0.0
        upper = 0.0
        lower = 0.0
    range_pct = ratio(span, bar.close)
    weights = params.signal_bar
    is_bull = bar.close > bar.open
    is_bear = bar.close < bar.open
    if side is Side.LONG:
        base = weights.close_location * close_location + weights.body * body + weights.wick * (1.0 - upper)
        subscore = base if is_bull else base * weights.against_bar_factor
    elif side is Side.SHORT:
        base = weights.close_location * (1.0 - close_location) + weights.body * body + weights.wick * (1.0 - lower)
        subscore = base if is_bear else base * weights.against_bar_factor
    else:
        subscore = 0.0
    penalty = weights.doji_penalty if range_pct < weights.doji_range_pct else 0.0
    if signal is None:
        subscore = 0.0
    return SignalBarFeatures(
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        range=span,
        range_pct=range_pct,
        close_location=close_location,
        body_ratio=body,
        upper_wick_ratio=upper,
        lower_wick_ratio=lower,
        is_bull=is_bull,
        is_bear=is_bear,
        subscore=subscore,
        penalty=penalty,
        skip=False,
    )
