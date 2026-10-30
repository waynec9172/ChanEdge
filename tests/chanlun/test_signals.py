from __future__ import annotations

from chanedge.chanlun.engine import ChanEngine
from chanedge.chanlun.version import ENGINE_VERSION
from chanedge.domain.enums import Direction, Mark, SignalStatus, SignalType, StructureBias, Timeframe

SIGNAL_TOKENS = (
    "second-buy-sell-no-first-class-point",
    "third-buy-sell-no-reemit-on-endpoint-replace-keep-fields-except-related-bi-id",
    "second-buy-sell-reemit-on-new-confirm-bar-when-price-holds-no-cap",
)
TRADE_DIRECTION = {
    SignalType.SECOND_BUY: Direction.UP,
    SignalType.THIRD_BUY: Direction.UP,
    SignalType.SECOND_SELL: Direction.DOWN,
    SignalType.THIRD_SELL: Direction.DOWN,
}


def _open_index(bars, when) -> int:
    for index, bar in enumerate(bars):
        if bar.open_time == when:
            return index
    raise AssertionError(f"open time not in window: {when}")


def _span(bi, bars) -> tuple[int, int]:
    return _open_index(bars, bi.start_time), _open_index(bars, bi.end_time)


def _members(zs, snap, bars) -> list[tuple[int, int]]:
    by_id = {bi.id: bi for bi in snap.bis}
    return [_span(by_id[bi_id], bars) for bi_id in zs.bi_ids]


def _prefix(engine: ChanEngine, bars, index: int):
    window = bars[: index + 1]
    return engine.compute(window, timeframe=Timeframe.M15, as_of=window[-1].close_time), window


def _zone(snap, catalog: dict, name: str | None):
    if name is None:
        assert snap.active_zhongshu_id is None
        return None
    spec = catalog[name]
    found = [zs for zs in snap.zhongshus if zs.zg == spec["zg"] and zs.zd == spec["zd"]]
    assert len(found) == 1, name
    assert snap.active_zhongshu_id == found[0].id
    return found[0]


def _bar_signals(snap, bar):
    return [signal for signal in snap.signals if signal.time == bar.close_time]


def _assert_signal(signal, bar, expected: dict, related_id: str | None) -> None:
    kind = SignalType(expected["type"])
    assert signal.type == kind
    assert signal.status == SignalStatus.CONFIRMED
    assert signal.direction == TRADE_DIRECTION[kind]
    assert signal.defending_price == expected["defending"]
    assert signal.prior_extreme == expected["prior"]
    assert signal.related_zhongshu_id == related_id
    assert signal.price == bar.close
    assert signal.bar_open_time == bar.open_time
    assert signal.time == bar.close_time
    assert signal.notes == ""
    assert signal.id.startswith("sig:")


def test_engine_version_records_the_signal_rules() -> None:
    for token in SIGNAL_TOKENS:
        assert token in ENGINE_VERSION


