"""Local vision CSV paths, warmup, and bar lines. No HTTP.

Monthly klines are preferred. A month that has no monthly file uses the daily
files. A missing file is an empty read, not a fabricated bar. Funding months
that are absent are reported missing and do not raise.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from chanedge.domain.bars import Bar, timeframe_duration
from chanedge.domain.canon import format_fixed8, format_time_z
from chanedge.domain.enums import Timeframe
from chanedge.marketdata.infer import is_plain_number

_UTC = timezone.utc
_DAY = timedelta(days=1)

INTERVALS = ("15m", "1h", "4h", "1d")


@dataclass(frozen=True)
class StoredBar:
    """A Bar plus the window line computed when the bar entered memory."""

    bar: Bar
    window_line: str


@dataclass(frozen=True)
class DailyQuote:
    """One daily ranking row. Not a Bar and not a Timeframe."""

    compact_symbol: str
    open_time: datetime
    quote_volume: Decimal | None
    min_qty: Decimal | None = None


@dataclass(frozen=True)
class FundingRow:
    calc_time: datetime
    last_funding_rate: Decimal


@dataclass(frozen=True)
class FundingMonth:
    path: Path
    missing: bool
    rows: tuple[FundingRow, ...]


def bar_window_line(bar: Bar) -> str:
    """open_time|open|high|low|close|volume using the canonical formatters."""
    return "|".join(
        (
            format_time_z(bar.open_time),
            format_fixed8(bar.open),
            format_fixed8(bar.high),
            format_fixed8(bar.low),
            format_fixed8(bar.close),
            format_fixed8(bar.volume),
        )
    )


def bar_window_hash(lines: Sequence[str]) -> str:
    """sha256 hex of the lines joined by newline. No prefix."""
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def store_bar(bar: Bar) -> StoredBar:
    return StoredBar(bar=bar, window_line=bar_window_line(bar))


def warmup_open(history_start: date, timeframe: Timeframe, window: int) -> datetime:
    """Open time of the bar that closes at history_start 00:00:00Z, minus window-1 bars."""
    if isinstance(history_start, datetime):
        raise TypeError("history_start must be a date")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("window must be an int >= 1")
    duration = timeframe_duration(timeframe)
    midnight = datetime(history_start.year, history_start.month, history_start.day, tzinfo=_UTC)
    closes_at_midnight = midnight - duration
    return closes_at_midnight - duration * (window - 1)


def download_start(history_start: date, windows: Mapping[Timeframe, int]) -> datetime:
    """Earliest warmup_open across the three timeframes."""
    if not windows:
        raise ValueError("windows must not be empty")
    return min(warmup_open(history_start, timeframe, window) for timeframe, window in windows.items())


def ranking_open_time(file_date: date) -> datetime:
    """File date D ranks the daily bar whose open_time is (D-1) 00:00:00Z."""
    midnight = datetime(file_date.year, file_date.month, file_date.day, tzinfo=_UTC)
    return midnight - _DAY


def monthly_kline_csv(root: Path, symbol: str, interval: str, year: int, month: int) -> Path:
    _check_interval(interval)
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.csv"
    return root / "data" / "futures" / "um" / "monthly" / "klines" / symbol / interval / name


def daily_kline_csv(root: Path, symbol: str, interval: str, day: date) -> Path:
    _check_interval(interval)
    name = f"{symbol}-{interval}-{day.year:04d}-{day.month:02d}-{day.day:02d}.csv"
    return root / "data" / "futures" / "um" / "daily" / "klines" / symbol / interval / name


def funding_month_csv(root: Path, symbol: str, year: int, month: int) -> Path:
    name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.csv"
    return root / "data" / "futures" / "um" / "monthly" / "fundingRate" / symbol / name


def kline_files_for_month(root: Path, symbol: str, interval: str, year: int, month: int) -> tuple[Path, ...]:
    """Monthly file when it exists. Otherwise the daily files of that month. Never invents a path's rows."""
    monthly = monthly_kline_csv(root, symbol, interval, year, month)
    if monthly.is_file():
        return (monthly,)
    folder = root / "data" / "futures" / "um" / "daily" / "klines" / symbol / interval
    if not folder.is_dir():
        return ()
    pattern = f"{symbol}-{interval}-{year:04d}-{month:02d}-*.csv"
    return tuple(sorted(path for path in folder.glob(pattern) if path.is_file()))


def read_funding_month(path: Path) -> FundingMonth:
    """A missing month is missing=True and does not raise."""
    if not path.is_file():
        return FundingMonth(path=path, missing=True, rows=())
    text = path.read_text(encoding="utf-8")
    return FundingMonth(path=path, missing=False, rows=tuple(_parse_funding(text)))


