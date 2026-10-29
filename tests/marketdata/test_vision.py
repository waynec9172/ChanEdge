from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from chanedge.domain.enums import Timeframe
from chanedge.marketdata.vision import (
    bar_window_hash,
    bar_window_line,
    download_start,
    funding_month_csv,
    kline_files_for_month,
    parse_daily_csv,
    parse_kline_csv,
    read_daily_for_month,
    read_funding_month,
    read_klines_for_month,
    utc_from_millis,
    warmup_open,
)

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _kline(open_time: datetime, price: str, volume: str, *, minutes: int = 15) -> str:
    close_ms = _ms(open_time) + minutes * 60 * 1000 - 1
    return (
        f"{_ms(open_time)},{price},{price},{price},{price},{volume},"
        f"{close_ms},12.5,3,0,0,0"
    )


def test_warmup_open_for_default_4h_window() -> None:
    history = date(2024, 1, 1)
    assert warmup_open(history, Timeframe.H4, 500) == datetime(2023, 10, 9, 16, tzinfo=UTC)
    windows = {Timeframe.M15: 1500, Timeframe.H1: 1000, Timeframe.H4: 500}
    assert download_start(history, windows) == datetime(2023, 10, 9, 16, tzinfo=UTC)
    assert warmup_open(history, Timeframe.M15, 1500) > download_start(history, windows)
    assert warmup_open(history, Timeframe.H1, 1000) > download_start(history, windows)


def test_bar_line_uses_canonical_formatters_and_collapses_negative_zero(make_bar) -> None:
    bar = make_bar()
    line = bar_window_line(bar)
    assert line == "2024-01-01T00:00:00.000Z|100.00000000|101.00000000|99.00000000|100.50000000|1.00000000"
    zero = bar_window_line(make_bar(volume=-0.0))
    assert zero.endswith("|0.00000000")
    assert "-0.00000000" not in zero
    digest = bar_window_hash((line, zero))
    assert digest == hashlib.sha256(f"{line}\n{zero}".encode("utf-8")).hexdigest()
    assert digest == digest.lower()
    assert not digest.startswith("sha")


def test_close_time_is_the_timeframe_not_the_csv_millisecond() -> None:
    clock = T0 + timedelta(minutes=15)
    text = _kline(T0, "100.5", "1")
    stored = parse_kline_csv(text, symbol="BTC/USDT", timeframe=Timeframe.M15, source="binanceusdm", clock=clock)
    bar = stored[0].bar
    assert bar.close_time == T0 + timedelta(minutes=15)
    assert bar.close_time != utc_from_millis(_ms(T0) + 15 * 60 * 1000 - 1)
    assert bar.is_closed is True
    assert stored[0].window_line == bar_window_line(bar)

    early = parse_kline_csv(
        text, symbol="BTC/USDT", timeframe=Timeframe.M15, source="binanceusdm", clock=T0 + timedelta(minutes=14)
    )
    assert early[0].bar.is_closed is False


def test_daily_quote_volume_stays_decimal_and_keys_on_open_time() -> None:
    day = datetime(2023, 12, 31, tzinfo=UTC)
    nxt = datetime(2024, 1, 1, tzinfo=UTC)
    text = "\n".join((_kline(day, "0.10", "1", minutes=24 * 60), _kline(nxt, "0.10", "9", minutes=24 * 60)))
    quotes = parse_daily_csv(text, compact_symbol="BTCUSDT")
    assert quotes[0].open_time == day
    assert quotes[0].quote_volume == Decimal("12.5")
    assert quotes[1].open_time == nxt


def test_monthly_file_wins_and_missing_month_is_empty(tmp_path) -> None:
    root = tmp_path
    month_path_parent = root / "data" / "futures" / "um" / "monthly" / "klines" / "BTCUSDT" / "15m"
    daily_parent = root / "data" / "futures" / "um" / "daily" / "klines" / "BTCUSDT" / "15m"
    month_path_parent.mkdir(parents=True)
    daily_parent.mkdir(parents=True)
    (month_path_parent / "BTCUSDT-15m-2024-01.csv").write_text(_kline(T0, "10", "1"), encoding="utf-8")
    (daily_parent / "BTCUSDT-15m-2024-01-01.csv").write_text(_kline(T0, "99", "1"), encoding="utf-8")
    paths = kline_files_for_month(root, "BTCUSDT", "15m", 2024, 1)
    assert len(paths) == 1
    assert paths[0].name == "BTCUSDT-15m-2024-01.csv"
    clock = T0 + timedelta(hours=1)
    bars = read_klines_for_month(
        root, "BTCUSDT", "15m", 2024, 1, symbol="BTC/USDT", source="binanceusdm", clock=clock
    )
    assert len(bars) == 1
    assert bars[0].bar.open == 10.0

    (month_path_parent / "BTCUSDT-15m-2024-01.csv").unlink()
    daily_only = read_klines_for_month(
        root, "BTCUSDT", "15m", 2024, 1, symbol="BTC/USDT", source="binanceusdm", clock=clock
    )
    assert daily_only[0].bar.open == 99.0
    assert read_klines_for_month(
        root, "ETHUSDT", "15m", 2024, 1, symbol="ETH/USDT", source="binanceusdm", clock=clock
    ) == ()


def test_daily_reader_and_funding_month(tmp_path) -> None:
    root = tmp_path
    day = datetime(2023, 12, 31, tzinfo=UTC)
    folder = root / "data" / "futures" / "um" / "daily" / "klines" / "FTMUSDT" / "1d"
    folder.mkdir(parents=True)
    (folder / "FTMUSDT-1d-2024-01-01.csv").write_text(
        _kline(day, "0.0001", "1", minutes=24 * 60),
        encoding="utf-8",
    )
    quotes = read_daily_for_month(root, "FTMUSDT", 2024, 1)
    assert quotes[0].compact_symbol == "FTMUSDT"
    assert quotes[0].quote_volume == Decimal("12.5")
    assert quotes[0].min_qty is None

    path = funding_month_csv(root, "BTCUSDT", 2024, 1)
    assert path.as_posix().endswith(
        "data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.csv"
    )
    missing = read_funding_month(path)
    assert missing.missing is True
    assert missing.rows == ()
    path.parent.mkdir(parents=True)
    path.write_text("calc_time,last_funding_rate\n1704067200000,0.0001\n", encoding="utf-8")
    found = read_funding_month(path)
    assert found.missing is False
    assert found.rows[0].calc_time == T0
    assert found.rows[0].last_funding_rate == Decimal("0.0001")
