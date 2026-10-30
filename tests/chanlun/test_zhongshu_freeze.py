from __future__ import annotations

from chanedge.chanlun.engine import ChanEngine
from chanedge.domain.enums import Direction, Mark, StructureBias, Timeframe


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
    snap = engine.compute(window, timeframe=Timeframe.M15, as_of=window[-1].close_time)
    assert snap.segments == (), index
    assert snap.bar_count == index + 1
    return snap, window


def _find(snap, bars, start: int, end: int):
    found = [bi for bi in snap.bis if _span(bi, bars) == (start, end)]
    assert len(found) == 1, (start, end)
    return found[0]


def test_zd_stays_frozen_when_the_third_endpoint_is_replaced(
    bars_from_prices, load_fixture, config_hash
) -> None:
    fixture = load_fixture("golden_zs_zd_frozen.json")
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    seen_ids: list[str] = []
    for check in fixture["checks"]:
        index = check["index"]
        snap, _window = _prefix(engine, bars, index)
        assert snap.structure_bias == StructureBias(check["structure_bias"]), index
        assert len(snap.zhongshus) == 1, index
        zs = snap.zhongshus[0]
        assert zs.level == 1, index
        assert zs.confirmed is True, index
        assert (zs.zg, zs.zd, zs.gg, zs.dd) == (check["zg"], check["zd"], check["gg"], check["dd"]), index
        assert zs.direction_into == Direction(check["direction_into"]), index
        assert _open_index(bars, zs.start_time) == 1, index
        assert _open_index(bars, zs.end_time) == check["end_index"], index
        assert [_span(bi, bars) for bi in snap.bis] == [tuple(pair) for pair in check["bis"]], index
        assert _members(zs, snap, bars) == [tuple(pair) for pair in check["members"]], index
        third = snap.bis[-1]
        assert (third.high, third.low, third.end_price) == (
            check["third"]["high"],
            check["third"]["low"],
            check["third"]["end_price"],
        ), index
        if check["active"]:
            assert snap.active_zhongshu_id == zs.id, index
        else:
            assert snap.active_zhongshu_id is None, index
        endpoints = {point for bi in snap.bis for point in _span(bi, bars)}
        prices = check.get("fenxing_prices", {})
        for mid in check["not_endpoints"]:
            assert mid not in endpoints, index
        for mid in check["fenxing_mids"]:
            matches = [fx for fx in snap.fenxings if fx.k_index_mid == mid]
            assert len(matches) == 1, index
            assert matches[0].confirmed is True, index
            assert matches[0].mark == Mark.TOP, index
            assert matches[0].price == prices[str(mid)], index
            assert mid not in endpoints, index
        for mid in check.get("absent_mids", []):
            assert all(fx.k_index_mid != mid for fx in snap.fenxings), index
        seen_ids.append(zs.id)
    assert len(set(seen_ids)) == 1


