"""Paper ccxt rows. Tests pass a fake exchange. This module does not open a socket.

fetch_tickers is available for tests. Ranking does not call it. Daily klines use
fetch_ohlcv timeframe 1d. A 6-column row has no quote_volume and stays empty.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping, Sequence

from chanedge.domain.bars import Bar, Instrument, timeframe_duration
from chanedge.domain.enums import InstrumentSource, ProductType, Timeframe
from chanedge.marketdata.infer import is_plain_number
from chanedge.marketdata.parquet_store import ParquetBarStore
from chanedge.marketdata.universe import symbol_allowed
from chanedge.marketdata.vision import (
    DailyQuote,
    StoredBar,
    store_bar,
    utc_from_millis,
    warmup_open,
)


# Binance USDⓈ-M klines return at most 1500 rows per request.
PAGE_LIMIT = 1500
_MAX_PAGES = 1000


def fetch_start(
    last_open: datetime | None,
    *,
    history_start: date,
    timeframe: Timeframe,
    window: int,
    start_if_empty: datetime | None = None,
) -> datetime:
    """No stored bar: start_if_empty, else the history_start warmup open. Otherwise the last open_time, inclusive."""
    if last_open is None:
        if start_if_empty is not None:
            return start_if_empty
        return warmup_open(history_start, timeframe, window)
    return last_open


class CcxtMarketData:
    """REST incremental reads. No create_order. The caller supplies the exchange object."""

    def __init__(self, exchange: object, *, clock: datetime, venue: str = "binanceusdm") -> None:
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        self._exchange = exchange
        self._clock = clock
        self._venue = venue

    def fetch_closed_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        return tuple(item.bar for item in self.fetch_stored(instrument, timeframe, start, end))

    def fetch_stored(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[StoredBar, ...]:
        rows = self._pages(instrument.venue_symbol, timeframe, start, end)
        stored: list[StoredBar] = []
        for row in rows:
            item = stored_bar_from_ohlcv(
                row,
                symbol=instrument.symbol,
                timeframe=timeframe,
                source=self._venue,
                clock=self._clock,
            )
            if not item.bar.is_closed:
                continue
            if item.bar.open_time < start or item.bar.close_time > end:
                continue
            stored.append(item)
        return tuple(stored)

    def _pages(self, venue_symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list:
        """Follow full pages forward until the window reaches end or the exchange stops advancing."""
        since = _millis(start)
        rows: list = []
        for _page in range(_MAX_PAGES):
            page = list(self._exchange.fetch_ohlcv(venue_symbol, timeframe.value, since, PAGE_LIMIT))  # type: ignore[attr-defined]
            rows.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            last = _millis_cell(page[-1][0])
            if last < since or utc_from_millis(last) + timeframe_duration(timeframe) >= end:
                break
            since = last + 1
        return rows

    def fetch_daily_klines(
        self,
        venue_symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[DailyQuote, ...]:
        since = _millis(start)
        rows = self._exchange.fetch_ohlcv(venue_symbol, "1d", since, None)  # type: ignore[attr-defined]
        compact = _compact_from_venue_symbol(venue_symbol)
        quotes: list[DailyQuote] = []
        for row in rows:
            open_time = utc_from_millis(_millis_cell(row[0]))
            if open_time < start or open_time >= end:
                continue
            quotes.append(
                DailyQuote(
                    compact_symbol=compact,
                    open_time=open_time,
                    quote_volume=_quote_cell(row),
                    min_qty=None,
                )
            )
        return tuple(quotes)

    def fetch_tickers(self) -> object:
        return self._exchange.fetch_tickers()  # type: ignore[attr-defined]


def sync_closed_bars(
    store: ParquetBarStore,
    market: CcxtMarketData,
    instrument: Instrument,
    timeframe: Timeframe,
    *,
    history_start: date,
    window: int,
    end: datetime,
    start_if_empty: datetime | None = None,
) -> tuple[StoredBar, ...]:
    last = store.last_open_time(instrument.venue, instrument.symbol, timeframe)
    start = fetch_start(
        last,
        history_start=history_start,
        timeframe=timeframe,
        window=window,
        start_if_empty=start_if_empty,
    )
    stored = market.fetch_stored(instrument, timeframe, start, end)
    store.write_closed(instrument.venue, instrument.symbol, timeframe, stored)
    return stored


def stored_bar_from_ohlcv(
    row: Sequence[object],
    *,
    symbol: str,
    timeframe: Timeframe,
    source: str,
    clock: datetime,
) -> StoredBar:
    if len(row) < 6:
        raise ValueError("ohlcv row is short")
    open_time = utc_from_millis(_millis_cell(row[0]))
    close_time = open_time + timeframe_duration(timeframe)
    quote = _quote_cell(row)
    trades = _trades_cell(row)
    bar = Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=_bar_float(row[1], allow_zero=False),
        high=_bar_float(row[2], allow_zero=False),
        low=_bar_float(row[3], allow_zero=False),
        close=_bar_float(row[4], allow_zero=False),
        volume=_bar_float(row[5], allow_zero=True),
        quote_volume=None if quote is None else float(quote),
        trades=trades,
        is_closed=close_time <= clock,
        source=source,
    )
    return store_bar(bar)


def paper_daily_quotes(
    markets: Sequence[Mapping[str, object]],
    quotes: Sequence[DailyQuote],
    exclude_bases: Sequence[str],
) -> tuple[DailyQuote, ...]:
    """Keep swap, linear, USDT-settled perps and attach limits.amount.min.

    Names that fail the symbol filter are dropped. This does not read tickers.
    """
    by_compact = {quote.compact_symbol: quote for quote in quotes}
    selected: list[DailyQuote] = []
    for market in markets:
        if not is_usdt_perp(market):
            continue
        base = market.get("base")
        if not isinstance(base, str) or market.get("quote") != "USDT":
            continue
        compact = base + "USDT"
        if not symbol_allowed(compact, exclude_bases):
            continue
        daily = by_compact.get(compact)
        if daily is None:
            continue
        limits = market.get("limits")
        amount = limits.get("amount") if isinstance(limits, Mapping) else None
        raw_min = amount.get("min") if isinstance(amount, Mapping) else None
        selected.append(
            DailyQuote(
                compact_symbol=compact,
                open_time=daily.open_time,
                quote_volume=daily.quote_volume,
                min_qty=_positive(raw_min),
            )
        )
    return tuple(selected)


def is_usdt_perp(market: Mapping[str, object]) -> bool:
    """swap, linear, and both quote and settle USDT. Delivery and USDC contracts are not."""
    return (
        market.get("swap") is True
        and market.get("linear") is True
        and market.get("quote") == "USDT"
        and market.get("settle") == "USDT"
    )


def instrument_from_market(
    market: Mapping[str, object],
    *,
    venue: str = "binanceusdm",
    default_leverage: int | None = None,
) -> Instrument:
    """limits.amount.min, limits.cost.min, and precision ticks. Source is exchange.

    ccxt leaves limits.leverage.max empty for Binance markets until leverage
    tiers are loaded. Sizing does not read it, so default_leverage fills it.
    """
    base = market.get("base")
    if not isinstance(base, str) or base == "":
        raise ValueError("market base is required")
    symbol = f"{base}/USDT"
    venue_symbol = market.get("symbol")
    if not isinstance(venue_symbol, str) or venue_symbol == "":
        venue_symbol = f"{symbol}:USDT"
    limits = market.get("limits") if isinstance(market.get("limits"), Mapping) else {}
    assert isinstance(limits, Mapping)
    amount = limits.get("amount") if isinstance(limits.get("amount"), Mapping) else {}
    cost = limits.get("cost") if isinstance(limits.get("cost"), Mapping) else {}
    leverage = limits.get("leverage") if isinstance(limits.get("leverage"), Mapping) else {}
    precision = market.get("precision") if isinstance(market.get("precision"), Mapping) else {}
    assert isinstance(amount, Mapping) and isinstance(cost, Mapping)
    assert isinstance(leverage, Mapping) and isinstance(precision, Mapping)
    leverage_max = _leverage(leverage.get("max"))
    if leverage_max is None:
        leverage_max = default_leverage
    if leverage_max is None or leverage_max < 1:
        raise ValueError("market leverage max is required")
    settle = market.get("settle")
    margin = settle if isinstance(settle, str) and settle else "USDT"
    return Instrument(
        symbol=symbol,
        venue=venue,
        venue_symbol=venue_symbol,
        product=ProductType.USDT_PERP,
        contract_size=_contract_size(market.get("contractSize", 1)),
        price_tick=_positive(precision.get("price")),
        qty_step=_positive(precision.get("amount")),
        min_qty=_positive(amount.get("min")),
        min_notional=_positive(cost.get("min")),
        margin_asset=margin,
        leverage_max=leverage_max,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _leverage(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and math.isfinite(value) and value >= 1 and value == int(value):
        return int(value)
    return None


def _quote_cell(row: Sequence[object]) -> Decimal | None:
    if len(row) <= 7:
        return None
    return _decimal(row[7])


def _trades_cell(row: Sequence[object]) -> int | None:
    if len(row) <= 8 or row[8] is None:
        return None
    value = row[8]
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("trades must be an integer")
    if isinstance(value, str):
        if not value.strip().isdigit():
            raise ValueError("trades must be an integer")
        return int(value.strip())
    if value < 0:
        raise ValueError("trades must be >= 0")
    return value


def _bar_float(value: object, *, allow_zero: bool) -> float:
    number = _decimal(value)
    if number is None:
        raise ValueError("ohlcv cell is not a number")
    if number < 0 or (number == 0 and not allow_zero):
        raise ValueError("ohlcv cell is not positive")
    return float(number)


def _positive(value: object) -> Decimal | None:
    number = _decimal(value)
    if number is None or number <= 0:
        return None
    return number


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not is_plain_number(text):
            return None
        return Decimal(text)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return value
    if isinstance(value, int):
        return Decimal(value)
    return None


def _contract_size(value: object) -> Decimal:
    number = _decimal(value)
    if number is None or number <= 0:
        raise ValueError("contract size must be positive")
    return number


def _millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _millis_cell(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("open time must be milliseconds")
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError("open time must be milliseconds")
        return int(text)
    return int(value)


def _compact_from_venue_symbol(venue_symbol: str) -> str:
    # BTC/USDT:USDT -> BTCUSDT
    head = venue_symbol.split(":", 1)[0]
    base, quote = head.split("/", 1)
    return base + quote
