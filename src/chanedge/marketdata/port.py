"""Paper market-data implementation. The protocol lives in domain.ports.

Daily klines are a method on this class. They are not a Timeframe and they are
not on the protocol. This class has no create_order. Loading keys is the
compose root's job in PR-12.
"""

from __future__ import annotations

from datetime import datetime

from chanedge.domain.bars import Bar, Instrument
from chanedge.domain.enums import Timeframe
from chanedge.marketdata.ccxt_adapter import CcxtMarketData
from chanedge.marketdata.vision import DailyQuote


class PaperMarketData:
    def __init__(self, exchange: object, *, clock: datetime, venue: str = "binanceusdm") -> None:
        self._adapter = CcxtMarketData(exchange, clock=clock, venue=venue)

    def fetch_closed_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        return self._adapter.fetch_closed_bars(instrument, timeframe, start, end)

    def fetch_daily_klines(
        self,
        venue_symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[DailyQuote, ...]:
        return self._adapter.fetch_daily_klines(venue_symbol, start, end)

    def fetch_tickers(self) -> object:
        """Present for tests. Universe ranking does not call this."""
        return self._adapter.fetch_tickers()
