from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from chanedge.domain.bars import Bar, DataQuality, Instrument, MultiTimeframeContext
from chanedge.domain.chanlun import Bi, ChanSignal, ChanSnapshot, Fenxing, Segment, Zhongshu
from chanedge.domain.decision import (
    CancelAck,
    ChartFrame,
    ComponentScore,
    Decision,
    FeatureVector,
    HardRuleResult,
    JevAssessment,
    LocationFeatures,
    OrderAck,
    OrderIntent,
    ReasonStep,
    ResonanceFeatures,
    SessionFeatures,
    SignalBarFeatures,
    SnapshotIds,
    StructureFeatures,
    Veto,
    VolatilityFeatures,
)
from chanedge.domain.enums import (
    CHANNEL_NAMES,
    DecisionAction,
    Direction,
    ExitKind,
    ExitReason,
    FillModel,
    InstrumentSource,
    OrderSide,
    ProductType,
    ProposedAction,
    ReasonStage,
    RegimeLabel,
    SessionBucket,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
    VetoCode,
)
from chanedge.domain.ports import Broker, ChanEngine, MarketDataPort
from chanedge.domain.risk import (
    AmendStop,
    ExitInstruction,
    InvalidationSpec,
    PartialTarget,
    PositionReview,
    PositionState,
    RiskPlan,
    TrailRule,
)

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)


def test_field_names_match_section6() -> None:
    expected = {
        Bar: {
            "symbol", "timeframe", "open_time", "close_time", "open", "high", "low", "close",
            "volume", "quote_volume", "trades", "is_closed", "source",
        },
        Fenxing: {
            "id", "timeframe", "mark", "index", "time", "price", "bar_open_time", "confirmed",
            "k_index_left", "k_index_mid", "k_index_right",
        },
        Bi: {
            "id", "timeframe", "direction", "start_fx_id", "end_fx_id", "start_time", "end_time",
            "start_price", "end_price", "high", "low", "bar_count", "confirmed", "established_at",
        },
        Segment: {
            "id", "timeframe", "direction", "start_bi_id", "end_bi_id", "start_time", "end_time",
            "high", "low", "bi_ids", "confirmed", "algo",
        },
        Zhongshu: {
            "id", "timeframe", "zg", "zd", "gg", "dd", "start_time", "end_time", "bi_ids",
            "direction_into", "level", "confirmed", "confirm_bar_open_time",
        },
        ChanSignal: {
            "id", "timeframe", "type", "status", "time", "price", "direction", "defending_fx_id",
            "defending_price", "related_zhongshu_id", "related_bi_id", "bar_open_time",
            "prior_extreme", "notes",
        },
        ChanSnapshot: {
            "snapshot_id", "symbol", "timeframe", "as_of", "config_hash", "engine_version",
            "bar_window_hash", "bars_start", "bars_end", "bar_count", "fenxings", "bis",
            "segments", "zhongshus", "signals", "structure_bias", "last_confirmed_bi_id",
            "active_zhongshu_id",
        },
        Instrument: {
            "symbol", "venue", "venue_symbol", "product", "contract_size", "price_tick",
            "qty_step", "min_qty", "min_notional", "margin_asset", "leverage_max",
            "instrument_source",
        },
        FeatureVector: {
            "feature_version", "symbol", "decision_time", "candidate_signal_id", "candidate_side",
            "ambiguous_signal_ids", "structure", "location", "resonance", "volatility_volume",
            "signal_bar", "session",
        },
        JevAssessment: {
            "jev_version", "calibrated", "candidate_side", "score", "p_buy", "p_sell", "p_hold",
            "components", "reasons", "threshold", "proposed_action", "systemone_status",
            "systemone_model", "quality_choice", "quality_choice_confidence", "systemone_ms",
        },
        HardRuleResult: {"passed", "vetoes"},
        RiskPlan: {
            "symbol", "side", "entry_reference", "atr", "structure_stop_price", "stop_buffer",
            "defending_fx_id", "invalidation", "risk_fraction", "target_risk_fraction",
            "realized_risk_fraction", "cost_r", "binding_constraint", "equity_quote", "qty",
            "notional", "max_notional", "partial_targets", "trail", "rejected", "reject_reason",
        },
        OrderIntent: {
            "intent_id", "decision_id", "symbol", "side", "order_type", "qty", "reduce_only",
            "client_order_id", "limit_price",
        },
        PositionState: {
            "symbol", "qty", "avg_price", "stop_price", "plan", "entry_decision_id",
            "entry_decision_time", "entry_bar_open_time",
        },
        ChartFrame: {
            "symbol", "timeframe", "as_of", "snapshot_id", "structure_bias", "bars", "bis",
            "zhongshus", "signals", "position", "stop_price", "assessment", "veto_codes",
            "universe_rank", "last_action",
        },
        Decision: {
            "decision_id", "symbol", "time", "action", "size", "stop", "targets", "reason_chain",
            "snapshot_ids", "feature_vector", "assessment", "hard_rule", "risk_plan", "order_ids",
        },
    }
    for model, names in expected.items():
        assert set(model.model_fields) == names, model.__name__
    assert "bars" not in ChanSnapshot.model_fields
    assert "fill_model" not in OrderIntent.model_fields
    assert "trigger_price" not in OrderIntent.model_fields
    assert "opened_decision_id" not in PositionState.model_fields


