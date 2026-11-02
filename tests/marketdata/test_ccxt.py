from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import ccxt
import pytest

from chanedge.app.compose import instruments_from_exchange
from chanedge.domain.bars import Instrument
from chanedge.domain.enums import InstrumentSource, ProductType, Timeframe
from chanedge.marketdata.ccxt_adapter import (
    CcxtMarketData,
    fetch_start,
    instrument_from_market,
    paper_daily_quotes,
    sync_closed_bars,
)
from chanedge.marketdata.parquet_store import ParquetBarStore
from chanedge.marketdata.port import PaperMarketData
from chanedge.marketdata.universe import select_universe
from chanedge.marketdata.vision import DailyQuote, ranking_open_time, warmup_open

UTC = timezone.utc
CLOCK = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
EXCLUDE = ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "EUR")


class FakeExchange:
    def __init__(self, rows, daily=None) -> None:
        self.rows = rows
        self.daily = daily if daily is not None else []
        self.calls: list[tuple] = []
        self.tickers = 0

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls.append((symbol, timeframe, since, limit))
        if timeframe == "1d":
            return self.daily
        return self.rows

    def fetch_tickers(self):
        self.tickers += 1
        raise AssertionError("ranking must not call fetch_tickers")

    def create_order(self, *args, **kwargs):
        raise AssertionError("paper market data must not create orders")


