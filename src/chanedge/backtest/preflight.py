"""Count the closed bars a backtest can see at history_start. Pure counting, no I/O of its own."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone

from chanedge.domain.bars import Bar
from chanedge.domain.enums import Timeframe


def bar_shortfalls(
    load: Callable[[str, Timeframe], Sequence[Bar]],
    symbols: Sequence[str],
    *,
    history_start: date,
    windows: Mapping[Timeframe, int],
) -> dict[str, dict[Timeframe, tuple[int, int]]]:
    """Return {symbol: {timeframe: (have, need)}} for symbols short of bars; only short timeframes appear.

    have counts closed bars whose close_time is at or before history_start 00:00:00Z.
    """
    cutoff = datetime(history_start.year, history_start.month, history_start.day, tzinfo=timezone.utc)
    short: dict[str, dict[Timeframe, tuple[int, int]]] = {}
    for symbol in symbols:
        lacking: dict[Timeframe, tuple[int, int]] = {}
        for timeframe, need in windows.items():
            have = sum(1 for bar in load(symbol, timeframe) if bar.is_closed and bar.close_time <= cutoff)
            if have < need:
                lacking[timeframe] = (have, need)
        if lacking:
            short[symbol] = lacking
    return short
