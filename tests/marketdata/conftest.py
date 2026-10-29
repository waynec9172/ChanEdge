from __future__ import annotations

from datetime import datetime, timezone

import pytest

from chanedge.domain.bars import Bar, timeframe_duration
from chanedge.domain.enums import Timeframe

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def make_bar():
    return _make_bar


def _make_bar(**overrides: object) -> Bar:
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
