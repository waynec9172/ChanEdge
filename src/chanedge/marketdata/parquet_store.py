"""Closed-bar Parquet. A file that does not open is an error, not an empty store.

The window line is computed when a bar is read back into memory. The file does
not store that line. Rewrites go through a sibling tmp and os.replace.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from chanedge.domain.bars import Bar
from chanedge.domain.enums import Timeframe
from chanedge.marketdata.universe import atomic_replace
from chanedge.marketdata.vision import StoredBar, store_bar

_UTC = timezone.utc

_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("timeframe", pa.string(), nullable=False),
        pa.field("open_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("close_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
        pa.field("quote_volume", pa.float64(), nullable=True),
        pa.field("trades", pa.int64(), nullable=True),
        pa.field("is_closed", pa.bool_(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
    ]
)


class ParquetUnreadable(ValueError):
    """The final file exists and cannot be opened. Do not treat it as empty."""


class ParquetBarStore:
    def __init__(
        self,
        root: Path,
        *,
        replace: Callable[[str | Path, str | Path], None] = os.replace,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 5,
    ) -> None:
        self._root = root
        self._replace = replace
        self._sleep = sleep
        self._attempts = attempts

    def path(self, venue: str, symbol: str, timeframe: Timeframe) -> Path:
        return self._root / "data" / "bars" / venue / symbol / f"{timeframe.value}.parquet"

    def last_open_time(self, venue: str, symbol: str, timeframe: Timeframe) -> datetime | None:
        bars = self.read(venue, symbol, timeframe)
        if not bars:
            return None
        return bars[-1].bar.open_time

    def read(self, venue: str, symbol: str, timeframe: Timeframe) -> tuple[StoredBar, ...]:
        path = self.path(venue, symbol, timeframe)
        if not path.exists():
            return ()
        try:
            table = pq.read_table(path)
        except Exception as exc:
            raise ParquetUnreadable(f"{path} cannot be opened") from exc
        if table.num_rows == 0:
            return ()
        stored = [store_bar(_bar_from_row(row, timeframe)) for row in table.to_pylist()]
        stored.sort(key=lambda item: item.bar.open_time)
        return tuple(stored)

    def write_closed(
        self,
        venue: str,
        symbol: str,
        timeframe: Timeframe,
        incoming: Sequence[StoredBar],
    ) -> None:
        """Replace from the earliest incoming closed open_time, inclusive.

        Bars with is_closed false are not written. An incoming batch that has
        no closed bar leaves the file untouched.
        """
        closed = [item for item in incoming if item.bar.is_closed]
        if not closed:
            return
        path = self.path(venue, symbol, timeframe)
        existing = list(self.read(venue, symbol, timeframe)) if path.exists() else []
        start = min(item.bar.open_time for item in closed)
        by_open = {item.bar.open_time: item for item in existing if item.bar.open_time < start}
        for item in sorted(closed, key=lambda item: item.bar.open_time):
            by_open[item.bar.open_time] = item
        merged = [by_open[key] for key in sorted(by_open)]
        self._write(path, merged)

    def _write(self, path: Path, bars: Sequence[StoredBar]) -> None:
        table = pa.Table.from_pylist([_row_from_bar(item.bar) for item in bars], schema=_SCHEMA)
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        atomic_replace(
            path,
            sink.getvalue().to_pybytes(),
            replace=self._replace,
            sleep=self._sleep,
            attempts=self._attempts,
        )


def _row_from_bar(bar: Bar) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "timeframe": bar.timeframe.value,
        "open_time": bar.open_time.astimezone(_UTC),
        "close_time": bar.close_time.astimezone(_UTC),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "quote_volume": bar.quote_volume,
        "trades": bar.trades,
        "is_closed": bar.is_closed,
        "source": bar.source,
    }


def _bar_from_row(row: dict[str, object], timeframe: Timeframe) -> Bar:
    open_time = _aware(row["open_time"])
    close_time = _aware(row["close_time"])
    trades = row["trades"]
    return Bar(
        symbol=str(row["symbol"]),
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=float(row["open"]),  # type: ignore[arg-type]
        high=float(row["high"]),  # type: ignore[arg-type]
        low=float(row["low"]),  # type: ignore[arg-type]
        close=float(row["close"]),  # type: ignore[arg-type]
        volume=float(row["volume"]),  # type: ignore[arg-type]
        quote_volume=None if row["quote_volume"] is None else float(row["quote_volume"]),  # type: ignore[arg-type]
        trades=None if trades is None else int(trades),  # type: ignore[arg-type]
        is_closed=bool(row["is_closed"]),
        source=str(row["source"]),
    )


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("parquet time must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC)
