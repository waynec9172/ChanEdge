from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from chanedge.domain.enums import Timeframe
from chanedge.marketdata.parquet_store import ParquetBarStore, ParquetUnreadable
from chanedge.marketdata.vision import bar_window_line, store_bar

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_empty_store_has_no_last_bar_and_rewrite_is_inclusive(tmp_path, make_bar) -> None:
    store = ParquetBarStore(tmp_path)
    assert store.last_open_time("binanceusdm", "BTC/USDT", Timeframe.M15) is None
    first = store_bar(make_bar(open_time=T0))
    second = store_bar(make_bar(open_time=T0 + timedelta(minutes=15)))
    forming = store_bar(make_bar(open_time=T0 + timedelta(minutes=30), is_closed=False))
    store.write_closed("binanceusdm", "BTC/USDT", Timeframe.M15, (first, second, forming))
    assert store.last_open_time("binanceusdm", "BTC/USDT", Timeframe.M15) == second.bar.open_time
    stored = store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert [item.bar.open_time for item in stored] == [first.bar.open_time, second.bar.open_time]
    assert stored[0].window_line == bar_window_line(stored[0].bar)
    revised = store_bar(make_bar(open_time=second.bar.open_time, close=102.0, high=103.0))
    third = store_bar(make_bar(open_time=T0 + timedelta(minutes=30)))
    store.write_closed("binanceusdm", "BTC/USDT", Timeframe.M15, (revised, third, forming))
    stored = store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert [item.bar.open_time for item in stored] == [
        first.bar.open_time,
        second.bar.open_time,
        third.bar.open_time,
    ]
    assert stored[1].bar.close == 102.0
    assert stored[0].bar.close == 100.5
    path = store.path("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert path.parts[-4:] == ("binanceusdm", "BTC", "USDT", "15m.parquet")


def test_unreadable_parquet_is_an_error(tmp_path) -> None:
    store = ParquetBarStore(tmp_path)
    path = store.path("binanceusdm", "BTC/USDT", Timeframe.M15)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a parquet")
    with pytest.raises(ParquetUnreadable):
        store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert path.read_bytes() == b"not a parquet"


def test_failed_replace_does_not_publish_the_parquet(tmp_path, make_bar) -> None:
    store = ParquetBarStore(tmp_path)
    original = store_bar(make_bar())
    store.write_closed("binanceusdm", "BTC/USDT", Timeframe.M15, (original,))

    def fail(src, dst) -> None:
        raise PermissionError("busy")

    flaky = ParquetBarStore(tmp_path, replace=fail)
    later = store_bar(make_bar(open_time=T0 + timedelta(minutes=15)))
    with pytest.raises(PermissionError):
        flaky.write_closed("binanceusdm", "BTC/USDT", Timeframe.M15, (later,))
    stored = store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert len(stored) == 1
    assert stored[0].bar.open_time == original.bar.open_time


def test_merge_keeps_bars_after_the_incoming_range(tmp_path, make_bar) -> None:
    store = ParquetBarStore(tmp_path)
    times = [T0 + timedelta(minutes=15 * index) for index in range(4)]
    store.write_closed("binanceusdm", "BTC/USDT", Timeframe.M15, [store_bar(make_bar(open_time=t)) for t in times])
    revised = store_bar(make_bar(open_time=times[1], close=102.0, high=103.0))
    store.merge_closed("binanceusdm", "BTC/USDT", Timeframe.M15, [store_bar(make_bar(open_time=times[0])), revised])
    stored = store.read("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert [item.bar.open_time for item in stored] == times
    assert stored[1].bar.close == 102.0
