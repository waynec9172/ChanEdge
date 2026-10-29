"""Gaps and closed-bar windows. The engine is not called.

missing_bar_count sums every positive hole in the window. One hole is a gap
only when its own missing is greater than max_gap_bars. The sum is not the
threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from chanedge.domain.bars import Bar, DataQuality, timeframe_duration
from chanedge.domain.enums import Timeframe, VetoCode

_FIFTEEN = timedelta(minutes=15)


@dataclass(frozen=True)
class GapCheck:
    is_gap: bool
    missing_bar_count: int


def closed_window(bars: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    """Bars with is_closed and close_time <= as_of. An unclosed 4H stays out."""
    _require_aware(as_of)
    kept = [
        bar
        for bar in bars
        if bar.is_closed and bar.close_time <= as_of
    ]
    return tuple(sorted(kept, key=lambda bar: bar.open_time))


def measure_gaps(bars: Sequence[Bar], *, max_gap_bars: int) -> GapCheck:
    """Adjacent closed bars only. Unclosed bars in the sequence are ignored."""
    if isinstance(max_gap_bars, bool) or not isinstance(max_gap_bars, int):
        raise TypeError("max_gap_bars must be an int")
    if max_gap_bars < 0:
        raise ValueError("max_gap_bars must be >= 0")
    closed = sorted((bar for bar in bars if bar.is_closed), key=lambda bar: bar.open_time)
    if not closed:
        return GapCheck(is_gap=False, missing_bar_count=0)
    timeframe = closed[0].timeframe
    duration = timeframe_duration(timeframe)
    total = 0
    is_gap = False
    previous = closed[0]
    for bar in closed[1:]:
        if bar.timeframe is not timeframe:
            raise ValueError("gap check received mixed timeframes")
        delta = bar.open_time - previous.open_time
        if delta % duration != timedelta(0):
            raise ValueError("open_time gap is not a whole number of bars")
        missing = (delta // duration) - 1
        if missing < 0:
            raise ValueError("duplicate open_time")
        if missing > 0:
            total += missing
        if missing > max_gap_bars:
            is_gap = True
        previous = bar
    return GapCheck(is_gap=is_gap, missing_bar_count=total)


def is_stale(
    now: datetime,
    last_15m_close: datetime,
    *,
    stale_grace_seconds: int,
) -> bool:
    """now - last close > 15m + grace. Equality is not stale."""
    _require_aware(now)
    _require_aware(last_15m_close)
    if isinstance(stale_grace_seconds, bool) or not isinstance(stale_grace_seconds, int):
        raise TypeError("stale_grace_seconds must be an int")
    limit = _FIFTEEN + timedelta(seconds=stale_grace_seconds)
    return now - last_15m_close > limit


def assess_quality(
    windows: Mapping[Timeframe, Sequence[Bar]],
    *,
    max_gap_bars: Mapping[Timeframe, int],
    now: datetime | None = None,
    stale_grace_seconds: int = 90,
    backtest: bool = False,
) -> DataQuality:
    """Any of 15m, 1H, or 4H gapped records GAP_DATA. Backtest is never stale."""
    total = 0
    gap = False
    for timeframe, bars in windows.items():
        check = measure_gaps(bars, max_gap_bars=max_gap_bars[timeframe])
        total += check.missing_bar_count
        if check.is_gap:
            gap = True
    last_close = _last_15m_close(windows.get(Timeframe.M15, ()))
    stale = False
    if not backtest and now is not None and last_close is not None:
        stale = is_stale(now, last_close, stale_grace_seconds=stale_grace_seconds)
    reasons: list[str] = []
    if gap:
        reasons.append(VetoCode.GAP_DATA.value)
    if stale:
        reasons.append(VetoCode.STALE_DATA.value)
    recorded = max_gap_bars.get(Timeframe.M15, max(max_gap_bars.values()))
    return DataQuality(
        stale=stale,
        max_gap_bars=recorded,
        missing_bar_count=total,
        last_bar_close=last_close,
        exchange_time_skew_ms=None,
        reasons=tuple(reasons),
    )


def _last_15m_close(bars: Sequence[Bar]) -> datetime | None:
    closed = [bar for bar in bars if bar.is_closed and bar.timeframe is Timeframe.M15]
    if not closed:
        return None
    return max(closed, key=lambda bar: bar.open_time).close_time


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