def test_snapshot_sequences_are_tuples_and_cannot_be_mutated() -> None:
    bi = _bi()
    items = [bi]
    snap = _snapshot(bis=items)
    items.append(bi)
    assert snap.bis == (bi,)
    assert isinstance(snap.bis, tuple)
    assert hash(snap) == hash(snap)
    with pytest.raises(AttributeError):
        snap.bis.append(bi)
    with pytest.raises(ValidationError):
        snap.bis = ()


def test_candidate_signal_is_rejected_and_confirmed_is_kept() -> None:
    with pytest.raises(ValidationError):
        _signal(status=SignalStatus.CANDIDATE)
    with pytest.raises(ValidationError):
        _signal(status=SignalStatus.INVALIDATED)
    kept = _signal()
    assert kept.status is SignalStatus.CONFIRMED
    assert kept.type is SignalType.SECOND_BUY


def test_order_intent_has_no_fill_fields_and_proposed_action_is_separate() -> None:
    intent = OrderIntent(
        intent_id="i1",
        decision_id="dec_ad70ba8d71d416fd",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        qty=Decimal("1"),
        reduce_only=False,
        client_order_id="dec_ad70ba8d71d416fd",
    )
    assert intent.limit_price is None
    assert ProposedAction.BUY.value == "BUY"
    assert DecisionAction.ENTER_LONG.value == "ENTER_LONG"
    assert OrderAck(client_order_id="c", accepted=True).accepted
    assert CancelAck(client_order_id="c", accepted=False).accepted is False


def test_hard_rule_passed_matches_vetoes_and_review_excludes_both() -> None:
    assert HardRuleResult(passed=True).passed
    veto = Veto(code=VetoCode.NO_CANDIDATE, message="none", measured="", threshold="")
    blocked = HardRuleResult(passed=False, vetoes=(veto,))
    assert blocked.passed is False
    with pytest.raises(ValidationError):
        HardRuleResult(passed=True, vetoes=(veto,))
    with pytest.raises(ValidationError):
        HardRuleResult(passed=False)
    exit_only = PositionReview(
        exit=ExitInstruction(
            kind=ExitKind.EXIT,
            reason=ExitReason.OPPOSITE_SIGNAL,
            qty=Decimal("1"),
            trigger_price=100.0,
            fill_model=FillModel.NEXT_OPEN,
        )
    )
    assert exit_only.amend_stop is None
    with pytest.raises(ValidationError):
        PositionReview(exit=exit_only.exit, amend_stop=AmendStop(new_stop_price=100.0, reason="breakeven"))


def test_risk_plan_rejection_shape() -> None:
    plan = _accepted_plan()
    assert plan.rejected is False
    assert plan.reject_reason is None
    rejected = RiskPlan(
        symbol="BTC/USDT",
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=Decimal("0"),
        notional=Decimal("0"),
        max_notional=Decimal("20000"),
        rejected=True,
        reject_reason=VetoCode.INSTRUMENT_SPEC,
        binding_constraint="instrument_spec",
    )
    assert rejected.realized_risk_fraction is None
    assert rejected.cost_r is None
    with pytest.raises(ValidationError):
        _revalidate(rejected, realized_risk_fraction=Decimal("0.001"))
    with pytest.raises(ValidationError):
        _revalidate(plan, cost_r=None)


