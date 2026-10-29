from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from chanedge.chanlun.engine import ChanEngine
from chanedge.chanlun.version import ENGINE_VERSION
from chanedge.domain.enums import Direction, Timeframe
from chanedge.marketdata.vision import bar_window_hash, bar_window_line

TOKENS = (
    "zhongshu-zg-zd-frozen-when-third-bi-endpoint-replaced",
    "outside-bi-stays-out-closed-zhongshu-stays-closed",
    "zg-le-zd-drop-earliest-keep-later-two-consumed-no-revive",
)
FORMAL_15M_WINDOW = 1500


def _open_index(bars, when) -> int:
    for index, bar in enumerate(bars):
        if bar.open_time == when:
            return index
    raise AssertionError(f"open time not in window: {when}")


def _span(bi, bars) -> tuple[int, int]:
    return _open_index(bars, bi.start_time), _open_index(bars, bi.end_time)


def test_golden_bi_machine_has_two_bis(bars_from_prices, load_fixture, config_hash) -> None:
    fixture = load_fixture("golden_bi_machine.json")
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    snap = engine.compute(bars, timeframe=Timeframe.M15, as_of=bars[-1].close_time)

    assert snap.signals == ()
    assert snap.segments == ()
    assert snap.zhongshus == ()
    assert len(snap.bis) == len(fixture["bis"])
    for bi, expected in zip(snap.bis, fixture["bis"], strict=True):
        assert _span(bi, bars) == (expected["start"], expected["end"])
        assert bi.direction == Direction(expected["direction"])
        assert bi.start_price == expected["start_price"]
        assert bi.end_price == expected["end_price"]
        assert bi.high == expected["high"]
        assert bi.low == expected["low"]
        assert bi.confirmed is True

    assert [fx.k_index_mid for fx in snap.fenxings] == fixture["fenxing_mids"]
    endpoints = {index for bi in snap.bis for index in _span(bi, bars)}
    for mid in fixture["not_endpoints"]:
        assert mid in fixture["fenxing_mids"]
        assert mid not in endpoints
    assert 6 not in endpoints
    assert any(fx.k_index_mid == 6 and fx.price == 48 for fx in snap.fenxings)


def test_same_input_keeps_one_snapshot_id(bars_from_prices, load_fixture, config_hash) -> None:
    fixture = load_fixture("golden_bi_machine.json")
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    kwargs = {"timeframe": Timeframe.M15, "as_of": bars[-1].close_time}
    first = engine.compute(bars, **kwargs)
    second = engine.compute(bars, **kwargs)

    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_id.startswith("cs_")
    assert len(first.snapshot_id) == 19
    int(first.snapshot_id[3:], 16)
    assert first.bar_window_hash == second.bar_window_hash
    assert first.bar_window_hash == bar_window_hash(
        [bar_window_line(bar) for bar in bars if bar.is_closed]
    )
    assert len(first.bar_window_hash) == 64
    assert first.engine_version == ENGINE_VERSION
    assert first.config_hash == config_hash
    assert first.symbol == "BTC/USDT"
    assert first.timeframe == Timeframe.M15
    assert first.bars_start == bars[0].open_time
    assert first.bars_end == bars[-1].open_time
    assert first.bar_count == len(bars)
    assert first.signals == ()


def test_engine_version_records_the_zhongshu_rules(bars_from_prices, config_hash) -> None:
    for token in TOKENS:
        assert token in ENGINE_VERSION
    bars = bars_from_prices([40, 25, 32, 18, 24, 22, 48, 40, 60, 50, 30, 36, 28, 34])
    snap = ChanEngine(config_hash=config_hash, min_bi_bars=2).compute(
        bars,
        timeframe=Timeframe.M15,
        as_of=bars[-1].close_time,
    )
    assert snap.engine_version == ENGINE_VERSION


def test_default_min_bi_bars_stays_five(config_hash) -> None:
    engine = ChanEngine(config_hash=config_hash)
    assert engine.min_bi_bars == 5
    assert engine.segment_enabled is False


def test_empty_bars_raise(config_hash) -> None:
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=2)
    with pytest.raises(ValueError, match="bars must not be empty"):
        engine.compute((), timeframe=Timeframe.M15, as_of=bars_as_of())


def test_segment_enabled_false_skips_minimal_break(bars_from_prices, monkeypatch, config_hash) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("minimal_break was called")

    monkeypatch.setattr("chanedge.chanlun.engine.minimal_break", fail)
    bars = bars_from_prices([40, 25, 32, 18, 24, 22, 48, 40, 60, 50, 30, 36, 28, 34])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=2)
    snap = engine.compute(bars, timeframe=Timeframe.M15, as_of=bars[-1].close_time)
    assert snap.segments == ()


def test_window_start_records_agreement_without_a_minimum(bars_from_prices, config_hash) -> None:
    """Formal 15m window is 1500. Feed the tail N and the full 2N. Do not use 42 bars."""
    count = FORMAL_15M_WINDOW * 2
    prices = [float(100 + (index % 18)) for index in range(count)]
    bars = bars_from_prices(prices)
    assert len(bars) == 3000
    tail = bars[-FORMAL_15M_WINDOW:]
    assert len(tail) == FORMAL_15M_WINDOW
    assert tail[0].open_time == bars[FORMAL_15M_WINDOW].open_time
    assert tail[-1].open_time == bars[-1].open_time
    as_of = bars[-1].close_time
    engine = ChanEngine(config_hash=config_hash)
    full = engine.compute(bars, timeframe=Timeframe.M15, as_of=as_of)
    short = engine.compute(tail, timeframe=Timeframe.M15, as_of=as_of)

    assert full.bar_count == 3000
    assert short.bar_count == 1500
    assert full.as_of == short.as_of == as_of
    assert full.segments == ()
    assert short.segments == ()
    assert engine.min_bi_bars == 5

    bias_agree = 1 if full.structure_bias == short.structure_bias else 0
    bias_disagree = 1 - bias_agree
    zone_agree = 1 if _active_zone(full) == _active_zone(short) else 0
    zone_disagree = 1 - zone_agree
    assert bias_agree + bias_disagree == 1
    assert zone_agree + zone_disagree == 1


def _active_zone(snap) -> tuple[float, float] | None:
    if snap.active_zhongshu_id is None:
        return None
    zs = next(item for item in snap.zhongshus if item.id == snap.active_zhongshu_id)
    return (zs.zg, zs.zd)


def bars_as_of() -> datetime:
    return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15)