def parse_kline_csv(
    text: str,
    *,
    symbol: str,
    timeframe: Timeframe,
    source: str,
    clock: datetime,
) -> tuple[StoredBar, ...]:
    """Build bars from CSV text. close_time is open_time plus the timeframe, not the CSV millisecond."""
    _require_aware(clock)
    stored: list[StoredBar] = []
    for row_number, row in enumerate(_rows(text), start=1):
        if len(row) <= 7:
            raise ValueError(f"kline row {row_number} is short")
        open_time = utc_from_millis(int(row[0]))
        duration = timeframe_duration(timeframe)
        close_time = open_time + duration
        bar = Bar(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time,
            close_time=close_time,
            open=_float_token(row[1], row_number, "open"),
            high=_float_token(row[2], row_number, "high"),
            low=_float_token(row[3], row_number, "low"),
            close=_float_token(row[4], row_number, "close"),
            volume=_float_token(row[5], row_number, "volume"),
            quote_volume=_optional_float(row[7]) if len(row) > 7 else None,
            trades=_optional_trades(row[8]) if len(row) > 8 else None,
            is_closed=close_time <= clock,
            source=source,
        )
        stored.append(store_bar(bar))
    return tuple(stored)


def parse_daily_csv(text: str, *, compact_symbol: str) -> tuple[DailyQuote, ...]:
    """quote_volume stays a Decimal taken from the text. The CSV close_time is not the next open."""
    quotes: list[DailyQuote] = []
    for row in _rows(text):
        if len(row) <= 7:
            continue
        open_time = utc_from_millis(int(row[0]))
        quotes.append(
            DailyQuote(
                compact_symbol=compact_symbol,
                open_time=open_time,
                quote_volume=_quote_token(row[7]),
                min_qty=None,
            )
        )
    return tuple(quotes)


def read_klines_for_month(
    root: Path,
    compact_symbol: str,
    interval: str,
    year: int,
    month: int,
    *,
    symbol: str,
    source: str,
    clock: datetime,
) -> tuple[StoredBar, ...]:
    """Read the month. No files means an empty tuple. Forming bars are left out."""
    if interval == "1d":
        raise ValueError("daily klines are not bars")
    timeframe = _timeframe(interval)
    found: dict[datetime, StoredBar] = {}
    for path in kline_files_for_month(root, compact_symbol, interval, year, month):
        text = path.read_text(encoding="utf-8")
        for item in parse_kline_csv(text, symbol=symbol, timeframe=timeframe, source=source, clock=clock):
            if not item.bar.is_closed:
                continue
            found[item.bar.open_time] = item
    return tuple(found[key] for key in sorted(found))


def read_daily_for_month(
    root: Path,
    compact_symbol: str,
    year: int,
    month: int,
) -> tuple[DailyQuote, ...]:
    found: dict[datetime, DailyQuote] = {}
    for path in kline_files_for_month(root, compact_symbol, "1d", year, month):
        text = path.read_text(encoding="utf-8")
        for quote in parse_daily_csv(text, compact_symbol=compact_symbol):
            found[quote.open_time] = quote
    return tuple(found[key] for key in sorted(found))


def utc_from_millis(millis: int) -> datetime:
    if isinstance(millis, bool) or not isinstance(millis, int):
        raise TypeError("millis must be an int")
    seconds, milli = divmod(millis, 1000)
    return datetime.fromtimestamp(seconds, tz=_UTC) + timedelta(milliseconds=milli)


def _quote_token(token: str) -> Decimal | None:
    text = token.strip()
    if not is_plain_number(text):
        return None
    return Decimal(text)


def _float_token(token: str, row_number: int, name: str) -> float:
    text = token.strip()
    if not is_plain_number(text):
        raise ValueError(f"kline row {row_number} {name} is not a number")
    return float(Decimal(text))


def _optional_float(token: str) -> float | None:
    text = token.strip()
    if text == "" or not is_plain_number(text):
        return None
    return float(Decimal(text))


def _optional_trades(token: str) -> int | None:
    text = token.strip()
    if text == "":
        return None
    if not text.isdigit():
        raise ValueError("trades must be an integer")
    return int(text)


def _rows(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    rows: list[list[str]] = []
    for raw in reader:
        cells = [cell.strip() for cell in raw]
        if not cells or all(cell == "" for cell in cells):
            continue
        if not cells[0].isdigit():
            continue
        rows.append(cells)
    return rows


def _parse_funding(text: str) -> list[FundingRow]:
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    rows = list(reader)
    if not rows:
        return []
    header = [cell.strip() for cell in rows[0]]
    if "calc_time" in header and "last_funding_rate" in header:
        time_index = header.index("calc_time")
        rate_index = header.index("last_funding_rate")
        body = rows[1:]
    else:
        time_index = 0
        rate_index = 1
        body = rows
    parsed: list[FundingRow] = []
    for raw in body:
        cells = [cell.strip() for cell in raw]
        if len(cells) <= max(time_index, rate_index) or cells[time_index] == "":
            continue
        if not cells[time_index].isdigit():
            continue
        rate = cells[rate_index]
        if not is_plain_number(rate):
            continue
        parsed.append(
            FundingRow(
                calc_time=utc_from_millis(int(cells[time_index])),
                last_funding_rate=Decimal(rate),
            )
        )
    return parsed


def _timeframe(interval: str) -> Timeframe:
    if interval == Timeframe.M15.value:
        return Timeframe.M15
    if interval == Timeframe.H1.value:
        return Timeframe.H1
    if interval == Timeframe.H4.value:
        return Timeframe.H4
    raise ValueError(f"interval {interval} is not a bar timeframe")


def _check_interval(interval: str) -> None:
    if interval not in INTERVALS:
        raise ValueError(f"unknown interval {interval}")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
