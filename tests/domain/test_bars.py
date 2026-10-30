from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from chanedge.domain.bars import Bar, open_time_is_aligned, timeframe_duration
from chanedge.domain.enums import Timeframe

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def make_bar(**overrides: object) -> Bar:
    timeframe = overrides.pop("timeframe", Timeframe.M15)
    assert isinstance(timeframe, Timeframe)
    open_time = overrides.pop("open_time", T0)
    assert isinstance(open_time, datetime)
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": open_time + timeframe_duration(timeframe),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1.0,
        "is_closed": True,
        "source": "binanceusdm",
    }
    values.update(overrides)
    return Bar(**values)


def test_volume_zero_bar_builds_and_windows_are_slices() -> None:
    first = make_bar(volume=0, quote_volume=0, trades=0)
    second = make_bar(open_time=T0 + timedelta(minutes=15))
    third = make_bar(open_time=T0 + timedelta(minutes=30))
    built = (first, second, third)
    window = built[1:]
    assert window[0] is second
    assert isinstance(window, tuple)
    assert first.volume == 0


def test_bar_rejects_bad_prices_volume_and_time() -> None:
    with pytest.raises(ValidationError):
        make_bar(volume=-1)
    with pytest.raises(ValidationError):
        make_bar(low=0, open=0, close=0, high=0)
    with pytest.raises(ValidationError):
        make_bar(low=-1, open=-1, close=-1, high=-1)
    with pytest.raises(ValidationError):
        make_bar(high=100)
    with pytest.raises(ValidationError):
        make_bar(quote_volume=-1)
    with pytest.raises(ValidationError):
        make_bar(open_time=T0 + timedelta(minutes=7))
    with pytest.raises(ValidationError):
        make_bar(close_time=T0 + timedelta(minutes=14))
    with pytest.raises(ValidationError):
        make_bar(open_time=datetime(2024, 1, 1, 0, 0), close_time=datetime(2024, 1, 1, 0, 15))
    with pytest.raises(ValidationError):
        make_bar(open=float("nan"))
    hour = make_bar(timeframe=Timeframe.H1, open_time=datetime(2024, 1, 1, 1, 0, tzinfo=UTC))
    assert hour.close_time == datetime(2024, 1, 1, 2, 0, tzinfo=UTC)
    four = make_bar(timeframe=Timeframe.H4, open_time=datetime(2024, 1, 1, 4, 0, tzinfo=UTC))
    assert four.close_time == datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        make_bar(timeframe=Timeframe.H4, open_time=datetime(2024, 1, 1, 1, 0, tzinfo=UTC))
    assert open_time_is_aligned(T0, Timeframe.M15)
    with pytest.raises(ValueError):
        open_time_is_aligned(datetime(2024, 1, 1, 0, 0), Timeframe.M15)


def test_window_line_is_cached_and_a_copy_with_new_prices_recomputes() -> None:
    bar = make_bar()
    line = bar.window_line()
    assert line.startswith("2024-01-01T00:00:00.000Z|")
    assert bar.window_line() is line
    assert "window_line" not in bar.model_dump()
    moved = bar.model_copy(update={"close": bar.close + 0.5, "high": bar.high + 0.5})
    assert moved.window_line() != line
    assert moved.window_line().split("|")[4] == f"{moved.close:.8f}"


def test_bar_windows_skip_revalidation_only_for_real_bars() -> None:
    from chanedge.domain.decision import ChartFrame
    from chanedge.domain.enums import DecisionAction, StructureBias

    bar = make_bar()
    fields = dict(
        symbol=bar.symbol, timeframe=Timeframe.M15, as_of=bar.close_time, snapshot_id="cs_0123456789abcdef",
        structure_bias=StructureBias.UP, bis=(), zhongshus=(), signals=(), last_action=DecisionAction.HOLD,
    )
    assert ChartFrame(bars=(bar,), **fields).bars == (bar,)
    from_dict = ChartFrame(bars=[bar.model_dump()], **fields)
    assert from_dict.bars == (bar,)
    with pytest.raises(ValidationError):
        ChartFrame(bars=[{**bar.model_dump(), "low": -1.0}], **fields)
    with pytest.raises(ValidationError):
        ChartFrame(bars=["not a bar"], **fields)
