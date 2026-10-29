"""Inclusive kline merge. One left-to-right pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from chanedge.domain.bars import Bar
from chanedge.domain.enums import Direction


@dataclass(frozen=True)
class MergedBar:
    high: float
    low: float
    raw_start: int
    raw_end: int


def include_merge(bars: Sequence[Bar]) -> tuple[MergedBar, ...]:
    """Merge contained bars. No non-inclusive pair means no later fenxing."""
    if not bars:
        return ()
    direction = _initial_direction(bars)
    if direction is None:
        direction = Direction.UP
    current = MergedBar(bars[0].high, bars[0].low, 0, 0)
    merged: list[MergedBar] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        if _overlaps_inclusive(current, bar.high, bar.low):
            current = _combine(current, bar.high, bar.low, index, direction)
            continue
        merged.append(current)
        if bar.high > current.high and bar.low > current.low:
            direction = Direction.UP
        elif bar.high < current.high and bar.low < current.low:
            direction = Direction.DOWN
        current = MergedBar(bar.high, bar.low, index, index)
    merged.append(current)
    return tuple(merged)


def _initial_direction(bars: Sequence[Bar]) -> Direction | None:
    for index in range(len(bars) - 1):
        left = bars[index]
        right = bars[index + 1]
        if _contains(left.high, left.low, right.high, right.low) or _contains(
            right.high, right.low, left.high, left.low
        ):
            continue
        if right.high > left.high:
            return Direction.UP
        return Direction.DOWN
    return None


def _overlaps_inclusive(current: MergedBar, high: float, low: float) -> bool:
    return _contains(current.high, current.low, high, low) or _contains(
        high, low, current.high, current.low
    )


def _contains(high_a: float, low_a: float, high_b: float, low_b: float) -> bool:
    return high_a >= high_b and low_a <= low_b


def _combine(current: MergedBar, high: float, low: float, index: int, direction: Direction) -> MergedBar:
    if direction is Direction.UP:
        return MergedBar(max(current.high, high), max(current.low, low), current.raw_start, index)
    return MergedBar(min(current.high, high), min(current.low, low), current.raw_start, index)