def test_feature_vector_and_six_channel_assessment_build() -> None:
    features = _features()
    assert features.structure.skip is False
    assert features.candidate_side is Side.NONE
    assessment = _assessment()
    assert assessment.calibrated is False
    assert assessment.proposed_action is ProposedAction.HOLD
    assert set(assessment.components) == set(CHANNEL_NAMES)
    with pytest.raises(ValidationError):
        _revalidate(assessment, components={"structure": assessment.components["structure"]})


def test_context_requires_three_timeframes_and_rank_starts_at_one() -> None:
    context = _context()
    assert context.universe_rank == 1
    assert set(context.bars) == set(Timeframe)
    with pytest.raises(ValidationError):
        _revalidate(context, universe_rank=0)
    with pytest.raises(ValidationError):
        _revalidate(context, bars={Timeframe.M15: ()})
    frame = ChartFrame(
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        as_of=T1,
        snapshot_id="cs_0123456789abcdef",
        structure_bias=StructureBias.UP,
        bars=(),
        bis=(),
        zhongshus=(),
        signals=(),
        last_action=DecisionAction.HOLD,
    )
    assert frame.position is None
    with pytest.raises(ValidationError):
        _revalidate(frame, universe_rank=0)
    decision = Decision(
        decision_id="dec_ad70ba8d71d416fd",
        symbol="BTC/USDT",
        time=T1,
        action=DecisionAction.HOLD,
        snapshot_ids=SnapshotIds(),
        reason_chain=(ReasonStep(stage=ReasonStage.RULES, code="no_candidate", detail=""),),
    )
    assert decision.feature_vector is None
    assert decision.hard_rule is None


def test_domain_sources_validate_on_construction() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "chanedge" / "domain"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "model_construct" not in text
    assert "isoformat" not in text
    assert "@dataclass" not in text
    assert ChanEngine is not None
    assert Broker is not None
    assert MarketDataPort is not None


def _revalidate(model: object, **update: object) -> object:
    data = model.model_dump()
    data.update(update)
    return type(model).model_validate(data)


def _bi() -> Bi:
    return Bi(
        id="bi:15m:down:2024-01-01T00:00:00.000Z:2024-01-01T00:15:00.000Z:100.00000000:90.00000000",
        timeframe=Timeframe.M15,
        direction=Direction.DOWN,
        start_fx_id="fx-start",
        end_fx_id="fx-end",
        start_time=T0,
        end_time=T1,
        start_price=100.0,
        end_price=90.0,
        high=100.0,
        low=90.0,
        bar_count=2,
        confirmed=True,
    )


def _snapshot(bis: list[Bi] | tuple[Bi, ...] = ()) -> ChanSnapshot:
    held = tuple(bis)
    return ChanSnapshot(
        snapshot_id="cs_0123456789abcdef",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        as_of=T1,
        config_hash="a" * 64,
        engine_version="engine-v1",
        bar_window_hash="b" * 64,
        bars_start=T0,
        bars_end=T1,
        bar_count=2,
        fenxings=(),
        bis=held,
        segments=(),
        zhongshus=(),
        signals=(),
        structure_bias=StructureBias.UP,
        last_confirmed_bi_id=held[0].id if held else None,
    )


def _signal(**overrides: object) -> ChanSignal:
    values: dict[str, object] = {
        "id": "sig:15m:second_buy:2024-01-01T00:15:00.000Z:100.50000000",
        "timeframe": Timeframe.M15,
        "type": SignalType.SECOND_BUY,
        "status": SignalStatus.CONFIRMED,
        "time": T1,
        "price": 100.5,
        "direction": Direction.UP,
        "defending_fx_id": "fx-end",
        "defending_price": 100.5,
        "related_bi_id": "bi-1",
        "bar_open_time": T1,
        "prior_extreme": 90.0,
    }
    values.update(overrides)
    return ChanSignal(**values)


def _accepted_plan() -> RiskPlan:
    return RiskPlan(
        symbol="BTC/USDT",
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=Decimal("1"),
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=100.0,
        atr=1.0,
        structure_stop_price=99.0,
        stop_buffer=0.15,
        defending_fx_id="fx-end",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL,),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=99.0,
            defending_fx_id="fx-end",
            effective_after=T1,
        ),
        realized_risk_fraction=Decimal("0.005"),
        cost_r=Decimal("0.35"),
        binding_constraint="risk_fraction",
        partial_targets=(PartialTarget(fraction=0.5, price=101.5, reason="prior_swing"),),
        trail=TrailRule(
            kind=TrailKind.STRUCTURE_FENXING,
            arm_r=1.0,
            breakeven_price=100.0,
            buffer=0.15,
        ),
    )