def _instrument() -> Instrument:
    return Instrument(
        symbol="BTC/USDT",
        venue="binanceusdm",
        venue_symbol="BTC/USDT:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal(1),
        price_tick=Decimal("0.1"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal(5),
        margin_asset="USDT",
        leverage_max=125,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _row(open_time: datetime, close: float = 100.5) -> list[object]:
    return [_ms(open_time), 100.0, 103.0, 99.0, close, 1.0]


def test_paper_port_drops_the_forming_bar_and_does_not_order(tmp_path) -> None:
    assert not hasattr(PaperMarketData, "create_order")
    exchange = FakeExchange([_row(datetime(2024, 1, 1, tzinfo=UTC)), _row(CLOCK)])
    port = PaperMarketData(exchange, clock=CLOCK)
    bars = port.fetch_closed_bars(_instrument(), Timeframe.M15, datetime(2024, 1, 1, tzinfo=UTC), CLOCK)
    assert [bar.open_time for bar in bars] == [datetime(2024, 1, 1, tzinfo=UTC)]
    assert bars[0].is_closed is True
    assert bars[0].close_time == CLOCK
    assert exchange.tickers == 0
    store = ParquetBarStore(tmp_path)
    market = CcxtMarketData(exchange, clock=CLOCK)
    sync_closed_bars(
        store,
        market,
        _instrument(),
        Timeframe.M15,
        history_start=date(2024, 1, 1),
        window=1500,
        end=CLOCK,
    )
    assert store.last_open_time("binanceusdm", "BTC/USDT", Timeframe.M15) == datetime(2024, 1, 1, tzinfo=UTC)
    warmup = warmup_open(date(2024, 1, 1), Timeframe.M15, 1500)
    assert exchange.calls[1][2] == _ms(warmup)


def test_incremental_fetch_starts_at_the_last_open_inclusive(tmp_path) -> None:
    store = ParquetBarStore(tmp_path)
    first_open = datetime(2024, 1, 1, tzinfo=UTC)
    exchange = FakeExchange([_row(first_open), _row(CLOCK, close=102.0)])
    market = CcxtMarketData(exchange, clock=CLOCK + timedelta(minutes=15))
    sync_closed_bars(
        store,
        market,
        _instrument(),
        Timeframe.M15,
        history_start=date(2024, 1, 1),
        window=4,
        end=CLOCK + timedelta(minutes=15),
    )
    assert fetch_start(first_open, history_start=date(2024, 1, 1), timeframe=Timeframe.M15, window=4) == first_open
    exchange.calls.clear()
    sync_closed_bars(
        store,
        market,
        _instrument(),
        Timeframe.M15,
        history_start=date(2024, 1, 1),
        window=4,
        end=CLOCK + timedelta(minutes=15),
    )
    assert exchange.calls[0][2] == _ms(CLOCK)
    stored = store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert stored[-1].bar.close == 102.0


def test_daily_row_without_quote_volume_stays_empty_and_rank_ignores_tickers() -> None:
    exchange = FakeExchange([], daily=[[_ms(datetime(2023, 12, 31, tzinfo=UTC)), 1, 1, 1, 1, 9]])
    port = PaperMarketData(exchange, clock=CLOCK)
    quotes = port.fetch_daily_klines(
        "BTC/USDT:USDT",
        datetime(2023, 12, 31, tzinfo=UTC),
        datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert quotes[0].quote_volume is None
    assert exchange.tickers == 0
    open_time = ranking_open_time(date(2024, 1, 2))
    ranked = select_universe(
        (
            DailyQuote("AAAUSDT", open_time, Decimal(5), Decimal(1)),
            DailyQuote("BBBUSDT", open_time, Decimal(9), Decimal(1)),
        ),
        file_date=date(2024, 1, 2),
        size=2,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=True,
    )
    assert [item[0] for item in ranked] == ["BBB/USDT", "AAA/USDT"]


def test_exchange_instrument_and_paper_pool_drop_bad_contracts() -> None:
    market = {
        "symbol": "BTC/USDT:USDT",
        "base": "BTC",
        "quote": "USDT",
        "settle": "USDT",
        "swap": True,
        "linear": True,
        "contractSize": 1,
        "precision": {"price": 0.1, "amount": 0.001},
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5}, "leverage": {"max": 125}},
    }
    instrument = instrument_from_market(market)
    assert instrument.price_tick == Decimal("0.1")
    assert instrument.qty_step == Decimal("0.001")
    assert instrument.min_qty == Decimal("0.001")
    assert instrument.min_notional == Decimal(5)
    assert instrument.instrument_source is InstrumentSource.EXCHANGE
    no_cost = dict(market)
    no_cost["limits"] = {"amount": {"min": 0.001}, "cost": {}, "leverage": {"max": 125}}
    assert instrument_from_market(no_cost).min_notional is None

    open_time = ranking_open_time(date(2024, 1, 2))
    names = []
    quotes = []
    for index in range(20):
        base = f"N{index:02d}"
        names.append(
            {
                "symbol": f"{base}/USDT:USDT",
                "base": base,
                "quote": "USDT",
                "settle": "USDT",
                "swap": True,
                "linear": True,
                "precision": {"price": 0.01, "amount": 0.01},
                "limits": {"amount": {"min": 0.01}, "leverage": {"max": 20}},
            }
        )
        quotes.append(DailyQuote(base + "USDT", open_time, Decimal(100 - index), None))
    names.append(
        {
            "symbol": "ZZ/USDT:USDT",
            "base": "ZZ",
            "quote": "USDT",
            "settle": "USDT",
            "swap": True,
            "linear": True,
            "limits": {"amount": {}, "leverage": {"max": 20}},
        }
    )
    quotes.append(DailyQuote("ZZUSDT", open_time, Decimal(1000), None))
    names.append(
        {
            "symbol": "USDC/USDT:USDT",
            "base": "USDC",
            "quote": "USDT",
            "settle": "USDT",
            "swap": True,
            "linear": True,
            "limits": {"amount": {"min": 1}, "leverage": {"max": 20}},
        }
    )
    quotes.append(DailyQuote("USDCUSDT", open_time, Decimal(5000), None))
    names.append(
        {
            "symbol": "INV/USDT:USDT",
            "base": "INV",
            "quote": "USDT",
            "settle": "USDT",
            "swap": True,
            "linear": False,
            "limits": {"amount": {"min": 1}, "leverage": {"max": 20}},
        }
    )
    quotes.append(DailyQuote("INVUSDT", open_time, Decimal(5000), None))
    pooled = paper_daily_quotes(names, quotes, EXCLUDE)
    selected = select_universe(
        pooled,
        file_date=date(2024, 1, 2),
        size=20,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=True,
    )
    symbols = [item[0] for item in selected]
    assert "ZZ/USDT" not in symbols
    assert "USDC/USDT" not in symbols
    assert "INV/USDT" not in symbols
    assert len(symbols) == 20


class RawKlineExchange(FakeExchange):
    """Binance raw klines: strings, quote asset volume at index 7, trades at index 8."""

    def __init__(self, raw) -> None:
        super().__init__([])
        self.raw = raw
        self.raw_calls: list[dict] = []

    def fapiPublicGetKlines(self, params):
        self.raw_calls.append(params)
        return self.raw


def test_daily_quote_volume_comes_from_the_raw_klines() -> None:
    open_time = datetime(2023, 12, 31, tzinfo=UTC)
    close_ms = _ms(open_time + timedelta(days=1)) - 1
    row = [_ms(open_time), "1.0", "1.0", "1.0", "1.0", "9.0", close_ms, "12345.5", 77, "4", "5", "0"]
    exchange = RawKlineExchange([row])
    port = PaperMarketData(exchange, clock=CLOCK)
    quotes = port.fetch_daily_klines("BTC/USDT:USDT", open_time, open_time + timedelta(days=1))
    assert [quote.quote_volume for quote in quotes] == [Decimal("12345.5")]
    assert exchange.raw_calls[0]["symbol"] == "BTCUSDT"
    assert exchange.raw_calls[0]["interval"] == "1d"
    assert exchange.calls == []
    assert exchange.tickers == 0


def test_unknown_leverage_max_takes_the_fallback() -> None:
    # ccxt 4.5's Binance parser returns limits.leverage.max as None.
    market = {
        "symbol": "BTC/USDT:USDT",
        "base": "BTC",
        "quote": "USDT",
        "settle": "USDT",
        "swap": True,
        "linear": True,
        "contractSize": 1,
        "precision": {"price": 0.1, "amount": 0.001},
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5}, "leverage": {"min": None, "max": None}},
    }
    assert instrument_from_market(market, leverage_fallback=2).leverage_max == 2
    with pytest.raises(ValueError, match="leverage max is required"):
        instrument_from_market(market)
    listed = dict(market)
    listed["limits"] = {"amount": {"min": 0.001}, "leverage": {"max": 125.0}}
    assert instrument_from_market(listed, leverage_fallback=2).leverage_max == 125


