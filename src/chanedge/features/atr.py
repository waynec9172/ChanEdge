"""One Wilder ATR. Risk reads the value copied onto the feature vector."""

from __future__ import annotations

from collections.abc import Sequence

from chanedge.domain.bars import Bar
from chanedge.features.mathutil import ratio


def wilder_atr(bars: Sequence[Bar], period: int) -> list[float | None]:
    """ATR aligned to bars. The first bar has no TR. The seed sits on bar `period`."""
    values: list[float | None] = [None] * len(bars)
    if period < 1 or len(bars) <= period:
        return values
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        current = bars[index]
        previous_close = bars[index - 1].close
        true_range = max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        )
        true_ranges.append(true_range)
        if index < period:
            continue
        if index == period:
            values[index] = sum(true_ranges[:period]) / period
            continue
        previous = values[index - 1]
        if previous is None:
            continue
        values[index] = (previous * (period - 1) + true_range) / period
    return values


def atr_pct(atr: float, close: float) -> float:
    return ratio(atr, close)