def _features() -> FeatureVector:
    structure = StructureFeatures(
        consecutive_bi_overlap_ratio=0.0,
        bi_segment_direction_agree=0.5,
        bi_contained_in_segment_ratio=None,
        zs_clarity=None,
        zs_bi_count=0,
        zs_overlap_valid=False,
        breakout_leave_atr=0.0,
        breakout_reentry_bars=0,
        signal_type=None,
        signal_confirmed=False,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    location = LocationFeatures(
        price=100.0,
        zs_zg=None,
        zs_zd=None,
        zs_gg=None,
        zs_dd=None,
        dist_zg_atr=None,
        dist_zd_atr=None,
        pos_in_zs=None,
        dist_pullback_to_zg_atr=None,
        dist_pullback_to_zd_atr=None,
        prior_high=None,
        prior_low=None,
        dist_prior_high_atr=None,
        dist_prior_low_atr=None,
        dist_defending_atr=None,
        htf_range_low=None,
        htf_range_high=None,
        pos_in_4h_range=None,
        at_lower_edge=False,
        at_upper_edge=False,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    resonance = ResonanceFeatures(
        bias_15m=StructureBias.NEUTRAL,
        bias_1h=StructureBias.NEUTRAL,
        bias_4h=StructureBias.NEUTRAL,
        signed_15m=0.0,
        signed_1h=0.0,
        signed_4h=0.0,
        signal_direction=Side.NONE,
        resonance_count=0,
        htf_gate_would_pass=False,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    volatility = VolatilityFeatures(
        atr=0.0,
        atr_pct=0.0,
        atr_pct_min=0.001,
        atr_pct_max=0.030,
        in_band=False,
        rel_volume_20=0.0,
        volume_20_median=0.0,
        vol_p10=None,
        vol_p50=None,
        vol_p90=None,
        vol_n=0,
        regime_label=RegimeLabel.UNKNOWN,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    signal_bar = SignalBarFeatures(
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        range=2.0,
        range_pct=0.02,
        close_location=0.5,
        body_ratio=0.0,
        upper_wick_ratio=0.5,
        lower_wick_ratio=0.5,
        is_bull=False,
        is_bear=False,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    session = SessionFeatures(
        hour_utc=0,
        dow=0,
        session_bucket=SessionBucket.ASIA,
        is_weekend=False,
        minutes_to_funding=60,
        in_funding_window=False,
        session_multiplier=0.85,
        hard_skip=False,
        subscore=0.85,
        penalty=0.0,
        skip=False,
    )
    return FeatureVector(
        feature_version="feature-v1",
        symbol="BTC/USDT",
        decision_time=T1,
        candidate_signal_id=None,
        candidate_side=Side.NONE,
        ambiguous_signal_ids=(),
        structure=structure,
        location=location,
        resonance=resonance,
        volatility_volume=volatility,
        signal_bar=signal_bar,
        session=session,
    )


def _assessment() -> JevAssessment:
    components = {
        name: ComponentScore(
            channel=name,
            subscore=0.0,
            penalty=0.0,
            adjusted=0.0,
            weight=0.0,
            contribution=0.0,
            skip=False,
            raw={},
        )
        for name in CHANNEL_NAMES
    }
    return JevAssessment(
        jev_version="weighted-v1",
        calibrated=False,
        candidate_side=Side.NONE,
        score=0.0,
        p_buy=0.0,
        p_sell=0.0,
        p_hold=1.0,
        components=components,
        reasons=(),
        threshold=0.62,
        proposed_action=ProposedAction.HOLD,
    )


def _context() -> MultiTimeframeContext:
    empty = _snapshot()
    return MultiTimeframeContext(
        context_id="ctx-1",
        symbol="BTC/USDT",
        decision_time=T1,
        bars={timeframe: () for timeframe in Timeframe},
        snapshots={
            Timeframe.M15: empty,
            Timeframe.H1: empty.model_copy(update={"timeframe": Timeframe.H1}),
            Timeframe.H4: empty.model_copy(update={"timeframe": Timeframe.H4}),
        },
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
        universe_date=date(2024, 1, 1),
        universe_rank=1,
    )
