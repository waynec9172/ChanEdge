"""bar_shortfalls counts closed bars at or before history_start 00:00Z."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from chanedge.backtest.preflight import bar_shortfalls
from chanedge.domain.bars import Bar, timeframe_duration
from chanedge.domain.enums import Timeframe

CUTOFF = datetime(2024, 1, 1, tzinfo=timezone.utc)
START = date(2024, 1, 1)
WINDOWS = {Timeframe.M15: 3, Timeframe.H1: 2, Timeframe.H4: 1}


def _bar(symbol: str, timeframe: Timeframe, close: datetime, *, closed: bool = True) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=close - timeframe_duration(timeframe),
        close_time=close,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1.0,
        is_closed=closed,
        source="binanceusdm",
    )


def _series(symbol: str, timeframe: Timeframe, count: int, *, last_close: datetime = CUTOFF, closed: bool = True):
    step = timeframe_duration(timeframe)
    return [_bar(symbol, timeframe, last_close - step * i, closed=closed) for i in reversed(range(count))]


def _loader(data):
    return lambda symbol, timeframe: data.get((symbol, timeframe), ())


def _full(symbol: str) -> dict:
    return {(symbol, tf): _series(symbol, tf, need) for tf, need in WINDOWS.items()}


def test_enough_bars_means_no_shortfall() -> None:
    assert bar_shortfalls(_loader(_full("A")), ["A"], history_start=START, windows=WINDOWS) == {}


def test_bars_closing_after_the_cutoff_do_not_count() -> None:
    data = _full("A")
    data[("A", Timeframe.M15)] = _series("A", Timeframe.M15, 3, last_close=CUTOFF + timedelta(minutes=15))
    result = bar_shortfalls(_loader(data), ["A"], history_start=START, windows=WINDOWS)
    assert result == {"A": {Timeframe.M15: (2, 3)}}


def test_a_bar_closing_exactly_at_the_cutoff_counts() -> None:
    data = _full("A")
    assert data[("A", Timeframe.M15)][-1].close_time == CUTOFF
    assert bar_shortfalls(_loader(data), ["A"], history_start=START, windows=WINDOWS) == {}


def test_unclosed_bars_do_not_count() -> None:
    data = _full("A")
    data[("A", Timeframe.H4)] = _series("A", Timeframe.H4, 1, closed=False)
    result = bar_shortfalls(_loader(data), ["A"], history_start=START, windows=WINDOWS)
    assert result == {"A": {Timeframe.H4: (0, 1)}}


def test_only_the_short_timeframe_is_listed() -> None:
    data = _full("A")
    data[("A", Timeframe.H1)] = _series("A", Timeframe.H1, 1)
    result = bar_shortfalls(_loader(data), ["A", "B"], history_start=START, windows=WINDOWS)
    assert result["A"] == {Timeframe.H1: (1, 2)}
    assert list(result) == ["A", "B"]
    assert result["B"] == {Timeframe.M15: (0, 3), Timeframe.H1: (0, 2), Timeframe.H4: (0, 1)}


def test_no_symbols_means_no_shortfall() -> None:
    assert bar_shortfalls(_loader({}), [], history_start=START, windows=WINDOWS) == {}