def test_golden_multi_zs_every_index(bars_from_prices, load_fixture, config_hash) -> None:
    fixture = load_fixture("golden_multi_zs.json")
    assert len(fixture["prices"]) == 42
    assert len(fixture["rows"]) == 17
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    catalog = {item["name"]: item for item in fixture["zhongshus"]}
    listed = {row["index"]: row for row in fixture["rows"]}
    carried = {"bias": "neutral", "active": None, "signal": None}
    seen_signals: list[dict] = []

    for index in range(len(bars)):
        if index in listed:
            carried = listed[index]
        snap, window = _prefix(engine, bars, index)
        assert snap.structure_bias == StructureBias(carried["bias"]), index
        _zone(snap, catalog, carried["active"])
        fresh = _bar_signals(snap, window[-1])
        if carried["signal"] is None or index not in listed:
            assert fresh == [], index
            continue
        assert len(fresh) == 1, index
        related = None
        if carried["signal"]["related"] is not None:
            related = _zone(snap, catalog, carried["signal"]["related"]).id
        _assert_signal(fresh[0], window[-1], carried["signal"], related)
        seen_signals.append(carried["signal"])

    final, _window = _prefix(engine, bars, len(bars) - 1)
    assert [signal.type for signal in final.signals] == [
        SignalType(item["type"]) for item in seen_signals
    ]
    assert all(
        signal.type not in (SignalType.FIRST_BUY, SignalType.FIRST_SELL, SignalType.THIRD_SELL)
        for signal in final.signals
    )
    marks = {(fx.mark, fx.k_index_mid) for fx in final.fenxings}
    expected_marks = {(Mark.TOP, mid) for mid in fixture["fenxing_mids"]["top"]}
    expected_marks |= {(Mark.BOTTOM, mid) for mid in fixture["fenxing_mids"]["bottom"]}
    assert marks == expected_marks
    assert len(final.zhongshus) == 2
    for zs, spec in zip(final.zhongshus, fixture["zhongshus"], strict=True):
        assert zs.level == 1
        assert (zs.zg, zs.zd, zs.gg, zs.dd) == (spec["zg"], spec["zd"], spec["gg"], spec["dd"])
        assert zs.direction_into == Direction(spec["direction_into"])
        assert _members(zs, final, bars) == [tuple(pair) for pair in spec["members"]]
        outside = _span_bi(final, bars, spec["outside"][0], spec["outside"][1])
        assert outside.id not in zs.bi_ids
    again = engine.compute(bars, timeframe=Timeframe.M15, as_of=bars[-1].close_time)
    assert again.snapshot_id == final.snapshot_id


def test_third_buy_is_not_reemitted_when_the_endpoint_is_replaced(
    bars_from_prices, load_fixture, config_hash
) -> None:
    multi = load_fixture("golden_multi_zs.json")
    fixture = load_fixture("golden_third_buy_no_reemit.json")
    assert fixture["extension"] == [59, 57, 60, 63]
    prices = multi["prices"] + fixture["extension"]
    assert len(prices) == 46
    bars = bars_from_prices(prices)
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    catalog = {item["name"]: item for item in multi["zhongshus"]}
    original, _window = _prefix(engine, bars, 41)
    original_signal = _only(original, _close_of(bars, 41))
    assert original_signal.type == SignalType.THIRD_BUY
    assert original_signal.defending_price == 58
    assert original_signal.related_zhongshu_id == _zone(original, catalog, "ZS2").id

    for check in fixture["checks"]:
        snap, window = _prefix(engine, bars, check["index"])
        assert snap.structure_bias == StructureBias(check["bias"]), check["index"]
        _zone(snap, catalog, check["active"])
        fresh = _bar_signals(snap, window[-1])
        if check["signal"] is None:
            assert fresh == [], check["index"]
        else:
            assert len(fresh) == 1, check["index"]
            assert fresh[0].type == SignalType(check["signal"])
            assert fresh[0].defending_price == check["defending"]

    for index in (44, 45):
        snap, _window = _prefix(engine, bars, index)
        kept = _only(snap, _close_of(bars, 41))
        assert kept.defending_price == 58
        assert kept.time == _close_of(bars, 41)
        assert kept.related_zhongshu_id == original_signal.related_zhongshu_id
        assert _dump_without_bi(kept) == _dump_without_bi(original_signal)
        assert kept.related_bi_id != original_signal.related_bi_id
        lengthened = _span_bi(snap, bars, 37, 43)
        assert kept.related_bi_id == lengthened.id
        assert lengthened.low > _zone(snap, catalog, "ZS2").zg
        defender = next(fx for fx in snap.fenxings if fx.id == kept.defending_fx_id)
        assert defender.k_index_mid == 40
        assert defender.price == 58
        endpoints = {point for bi in snap.bis for point in _span(bi, bars)}
        assert 40 not in endpoints
        assert [signal for signal in snap.signals if signal.time == _close_of(bars, index)] == []
        assert [signal for signal in snap.signals if signal.type == SignalType.THIRD_BUY and signal.time == _close_of(bars, 41)] == [kept]

    ignored, _window = _prefix(engine, bars, 42)
    tops = [fx for fx in ignored.fenxings if fx.k_index_mid == 41]
    assert len(tops) == 1
    assert tops[0].price == 61
    endpoints = {point for bi in ignored.bis for point in _span(bi, ignored_bars(bars, 42))}
    assert 41 not in endpoints


