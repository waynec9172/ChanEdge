"""Top-20 universe files. Existing final names are never overwritten.

Writes land on a sibling *.tmp and then os.replace. A busy replace is retried
up to 5 times. A final file that is not JSON is refused and left in place.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.domain.canon import format_fixed8, format_time_z
from chanedge.marketdata.vision import DailyQuote, ranking_open_time

_UTC = timezone.utc
_DAY = timedelta(days=1)
_SOURCES = ("reconstructed", "daily_kline")


class UniverseFileError(ValueError):
    """The final file exists and cannot be used. Do not overwrite it."""


class UniverseTooSmall(ValueError):
    def __init__(self, found: int, needed: int) -> None:
        super().__init__(f"universe has {found} names after filters, need {needed}")
        self.found = found
        self.needed = needed


@dataclass(frozen=True)
class UniverseMember:
    rank: int
    symbol: str
    venue_symbol: str
    quote_volume: Decimal
    as_of: datetime
    source: str
    bar_open_time: datetime
    bar_close_time: datetime
    fallback_from: date | None


@dataclass(frozen=True)
class WriteResult:
    path: Path
    written: bool


@dataclass(frozen=True)
class FallbackResult:
    path: Path
    written: bool
    error: str
    previous_missing: bool


def atomic_replace(
    path: Path,
    data: bytes,
    *,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
    pause_seconds: float = 0.05,
) -> None:
    """Write path.name.tmp, then replace the final name. Existence is the caller's check.

    OSError is retried. After `attempts` failures the error is raised and the
    tmp file is not renamed to the final name by any other means.
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be an int >= 1")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            replace(tmp, path)
            return
        except OSError as exc:
            last = exc
            if attempt + 1 == attempts:
                break
            sleep(pause_seconds)
    assert last is not None
    raise last


def universe_path(root: Path, venue: str, file_date: date) -> Path:
    return root / "data" / "universe" / venue / f"{file_date.isoformat()}.json"


def universe_date(decision_time: datetime, refresh_minute: int) -> date:
    """UTC date of decision_time minus refresh_minute. Not decision_time.date()."""
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    if isinstance(refresh_minute, bool) or not isinstance(refresh_minute, int):
        raise TypeError("refresh_minute must be an int")
    utc = decision_time.astimezone(_UTC)
    return (utc - timedelta(minutes=refresh_minute)).date()


def symbol_allowed(compact_symbol: str, exclude_bases: Sequence[str]) -> bool:
    """USDT suffix, no underscore, base not in exclude_bases."""
    if "_" in compact_symbol or not compact_symbol.endswith("USDT"):
        return False
    base = compact_symbol[: -len("USDT")]
    if base == "" or base in exclude_bases:
        return False
    return True


def compact_to_symbols(compact_symbol: str) -> tuple[str, str]:
    """BTCUSDT -> (BTC/USDT, BTC/USDT:USDT)."""
    if not compact_symbol.endswith("USDT") or "_" in compact_symbol:
        raise ValueError(f"not a USDT perp symbol: {compact_symbol}")
    base = compact_symbol[: -len("USDT")]
    symbol = f"{base}/USDT"
    return symbol, f"{symbol}:USDT"


def select_universe(
    quotes: Sequence[DailyQuote],
    *,
    file_date: date,
    size: int,
    exclude_bases: Sequence[str],
    require_positive_min_qty: bool,
) -> tuple[tuple[str, str, DailyQuote], ...]:
    """Rank the (D-1) 00:00:00Z daily bar. Fewer than `size` names raises.

    require_positive_min_qty is the paper freeze. Reconstruct leaves it false
    so a name whose spec is not inferred yet can still be listed.
    """
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("size must be an int >= 1")
    open_time = ranking_open_time(file_date)
    best: dict[str, DailyQuote] = {}
    for quote in quotes:
        if quote.open_time != open_time:
            continue
        if not symbol_allowed(quote.compact_symbol, exclude_bases):
            continue
        if quote.quote_volume is None or quote.quote_volume <= 0:
            continue
        if require_positive_min_qty and (quote.min_qty is None or quote.min_qty <= 0):
            continue
        current = best.get(quote.compact_symbol)
        if current is None or (current.quote_volume or Decimal(0)) < quote.quote_volume:
            best[quote.compact_symbol] = quote
    if len(best) < size:
        raise UniverseTooSmall(len(best), size)
    ordered = sorted(best.values(), key=lambda quote: (-(quote.quote_volume or Decimal(0)), _symbol(quote)))
    ranked: list[tuple[str, str, DailyQuote]] = []
    for quote in ordered[:size]:
        symbol, venue_symbol = compact_to_symbols(quote.compact_symbol)
        ranked.append((symbol, venue_symbol, quote))
    return tuple(ranked)


def members_from_selection(
    selected: Sequence[tuple[str, str, DailyQuote]],
    *,
    source: str,
    as_of: datetime,
    fallback_from: date | None = None,
) -> tuple[UniverseMember, ...]:
    if source not in _SOURCES:
        raise ValueError("source must be reconstructed or daily_kline")
    _require_aware(as_of)
    members: list[UniverseMember] = []
    for rank, (symbol, venue_symbol, quote) in enumerate(selected, start=1):
        assert quote.quote_volume is not None
        members.append(
            UniverseMember(
                rank=rank,
                symbol=symbol,
                venue_symbol=venue_symbol,
                quote_volume=quote.quote_volume,
                as_of=as_of,
                source=source,
                bar_open_time=quote.open_time,
                bar_close_time=quote.open_time + _DAY,
                fallback_from=fallback_from,
            )
        )
    return tuple(members)


