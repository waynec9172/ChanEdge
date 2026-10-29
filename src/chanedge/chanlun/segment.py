"""Minimal-break segments. The default engine path does not call this."""

from __future__ import annotations

from typing import Sequence

from chanedge.domain.chanlun import Bi, Segment
from chanedge.domain.enums import Direction, Timeframe
from chanedge.domain.ids import seg_id


def minimal_break(bis: Sequence[Bi], timeframe: Timeframe) -> tuple[Segment, ...]:
    """At least three bis. An up segment ends when a later down bi undercuts the previous down low."""
    found: list[Segment] = []
    start = 0
    count = len(bis)
    while start + 2 < count:
        direction = bis[start].direction
        previous_down: float | None = None
        previous_up: float | None = None
        end = start
        breaker: int | None = None
        for index in range(start, count):
            bi = bis[index]
            if direction is Direction.UP and bi.direction is Direction.DOWN:
                if previous_down is not None and bi.low < previous_down and index >= start + 3:
                    breaker = index
                    break
                previous_down = bi.low
            elif direction is Direction.DOWN and bi.direction is Direction.UP:
                if previous_up is not None and bi.high > previous_up and index >= start + 3:
                    breaker = index
                    break
                previous_up = bi.high
            end = index
        if end - start + 1 < 3:
            start += 1
            continue
        found.append(_segment(bis[start : end + 1], direction, timeframe))
        if breaker is None:
            break
        start = breaker
    return tuple(found)


def _segment(chunk: Sequence[Bi], direction: Direction, timeframe: Timeframe) -> Segment:
    high = max(bi.high for bi in chunk)
    low = min(bi.low for bi in chunk)
    start = chunk[0]
    end = chunk[-1]
    return Segment(
        id=seg_id(timeframe, direction, start.start_time, end.end_time, high, low),
        timeframe=timeframe,
        direction=direction,
        start_bi_id=start.id,
        end_bi_id=end.id,
        start_time=start.start_time,
        end_time=end.end_time,
        high=high,
        low=low,
        bi_ids=tuple(bi.id for bi in chunk),
        confirmed=True,
        algo="minimal_break",
    )
