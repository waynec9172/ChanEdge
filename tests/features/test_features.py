"""PR-7 feature channels. Scores use constructor params. No JEV weighting."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from chanedge.chanlun.engine import ChanEngine
from chanedge.domain.bars import Bar, DataQuality, Instrument, MultiTimeframeContext, timeframe_duration
from chanedge.domain.chanlun import Bi, ChanSignal, ChanSnapshot, Fenxing, Segment, Zhongshu
from chanedge.domain.enums import (
    Direction,
    InstrumentSource,
    Mark,
    ProductType,
    RegimeLabel,
    SessionBucket,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
)
from chanedge.domain.params import FeatureParams
from chanedge.features.atr import wilder_atr
from chanedge.features.builder import FeatureBuilder
from chanedge.features.structure import structure_channel
from chanedge.features.version import FEATURE_VERSION
from chanedge.features.volatility import percentile

UTC = timezone.utc
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def make_bars(
    count: int,
    *,
    price: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    volume: float = 1.0,
    volumes: list[float] | None = None,
    prices: list[float] | None = None,
    timeframe: Timeframe = Timeframe.M15,
    origin: datetime = ORIGIN,
    symbol: str = "BTC/USDT",
) -> tuple[Bar, ...]:
    step = timeframe_duration(timeframe)
    bars: list[Bar] = []
    for index in range(count):
        close = price if prices is None else prices[index]
        opened = close if open_price is None else open_price
        upper = close if high is None else high
        lower = close if low is None else low
        open_time = origin + step * index
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + step,
                open=opened,
                high=upper,
                low=lower,
                close=close,
                volume=volume if volumes is None else volumes[index],
                is_closed=True,
                source="binanceusdm",
            )
        )
    return tuple(bars)


def make_ohlc(
    rows: list[tuple[float, float, float, float]],
    *,
    volume: float = 1.0,
    origin: datetime = ORIGIN,
) -> tuple[Bar, ...]:
    step = timeframe_duration(Timeframe.M15)
    bars: list[Bar] = []
    for index, (opened, high, low, close) in enumerate(rows):
        open_time = origin + step * index
        bars.append(
            Bar(
                symbol="BTC/USDT",
                timeframe=Timeframe.M15,
                open_time=open_time,
                close_time=open_time + step,
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=volume,
                is_closed=True,
                source="binanceusdm",
            )
        )
    return tuple(bars)


def make_fx(
    fx_id: str,
    mid: int,
    price: float,
    *,
    mark: Mark = Mark.BOTTOM,
    right: int | None = None,
) -> Fenxing:
    open_time = ORIGIN + timedelta(minutes=15 * mid)
    return Fenxing(
        id=fx_id,
        timeframe=Timeframe.M15,
        mark=mark,
        index=mid,
        time=open_time + timedelta(minutes=15),
        price=price,
        bar_open_time=open_time,
        confirmed=True,
        k_index_left=max(mid - 1, 0),
        k_index_mid=mid,
        k_index_right=mid + 1 if right is None else right,
    )


def make_bi(
    bi_id: str,
    direction: Direction,
    end_fx: str,
    end_price: float,
    *,
    high: float,
    low: float,
    end_mid: int,
    confirmed: bool = True,
) -> Bi:
    end_time = ORIGIN + timedelta(minutes=15 * end_mid)
    return Bi(
        id=bi_id,
        timeframe=Timeframe.M15,
        direction=direction,
        start_fx_id="start-" + bi_id,
        end_fx_id=end_fx,
        start_time=end_time - timedelta(minutes=15),
        end_time=end_time,
        start_price=end_price,
        end_price=end_price,
        high=high,
        low=low,
        bar_count=2,
        confirmed=confirmed,
    )


def make_signal(
    sig_id: str,
    kind: SignalType,
    when: datetime,
    defending: float,
    fx_id: str,
    *,
    prior: float | None = None,
    related: str | None = None,
    price: float = 100.0,
) -> ChanSignal:
    upward = kind in {SignalType.SECOND_BUY, SignalType.THIRD_BUY, SignalType.FIRST_BUY}
    return ChanSignal(
        id=sig_id,
        timeframe=Timeframe.M15,
        type=kind,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=price,
        direction=Direction.UP if upward else Direction.DOWN,
        defending_fx_id=fx_id,
        defending_price=defending,
        related_bi_id="bi-signal",
        bar_open_time=when - timedelta(minutes=15),
        related_zhongshu_id=related,
        prior_extreme=prior,
    )


def make_zs(
    zs_id: str,
    *,
    zg: float,
    zd: float,
    gg: float,
    dd: float,
    bi_ids: tuple[str, ...] = ("b0", "b1", "b2"),
) -> Zhongshu:
    return Zhongshu(
        id=zs_id,
        timeframe=Timeframe.M15,
        zg=zg,
        zd=zd,
        gg=gg,
        dd=dd,
        start_time=ORIGIN,
        end_time=ORIGIN,
        bi_ids=bi_ids,
        direction_into=Direction.DOWN,
        level=1,
        confirmed=True,
    )


def make_segment(
    seg_id: str,
    direction: Direction,
    *,
    low: float,
    high: float,
    bi_ids: tuple[str, ...],
) -> Segment:
    return Segment(
        id=seg_id,
        timeframe=Timeframe.M15,
        direction=direction,
        start_bi_id=bi_ids[0],
        end_bi_id=bi_ids[-1],
        start_time=ORIGIN,
        end_time=ORIGIN + timedelta(minutes=15),
        high=high,
        low=low,
        bi_ids=bi_ids,
        confirmed=True,
        algo="minimal_break",
    )


def make_snapshot(
    *,
    timeframe: Timeframe = Timeframe.M15,
    bias: StructureBias = StructureBias.NEUTRAL,
    bis: tuple[Bi, ...] = (),
    fenxings: tuple[Fenxing, ...] = (),
    zhongshus: tuple[Zhongshu, ...] = (),
    signals: tuple[ChanSignal, ...] = (),
    segments: tuple[Segment, ...] = (),
    active: str | None = None,
    as_of: datetime | None = None,
    bar_count: int = 1,
) -> ChanSnapshot:
    moment = ORIGIN if as_of is None else as_of
    return ChanSnapshot(
        snapshot_id="cs_0123456789abcdef",
        symbol="BTC/USDT",
        timeframe=timeframe,
        as_of=moment,
        config_hash="a" * 64,
        engine_version="engine-v1",
        bar_window_hash="b" * 64,
        bars_start=ORIGIN,
        bars_end=moment,
        bar_count=bar_count,
        fenxings=fenxings,
        bis=bis,
        segments=segments,
        zhongshus=zhongshus,
        signals=signals,
        structure_bias=bias,
        last_confirmed_bi_id=bis[-1].id if bis else None,
        active_zhongshu_id=active,
    )


def make_context(
    bars: tuple[Bar, ...],
    snapshot: ChanSnapshot,
    *,
    snapshot_1h: ChanSnapshot | None = None,
    snapshot_4h: ChanSnapshot | None = None,
    decision_time: datetime | None = None,
) -> MultiTimeframeContext:
    moment = bars[-1].close_time if decision_time is None else decision_time
    higher_1h = snapshot_1h or make_snapshot(timeframe=Timeframe.H1, as_of=moment)
    higher_4h = snapshot_4h or make_snapshot(timeframe=Timeframe.H4, as_of=moment)
    return MultiTimeframeContext(
        context_id="ctx-features",
        symbol="BTC/USDT",
        decision_time=moment,
        bars={Timeframe.M15: bars, Timeframe.H1: (), Timeframe.H4: ()},
        snapshots={Timeframe.M15: snapshot, Timeframe.H1: higher_1h, Timeframe.H4: higher_4h},
        data_quality=DataQuality(stale=False, max_gap_bars=1, missing_bar_count=0),
        instrument=Instrument(
            symbol="BTC/USDT",
            venue="binanceusdm",
            venue_symbol="BTC/USDT:USDT",
            product=ProductType.USDT_PERP,
            contract_size=Decimal("1"),
            price_tick=Decimal("0.1"),
            qty_step=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            margin_asset="USDT",
            leverage_max=20,
            instrument_source=InstrumentSource.EXCHANGE,
        ),
        universe_date=ORIGIN.date(),
        universe_rank=1,
    )


ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "src" / "chanedge" / "features"


def test_feature_version_records_the_locked_formulas() -> None:
    for token in (
        "prior-high-low-are-bi-endpoints-only",
        "missing-prior-high-or-low-skips-0.20-penalty",
        "second-buy-sell-loc-uses-dist-defending-atr",
        "zhongshu-absent-clarity-term-0.5",
        "vol-tent-peak-is-symbol-atr-pct-p50",
    ):
        assert token in FEATURE_VERSION


def test_features_import_only_domain() -> None:
    forbidden = ("chanedge.risk", "chanedge.execution", "chanedge.chanlun", "chanedge.config", "chanedge.jev")
    for path in FEATURES.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            for name in forbidden:
                assert not module.startswith(name), path
        assert "vol_band" not in text
        assert "VOL_BAND" not in text


def test_build_takes_only_the_context(feature_params) -> None:
    assert list(inspect.signature(FeatureBuilder.build).parameters) == ["self", "context"]
    with pytest.raises(TypeError):
        FeatureBuilder(object())
    rejected = feature_params.model_dump()
    rejected["atr_period"] = True
    with pytest.raises(ValueError):
        FeatureParams.model_validate(rejected)
    empty = feature_params.model_dump()
    empty["structure"]["reentry_factor"] = ()
    with pytest.raises(ValueError):
        FeatureParams.model_validate(empty)


def test_wilder_atr_seed_then_smooths() -> None:
    bars = make_ohlc(
        [
            (10, 10, 10, 10),
            (11, 12, 10, 11),
            (10, 11, 9, 10),
            (12, 14, 10, 12),
            (12, 12, 12, 12),
        ]
    )
    values = wilder_atr(bars, 3)
    assert values[:3] == [None, None, None]
    assert values[3] == pytest.approx(8 / 3)
    assert values[4] == pytest.approx(16 / 9)


def test_percentile_interpolates() -> None:
    assert percentile([1, 2, 3], 10) == pytest.approx(1.2)
    assert percentile([3, 1, 2], 50) == pytest.approx(2)
    assert percentile([1, 2, 3], 90) == pytest.approx(2.8)


def test_absent_zhongshu_clarity_term_is_half(feature_params) -> None:
    params = _structure(feature_params, clarity=1)
    vector = _build(params, _candidate())
    assert vector.structure.zs_clarity is None
    assert vector.structure.notes == ("segment_absent", "zhongshu_absent")
    assert vector.structure.subscore == pytest.approx(0.5)
    assert vector.structure.skip is False


def test_present_zhongshu_clarity_uses_the_ratio(feature_params) -> None:
    params = _structure(feature_params, clarity=1)
    zone = make_zs("zs-1", zg=50, zd=32, gg=60, dd=30)
    vector = _build(params, _candidate(), zhongshus=(zone,), active="zs-1")
    assert vector.structure.zs_clarity == pytest.approx(18 / 30)
    assert "zhongshu_absent" not in vector.structure.notes
    assert vector.structure.subscore == pytest.approx(1)
    flat = make_zs("zs-flat", zg=10, zd=10, gg=10, dd=10)
    zero = _build(params, _candidate(), zhongshus=(flat,), active="zs-flat")
    assert zero.structure.zs_clarity == 0
    assert zero.location.pos_in_zs == pytest.approx(0.5)
    assert zero.structure.subscore == 0


def test_overlap_averages_existing_pairs_and_penalises_above_the_line(feature_params) -> None:
    params = _structure(feature_params, overlap=1)
    mixed = _range_bis((0, 10), (0, 1), (0, 10), (100, 110))
    mixed_vector = _build(params, _candidate(), bis=mixed)
    assert mixed_vector.structure.consecutive_bi_overlap_ratio == pytest.approx(0.5)
    assert mixed_vector.structure.subscore == pytest.approx(1 - (0.15 / 0.35))
    assert mixed_vector.structure.penalty == 0
    tight = _range_bis((0, 10), (0, 10), (0, 10), (0, 10))
    ignored = make_bi("wild", Direction.UP, "fx-wild", 1000, high=1000, low=0, end_mid=9, confirmed=False)
    tight_vector = _build(params, None, bis=tight + (ignored,))
    assert tight_vector.structure.consecutive_bi_overlap_ratio == pytest.approx(1)
    assert tight_vector.structure.subscore == 0
    assert tight_vector.structure.penalty == pytest.approx(0.15)
    short = _build(params, _candidate(), bis=_range_bis((0, 10), (0, 10)))
    assert short.structure.consecutive_bi_overlap_ratio == 0


def test_missing_segment_uses_half_and_a_real_segment_uses_the_ratio(feature_params) -> None:
    params = _structure(feature_params, contained=1)
    missing = _build(params, _candidate())
    assert missing.structure.bi_contained_in_segment_ratio is None
    assert "segment_absent" in missing.structure.notes
    assert missing.structure.subscore == pytest.approx(0.5)
    member_ids = ("a", "b", "c")
    bis = (
        make_bi("a", Direction.UP, "fa", 1, high=10, low=0, end_mid=1),
        make_bi("b", Direction.DOWN, "fb", 1, high=11, low=0, end_mid=2),
        make_bi("c", Direction.UP, "fc", 1, high=9, low=1, end_mid=3),
    )
    segment = make_segment("seg", Direction.UP, low=0, high=10, bi_ids=member_ids)
    present = _build(params, _candidate(), bis=bis, segments=(segment,))
    assert present.structure.bi_contained_in_segment_ratio == pytest.approx(2 / 3)
    assert present.structure.subscore == pytest.approx(2 / 3)
    assert "segment_absent" not in present.structure.notes
    agreed = _build(_structure(feature_params, agree=1), _candidate(), bis=bis, segments=(segment,))
    assert agreed.structure.bi_segment_direction_agree == 1
    assert agreed.structure.subscore == pytest.approx(1)


def test_third_buy_leave_starts_after_the_departure_and_second_uses_l1_l0(feature_params) -> None:
    bars = make_ohlc(
        [
            (45, 200, 45, 45),
            (55, 70, 55, 55),
            (60, 80, 60, 60),
            (58, 65, 58, 58),
        ]
    )
    anchor = make_fx("fx-anchor", 0, 45, right=0)
    anchor_bi = make_bi("b2", Direction.DOWN, "fx-anchor", 45, high=45, low=40, end_mid=0)
    zone = make_zs("zs-leave", zg=50, zd=40, gg=80, dd=40, bi_ids=("b0", "b1", "b2"))
    third = make_signal("sig-third", SignalType.THIRD_BUY, bars[-1].close_time, 58, "fx-anchor", related="zs-leave", price=58)
    snapshot = make_snapshot(
        fenxings=(anchor,),
        bis=(anchor_bi,),
        zhongshus=(zone,),
        signals=(third,),
        active="zs-leave",
        as_of=bars[-1].close_time,
        bar_count=4,
    )
    params = _structure(feature_params, clean=1)
    built = structure_channel(snapshot, bars, 3, third, 10, params)
    assert built.breakout_leave_atr == pytest.approx(3)
    assert built.breakout_reentry_bars == 0
    assert built.subscore == pytest.approx(1)
    second = make_signal("sig-second", SignalType.SECOND_BUY, bars[-1].close_time, 12, "fx-anchor", prior=10, price=58)
    second_built = structure_channel(
        make_snapshot(signals=(second,), as_of=bars[-1].close_time),
        bars,
        3,
        second,
        4,
        params,
    )
    assert second_built.breakout_leave_atr == pytest.approx(0.5)
    assert second_built.breakout_reentry_bars == 0
    full = make_signal("sig-full", SignalType.SECOND_BUY, bars[-1].close_time, 18, "fx-anchor", prior=10, price=58)
    full_built = structure_channel(
        make_snapshot(signals=(full,), as_of=bars[-1].close_time),
        bars,
        3,
        full,
        10,
        params,
    )
    assert full_built.subscore == pytest.approx(1)


def test_second_buy_loc_uses_defending_distance_not_prior_low(feature_params) -> None:
    params = _location(feature_params, loc=1).model_copy(update={"atr_period": 1})
    vector = _located(
        params,
        close=100,
        high=101,
        low=99,
        kind=SignalType.SECOND_BUY,
        defending=99,
        prior_low=50,
        prior_high=160,
    )
    assert vector.location.dist_defending_atr == pytest.approx(0.5)
    assert vector.location.dist_prior_low_atr == pytest.approx(25)
    assert vector.location.subscore == pytest.approx(1)
    assert vector.location.at_lower_edge is True
    touched = _located(params, close=100, high=101, low=99, kind=SignalType.SECOND_BUY, defending=100)
    assert touched.location.dist_defending_atr == 0
    assert touched.location.subscore == 0
    assert touched.location.at_lower_edge is False


def test_missing_prior_high_does_not_pay_the_nearby_penalty(feature_params) -> None:
    params = _location(feature_params, room=1).model_copy(update={"atr_period": 1})
    missing = _located(params, close=100, high=110, low=90, kind=SignalType.SECOND_BUY, defending=95)
    assert missing.location.prior_high is None
    assert missing.location.dist_prior_high_atr is None
    assert missing.location.penalty == 0
    assert missing.location.subscore == 0
    nearby = _located(
        params,
        close=100,
        high=105,
        low=95,
        kind=SignalType.SECOND_BUY,
        defending=95,
        prior_high=102,
    )
    assert nearby.location.dist_prior_high_atr == pytest.approx(0.2)
    assert nearby.location.penalty == pytest.approx(0.20)
    negative = _located(
        params,
        close=100,
        high=105,
        low=95,
        kind=SignalType.SECOND_BUY,
        defending=95,
        prior_high=90,
    )
    assert negative.location.dist_prior_high_atr == pytest.approx(-1)
    assert negative.location.penalty == pytest.approx(0.20)
    assert negative.location.subscore == 0
    far = _located(
        params,
        close=100,
        high=105,
        low=95,
        kind=SignalType.SECOND_BUY,
        defending=95,
        prior_high=130,
    )
    assert far.location.dist_prior_high_atr == pytest.approx(3)
    assert far.location.penalty == 0
    assert far.location.subscore == pytest.approx(1)
    zero_atr = _located(feature_params, close=100, high=100, low=100, kind=SignalType.SECOND_BUY, defending=90, prior_high=110)
    assert zero_atr.volatility_volume.atr == 0
    assert zero_atr.location.dist_prior_high_atr == 0
    assert zero_atr.location.penalty == pytest.approx(0.20)


def test_prior_high_ignores_fenxings_that_are_not_bi_endpoints(feature_params) -> None:
    params = feature_params.model_copy(update={"atr_period": 1})
    stray = make_fx("fx-stray", 8, 999, mark=Mark.TOP)
    up_fx = make_fx("fx-up", 4, 50, mark=Mark.TOP)
    signal_fx = make_fx("fx-buy", 10, 40)
    bis = (
        make_bi("down-old", Direction.DOWN, "fx-old", 30, high=40, low=30, end_mid=2),
        make_bi("up", Direction.UP, "fx-up", 50, high=50, low=30, end_mid=4),
        make_bi("down", Direction.DOWN, "fx-buy", 40, high=50, low=40, end_mid=10),
    )
    fenxings = (make_fx("fx-old", 2, 30), up_fx, stray, signal_fx)
    vector = _build(
        params,
        make_signal("sig", SignalType.SECOND_BUY, _close(2), 40, "fx-buy", prior=30, price=100),
        bars=make_bars(2, high=101, low=99),
        bis=bis,
        fenxings=fenxings,
    )
    assert vector.location.prior_high == 50
    assert vector.location.prior_low == 30


def test_third_loc_and_short_loc_keep_their_own_formulas(feature_params) -> None:
    params = _location(feature_params, loc=1).model_copy(update={"atr_period": 1})
    zone = make_zs("zs-3", zg=50, zd=40, gg=80, dd=30)
    third = _located(
        params,
        close=100,
        high=105,
        low=95,
        kind=SignalType.THIRD_BUY,
        defending=53,
        related="zs-3",
        zhongshus=(zone,),
        active="zs-3",
    )
    assert third.location.dist_pullback_to_zg_atr == pytest.approx(0.3)
    assert third.location.dist_defending_atr is None
    assert third.location.subscore == pytest.approx(1 - (0.05 / 0.8))
    assert third.location.at_lower_edge is True
    short = _located(params, close=95, high=100, low=90, kind=SignalType.SECOND_SELL, defending=100, prior_low=94)
    assert short.location.dist_defending_atr == pytest.approx(0.5)
    assert short.location.subscore == pytest.approx(1)
    assert short.location.at_upper_edge is True
    assert short.location.penalty == pytest.approx(0.20)
    no_low = _located(params, close=95, high=100, low=90, kind=SignalType.SECOND_SELL, defending=100)
    assert no_low.location.prior_low is None
    assert no_low.location.penalty == 0


def test_four_hour_position_above_the_range_uses_the_outside_score(feature_params) -> None:
    params = _location(feature_params, htf_pos=1).model_copy(update={"atr_period": 1})
    higher = make_bi("h4", Direction.UP, "h4-fx", 20, high=20, low=10, end_mid=1)
    snapshot_4h = make_snapshot(timeframe=Timeframe.H4, bis=(higher,))
    above = _located(params, close=100, high=101, low=99, kind=SignalType.SECOND_BUY, defending=99, snapshot_4h=snapshot_4h)
    assert above.location.pos_in_4h_range == pytest.approx(9)
    assert above.location.subscore == pytest.approx(0.75)
    flat = make_bi("flat", Direction.UP, "flat-fx", 10, high=10, low=10, end_mid=1)
    flat_4h = make_snapshot(timeframe=Timeframe.H4, bis=(flat,))
    inside = _located(params, close=100, high=101, low=99, kind=SignalType.SECOND_BUY, defending=99, snapshot_4h=flat_4h)
    assert inside.location.pos_in_4h_range == pytest.approx(0.5)
    short_below = _located(
        _location(feature_params, htf_pos=1).model_copy(update={"atr_period": 1}),
        close=5,
        high=6,
        low=4,
        kind=SignalType.SECOND_SELL,
        defending=6,
        snapshot_4h=snapshot_4h,
    )
    assert short_below.location.pos_in_4h_range < 0
    assert short_below.location.subscore == pytest.approx(0.75)


def test_resonance_uses_the_side_map_and_floors_only_15m(feature_params) -> None:
    long = _biased(feature_params, Side.LONG, StructureBias.DOWN, StructureBias.NEUTRAL, StructureBias.UP)
    assert long.resonance.signed_15m == pytest.approx(-1)
    assert long.resonance.signed_4h == pytest.approx(1)
    assert long.resonance.resonance_count == 1
    assert long.resonance.htf_gate_would_pass is True
    assert long.resonance.subscore == pytest.approx(2 / 3)
    short = _biased(feature_params, Side.SHORT, StructureBias.DOWN, StructureBias.NEUTRAL, StructureBias.UP)
    assert short.resonance.htf_gate_would_pass is False
    assert short.resonance.subscore == pytest.approx(0.5)
    assert short.resonance.penalty == 0


def test_signal_bar_short_formula_is_not_the_long_formula_negated(feature_params) -> None:
    bear = make_ohlc([(100, 110, 90, 92)])
    short = _on_bar(feature_params, bear, SignalType.SECOND_SELL, defending=100)
    long = _on_bar(feature_params, bear, SignalType.SECOND_BUY, defending=90)
    assert short.signal_bar.is_bear is True
    assert short.signal_bar.subscore == pytest.approx(0.725)
    assert long.signal_bar.subscore == pytest.approx(0.1425)
    wide = make_ohlc([(100, 101, 99, 100)])
    no_penalty = _on_bar(feature_params, wide, SignalType.SECOND_BUY, defending=99)
    assert no_penalty.signal_bar.penalty == 0
    doji = make_ohlc([(100, 100.02, 99.98, 100)])
    penalised = _on_bar(feature_params, doji, SignalType.SECOND_BUY, defending=99.99)
    assert penalised.signal_bar.penalty == pytest.approx(0.15)
    assert penalised.signal_bar.subscore > 0


def test_vol_tent_is_half_below_min_samples_and_zero_outside_the_band(feature_params) -> None:
    thin = feature_params.model_copy(
        update={
            "atr_period": 1,
            "min_samples": 200,
            "volatility_volume": feature_params.volatility_volume.model_copy(update={"vol_weight": 1, "volume_weight": 0}),
        }
    )
    inside = _vol_bars(201, high=101, low=99)
    vector = _on_bar(thin, inside, SignalType.SECOND_BUY, defending=99)
    assert vector.volatility_volume.vol_n == 199
    assert vector.volatility_volume.in_band is True
    assert vector.volatility_volume.notes == ("vol_center_absent",)
    assert vector.volatility_volume.regime_label is RegimeLabel.UNKNOWN
    assert vector.volatility_volume.subscore == pytest.approx(0.5)
    assert vector.volatility_volume.penalty == 0
    outside = _on_bar(thin, _vol_bars(201, high=110, low=90), SignalType.SECOND_BUY, defending=90)
    assert outside.volatility_volume.in_band is False
    assert outside.volatility_volume.notes == ()
    assert outside.volatility_volume.subscore == 0
    assert outside.volatility_volume.penalty == 0
    centered = feature_params.model_copy(
        update={
            "atr_period": 1,
            "min_samples": 10,
            "volatility_volume": feature_params.volatility_volume.model_copy(update={"vol_weight": 1, "volume_weight": 0}),
        }
    )
    peaked = _on_bar(centered, _vol_bars(30, high=101, low=99), SignalType.SECOND_BUY, defending=99)
    assert peaked.volatility_volume.vol_p50 == pytest.approx(0.02)
    assert peaked.volatility_volume.regime_label is RegimeLabel.HIGH_NORMAL
    assert peaked.volatility_volume.subscore == pytest.approx(1)
    volumes = make_bars(2, high=101, low=99, volumes=[1, 100])
    rel = _on_bar(feature_params.model_copy(update={"atr_period": 1}), volumes, SignalType.SECOND_BUY, defending=99)
    assert rel.volatility_volume.volume_20_median == 1
    assert rel.volatility_volume.rel_volume_20 == pytest.approx(100)


def test_session_buckets_weekend_and_funding_window(feature_params) -> None:
    monday = _session(feature_params, datetime(2024, 1, 1, 0, 0, tzinfo=UTC))
    assert monday.session.hour_utc == 0
    assert monday.session.dow == 0
    assert monday.session.session_bucket is SessionBucket.ASIA
    assert monday.session.minutes_to_funding == 15
    assert monday.session.in_funding_window is True
    assert monday.session.penalty == pytest.approx(0.15)
    assert monday.session.subscore == pytest.approx(0.85)
    later = _session(feature_params, datetime(2024, 1, 1, 0, 15, tzinfo=UTC))
    assert later.session.minutes_to_funding == 30
    assert later.session.in_funding_window is False
    assert later.session.penalty == 0
    assert later.session.subscore == pytest.approx(0.85)
    wrap = _session(feature_params, datetime(2024, 1, 1, 23, 30, tzinfo=UTC))
    assert wrap.session.minutes_to_funding == 15
    assert wrap.session.in_funding_window is True
    assert wrap.session.session_bucket is SessionBucket.LATE
    europe = _session(feature_params, datetime(2024, 1, 1, 6, 45, tzinfo=UTC))
    assert europe.session.hour_utc == 7
    assert europe.session.session_bucket is SessionBucket.EUROPE
    assert europe.session.subscore == pytest.approx(0.95)
    asia = _session(feature_params, datetime(2024, 1, 1, 5, 45, tzinfo=UTC))
    assert asia.session.hour_utc == 6
    assert asia.session.session_bucket is SessionBucket.ASIA
    weekend = _session(feature_params, datetime(2024, 1, 6, 11, 45, tzinfo=UTC))
    assert weekend.session.is_weekend is True
    assert weekend.session.session_bucket is SessionBucket.OVERLAP
    assert weekend.session.subscore == pytest.approx(0.70)
    skipped = feature_params.model_copy(
        update={"session": feature_params.session.model_copy(update={"hard_skip_buckets": ("asia",)})}
    )
    flagged = _session(skipped, datetime(2024, 1, 1, 0, 15, tzinfo=UTC))
    assert flagged.session.hard_skip is True
    assert flagged.session.subscore == pytest.approx(0.85)


def test_same_bar_buy_and_sell_clears_the_candidate(feature_params) -> None:
    when = _close(4)
    sell = make_signal("sig-sell", SignalType.SECOND_SELL, when, 10, "fx", price=100)
    buy = make_signal("sig-buy", SignalType.THIRD_BUY, when, 9, "fx", price=100)
    bars = _range_bars(4)
    vector = _build(feature_params, None, bars=bars, signals=(sell, buy), bis=_range_bis((0, 10), (0, 10), (0, 10), (0, 10)))
    assert vector.candidate_signal_id is None
    assert vector.candidate_side is Side.NONE
    assert vector.ambiguous_signal_ids == ("sig-sell", "sig-buy")
    assert vector.structure.subscore == 0
    assert vector.location.subscore == 0
    assert vector.resonance.subscore == 0
    assert vector.volatility_volume.subscore == 0
    assert vector.signal_bar.subscore == 0
    assert vector.session.subscore == 0
    assert vector.structure.penalty == pytest.approx(0.15)
    assert vector.session.session_multiplier == pytest.approx(0.85)


def test_third_class_beats_second_class_and_first_class_is_ignored(feature_params) -> None:
    when = _close(2)
    second = make_signal("sig-second", SignalType.SECOND_BUY, when, 9, "fx", prior=8)
    third = make_signal("sig-third", SignalType.THIRD_BUY, when, 11, "fx")
    chosen = _build(feature_params, None, bars=make_bars(2), signals=(second, third))
    assert chosen.candidate_signal_id == "sig-third"
    assert chosen.candidate_side is Side.LONG
    assert chosen.ambiguous_signal_ids == ()
    assert chosen.structure.signal_type is SignalType.THIRD_BUY
    first = make_signal("sig-first", SignalType.FIRST_BUY, when, 9, "fx")
    ignored = _build(feature_params, None, bars=make_bars(2), signals=(first,))
    assert ignored.candidate_signal_id is None
    assert ignored.structure.subscore == 0


def test_engine_second_buy_reads_bi_endpoints(feature_params) -> None:
    prices = [50, 60, 50, 40, 30, 37, 44, 50, 44, 38, 34, 37]
    bars = make_bars(len(prices), prices=prices)
    snapshot = ChanEngine(config_hash="a" * 64, min_bi_bars=2).compute(
        bars,
        timeframe=Timeframe.M15,
        as_of=bars[-1].close_time,
    )
    vector = FeatureBuilder(feature_params).build(make_context(bars, snapshot))
    assert vector.feature_version == FEATURE_VERSION
    assert vector.structure.signal_type is SignalType.SECOND_BUY
    assert vector.candidate_side is Side.LONG
    assert vector.location.prior_high == 50
    assert vector.location.prior_low == 30
    assert vector.location.dist_prior_high_atr == 0
    assert vector.location.dist_defending_atr == 0
    assert vector.location.penalty == pytest.approx(0.20)
    assert vector.structure.zs_clarity is None
    assert "zhongshu_absent" in vector.structure.notes
    assert vector.structure.skip is False
    assert all(channel.skip is False for channel in (
        vector.structure,
        vector.location,
        vector.resonance,
        vector.volatility_volume,
        vector.signal_bar,
        vector.session,
    ))


def test_decision_bar_must_be_in_the_window(feature_params) -> None:
    bars = make_bars(1)
    with pytest.raises(ValueError, match="decision bar"):
        FeatureBuilder(feature_params).build(
            make_context(bars, make_snapshot(), decision_time=bars[-1].close_time + timedelta(minutes=15))
        )
    foreign = make_bars(1, symbol="ETH/USDT")
    with pytest.raises(ValueError, match="symbol"):
        FeatureBuilder(feature_params).build(make_context(foreign, make_snapshot()))


def _structure(params, **weights):
    current = {name: 0.0 for name in ("overlap", "agree", "contained", "clarity", "clean")}
    current.update(weights)
    return params.model_copy(update={"structure": params.structure.model_copy(update=current)})


def _location(params, **weights):
    current = {name: 0.0 for name in ("loc", "htf_pos", "room")}
    current.update(weights)
    return params.model_copy(update={"location": params.location.model_copy(update=current)})


def _close(count: int) -> datetime:
    return ORIGIN + timedelta(minutes=15 * count)


def _candidate():
    return make_signal("sig", SignalType.SECOND_BUY, _close(2), 90, "fx-buy", prior=80)


def _range_bis(*ranges: tuple[float, float]) -> tuple:
    bis = []
    for index, (low, high) in enumerate(ranges):
        direction = Direction.DOWN if index % 2 == 0 else Direction.UP
        bis.append(make_bi(f"b{index}", direction, f"fx{index}", high, high=high, low=low, end_mid=index))
    return tuple(bis)


def _range_bars(count: int):
    return make_bars(count, high=101, low=99)


def _build(params, signal, *, bars=None, bis=(), fenxings=(), zhongshus=(), signals=None, segments=(), active=None, snapshot_4h=None, snapshot_1h=None):
    series = make_bars(2) if bars is None else bars
    moment = series[-1].close_time
    chosen = () if signal is None and signals is None else ((signal,) if signals is None else signals)
    if signal is not None and signals is None:
        chosen = (signal.model_copy(update={"time": moment, "bar_open_time": series[-1].open_time}),)
    snapshot = make_snapshot(
        bis=bis,
        fenxings=fenxings,
        zhongshus=zhongshus,
        signals=chosen,
        segments=segments,
        active=active,
        as_of=moment,
        bar_count=len(series),
    )
    return FeatureBuilder(params).build(
        make_context(series, snapshot, snapshot_1h=snapshot_1h, snapshot_4h=snapshot_4h, decision_time=moment)
    )


def _located(params, *, close, high, low, kind, defending, prior_low=None, prior_high=None, related=None, zhongshus=(), active=None, snapshot_4h=None):
    bars = make_bars(2, price=close, high=high, low=low)
    fenxings = []
    bis = []
    signal_fx = "fx-signal"
    fenxings.append(make_fx(signal_fx, 3, defending))
    if prior_low is not None:
        fenxings.append(make_fx("fx-low", 1, prior_low))
        bis.append(make_bi("bi-low", Direction.DOWN, "fx-low", prior_low, high=prior_low, low=prior_low, end_mid=1))
    if prior_high is not None:
        fenxings.append(make_fx("fx-high", 2, prior_high, mark=Mark.TOP))
        bis.append(make_bi("bi-high", Direction.UP, "fx-high", prior_high, high=prior_high, low=prior_low or prior_high, end_mid=2))
    signal = make_signal("sig", kind, bars[-1].close_time, defending, signal_fx, prior=prior_low, related=related, price=close)
    return _build(
        params,
        signal,
        bars=bars,
        bis=tuple(bis),
        fenxings=tuple(fenxings),
        zhongshus=zhongshus,
        active=active,
        snapshot_4h=snapshot_4h,
    )


def _biased(params, side, bias_15m, bias_1h, bias_4h):
    kind = SignalType.SECOND_BUY if side is Side.LONG else SignalType.SECOND_SELL
    bars = make_bars(2)
    moment = bars[-1].close_time
    signal = make_signal("sig", kind, moment, 90, "fx")
    snapshot = make_snapshot(signals=(signal,), bias=bias_15m, as_of=moment, bar_count=2)
    return FeatureBuilder(params).build(
        make_context(
            bars,
            snapshot,
            snapshot_1h=make_snapshot(timeframe=Timeframe.H1, bias=bias_1h, as_of=moment),
            snapshot_4h=make_snapshot(timeframe=Timeframe.H4, bias=bias_4h, as_of=moment),
        )
    )


def _on_bar(params, bars, kind, defending):
    moment = bars[-1].close_time
    signal = make_signal("sig", kind, moment, defending, "fx", price=bars[-1].close)
    return _build(params, signal, bars=bars)


def _vol_bars(count, *, high, low):
    return make_bars(count, price=100, high=high, low=low)


def _session(params, open_time):
    bars = make_bars(1, origin=open_time)
    return _on_bar(params, bars, SignalType.SECOND_BUY, 99)


def test_third_buy_leave_scans_from_the_frozen_confirm_bar(feature_params) -> None:
    bars = make_ohlc(
        [
            (45, 200, 45, 45),
            (55, 90, 55, 55),
            (60, 80, 60, 60),
            (58, 65, 58, 58),
        ]
    )
    # The third bi's endpoint was later replaced, so its end fenxing now confirms on bar 2.
    moved = make_fx("fx-moved", 1, 45, right=2)
    moved_bi = make_bi("b2", Direction.DOWN, "fx-moved", 45, high=45, low=40, end_mid=1)
    zone = make_zs("zs-frozen", zg=50, zd=40, gg=90, dd=40).model_copy(
        update={"confirm_bar_open_time": bars[0].open_time}
    )
    third = make_signal("sig-third", SignalType.THIRD_BUY, bars[-1].close_time, 58, "fx-moved", related="zs-frozen", price=58)
    snapshot = make_snapshot(
        fenxings=(moved,),
        bis=(moved_bi,),
        zhongshus=(zone,),
        signals=(third,),
        active="zs-frozen",
        as_of=bars[-1].close_time,
        bar_count=4,
    )
    built = structure_channel(snapshot, bars, 3, third, 10, _structure(feature_params, clean=1))
    assert built.breakout_leave_atr == pytest.approx(4)