def _binance(symbol: str, base: str, quote: str, contract: str, delivery: int) -> dict:
    """One exchangeInfo row, parsed offline by the installed ccxt."""
    return {
        "symbol": symbol,
        "pair": base + quote,
        "contractType": contract,
        "deliveryDate": delivery,
        "onboardDate": 1569398400000,
        "status": "TRADING",
        "baseAsset": base,
        "quoteAsset": quote,
        "marginAsset": quote,
        "pricePrecision": 2,
        "quantityPrecision": 3,
        "baseAssetPrecision": 8,
        "quotePrecision": 8,
        "underlyingType": "COIN",
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "1", "maxPrice": "1000000", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
        "orderTypes": ["LIMIT", "MARKET"],
        "timeInForce": ["GTC"],
    }


class MarketsExchange:
    def __init__(self, markets: list[dict]) -> None:
        self.markets = markets

    def load_markets(self):
        return {market["symbol"]: market for market in self.markets}


@pytest.mark.parametrize("reverse", [False, True])
def test_usdc_perp_and_dated_future_do_not_replace_the_usdt_perp(reverse: bool) -> None:
    parser = ccxt.binanceusdm()
    parsed = [
        parser.parse_market(_binance("BTCUSDT", "BTC", "USDT", "PERPETUAL", 4133404800000)),
        parser.parse_market(_binance("BTCUSDC", "BTC", "USDC", "PERPETUAL", 4133404800000)),
        parser.parse_market(_binance("BTCUSDT_261225", "BTC", "USDT", "CURRENT_QUARTER", 1798185600000)),
    ]
    assert [market["symbol"] for market in parsed] == [
        "BTC/USDT:USDT",
        "BTC/USDC:USDC",
        "BTC/USDT:USDT-261225",
    ]
    if reverse:
        parsed.reverse()
    found = instruments_from_exchange(MarketsExchange(parsed), "binanceusdm", leverage_fallback=2)
    assert list(found) == ["BTC/USDT"]
    assert found["BTC/USDT"].venue_symbol == "BTC/USDT:USDT"
    for market in parsed:
        if market["symbol"] == "BTC/USDT:USDT":
            continue
        with pytest.raises(ValueError, match="USDT-settled linear perpetual"):
            instrument_from_market(market, leverage_fallback=2)
