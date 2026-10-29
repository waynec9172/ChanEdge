"""Bars, instruments, and the multi-timeframe context. No I/O."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import model_validator

from chanedge.domain.chanlun import ChanSnapshot
from chanedge.domain.enums import InstrumentSource, ProductType, Timeframe
from chanedge.domain.model import AwareDatetime, DomainModel

_UTC = timezone.utc


def timeframe_duration(timeframe: Timeframe) -> timedelta:
    if timeframe is Timeframe.M15:
        return timedelta(minutes=15)
    if timeframe is Timeframe.H1:
        return timedelta(hours=1)
    if timeframe is Timeframe.H4:
        return timedelta(hours=4)
    raise ValueError(f"unknown timeframe {timeframe}")


def open_time_is_aligned(open_time: datetime, timeframe: Timeframe) -> bool:
    """True when open_time falls on that timeframe's UTC boundary."""
    if open_time.tzinfo is None or open_time.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return _aligned_utc(open_time.astimezone(_UTC), timeframe)


def _aligned_utc(utc: datetime, timeframe: Timeframe) -> bool:
    if utc.second != 0 or utc.microsecond != 0:
        return False
    if timeframe is Timeframe.M15:
        return utc.minute % 15 == 0
    if timeframe is Timeframe.H1:
        return utc.minute == 0
    if timeframe is Timeframe.H4:
        return utc.minute == 0 and utc.hour % 4 == 0
    return False


class Bar(DomainModel):
    symbol: str
    timeframe: Timeframe
    open_time: AwareDatetime
    close_time: AwareDatetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades: int | None = None
    is_closed: bool
    source: str

    @model_validator(mode="after")
    def check_ohlcv(self) -> Bar:
        for name in ("open", "high", "low", "close", "volume"):
            _require_finite(name, getattr(self, name))
        if self.quote_volume is not None:
            _require_finite("quote_volume", self.quote_volume)
            if self.quote_volume < 0:
                raise ValueError("quote_volume must be >= 0")
        if self.trades is not None and (isinstance(self.trades, bool) or self.trades < 0):
            raise ValueError("trades must be >= 0")
        if not self.low > 0:
            raise ValueError("low must be > 0")
        if self.volume < 0:
            raise ValueError("volume must be >= 0")
        if self.high < max(self.open, self.close):
            raise ValueError("high must cover open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must cover open and close")
        open_utc = self.open_time.astimezone(_UTC)
        close_utc = self.close_time.astimezone(_UTC)
        if not _aligned_utc(open_utc, self.timeframe):
            raise ValueError("open_time is not on the timeframe UTC boundary")
        if close_utc != open_utc + timeframe_duration(self.timeframe):
            raise ValueError("close_time must be open_time plus one timeframe")
        return self


class Instrument(DomainModel):
    symbol: str
    venue: str
    venue_symbol: str
    product: ProductType
    contract_size: Decimal
    price_tick: Decimal | None = None
    qty_step: Decimal | None = None
    min_qty: Decimal | None = None
    min_notional: Decimal | None = None
    margin_asset: str
    leverage_max: int
    instrument_source: InstrumentSource


class DataQuality(DomainModel):
    stale: bool
    max_gap_bars: int
    missing_bar_count: int
    last_bar_close: AwareDatetime | None = None
    exchange_time_skew_ms: int | None = None
    reasons: tuple[str, ...] = ()


class MultiTimeframeContext(DomainModel):
    context_id: str
    symbol: str
    decision_time: AwareDatetime
    bars: dict[Timeframe, tuple[Bar, ...]]
    snapshots: dict[Timeframe, ChanSnapshot]
    data_quality: DataQuality
    instrument: Instrument
    universe_date: date
    universe_rank: int | None = None

    @model_validator(mode="after")
    def three_timeframes(self) -> MultiTimeframeContext:
        expected = set(Timeframe)
        if set(self.bars) != expected or set(self.snapshots) != expected:
            raise ValueError("bars and snapshots must contain 15m, 1h, and 4h")
        if self.universe_rank is not None and self.universe_rank < 1:
            raise ValueError("universe_rank starts at 1")
        return self


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