def test_outside_bi_is_not_pulled_back_into_the_closed_zhongshu(
    bars_from_prices, load_fixture, config_hash
) -> None:
    fixture = load_fixture("golden_zs_outside_stays_out.json")
    prices = fixture["prices"]
    assert len(prices) == 51
    assert prices[42:] == fixture["extension"]
    assert fixture["extension"] == [59, 55, 58, 60, 64, 62, 60, 58, 61]
    bars = bars_from_prices(prices)
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])

    snap, _window = _prefix(engine, bars, 41)
    assert len(snap.zhongshus) == 2
    zs1, zs2 = snap.zhongshus
    _assert_zone(zs1, snap, bars, fixture["at_41"]["zs1"])
    _assert_zone(zs2, snap, bars, fixture["at_41"]["zs2"])
    outside = fixture["at_41"]["outside_bi"]
    outside_bi = _find(snap, bars, outside["start"], outside["end"])
    assert outside_bi.direction == Direction(outside["direction"])
    assert (outside_bi.high, outside_bi.low) == (outside["high"], outside["low"])
    assert outside_bi.id not in zs1.bi_ids
    assert outside_bi.id not in zs2.bi_ids
    assert _members(zs1, snap, bars)[-1] == (16, 19)
    assert _members(zs2, snap, bars)[-1] == (34, 37)
    zs1_id = zs1.id
    zs2_id = zs2.id

    snap, _window = _prefix(engine, bars, 44)
    assert len(snap.zhongshus) == 2
    assert snap.zhongshus[0].id == zs1_id
    assert snap.zhongshus[1].id == zs2_id
    zs2 = snap.zhongshus[1]
    assert (zs2.zg, zs2.zd) == (56, 52)
    assert _members(zs2, snap, bars)[-1] == (34, 37)
    replaced = fixture["at_44"]["replaced_bi"]
    bi = _find(snap, bars, replaced["start"], replaced["end"])
    assert bi.direction == Direction(replaced["direction"])
    assert (bi.high, bi.low, bi.end_price) == (replaced["high"], replaced["low"], replaced["end_price"])
    assert zs2.zd <= bi.low <= zs2.zg
    assert bi.id not in zs2.bi_ids
    assert all(item.zg != 64 for item in snap.zhongshus)

    snap, _window = _prefix(engine, bars, 47)
    assert len(snap.zhongshus) == 2
    assert snap.zhongshus[1].id == zs2_id
    assert _members(snap.zhongshus[1], snap, bars)[-1] == (34, 37)
    trailing = [_span(bi, bars) for bi in snap.bis]
    for pair in fixture["at_47"]["trailing_bis"]:
        assert tuple(pair) in trailing
        assert tuple(pair) not in _members(snap.zhongshus[1], snap, bars)
    assert all(item.zg != 64 for item in snap.zhongshus)

    snap, _window = _prefix(engine, bars, 50)
    assert len(snap.zhongshus) == 3
    assert snap.zhongshus[0].id == zs1_id
    assert snap.zhongshus[1].id == zs2_id
    zs2 = snap.zhongshus[1]
    zs3 = snap.zhongshus[2]
    assert (zs2.zg, zs2.zd) == (56, 52)
    assert _members(zs2, snap, bars)[-1] == (34, 37)
    _assert_zone(zs3, snap, bars, fixture["at_50"]["zs3"])
    for pair, rng in zip(fixture["at_50"]["zs3"]["members"], fixture["at_50"]["zs3"]["ranges"], strict=True):
        bi = _find(snap, bars, pair[0], pair[1])
        assert (bi.high, bi.low) == (rng["high"], rng["low"])
        assert bi.id not in zs2.bi_ids
        assert bi.id in zs3.bi_ids


def test_empty_intersection_keeps_the_later_two_for_the_next_bi(
    bars_from_prices, config_hash
) -> None:
    prices = [15, 20, 18, 16, 10, 12, 14, 30, 28, 27, 25, 26, 28, 40, 35]
    bars = bars_from_prices(prices)
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=2)

    early, _window = _prefix(engine, bars, 11)
    assert early.zhongshus == ()
    assert [_span(bi, bars) for bi in early.bis] == [(1, 4), (4, 7), (7, 10)]
    assert (early.bis[0].low, early.bis[0].high) == (10, 20)
    assert (early.bis[1].low, early.bis[1].high) == (10, 30)
    assert (early.bis[2].low, early.bis[2].high) == (25, 30)

    full, _window = _prefix(engine, bars, 14)
    assert len(full.zhongshus) == 1
    zs = full.zhongshus[0]
    assert zs.level == 1
    assert (zs.zg, zs.zd, zs.gg, zs.dd) == (30, 25, 40, 10)
    assert zs.direction_into == Direction.UP
    assert _members(zs, full, bars) == [(4, 7), (7, 10), (10, 13)]
    assert _span(full.bis[0], bars) == (1, 4)
    assert full.bis[0].id not in zs.bi_ids
    fourth = _find(full, bars, 10, 13)
    assert (fourth.low, fourth.high, fourth.end_price) == (25, 40, 40)