def write_universe_file(
    path: Path,
    members: Sequence[UniverseMember],
    *,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 5,
) -> WriteResult:
    """Skip when the final name already exists, whatever is inside it."""
    if path.exists():
        return WriteResult(path=path, written=False)
    payload = _dump_members(members)
    atomic_replace(path, payload, replace=replace, sleep=sleep, attempts=attempts)
    return WriteResult(path=path, written=True)


def load_universe(path: Path) -> tuple[UniverseMember, ...]:
    """Refuse a file that is not valid JSON. The file is not rewritten."""
    hint = f"{path} 不是合法的 JSON。先刪掉該檔，再跑 universe --reconstruct。"
    try:
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise UniverseFileError(hint) from exc
    if not isinstance(payload, list):
        raise UniverseFileError(hint)
    members: list[UniverseMember] = []
    for item in payload:
        try:
            members.append(_member_from_json(item))
        except (KeyError, TypeError, ValueError) as exc:
            raise UniverseFileError(hint) from exc
    members.sort(key=lambda member: member.rank)
    return tuple(members)


def reconstruct_dates(
    root: Path,
    venue: str,
    dates: Sequence[date],
    quotes_by_date: Mapping[date, Sequence[DailyQuote]],
    *,
    size: int,
    exclude_bases: Sequence[str],
    as_of: datetime,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    """Write only dates whose final file is absent. New files are source reconstructed.

    Returns (written, skipped). An existing daily_kline, fallback, or reconstructed
    file is skipped. The caller passes quotes; this does not download.
    """
    written: list[date] = []
    skipped: list[date] = []
    for file_date in dates:
        path = universe_path(root, venue, file_date)
        if path.exists():
            skipped.append(file_date)
            continue
        selected = select_universe(
            quotes_by_date.get(file_date, ()),
            file_date=file_date,
            size=size,
            exclude_bases=exclude_bases,
            require_positive_min_qty=False,
        )
        members = members_from_selection(selected, source="reconstructed", as_of=as_of)
        result = write_universe_file(path, members, replace=replace, sleep=sleep)
        if result.written:
            written.append(file_date)
        else:
            skipped.append(file_date)
    return tuple(written), tuple(skipped)


def write_fallback(
    root: Path,
    venue: str,
    file_date: date,
    *,
    as_of: datetime,
    error: str,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
) -> FallbackResult:
    """Copy yesterday's ranks. source stays as copied. fallback_from is yesterday.

    The error is returned to the caller. It is not a JSON field. Today's file,
    if it already exists, is left alone. A missing yesterday does not invent a board.
    """
    path = universe_path(root, venue, file_date)
    if path.exists():
        return FallbackResult(path=path, written=False, error=error, previous_missing=False)
    previous = file_date - _DAY
    previous_path = universe_path(root, venue, previous)
    if not previous_path.exists():
        return FallbackResult(path=path, written=False, error=error, previous_missing=True)
    copied = tuple(
        UniverseMember(
            rank=member.rank,
            symbol=member.symbol,
            venue_symbol=member.venue_symbol,
            quote_volume=member.quote_volume,
            as_of=as_of,
            source=member.source,
            bar_open_time=member.bar_open_time,
            bar_close_time=member.bar_close_time,
            fallback_from=previous,
        )
        for member in load_universe(previous_path)
    )
    write_universe_file(path, copied, replace=replace, sleep=sleep)
    return FallbackResult(path=path, written=True, error=error, previous_missing=False)


def _symbol(quote: DailyQuote) -> str:
    return compact_to_symbols(quote.compact_symbol)[0]


def _dump_members(members: Sequence[UniverseMember]) -> bytes:
    payload = [_member_to_json(member) for member in members]
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


def _member_to_json(member: UniverseMember) -> dict[str, object]:
    return {
        "rank": member.rank,
        "symbol": member.symbol,
        "venue_symbol": member.venue_symbol,
        "quote_volume": format_fixed8(member.quote_volume),
        "as_of": format_time_z(member.as_of),
        "source": member.source,
        "bar_open_time": format_time_z(member.bar_open_time),
        "bar_close_time": format_time_z(member.bar_close_time),
        "fallback_from": None if member.fallback_from is None else member.fallback_from.isoformat(),
    }


def _member_from_json(item: object) -> UniverseMember:
    if not isinstance(item, dict):
        raise TypeError("member must be an object")
    source = item["source"]
    if source not in _SOURCES:
        raise ValueError("unknown source")
    fallback = item["fallback_from"]
    fallback_from = None if fallback is None else date.fromisoformat(str(fallback))
    volume = item["quote_volume"]
    if isinstance(volume, bool) or not isinstance(volume, (str, int, float)):
        raise TypeError("quote_volume")
    if isinstance(volume, float):
        quote_volume = Decimal(format_fixed8(volume))
    elif isinstance(volume, int):
        quote_volume = Decimal(volume)
    else:
        quote_volume = Decimal(volume)
    return UniverseMember(
        rank=int(item["rank"]),
        symbol=str(item["symbol"]),
        venue_symbol=str(item["venue_symbol"]),
        quote_volume=quote_volume,
        as_of=_parse_time(str(item["as_of"])),
        source=str(source),
        bar_open_time=_parse_time(str(item["bar_open_time"])),
        bar_close_time=_parse_time(str(item["bar_close_time"])),
        fallback_from=fallback_from,
    )


def _parse_time(text: str) -> datetime:
    if not text.endswith("Z"):
        raise ValueError("time must end with Z")
    parsed = datetime.strptime(text[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=_UTC)
    return parsed


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
