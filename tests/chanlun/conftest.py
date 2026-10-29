"""PR-5 fixtures. Pytest injects these; tests do not import this module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chanedge.domain.bars import Bar, timeframe_duration
from chanedge.domain.enums import Timeframe

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ORIGIN = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars_from_prices(
    prices: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    closes: list[float] | None = None,
    timeframe: Timeframe = Timeframe.M15,
) -> tuple[Bar, ...]:
    """Single-price bars unless a column is passed. open_time steps by the timeframe."""
    count = len(prices)
    columns = {"high": highs, "low": lows, "open": opens, "close": closes}
    for name, column in columns.items():
        if column is not None and len(column) != count:
            raise ValueError(f"{name} length does not match prices")
    step = timeframe_duration(timeframe)
    bars: list[Bar] = []
    for index, price in enumerate(prices):
        open_time = ORIGIN + step * index
        bars.append(
            Bar(
                symbol="BTC/USDT",
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + step,
                open=price if opens is None else opens[index],
                high=price if highs is None else highs[index],
                low=price if lows is None else lows[index],
                close=price if closes is None else closes[index],
                volume=1.0,
                is_closed=True,
                source="binanceusdm",
            )
        )
    return tuple(bars)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def bars_from_prices():
    return _bars_from_prices


@pytest.fixture
def load_fixture():
    return _load_fixture


@pytest.fixture
def config_hash() -> str:
    return "a" * 64