def test_second_buy_reemits_on_the_new_confirm_bar(bars_from_prices, load_fixture, config_hash) -> None:
    frozen = load_fixture("golden_zs_zd_frozen.json")
    fixture = load_fixture("golden_second_buy_reemit.json")
    assert fixture["prices"] == frozen["prices"][:14]
    assert "30" in fixture["description"]
    assert "34" in fixture["description"]
    assert "33" in fixture["description"]
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])

    first, window = _prefix(engine, bars, 11)
    assert first.structure_bias == StructureBias.UP
    assert first.active_zhongshu_id is None
    assert (first.zhongshus[0].zg, first.zhongshus[0].zd) == (50, 34)
    opened = _only(first, window[-1].close_time)
    _assert_signal(
        opened,
        window[-1],
        {"type": "second_buy", "defending": 34, "prior": 30, "related": None},
        None,
    )
    assert opened.related_bi_id == _span_bi(first, bars, 7, 10).id

    ignored, window = _prefix(engine, bars, 12)
    assert _bar_signals(ignored, window[-1]) == []
    assert ignored.structure_bias == StructureBias.BREAKOUT_DOWN
    assert ignored.active_zhongshu_id == ignored.zhongshus[0].id
    assert [fx.k_index_mid for fx in ignored.fenxings if fx.price == 37] == [11]
    endpoints = {point for bi in ignored.bis for point in _span(bi, bars)}
    assert 11 not in endpoints
    assert _only(ignored, _close_of(bars, 11)).id == opened.id

    renewed, window = _prefix(engine, bars, 13)
    assert renewed.structure_bias == StructureBias.UP
    assert renewed.active_zhongshu_id is None
    zs = renewed.zhongshus[0]
    assert (zs.zg, zs.zd, zs.gg, zs.dd) == (50, 34, 60, 30)
    assert zs.id == first.zhongshus[0].id
    assert len(renewed.signals) == 2
    kept = _only(renewed, _close_of(bars, 11))
    added = _only(renewed, window[-1].close_time)
    _assert_signal(
        added,
        window[-1],
        {"type": "second_buy", "defending": 33, "prior": 30, "related": None},
        None,
    )
    assert kept.defending_price == 34
    assert kept.prior_extreme == 30
    assert kept.id == opened.id
    assert _dump_without_bi(kept) == _dump_without_bi(opened)
    current = _span_bi(renewed, bars, 7, 12)
    assert kept.related_bi_id == current.id
    assert added.related_bi_id == current.id
    assert kept.related_bi_id != opened.related_bi_id
    assert kept.defending_fx_id == opened.defending_fx_id
    assert added.defending_fx_id != kept.defending_fx_id
    assert (current.high, current.low, current.end_price) == (50, 33, 33)


def _span_bi(snap, bars, start: int, end: int):
    found = [bi for bi in snap.bis if _span(bi, bars) == (start, end)]
    assert len(found) == 1, (start, end)
    return found[0]


def _close_of(bars, index):
    return bars[index].close_time


def _only(snap, when):
    found = [signal for signal in snap.signals if signal.time == when]
    assert len(found) == 1
    return found[0]


def _dump_without_bi(signal) -> dict:
    payload = signal.model_dump()
    payload.pop("related_bi_id")
    return payload


def ignored_bars(bars, index):
    return bars[: index + 1]


def test_inside_bars_after_confirmation_do_not_move_the_signal(bars_from_prices, config_hash) -> None:
    # golden_multi_zs through index 11 (SECOND_BUY), then two bars contained in bar 11.
    prices = [50, 60, 50, 40, 30, 37, 44, 50, 44, 38, 32, 37, 37, 37, 40]
    bars = bars_from_prices(prices)
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=2)
    first, _ = _prefix(engine, bars, 11)
    emitted = [signal for signal in first.signals if signal.time == bars[11].close_time]
    assert [signal.type for signal in emitted] == [SignalType.SECOND_BUY]
    for index in (12, 13, 14):
        snap, _ = _prefix(engine, bars, index)
        assert _bar_signals(snap, bars[index]) == []
        assert [signal.id for signal in snap.signals] == [emitted[0].id]
        assert snap.signals[0].time == bars[11].close_time
        assert snap.signals[0].price == emitted[0].price