def test_dropped_bi_is_not_revived(bars_from_prices, load_fixture, config_hash) -> None:
    fixture = load_fixture("golden_zs_drop_no_revive.json")
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])

    snap, _window = _prefix(engine, bars, 11)
    assert snap.zhongshus == ()
    assert [_span(bi, bars) for bi in snap.bis] == [tuple(pair) for pair in fixture["at_11"]["bis"]]
    for bi, rng in zip(snap.bis, fixture["at_11"]["ranges"], strict=True):
        assert bi.direction == Direction(rng["direction"])
        assert (bi.high, bi.low, bi.end_price) == (rng["high"], rng["low"], rng["end_price"])

    snap, _window = _prefix(engine, bars, 12)
    assert snap.zhongshus == ()
    assert [_span(bi, bars) for bi in snap.bis] == [tuple(pair) for pair in fixture["at_12"]["bis"]]
    _assert_fenxing(snap, bars, fixture["at_12"]["fenxing"])

    snap, window = _prefix(engine, bars, 13)
    assert snap.zhongshus == ()
    assert snap.structure_bias == StructureBias(fixture["at_13"]["structure_bias"])
    assert window[-1].close == fixture["at_13"]["close"]
    assert [_span(bi, bars) for bi in snap.bis] == [tuple(pair) for pair in fixture["at_13"]["bis"]]
    first = snap.bis[0]
    last = snap.bis[-1]
    assert first.direction == Direction(fixture["at_13"]["first_bi"]["direction"])
    assert (first.high, first.low, first.end_price) == (
        fixture["at_13"]["first_bi"]["high"],
        fixture["at_13"]["first_bi"]["low"],
        fixture["at_13"]["first_bi"]["end_price"],
    )
    assert last.direction == Direction(fixture["at_13"]["last_bi"]["direction"])
    assert (last.high, last.low, last.end_price) == (
        fixture["at_13"]["last_bi"]["high"],
        fixture["at_13"]["last_bi"]["low"],
        fixture["at_13"]["last_bi"]["end_price"],
    )
    _assert_fenxing(snap, bars, fixture["at_13"]["fenxing"])
    assert _span(first, bars) == (1, 4)


def _assert_zone(zs, snap, bars, expected: dict) -> None:
    assert zs.level == 1
    assert zs.confirmed is True
    assert zs.zg == expected["zg"]
    assert zs.zd == expected["zd"]
    if "gg" in expected:
        assert zs.gg == expected["gg"]
        assert zs.dd == expected["dd"]
    assert zs.direction_into == Direction(expected["direction_into"])
    assert _members(zs, snap, bars) == [tuple(pair) for pair in expected["members"]]


def _assert_fenxing(snap, bars, expected: dict) -> None:
    matches = [fx for fx in snap.fenxings if fx.k_index_mid == expected["mid"]]
    assert len(matches) == 1
    fx = matches[0]
    assert fx.confirmed is True
    assert fx.price == expected["price"]
    assert fx.mark == Mark(expected["mark"])
    endpoints = {point for bi in snap.bis for point in _span(bi, bars)}
    assert expected["mid"] not in endpoints


def test_replaced_third_bi_keeps_its_confirm_bar_and_established_time(
    bars_from_prices, load_fixture, config_hash
) -> None:
    fixture = load_fixture("golden_zs_zd_frozen.json")
    bars = bars_from_prices(fixture["prices"])
    engine = ChanEngine(config_hash=config_hash, min_bi_bars=fixture["min_bi_bars"])
    confirmed, _ = _prefix(engine, bars, 11)
    replaced, _ = _prefix(engine, bars, 13)
    # The third bi 7->10 is confirmed at index 11 and becomes 7->12 at index 13.
    assert confirmed.zhongshus[0].confirm_bar_open_time == bars[11].open_time
    assert replaced.zhongshus[0].confirm_bar_open_time == bars[11].open_time
    third = _find(replaced, bars, 7, 12)
    assert third.established_at == bars[11].close_time
    first = _find(replaced, bars, 1, 4)
    assert first.established_at == bars[5].close_time
