"""Direct plan_entry and review_open behavior. No pipeline."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from chanedge.domain.bars import (
    Bar,
    DataQuality,
    Instrument,
    MultiTimeframeContext,
    timeframe_duration,
)
from chanedge.domain.chanlun import Bi, ChanSignal, ChanSnapshot, Fenxing, Zhongshu
from chanedge.domain.decision import (
    ComponentScore,
    FeatureVector,
    HardRuleResult,
    JevAssessment,
    LocationFeatures,
    ResonanceFeatures,
    SessionFeatures,
    SignalBarFeatures,
    StructureFeatures,
    Veto,
    VolatilityFeatures,
)
from chanedge.domain.enums import (
    CHANNEL_NAMES,
    AmendReason,
    Direction,
    ExitKind,
    ExitReason,
    FillModel,
    InstrumentSource,
    Mark,
    PartialReason,
    ProductType,
    ProposedAction,
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
from chanedge.domain.params import RiskParams
from chanedge.domain.ports import RiskManager as RiskPort
from chanedge.domain.risk import AccountView, PositionState, RiskPlan
from chanedge.risk.size import RiskManager

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
T2 = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
T3 = datetime(2024, 1, 1, 0, 45, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
RISK = ROOT / "src" / "chanedge" / "risk"
_LITERALS = (
    "0.005",
    "0.40",
    "0.62",
    "20000",
    "14706",
    "0.15",
    "wilder",
    "pipeline_timeout",
    "MIN_QTY",
)
_FIELDS = (
    "risk_fraction",
    "max_notional_quote",
    "max_gross_notional_quote",
    "max_open_positions",
    "max_same_direction",
    "max_leverage",
    "max_cost_r",
    "stop_buffer_atr",
    "partial_fraction",
    "r_fallback",
    "arm_r",
    "fee_bps",
    "slippage_bps",
)


def test_risk_imports_only_domain_and_keeps_locks_out_of_source() -> None:
    forbidden = (
        "chanedge.rules",
        "chanedge.features",
        "chanedge.jev",
        "chanedge.config",
        "chanedge.marketdata",
        "chanedge.chanlun",
        "chanedge.execution",
        "chanedge.app",
        "chanedge.journal",
        "chanedge.backtest",
        "chanedge.monitor",
    )
    init = (RISK / "__init__.py").read_text(encoding="utf-8")
    assert "import" not in init
    for path in RISK.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            for name in forbidden:
                assert not module.startswith(name), path
        if path.name != "__init__.py":
            for literal in _LITERALS:
                assert literal not in source, (path.name, literal)
    review = (RISK / "review.py").read_text(encoding="utf-8").lower()
    for token in ("atr", "reduce", "intrabar", "rulegate", "riskparams"):
        assert token not in review


def test_signatures_match_the_protocol_and_params_have_no_defaults() -> None:
    assert list(inspect.signature(RiskManager.plan_entry).parameters) == [
        "self",
        "context",
        "features",
        "assessment",
        "rules",
        "account",
    ]
    assert list(inspect.signature(RiskManager.review_open).parameters) == [
        "self",
        "context",
        "position",
    ]
    assert list(inspect.signature(RiskPort.plan_entry).parameters) == list(
        inspect.signature(RiskManager.plan_entry).parameters
    )
    assert list(inspect.signature(RiskPort.review_open).parameters) == list(
        inspect.signature(RiskManager.review_open).parameters
    )
    with pytest.raises(TypeError):
        RiskManager(object())  # type: ignore[arg-type]
    for name in _FIELDS:
        assert RiskParams.model_fields[name].is_required()
    made = _params(risk_fraction=0.005, fee_bps=5)
    assert made.risk_fraction == Decimal("0.005")
    assert made.fee_bps == Decimal("5")
    assert _params(stop_buffer_atr=Decimal("0")).stop_buffer_atr == 0
    assert _params(max_cost_r=Decimal("1")).max_cost_r == 1
    assert _params(partial_fraction=Decimal("1")).partial_fraction == 1
    with pytest.raises(ValueError):
        _params(max_open_positions=True)
    with pytest.raises(ValueError):
        _params(max_leverage=True)
    with pytest.raises(ValueError):
        _params(risk_fraction=True)
    with pytest.raises(ValueError):
        _params(fee_bps=float("nan"))
    with pytest.raises(ValueError):
        _params(max_cost_r=Decimal("0"))
    with pytest.raises(ValueError):
        _params(max_cost_r=Decimal("1.01"))
    with pytest.raises(ValueError):
        _params(partial_fraction=Decimal("0"))
    with pytest.raises(ValueError):
        _params(arm_r=Decimal("0"))
    with pytest.raises(ValueError):
        _params(r_fallback=Decimal("0"))
    with pytest.raises(ValueError):
        _params(max_notional_quote=Decimal("0"))
    with pytest.raises(ValueError):
        _params(max_gross_notional_quote=Decimal("-1"))
    with pytest.raises(ValueError):
        _params(stop_buffer_atr=Decimal("-0.01"))
    with pytest.raises(ValueError):
        _params(slippage_bps=Decimal("-1"))
    with pytest.raises(ValueError):
        _params(max_same_direction=3, max_open_positions=2)
    with pytest.raises(ValueError):
        _params(max_open_positions=0)
    with pytest.raises(ValueError):
        _params(max_leverage=1.5)


def test_default_long_is_about_14706_and_binds_risk_fraction() -> None:
    plan = _plan()
    assert plan.rejected is False
    assert plan.side is Side.LONG
    assert plan.qty == Decimal("147.058")
    assert plan.notional == Decimal("14705.8")
    assert abs(plan.notional - Decimal("14706")) < 1
    assert plan.notional < Decimal("20000")
    assert plan.binding_constraint == "risk_fraction"
    assert plan.max_notional == Decimal("20000")
    assert plan.target_risk_fraction == Decimal("0.005")
    assert plan.risk_fraction == Decimal("0.005")
    assert plan.realized_risk_fraction == Decimal("0.004999972")
    assert plan.realized_risk_fraction < plan.target_risk_fraction
    assert plan.cost_r == Decimal("0.0012") / Decimal("0.0034")
    assert plan.entry_reference == 100.0
    assert plan.atr == pytest.approx(1.0)
    assert plan.structure_stop_price == pytest.approx(99.66)
    assert plan.stop_buffer == pytest.approx(0.15)
    assert plan.defending_fx_id == "fx-def"
    assert type(plan.qty) is Decimal
    assert type(plan.notional) is Decimal
    trail = plan.trail
    assert trail is not None
    assert trail.kind is TrailKind.STRUCTURE_FENXING
    assert trail.arm_r == pytest.approx(1.0)
    assert trail.breakeven_price == plan.entry_reference
    assert trail.buffer == plan.stop_buffer
    assert trail.ratchet is None
    assert plan.partial_targets[0].reason is PartialReason.R_MULTIPLE
    assert plan.partial_targets[0].fraction == pytest.approx(0.5)
    assert plan.partial_targets[0].price == pytest.approx(100.51)
    assert plan.invalidation is not None
    assert plan.invalidation.effective_after == T1
    assert plan.invalidation.stop_price == plan.structure_stop_price


def test_short_mirror_keeps_qty_positive() -> None:
    plan = _short_plan()
    assert plan.rejected is False
    assert plan.side is Side.SHORT
    assert plan.qty == Decimal("147.058")
    assert plan.qty > 0
    assert plan.notional == Decimal("14705.8")
    assert plan.structure_stop_price == pytest.approx(100.34)
    assert plan.binding_constraint == "risk_fraction"
    assert plan.invalidation is not None
    assert plan.invalidation.opposite_signal_types == (
        SignalType.SECOND_BUY,
        SignalType.THIRD_BUY,
    )
    assert plan.invalidation.htf_bias_exit == (
        StructureBias.UP,
        StructureBias.BREAKOUT_UP,
    )


def test_direct_call_sizes_hold_and_a_failed_gate() -> None:
    held = _plan(action=ProposedAction.HOLD)
    assert held.rejected is False
    assert held.qty == Decimal("147.058")
    blocked = _plan(passed=False)
    assert blocked.rejected is False
    assert blocked.binding_constraint == "risk_fraction"


def test_inputs_are_not_mutated() -> None:
    manager, context, features, assessment, rules, account = _pieces()
    before = (
        rules.model_dump(),
        assessment.model_dump(),
        features.model_dump(),
        account.model_dump(),
    )
    manager.plan_entry(context, features, assessment, rules, account)
    assert (
        rules.model_dump(),
        assessment.model_dump(),
        features.model_dump(),
        account.model_dump(),
    ) == before


def test_entry_is_the_signal_close_and_atr_is_copied() -> None:
    plan = _plan(atr=2.5)
    assert plan.entry_reference == 100.0
    assert plan.atr == pytest.approx(2.5)
    assert plan.stop_buffer == pytest.approx(0.375)
    assert plan.structure_stop_price == pytest.approx(99.43)


def test_stop_rounds_away_from_entry() -> None:
    long_plan = _plan(defending=99.816)
    assert long_plan.rejected is False
    assert long_plan.structure_stop_price == pytest.approx(99.66)
    assert long_plan.structure_stop_price < 99.665
    short_plan = _plan(
        side=Side.SHORT,
        action=ProposedAction.SELL,
        signal_type=SignalType.SECOND_SELL,
        defending=100.0,
        tick=Decimal("0.1"),
    )
    assert short_plan.reject_reason is VetoCode.COST_R
    assert short_plan.structure_stop_price == pytest.approx(100.2)
    assert short_plan.structure_stop_price > 100.15


def test_narrow_stop_is_cost_r_before_the_notional_cap() -> None:
    plan = _plan(defending=99.95)
    assert plan.reject_reason is VetoCode.COST_R
    assert plan.binding_constraint == "cost_r"
    assert plan.cost_r == Decimal("0.6")
    assert plan.realized_risk_fraction is None
    assert plan.qty == 0
    assert plan.notional == 0
    assert plan.structure_stop_price == pytest.approx(99.80)
    assert plan.partial_targets == ()
    assert plan.trail is None
    assert plan.invalidation is None


def test_cost_r_equal_to_the_cap_is_accepted() -> None:
    plan = _plan(defending=99.85)
    assert plan.rejected is False
    assert plan.cost_r == Decimal("0.4")
    assert plan.notional == Decimal("16666.6")
    assert plan.notional < Decimal("20000")
    assert plan.binding_constraint == "risk_fraction"


def test_equity_5000_gross_uses_the_levered_cap() -> None:
    plan = _plan(equity=Decimal("5000"), gross=Decimal("6000"))
    assert plan.rejected is False
    assert plan.notional == Decimal("4000")
    assert plan.qty == Decimal("40")
    assert plan.binding_constraint == "max_gross_notional"
    assert plan.max_notional == Decimal("10000")
    assert plan.realized_risk_fraction < plan.target_risk_fraction


def test_equity_1000_single_cap_is_2000_and_names_leverage() -> None:
    plan = _plan(equity=Decimal("1000"), param_overrides={"risk_fraction": Decimal("0.02")})
    assert plan.rejected is False
    assert plan.notional == Decimal("2000")
    assert plan.max_notional == Decimal("2000")
    assert plan.binding_constraint == "max_leverage"


def test_equal_caps_that_shrink_are_named_max_notional() -> None:
    plan = _plan(param_overrides={"risk_fraction": Decimal("0.02")})
    assert plan.notional == Decimal("20000")
    assert plan.binding_constraint == "max_notional"


def test_gross_reduction_wins_the_binding_name() -> None:
    plan = _plan(
        equity=Decimal("1000"),
        gross=Decimal("1500"),
        param_overrides={"risk_fraction": Decimal("0.02")},
    )
    assert plan.notional == Decimal("500")
    assert plan.binding_constraint == "max_gross_notional"


def test_gross_field_is_used_when_the_position_tuple_is_empty() -> None:
    plan = _plan(gross=Decimal("19000"), positions=(), count=0)
    assert plan.notional == Decimal("1000")
    assert plan.binding_constraint == "max_gross_notional"


def test_second_order_after_14705_binds_gross_and_realizes_less() -> None:
    plan = _plan(gross=Decimal("14705.8"))
    assert plan.notional == Decimal("5294.2")
    assert plan.binding_constraint == "max_gross_notional"
    assert plan.realized_risk_fraction == Decimal("0.001800028")


def test_touching_the_single_cap_does_not_count_as_a_shrink() -> None:
    plan = _plan(param_overrides={"max_notional_quote": Decimal("14705.8")})
    assert plan.notional == Decimal("14705.8")
    assert plan.binding_constraint == "risk_fraction"
    assert plan.max_notional == Decimal("14705.8")


def test_min_notional_equal_to_the_order_does_not_reject() -> None:
    plan = _plan(min_notional=Decimal("14705.8"))
    assert plan.rejected is False


def test_qty_step_floors_the_risk_quantity() -> None:
    plan = _plan(
        equity=Decimal("190"),
        step=Decimal("1"),
        min_qty=Decimal("1"),
        defending=99.15,
        param_overrides={"risk_fraction": Decimal("0.01")},
    )
    assert plan.rejected is False
    assert plan.qty == Decimal("1")
    assert plan.notional == Decimal("100")
    assert plan.binding_constraint == "risk_fraction"


def test_instrument_spec_returns_before_the_position_count() -> None:
    held = (_held(Decimal("1")), _held(Decimal("1")))
    cases = (
        {"tick": None},
        {"tick": Decimal("0")},
        {"tick": Decimal("-0.01")},
        {"step": None},
        {"step": Decimal("0")},
        {"min_qty": None},
        {"min_qty": Decimal("0")},
        {"min_qty": Decimal("-1")},
    )
    for overrides in cases:
        plan = _plan(count=3, positions=held, **overrides)
        assert plan.reject_reason is VetoCode.INSTRUMENT_SPEC
        assert plan.binding_constraint == "instrument_spec"
        assert plan.cost_r is None
        assert plan.realized_risk_fraction is None
        assert plan.qty == 0
        assert plan.notional == 0


def test_missing_min_notional_is_legal() -> None:
    plan = _plan(min_notional=None)
    assert plan.rejected is False


def test_open_count_is_the_field_and_returns_before_direction() -> None:
    plan = _plan(count=3, positions=())
    assert plan.reject_reason is VetoCode.MAX_OPEN_POSITIONS
    assert plan.cost_r is None
    assert plan.structure_stop_price is None
    both = _plan(count=3, positions=(_held(Decimal("1")), _held(Decimal("1"))))
    assert both.reject_reason is VetoCode.MAX_OPEN_POSITIONS
    assert both.cost_r is None
    allowed = _plan(count=2)
    assert allowed.rejected is False


def test_same_direction_uses_qty_sign_before_notional() -> None:
    crowded = _plan(
        count=2,
        positions=(_held(Decimal("1"), "ETH/USDT"), _held(Decimal("2"), "SOL/USDT")),
        min_qty=Decimal("1000000"),
    )
    assert crowded.reject_reason is VetoCode.MAX_SAME_DIRECTION
    assert crowded.cost_r is None
    assert crowded.realized_risk_fraction is None
    mixed = _plan(count=2, positions=(_held(Decimal("1")), _held(Decimal("-1"))))
    assert mixed.rejected is False
    flat = _plan(count=1, positions=(_held(Decimal("0")), _held(Decimal("1"))))
    assert flat.rejected is False
    orders = _plan(count=0, orders=("o1", "o2"))
    assert orders.rejected is False
    counted = _plan(count=0, positions=(_held(Decimal("1")), _held(Decimal("1"))))
    assert counted.reject_reason is VetoCode.MAX_SAME_DIRECTION
    short = _short_plan(count=2, positions=(_held(Decimal("-1")), _held(Decimal("-2"))))
    assert short.reject_reason is VetoCode.MAX_SAME_DIRECTION
    opposite = _short_plan(count=2, positions=(_held(Decimal("-1")), _held(Decimal("1"))))
    assert opposite.rejected is False


def test_non_positive_stop_equity_or_entry_is_risk_cap_with_empty_cost() -> None:
    wide = _plan(defending=100.20)
    assert wide.reject_reason is VetoCode.RISK_CAP
    assert wide.cost_r is None
    assert wide.structure_stop_price == pytest.approx(100.05)
    assert wide.realized_risk_fraction is None
    touched = _plan(defending=100.15)
    assert touched.reject_reason is VetoCode.RISK_CAP
    assert touched.structure_stop_price == pytest.approx(100.0)
    assert touched.cost_r is None
    broke = _plan(equity=Decimal("0"))
    assert broke.reject_reason is VetoCode.RISK_CAP
    assert broke.cost_r is None
    assert broke.structure_stop_price == pytest.approx(99.66)
    negative = _plan(equity=Decimal("-5"))
    assert negative.reject_reason is VetoCode.RISK_CAP
    assert negative.max_notional == Decimal("20000")
    zero = _plan(close=0.0)
    assert zero.reject_reason is VetoCode.RISK_CAP
    assert zero.entry_reference == 0.0
    assert zero.cost_r is None
    below = _plan(close=-1.0)
    assert below.entry_reference == -1.0
    assert below.reject_reason is VetoCode.RISK_CAP


def test_missing_signal_or_bad_atr_does_not_invent_a_stop() -> None:
    missing = _plan(candidate_id=None)
    assert missing.reject_reason is VetoCode.RISK_CAP
    assert missing.entry_reference == 100.0
    assert missing.atr == pytest.approx(1.0)
    assert missing.structure_stop_price is None
    assert missing.cost_r is None
    assert _plan(candidate_id="missing").reject_reason is VetoCode.RISK_CAP
    other = _plan(signal_on=Timeframe.H1)
    assert other.reject_reason is VetoCode.RISK_CAP
    assert other.structure_stop_price is None
    none = _plan(side=Side.NONE, action=ProposedAction.HOLD)
    assert none.reject_reason is VetoCode.RISK_CAP
    assert none.side is Side.NONE
    assert none.structure_stop_price is None
    assert none.cost_r is None
    quiet = _plan(atr=float("nan"))
    assert quiet.reject_reason is VetoCode.RISK_CAP
    assert quiet.atr is None
    assert quiet.cost_r is None
    negative = _plan(atr=-1.0)
    assert negative.reject_reason is VetoCode.RISK_CAP
    assert negative.atr == pytest.approx(-1.0)
    assert negative.structure_stop_price is None
    assert negative.cost_r is None


def test_risk_quantity_below_the_floor_is_risk_cap_after_cost_is_known() -> None:
    small = _plan(min_qty=Decimal("1000"))
    assert small.reject_reason is VetoCode.RISK_CAP
    assert small.reject_reason is not VetoCode.MIN_QTY
    assert small.cost_r == Decimal("0.0012") / Decimal("0.0034")
    assert small.realized_risk_fraction is None
    assert small.structure_stop_price == pytest.approx(99.66)
    cheap = _plan(min_notional=Decimal("100000"))
    assert cheap.reject_reason is VetoCode.RISK_CAP
    assert cheap.cost_r is not None
    assert cheap.qty == 0


def test_cap_floors_below_the_minimum_use_the_cap_code() -> None:
    single = _plan(
        equity=Decimal("1000"),
        min_qty=Decimal("1"),
        param_overrides={"max_notional_quote": Decimal("50")},
    )
    assert single.reject_reason is VetoCode.MAX_NOTIONAL
    assert single.cost_r is not None
    assert single.realized_risk_fraction is None
    assert single.structure_stop_price == pytest.approx(99.66)
    assert single.max_notional == Decimal("50")
    exhausted = _plan(gross=Decimal("20000"))
    assert exhausted.reject_reason is VetoCode.MAX_GROSS_NOTIONAL
    assert exhausted.cost_r is not None
    assert exhausted.realized_risk_fraction is None
    shrunk = _plan(gross=Decimal("19950"), min_qty=Decimal("1"))
    assert shrunk.reject_reason is VetoCode.MAX_GROSS_NOTIONAL
    assert shrunk.cost_r is not None
    over = _plan(gross=Decimal("25000"))
    assert over.reject_reason is VetoCode.MAX_GROSS_NOTIONAL


def test_partial_fraction_and_r_fallback_come_from_params() -> None:
    plan = _plan(param_overrides={"partial_fraction": Decimal("0.25"), "r_fallback": Decimal("2")})
    assert plan.partial_targets[0].fraction == pytest.approx(0.25)
    assert plan.partial_targets[0].price == pytest.approx(100.68)
    assert plan.partial_targets[0].reason is PartialReason.R_MULTIPLE


def test_tp1_uses_only_the_last_favorable_endpoint() -> None:
    high = _fx("fx-hi", T0, 120.0)
    low = _fx("fx-lo", T1, 105.0)
    plan = _plan(
        fenxings=(high, low),
        bis=(
            _bi("bi-hi", Direction.UP, "fx-hi", 120.0, high=130.0, low=100.0, end_time=T2),
            _bi("bi-lo", Direction.UP, "fx-lo", 105.0, high=120.0, low=100.0, end_time=T0),
        ),
    )
    assert plan.partial_targets[0].price == pytest.approx(105.0)
    assert plan.partial_targets[0].reason is PartialReason.PRIOR_SWING
    weak = _plan(
        fenxings=(high, _fx("fx-bad", T1, 99.0)),
        bis=(
            _bi("bi-hi", Direction.UP, "fx-hi", 120.0, high=130.0, low=100.0, end_time=T0),
            _bi("bi-bad", Direction.UP, "fx-bad", 99.0, high=120.0, low=90.0, end_time=T0),
        ),
    )
    assert weak.partial_targets[0].reason is PartialReason.R_MULTIPLE
    assert weak.partial_targets[0].price == pytest.approx(100.51)
    future = _plan(
        fenxings=(_fx("fx-ok", T0, 110.0), _fx("fx-later", T2, 130.0)),
        bis=(
            _bi("bi-ok", Direction.UP, "fx-ok", 110.0, high=110.0, low=100.0, end_time=T2),
            _bi("bi-later", Direction.UP, "fx-later", 130.0, high=130.0, low=100.0, end_time=T0),
        ),
    )
    assert future.partial_targets[0].price == pytest.approx(110.0)
    hidden = _plan(
        fenxings=(_fx("fx-ok", T0, 108.0),),
        bis=(
            _bi("bi-ok", Direction.UP, "fx-ok", 108.0, high=108.0, low=100.0, end_time=T0),
            _bi(
                "bi-open",
                Direction.UP,
                "fx-open",
                130.0,
                high=130.0,
                low=100.0,
                end_time=T1,
                confirmed=False,
            ),
        ),
    )
    assert hidden.partial_targets[0].price == pytest.approx(108.0)
    foreign = _plan(
        fenxings=(_fx("fx-h1", T1, 130.0),),
        bis=(
            _bi(
                "bi-h1",
                Direction.UP,
                "fx-h1",
                130.0,
                high=130.0,
                low=100.0,
                end_time=T0,
                timeframe=Timeframe.H1,
            ),
        ),
    )
    assert foreign.partial_targets[0].reason is PartialReason.R_MULTIPLE
    orphan = _plan(
        bis=(_bi("bi-x", Direction.UP, "fx-missing", 130.0, high=130.0, low=100.0, end_time=T0),)
    )
    assert orphan.partial_targets[0].reason is PartialReason.R_MULTIPLE
    down = _fx("fx-down", T1, 90.0, Mark.BOTTOM)
    earlier = _fx("fx-earlier", T0, 70.0, Mark.BOTTOM)
    short = _short_plan(
        fenxings=(earlier, down),
        bis=(
            _bi("bi-old", Direction.DOWN, "fx-earlier", 70.0, high=100.0, low=70.0, end_time=T0),
            _bi("bi-new", Direction.DOWN, "fx-down", 90.0, high=100.0, low=80.0, end_time=T0),
        ),
    )
    assert short.partial_targets[0].price == pytest.approx(90.0)
    assert short.partial_targets[0].reason is PartialReason.PRIOR_SWING
    above = _short_plan(
        fenxings=(earlier, _fx("fx-above", T1, 101.0, Mark.BOTTOM)),
        bis=(
            _bi("bi-old", Direction.DOWN, "fx-earlier", 70.0, high=100.0, low=70.0, end_time=T0),
            _bi("bi-above", Direction.DOWN, "fx-above", 101.0, high=110.0, low=90.0, end_time=T0),
        ),
    )
    assert above.partial_targets[0].reason is PartialReason.R_MULTIPLE
    assert above.partial_targets[0].price == pytest.approx(99.49)


def test_invalidation_freezes_the_signal_levels() -> None:
    second = _plan(prior_extreme=90.0, zhongshu_id="zs-ignored")
    spec = second.invalidation
    assert spec is not None
    assert spec.opposite_signal_types == (SignalType.SECOND_SELL, SignalType.THIRD_SELL)
    assert spec.htf_timeframe is Timeframe.H1
    assert spec.htf_bias_exit == (StructureBias.DOWN, StructureBias.BREAKOUT_DOWN)
    assert spec.swing_fail_price == pytest.approx(90.0)
    assert spec.zhongshu_fail_price is None
    assert spec.zhongshu_id == "zs-ignored"
    assert spec.defending_fx_id == "fx-def"
    assert spec.effective_after == T1
    third = _plan(
        signal_type=SignalType.THIRD_BUY,
        zhongshu_id="zs-1",
        prior_extreme=80.0,
        zhongshus=(_zhongshu("zs-other", 50.0, 40.0), _zhongshu("zs-1", 110.0, 90.0)),
    )
    assert third.rejected is False
    assert third.invalidation is not None
    assert third.invalidation.zhongshu_fail_price == pytest.approx(110.0)
    assert third.invalidation.swing_fail_price is None
    assert third.invalidation.zhongshu_id == "zs-1"
    missing = _plan(signal_type=SignalType.THIRD_BUY, zhongshu_id="zs-missing", prior_extreme=80.0)
    assert missing.rejected is False
    assert missing.invalidation is not None
    assert missing.invalidation.zhongshu_fail_price is None
    assert missing.invalidation.zhongshu_id == "zs-missing"
    sell = _short_plan(
        signal_type=SignalType.THIRD_SELL,
        zhongshu_id="zs-s",
        prior_extreme=120.0,
        zhongshus=(_zhongshu("zs-s", 110.0, 95.0),),
    )
    assert sell.invalidation is not None
    assert sell.invalidation.zhongshu_fail_price == pytest.approx(95.0)
    assert sell.invalidation.swing_fail_price is None
    second_sell = _short_plan(signal_type=SignalType.SECOND_SELL, prior_extreme=110.0)
    assert second_sell.invalidation is not None
    assert second_sell.invalidation.swing_fail_price == pytest.approx(110.0)
    assert second_sell.invalidation.zhongshu_fail_price is None
    first = _plan(
        signal_type=SignalType.FIRST_BUY,
        prior_extreme=80.0,
        zhongshu_id="zs-1",
        zhongshus=(_zhongshu("zs-1", 110.0, 90.0),),
    )
    assert first.rejected is False
    assert first.invalidation is not None
    assert first.invalidation.zhongshu_fail_price is None
    assert first.invalidation.swing_fail_price is None


def test_opposite_signal_exits_only_after_the_entry_decision() -> None:
    plan = _plan()
    position = _position(plan, qty=Decimal("1.25"))
    early = _market(T2, (_calm(T1),), signals=(_opp(SignalType.SECOND_SELL, T1, 103.0),))
    _assert_hold(RiskManager(_params()).review_open(early, position))
    late = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=100.34, low=99.4, close=99.5),),
        signals=(_opp(SignalType.SECOND_SELL, T2, 103.0),),
    )
    _assert_exit(RiskManager(_params()).review_open(late, position), ExitReason.OPPOSITE_SIGNAL, Decimal("1.25"), 103.0)
    first = _market(T2, (_calm(T1),), signals=(_opp(SignalType.FIRST_SELL, T2, 103.0),))
    _assert_hold(RiskManager(_params()).review_open(first, position))
    higher = _market(
        T2,
        (_calm(T1),),
        h1_signals=(_opp(SignalType.SECOND_SELL, T2, 103.0, timeframe=Timeframe.H1),),
    )
    _assert_hold(RiskManager(_params()).review_open(higher, position))
    both = _market(
        T3,
        (_calm(T1), _calm(T2, close=100.2)),
        signals=(_opp(SignalType.THIRD_SELL, T2, 103.0), _opp(SignalType.SECOND_SELL, T3, 110.0)),
    )
    _assert_exit(
        RiskManager(_params()).review_open(both, position),
        ExitReason.OPPOSITE_SIGNAL,
        Decimal("1.25"),
        103.0,
    )


def test_one_hour_bias_exits_and_four_hour_neutral_does_not() -> None:
    plan = _plan()
    position = _position(plan)
    down = _market(T2, (_calm(T1, close=100.2),), bias_1h=StructureBias.DOWN)
    _assert_exit(
        RiskManager(_params()).review_open(down, position),
        ExitReason.BIAS_1H,
        plan.qty,
        100.2,
    )
    breakout = _market(T2, (_calm(T1),), bias_1h=StructureBias.BREAKOUT_DOWN)
    _assert_exit(
        RiskManager(_params()).review_open(breakout, position),
        ExitReason.BIAS_1H,
        plan.qty,
        100.0,
    )
    _assert_hold(RiskManager(_params()).review_open(_market(T2, (_calm(T1),)), position))
    _assert_hold(
        RiskManager(_params()).review_open(
            _market(T2, (_calm(T1),), bias_1h=StructureBias.UP, bias_4h=StructureBias.DOWN),
            position,
        )
    )
    empty = _market(T2, (), bias_1h=StructureBias.DOWN)
    review = RiskManager(_params()).review_open(empty, position)
    assert review.exit is not None
    assert review.exit.trigger_price == plan.entry_reference
    short_plan = _short_plan(prior_extreme=150.0)
    short = _position(short_plan)
    up = _market(T2, (_calm(T1, close=100.4),), bias_1h=StructureBias.UP)
    _assert_exit(RiskManager(_params()).review_open(up, short), ExitReason.BIAS_1H, short_plan.qty, 100.4)
    _assert_exit(
        RiskManager(_params()).review_open(
            _market(T2, (_calm(T1),), bias_1h=StructureBias.BREAKOUT_UP),
            short,
        ),
        ExitReason.BIAS_1H,
        short_plan.qty,
        100.0,
    )
    _assert_hold(
        RiskManager(_params()).review_open(_market(T2, (_calm(T1),), bias_1h=StructureBias.DOWN), short)
    )


def test_zhongshu_and_swing_use_the_frozen_price() -> None:
    plan = _plan(
        signal_type=SignalType.THIRD_BUY,
        zhongshu_id="zs-1",
        zhongshus=(_zhongshu("zs-1", 102.0, 90.0),),
    )
    position = _position(plan)
    fail = _market(T2, (_bar(Timeframe.M15, T1, high=103.0, low=100.0, close=101.0, open_=102.0),))
    _assert_exit(RiskManager(_params()).review_open(fail, position), ExitReason.ZHONGSHU_FAIL, plan.qty, 101.0)
    equal = _market(T2, (_bar(Timeframe.M15, T1, high=103.0, low=101.0, close=102.0, open_=102.0),))
    _assert_hold(
        RiskManager(_params()).review_open(equal, _position(plan, stop_price=plan.entry_reference))
    )
    early = _market(
        T3,
        (
            _bar(Timeframe.M15, T1, high=101.0, low=89.0, close=90.0),
            _bar(Timeframe.M15, T2, high=103.0, low=100.0, close=101.0, open_=102.0),
        ),
    )
    _assert_exit(
        RiskManager(_params()).review_open(early, _position(plan, entry_bar_open_time=T2)),
        ExitReason.ZHONGSHU_FAIL,
        plan.qty,
        101.0,
    )
    unclosed = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=103.0, low=100.0, close=101.0, open_=102.0, closed=False),),
    )
    _assert_hold(RiskManager(_params()).review_open(unclosed, position))
    swing = _plan(prior_extreme=98.0)
    swung = _market(T2, (_bar(Timeframe.M15, T1, high=101.0, low=97.0, close=97.5),))
    _assert_exit(RiskManager(_params()).review_open(swung, _position(swing)), ExitReason.SWING_FAIL, swing.qty, 97.5)
    held = _market(T2, (_bar(Timeframe.M15, T1, high=100.2, low=97.0, close=98.0),))
    _assert_hold(RiskManager(_params()).review_open(held, _position(swing)))
    short_plan = _short_plan(
        signal_type=SignalType.THIRD_SELL,
        zhongshu_id="zs-s",
        zhongshus=(_zhongshu("zs-s", 110.0, 98.0),),
    )
    short_fail = _market(T2, (_bar(Timeframe.M15, T1, high=101.0, low=97.0, close=98.01),))
    _assert_exit(
        RiskManager(_params()).review_open(short_fail, _position(short_plan)),
        ExitReason.ZHONGSHU_FAIL,
        short_plan.qty,
        98.01,
    )
    short_equal = _market(T2, (_bar(Timeframe.M15, T1, high=101.0, low=97.0, close=98.0),))
    _assert_hold(
        RiskManager(_params()).review_open(
            short_equal,
            _position(short_plan, stop_price=short_plan.entry_reference),
        )
    )
    high_fail = _short_plan(prior_extreme=102.0)
    broke = _market(T2, (_bar(Timeframe.M15, T1, high=103.0, low=99.0, close=102.5),))
    _assert_exit(
        RiskManager(_params()).review_open(broke, _position(high_fail)),
        ExitReason.SWING_FAIL,
        high_fail.qty,
        102.5,
    )


def test_exit_precedence_is_opposite_then_bias_then_zhongshu_then_swing() -> None:
    plan = _plan(
        signal_type=SignalType.THIRD_BUY,
        zhongshu_id="zs-1",
        zhongshus=(_zhongshu("zs-1", 102.0, 90.0),),
    )
    spec = plan.invalidation.model_copy(update={"swing_fail_price": 95.0})
    plan = plan.model_copy(update={"invalidation": spec})
    position = _position(plan)
    bar = _bar(Timeframe.M15, T1, high=100.34, low=89.0, close=90.0)
    opposite = _market(T2, (bar,), bias_1h=StructureBias.DOWN, signals=(_opp(SignalType.SECOND_SELL, T2, 103.0),))
    _assert_exit(
        RiskManager(_params()).review_open(opposite, position),
        ExitReason.OPPOSITE_SIGNAL,
        plan.qty,
        103.0,
    )
    bias = _market(T2, (bar,), bias_1h=StructureBias.BREAKOUT_DOWN)
    _assert_exit(RiskManager(_params()).review_open(bias, position), ExitReason.BIAS_1H, plan.qty, 90.0)
    level = _market(T2, (bar,))
    _assert_exit(RiskManager(_params()).review_open(level, position), ExitReason.ZHONGSHU_FAIL, plan.qty, 90.0)
    swing_only = plan.model_copy(
        update={"invalidation": spec.model_copy(update={"zhongshu_fail_price": None})}
    )
    _assert_exit(
        RiskManager(_params()).review_open(level, _position(swing_only)),
        ExitReason.SWING_FAIL,
        plan.qty,
        90.0,
    )


def test_arm_uses_the_decision_bar_high_and_the_frozen_entry() -> None:
    plan = _plan()
    manager = RiskManager(_params(arm_r=Decimal("2")))
    armed = _bar(Timeframe.M15, T1, high=100.34, low=99.4, close=99.5)
    review = manager.review_open(_market(T2, (armed,)), _position(plan))
    assert review.exit is None
    assert review.amend_stop is not None
    assert review.amend_stop.reason is AmendReason.BREAKEVEN
    assert review.amend_stop.new_stop_price == plan.entry_reference
    quiet = _bar(Timeframe.M15, T1, high=91.0, low=89.0, close=90.0, open_=90.0)
    _assert_hold(manager.review_open(_market(T2, (quiet,)), _position(plan)))
    before = _bar(Timeframe.M15, T0, high=120.0, low=99.0, close=110.0)
    _assert_hold(manager.review_open(_market(T1, (before,)), _position(plan)))
    older = _bar(Timeframe.M15, T0, high=120.0, low=99.0, close=110.0)
    current = _bar(Timeframe.M15, T1, high=100.1, low=99.5, close=100.0)
    _assert_hold(
        manager.review_open(
            _market(T2, (older, current)),
            _position(plan, entry_bar_open_time=T0),
        )
    )


def test_ratchet_waits_until_armed_and_never_loosens() -> None:
    plan = _plan()
    manager = RiskManager(_params())
    end = _fx("fx-end", T2, 100.5, Mark.BOTTOM)
    bi = _bi("bi-down", Direction.DOWN, "fx-end", 100.5, high=101.0, low=99.0, end_time=T1)
    early = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=100.1, low=99.5, close=100.0),),
        fenxings=(end,),
        bis=(bi,),
    )
    _assert_hold(manager.review_open(early, _position(plan)))
    same = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=100.34, low=99.4, close=99.5),),
        fenxings=(end,),
        bis=(bi,),
    )
    review = manager.review_open(same, _position(plan))
    assert review.exit is None
    assert review.amend_stop is not None
    assert review.amend_stop.reason is AmendReason.BREAKEVEN
    assert review.amend_stop.new_stop_price == plan.entry_reference
    armed = _position(plan, stop_price=plan.entry_reference)
    _assert_hold(manager.review_open(_market(T2, (_calm(T1, high=101.0),)), armed))
    moved = manager.review_open(_market(T2, (_calm(T1),), fenxings=(end,), bis=(bi,)), armed)
    assert moved.exit is None
    assert moved.amend_stop is not None
    assert moved.amend_stop.reason is AmendReason.RATCHET
    assert moved.amend_stop.new_stop_price == pytest.approx(100.35)
    pierced = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=101.0, low=99.0, close=100.2),),
        fenxings=(end,),
        bis=(bi,),
    )
    pierced_review = manager.review_open(pierced, armed)
    assert pierced_review.exit is None
    assert pierced_review.amend_stop is not None
    assert pierced_review.amend_stop.reason is AmendReason.RATCHET
    lower = _fx("fx-low", T2, 100.4, Mark.BOTTOM)
    low_bi = _bi("bi-low", Direction.DOWN, "fx-low", 100.4, high=101.0, low=99.0, end_time=T1)
    _assert_hold(
        manager.review_open(
            _market(T2, (_calm(T1),), fenxings=(lower,), bis=(low_bi,)),
            _position(plan, stop_price=100.50),
        )
    )
    _assert_hold(
        manager.review_open(
            _market(T2, (_calm(T1),), fenxings=(end,), bis=(bi,)),
            _position(plan, stop_price=100.35),
        )
    )


def test_ratchet_uses_the_confirming_endpoint_only() -> None:
    plan = _plan()
    manager = RiskManager(_params())
    armed = _position(plan, stop_price=plan.entry_reference)
    first = _fx("fx-a", T2, 100.4, Mark.BOTTOM)
    second = _fx("fx-b", T2, 100.8, Mark.BOTTOM)
    bis = (
        _bi("bi-a", Direction.DOWN, "fx-a", 100.4, high=101.0, low=99.0, end_time=T0),
        _bi("bi-b", Direction.DOWN, "fx-b", 100.8, high=101.0, low=99.0, end_time=T0),
    )
    review = manager.review_open(_market(T2, (_calm(T1),), fenxings=(first, second), bis=bis), armed)
    assert review.amend_stop is not None
    assert review.amend_stop.new_stop_price == pytest.approx(100.65)
    weak = (
        _bi("bi-a", Direction.DOWN, "fx-a", 100.8, high=101.0, low=99.0, end_time=T0),
        _bi("bi-b", Direction.DOWN, "fx-b", 100.1, high=101.0, low=99.0, end_time=T0),
    )
    _assert_hold(
        manager.review_open(
            _market(T2, (_calm(T1),), fenxings=(first, second), bis=weak),
            armed,
        )
    )
    confirmed = _fx("fx-now", T3, 100.5, Mark.BOTTOM)
    clock = _bi("bi-now", Direction.DOWN, "fx-now", 100.5, high=101.0, low=99.0, end_time=T2)
    moved = manager.review_open(
        _market(T3, (_calm(T2),), fenxings=(confirmed,), bis=(clock,)),
        armed,
    )
    assert moved.amend_stop is not None
    assert moved.amend_stop.new_stop_price == pytest.approx(100.35)
    stale = _fx("fx-stale", T2, 100.5, Mark.BOTTOM)
    stale_bi = _bi("bi-stale", Direction.DOWN, "fx-stale", 100.5, high=101.0, low=99.0, end_time=T3)
    _assert_hold(
        manager.review_open(_market(T3, (_calm(T2),), fenxings=(stale,), bis=(stale_bi,)), armed)
    )
    ignored = _fx("fx-ignored", T2, 100.8, Mark.BOTTOM)
    old = _fx("fx-old", T1, 100.2, Mark.BOTTOM)
    old_bi = _bi("bi-old", Direction.DOWN, "fx-old", 100.2, high=101.0, low=99.0, end_time=T0)
    _assert_hold(
        manager.review_open(
            _market(T2, (_calm(T1),), fenxings=(old, ignored), bis=(old_bi,)),
            armed,
        )
    )
    replaced_old = _fx("fx-higher", T2, 100.8, Mark.BOTTOM)
    replaced_new = _fx("fx-lower", T3, 100.4, Mark.BOTTOM)
    replaced = _bi("bi-replaced", Direction.DOWN, "fx-lower", 100.4, high=101.0, low=99.0, end_time=T1)
    _assert_hold(
        manager.review_open(
            _market(T3, (_calm(T2),), fenxings=(replaced_old, replaced_new), bis=(replaced,)),
            _position(plan, stop_price=100.50),
        )
    )
    _assert_hold(
        manager.review_open(
            _market(T2, (_calm(T1),), fenxings=(end_tick(),), bis=(bi_tick(),), tick=None),
            armed,
        )
    )


def test_a_reduced_qty_can_still_move_to_breakeven() -> None:
    plan = _plan()
    bar = _bar(Timeframe.M15, T1, high=100.34, low=99.4, close=99.5)
    review = RiskManager(_params()).review_open(
        _market(T2, (bar,)),
        _position(plan, qty=Decimal("0.4")),
    )
    assert review.exit is None
    assert review.amend_stop is not None
    assert review.amend_stop.new_stop_price == plan.entry_reference


def test_a_stop_pierce_does_not_exit_from_review() -> None:
    plan = _plan()
    bar = _bar(Timeframe.M15, T1, high=100.2, low=99.0, close=99.8)
    _assert_hold(RiskManager(_params()).review_open(_market(T2, (bar,)), _position(plan)))
    short = _short_plan(prior_extreme=150.0)
    short_bar = _bar(Timeframe.M15, T1, high=100.5, low=100.0, close=100.2)
    _assert_hold(RiskManager(_params()).review_open(_market(T2, (short_bar,)), _position(short)))


def test_short_arm_and_ratchet_mirror_the_long() -> None:
    plan = _short_plan(prior_extreme=150.0)
    manager = RiskManager(_params())
    arm = _bar(Timeframe.M15, T1, high=100.5, low=99.66, close=100.2)
    review = manager.review_open(_market(T2, (arm,)), _position(plan))
    assert review.exit is None
    assert review.amend_stop is not None
    assert review.amend_stop.reason is AmendReason.BREAKEVEN
    assert review.amend_stop.new_stop_price == plan.entry_reference
    up = _fx("fx-up", T2, 99.5, Mark.TOP)
    bi = _bi("bi-up", Direction.UP, "fx-up", 99.5, high=100.0, low=99.0, end_time=T1)
    same = _market(T2, (arm,), fenxings=(up,), bis=(bi,))
    breakeven = manager.review_open(same, _position(plan))
    assert breakeven.amend_stop is not None
    assert breakeven.amend_stop.reason is AmendReason.BREAKEVEN
    quiet = _bar(Timeframe.M15, T1, high=100.2, low=99.8, close=100.0)
    _assert_hold(manager.review_open(_market(T2, (quiet,), fenxings=(up,), bis=(bi,)), _position(plan)))
    armed = _position(plan, stop_price=plan.entry_reference)
    moved = manager.review_open(_market(T2, (_calm(T1),), fenxings=(up,), bis=(bi,)), armed)
    assert moved.amend_stop is not None
    assert moved.amend_stop.reason is AmendReason.RATCHET
    assert moved.amend_stop.new_stop_price == pytest.approx(99.65)
    tight = _fx("fx-tight", T2, 99.333, Mark.TOP)
    tight_bi = _bi("bi-tight", Direction.UP, "fx-tight", 99.333, high=100.0, low=99.0, end_time=T1)
    ceiled = manager.review_open(
        _market(T2, (_calm(T1),), fenxings=(tight,), bis=(tight_bi,)),
        armed,
    )
    assert ceiled.amend_stop is not None
    assert ceiled.amend_stop.new_stop_price == pytest.approx(99.49)
    assert ceiled.amend_stop.new_stop_price > 99.485
    higher = _fx("fx-high", T2, 99.9, Mark.TOP)
    high_bi = _bi("bi-high", Direction.UP, "fx-high", 99.9, high=100.0, low=99.0, end_time=T1)
    _assert_hold(
        manager.review_open(_market(T2, (_calm(T1),), fenxings=(higher,), bis=(high_bi,)), armed)
    )


def test_rejected_plan_review_is_a_hold() -> None:
    plan = _plan(defending=100.20)
    assert plan.rejected is True
    position = _position(plan, stop_price=99.0, qty=Decimal("1"))
    context = _market(
        T2,
        (_bar(Timeframe.M15, T1, high=101.0, low=90.0, close=91.0),),
        bias_1h=StructureBias.DOWN,
    )
    _assert_hold(RiskManager(_params()).review_open(context, position))


def _assert_exit(review, reason: ExitReason, qty: Decimal, trigger: float) -> None:
    assert review.amend_stop is None
    assert review.exit is not None
    assert review.exit.kind is ExitKind.EXIT
    assert review.exit.fill_model is FillModel.NEXT_OPEN
    assert review.exit.reason is reason
    assert review.exit.qty == qty
    assert review.exit.trigger_price == pytest.approx(trigger)


def _assert_hold(review) -> None:
    assert review.exit is None
    assert review.amend_stop is None


def _params(**overrides: object) -> RiskParams:
    values: dict[str, object] = {
        "risk_fraction": Decimal("0.005"),
        "max_notional_quote": Decimal("20000"),
        "max_gross_notional_quote": Decimal("20000"),
        "max_open_positions": 3,
        "max_same_direction": 2,
        "max_leverage": 2,
        "max_cost_r": Decimal("0.40"),
        "stop_buffer_atr": Decimal("0.15"),
        "partial_fraction": Decimal("0.5"),
        "r_fallback": Decimal("1.5"),
        "arm_r": Decimal("1"),
        "fee_bps": Decimal("5"),
        "slippage_bps": Decimal("1"),
    }
    values.update(overrides)
    return RiskParams(**values)  # type: ignore[arg-type]


def _plan(**kwargs: object) -> RiskPlan:
    manager, context, features, assessment, rules, account = _pieces(**kwargs)
    return manager.plan_entry(context, features, assessment, rules, account)


def _short_plan(**kwargs: object) -> RiskPlan:
    values: dict[str, object] = {
        "side": Side.SHORT,
        "action": ProposedAction.SELL,
        "signal_type": SignalType.SECOND_SELL,
        "defending": 100.19,
    }
    values.update(kwargs)
    return _plan(**values)


def _pieces(**kwargs: object):
    equity = kwargs.get("equity", Decimal("10000"))
    gross = kwargs.get("gross", Decimal("0"))
    count = kwargs.get("count", 0)
    positions = kwargs.get("positions", ())
    orders = kwargs.get("orders", ())
    tick = kwargs.get("tick", Decimal("0.01"))
    step = kwargs.get("step", Decimal("0.001"))
    min_qty = kwargs.get("min_qty", Decimal("0.001"))
    min_notional = kwargs.get("min_notional", None)
    close = kwargs.get("close", 100.0)
    atr = kwargs.get("atr", 1.0)
    defending = kwargs.get("defending", 99.81)
    side = kwargs.get("side", Side.LONG)
    action = kwargs.get("action", ProposedAction.BUY)
    signal_type = kwargs.get("signal_type", SignalType.SECOND_BUY)
    signal_id = kwargs.get("signal_id", "sig-1")
    candidate_id = kwargs.get("candidate_id", signal_id)
    signal_on = kwargs.get("signal_on", Timeframe.M15)
    signal_timeframe = kwargs.get("signal_timeframe", Timeframe.M15)
    prior = kwargs.get("prior_extreme", 90.0)
    zhongshu_id = kwargs.get("zhongshu_id", None)
    zhongshus = kwargs.get("zhongshus", ())
    bis = kwargs.get("bis", ())
    fenxings = kwargs.get("fenxings", ())
    passed = kwargs.get("passed", True)
    decision = kwargs.get("decision", T1)
    overrides = kwargs.get("param_overrides", {})
    buy = signal_type in (SignalType.SECOND_BUY, SignalType.THIRD_BUY, SignalType.FIRST_BUY)
    signal = ChanSignal(
        id=str(signal_id),
        timeframe=signal_timeframe,
        type=signal_type,
        status=SignalStatus.CONFIRMED,
        time=decision,
        price=110.0,
        direction=Direction.UP if buy else Direction.DOWN,
        defending_fx_id="fx-def",
        defending_price=defending,
        related_bi_id="bi-1",
        bar_open_time=T0,
        related_zhongshu_id=zhongshu_id,
        prior_extreme=prior,
    )
    placed = (signal,)
    m15_signals = placed if signal_on is Timeframe.M15 else ()
    h1_signals = placed if signal_on is Timeframe.H1 else ()
    h4_signals = placed if signal_on is Timeframe.H4 else ()
    context = MultiTimeframeContext(
        context_id="ctx-1",
        symbol="BTC/USDT",
        decision_time=decision,
        bars={timeframe: () for timeframe in Timeframe},
        snapshots={
            Timeframe.M15: _snap(
                Timeframe.M15,
                StructureBias.NEUTRAL,
                m15_signals,
                bis,
                fenxings,
                zhongshus,
            ),
            Timeframe.H1: _snap(Timeframe.H1, StructureBias.NEUTRAL, h1_signals),
            Timeframe.H4: _snap(Timeframe.H4, StructureBias.UP, h4_signals),
        },
        data_quality=DataQuality(stale=False, max_gap_bars=1, missing_bar_count=0),
        instrument=_instrument(tick, step, min_qty, min_notional),
        universe_date=decision.date(),
        universe_rank=1,
    )
    features = _features(close, atr, None if candidate_id is None else str(candidate_id), side, decision)
    assessment = _assessment(side, action)
    rules = _rules(bool(passed))
    account = AccountView(
        equity_quote=equity,
        positions=positions,
        open_order_ids=orders,
        open_position_count=count,
        gross_notional_quote=gross,
    )
    return RiskManager(_params(**overrides)), context, features, assessment, rules, account


def _features(close: float, atr: float, signal_id: str | None, side: Side, decision: datetime) -> FeatureVector:
    structure = StructureFeatures(
        consecutive_bi_overlap_ratio=0.0,
        bi_segment_direction_agree=0.5,
        bi_contained_in_segment_ratio=None,
        zs_clarity=None,
        zs_bi_count=0,
        zs_overlap_valid=False,
        breakout_leave_atr=0.0,
        breakout_reentry_bars=0,
        signal_type=SignalType.FIRST_BUY,
        signal_confirmed=False,
        subscore=0.0,
        penalty=0.0,
        skip=False,
    )
    location = LocationFeatures(
        price=90.0,
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
        atr=atr,
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
        close=close,
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
        decision_time=decision,
        candidate_signal_id=signal_id,
        candidate_side=Side.NONE,
        ambiguous_signal_ids=(),
        structure=structure,
        location=location,
        resonance=resonance,
        volatility_volume=volatility,
        signal_bar=signal_bar,
        session=session,
    )


def _assessment(side: Side, action: ProposedAction) -> JevAssessment:
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
        candidate_side=side,
        score=0.10,
        p_buy=0.0,
        p_sell=0.0,
        p_hold=1.0,
        components=components,
        reasons=(),
        threshold=0.62,
        proposed_action=action,
    )


def _rules(passed: bool) -> HardRuleResult:
    if passed:
        return HardRuleResult(passed=True)
    return HardRuleResult(
        passed=False,
        vetoes=(Veto(code=VetoCode.SESSION_SKIP, message="skip", measured="late", threshold="late"),),
    )


def _instrument(tick, step, min_qty, min_notional) -> Instrument:
    return Instrument(
        symbol="BTC/USDT",
        venue="binanceusdm",
        venue_symbol="BTC/USDT:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=tick,
        qty_step=step,
        min_qty=min_qty,
        min_notional=min_notional,
        margin_asset="USDT",
        leverage_max=20,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _snap(timeframe, bias, signals=(), bis=(), fenxings=(), zhongshus=()) -> ChanSnapshot:
    return ChanSnapshot(
        snapshot_id="cs_0123456789abcdef",
        symbol="BTC/USDT",
        timeframe=timeframe,
        as_of=T1,
        config_hash="a" * 64,
        engine_version="engine-v1",
        bar_window_hash="b" * 64,
        bars_start=T0,
        bars_end=T1,
        bar_count=1,
        fenxings=fenxings,
        bis=bis,
        segments=(),
        zhongshus=zhongshus,
        signals=signals,
        structure_bias=bias,
    )


def _zhongshu(zs_id: str, zg: float, zd: float) -> Zhongshu:
    return Zhongshu(
        id=zs_id,
        timeframe=Timeframe.M15,
        zg=zg,
        zd=zd,
        gg=zg,
        dd=zd,
        start_time=T0,
        end_time=T1,
        bi_ids=("bi-1",),
        direction_into=Direction.UP,
        level=1,
        confirmed=True,
    )


def _fx(fx_id: str, when: datetime, price: float, mark: Mark = Mark.TOP) -> Fenxing:
    return Fenxing(
        id=fx_id,
        timeframe=Timeframe.M15,
        mark=mark,
        index=1,
        time=when,
        price=price,
        bar_open_time=when,
        confirmed=True,
        k_index_left=0,
        k_index_mid=1,
        k_index_right=2,
    )


def _bi(
    bi_id: str,
    direction: Direction,
    end_fx: str,
    end_price: float,
    *,
    high: float,
    low: float,
    end_time: datetime,
    confirmed: bool = True,
    timeframe: Timeframe = Timeframe.M15,
) -> Bi:
    return Bi(
        id=bi_id,
        timeframe=timeframe,
        direction=direction,
        start_fx_id="fx-start",
        end_fx_id=end_fx,
        start_time=T0,
        end_time=end_time,
        start_price=100.0,
        end_price=end_price,
        high=high,
        low=low,
        bar_count=4,
        confirmed=confirmed,
    )


def _held(qty: Decimal, symbol: str = "ETH/USDT") -> PositionState:
    return PositionState(
        symbol=symbol,
        qty=qty,
        avg_price=100.0,
        stop_price=99.0,
        plan=RiskPlan(
            symbol=symbol,
            side=Side.LONG if qty > 0 else Side.SHORT,
            risk_fraction=Decimal("0.005"),
            target_risk_fraction=Decimal("0.005"),
            equity_quote=Decimal("10000"),
            qty=Decimal("0"),
            notional=Decimal("0"),
            max_notional=Decimal("20000"),
            rejected=True,
            reject_reason=VetoCode.INSTRUMENT_SPEC,
            binding_constraint="instrument_spec",
        ),
        entry_decision_id="dec-held",
        entry_decision_time=T0,
        entry_bar_open_time=T0,
    )


def _position(plan, **overrides: object) -> PositionState:
    qty = plan.qty if plan.side is not Side.SHORT else -plan.qty
    values: dict[str, object] = {
        "symbol": plan.symbol,
        "qty": qty,
        "avg_price": 90.0 if plan.side is not Side.SHORT else 110.0,
        "stop_price": plan.structure_stop_price if plan.structure_stop_price is not None else 99.0,
        "plan": plan,
        "entry_decision_id": "dec-1",
        "entry_decision_time": T1,
        "entry_bar_open_time": T1,
    }
    values.update(overrides)
    return PositionState(**values)  # type: ignore[arg-type]


def _market(
    decision: datetime,
    bars: tuple[Bar, ...],
    *,
    bias_1h: StructureBias = StructureBias.NEUTRAL,
    bias_4h: StructureBias = StructureBias.UP,
    signals: tuple[ChanSignal, ...] = (),
    h1_signals: tuple[ChanSignal, ...] = (),
    bis: tuple[Bi, ...] = (),
    fenxings: tuple[Fenxing, ...] = (),
    tick: Decimal | None = Decimal("0.01"),
) -> MultiTimeframeContext:
    return MultiTimeframeContext(
        context_id="ctx-review",
        symbol="BTC/USDT",
        decision_time=decision,
        bars={Timeframe.M15: bars, Timeframe.H1: (), Timeframe.H4: ()},
        snapshots={
            Timeframe.M15: _snap(Timeframe.M15, StructureBias.NEUTRAL, signals, bis, fenxings),
            Timeframe.H1: _snap(Timeframe.H1, bias_1h, h1_signals),
            Timeframe.H4: _snap(Timeframe.H4, bias_4h),
        },
        data_quality=DataQuality(stale=False, max_gap_bars=1, missing_bar_count=0),
        instrument=_instrument(tick, Decimal("0.001"), Decimal("0.001"), None),
        universe_date=decision.date(),
        universe_rank=1,
    )


def _bar(
    timeframe: Timeframe,
    open_time: datetime,
    *,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    open_: float = 100.0,
    closed: bool = True,
) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe_duration(timeframe),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        is_closed=closed,
        source="binanceusdm",
    )


def _calm(open_time: datetime, *, close: float = 100.0, high: float | None = None, low: float = 99.8) -> Bar:
    """A bar that does not arm a long or a short unless the caller raises the range."""
    top = max(100.2 if high is None else high, 100.0, close)
    bottom = min(low, 100.0, close)
    return _bar(Timeframe.M15, open_time, high=top, low=bottom, close=close)


def _opp(
    kind: SignalType,
    when: datetime,
    price: float,
    *,
    timeframe: Timeframe = Timeframe.M15,
) -> ChanSignal:
    return ChanSignal(
        id=f"sig-{kind.value}-{when.isoformat()}",
        timeframe=timeframe,
        type=kind,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=price,
        direction=Direction.DOWN,
        defending_fx_id="fx-opp",
        defending_price=price,
        related_bi_id="bi-opp",
        bar_open_time=when,
    )


def end_tick() -> Fenxing:
    return _fx("fx-tick", T2, 100.5, Mark.BOTTOM)


def bi_tick() -> Bi:
    return _bi("bi-tick", Direction.DOWN, "fx-tick", 100.5, high=101.0, low=99.0, end_time=T1)
