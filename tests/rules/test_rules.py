"""PR-9 hard rules. Handmade assessments. No engine and no plan_entry."""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
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
from chanedge.domain.chanlun import ChanSignal, ChanSnapshot
from chanedge.domain.decision import ComponentScore, HardRuleResult, JevAssessment
from chanedge.domain.enums import (
    CHANNEL_NAMES,
    Direction,
    InstrumentSource,
    ProductType,
    ProposedAction,
    RuntimeMode,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
    VetoCode,
)
from chanedge.domain.params import RuleParams
from chanedge.domain.ports import RuleGate as RulePort
from chanedge.domain.risk import AccountView, PositionState, RiskPlan, SafetyState
from chanedge.rules.gate import RuleGate

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "src" / "chanedge" / "rules"
UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
_RISK = {
    VetoCode.PIPELINE_TIMEOUT,
    VetoCode.RISK_CAP,
    VetoCode.MAX_NOTIONAL,
    VetoCode.MIN_QTY,
    VetoCode.MAX_OPEN_POSITIONS,
    VetoCode.MAX_SAME_DIRECTION,
    VetoCode.MAX_GROSS_NOTIONAL,
    VetoCode.COST_R,
    VetoCode.INSTRUMENT_SPEC,
}
_LITERALS = (
    "0.62",
    "0.24",
    "0.18",
    "0.14",
    "0.12",
    "0.35",
    "0.15",
    "0.001",
    "0.030",
    "1500",
    "1000",
    "500",
    "pipeline_timeout",
    "plan_entry",
    "enter_threshold",
    "FIRST_BUY",
    "FIRST_SELL",
    "candidate_signal_id",
    "ambiguous_signal_ids",
    "min_samples",
)


def test_rules_import_only_domain() -> None:
    forbidden = (
        "chanedge.risk",
        "chanedge.execution",
        "chanedge.config",
        "chanedge.jev",
        "chanedge.features",
        "chanedge.chanlun",
        "chanedge.marketdata",
        "chanedge.app",
        "chanedge.journal",
        "chanedge.backtest",
    )
    for path in RULES.rglob("*.py"):
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
        for literal in _LITERALS:
            assert literal not in source, literal


def test_evaluate_signature_and_params_have_no_defaults() -> None:
    assert list(inspect.signature(RuleGate.evaluate).parameters) == [
        "self",
        "context",
        "assessment",
        "account",
        "safety",
    ]
    assert list(inspect.signature(RulePort.evaluate).parameters) == list(
        inspect.signature(RuleGate.evaluate).parameters
    )
    with pytest.raises(TypeError):
        RuleGate(object())  # type: ignore[arg-type]
    for name in (
        "window_15m",
        "window_1h",
        "window_4h",
        "atr_pct_min",
        "atr_pct_max",
        "hard_skip_buckets",
    ):
        assert RuleParams.model_fields[name].is_required()
    with pytest.raises(ValueError):
        _params(window_15m=True)
    with pytest.raises(ValueError):
        _params(window_1h=0)
    with pytest.raises(ValueError):
        _params(window_4h=1.5)
    with pytest.raises(ValueError):
        _params(atr_pct_min=True)
    with pytest.raises(ValueError):
        _params(atr_pct_min=float("nan"))
    with pytest.raises(ValueError):
        _params(atr_pct_max=float("inf"))
    with pytest.raises(ValueError):
        _params(atr_pct_min=-0.1)
    with pytest.raises(ValueError):
        _params(atr_pct_min=0.03, atr_pct_max=0.001)
    with pytest.raises(ValueError):
        _params(hard_skip_buckets="asia")
    with pytest.raises(ValueError):
        _params(hard_skip_buckets=("midnight",))
    with pytest.raises(ValueError):
        _params(hard_skip_buckets=("asia", "asia"))
    kept = _params(hard_skip_buckets=["asia", "late"])
    assert kept.hard_skip_buckets == ("asia", "late")


def test_hold_can_pass_without_a_score_veto() -> None:
    raw = {"htf_gate_would_pass": False}
    result, assessment = _evaluate(
        action=ProposedAction.HOLD,
        score=0.10,
        bias_4h=StructureBias.BREAKOUT_UP,
        bias_1h=StructureBias.NEUTRAL,
        signals=(_signal(SignalType.SECOND_BUY, T0, signal_id="old-buy"),),
        rank=1,
        missing=1,
        unclosed=1,
        positions=(
            _position(symbol="ETH/USDT", qty=Decimal("3")),
            _position(qty=Decimal("0")),
        ),
        orders=("ord-1",),
        count=1,
        kill=True,
        vol_raw={"atr_pct": 0.01, "in_band": True, "vol_n": 1},
        session_raw={"session_bucket": "asia", "hard_skip": True, "in_funding_window": True},
        resonance_raw=raw,
    )
    assert result.passed is True
    assert result.vetoes == ()
    assert assessment.score == 0.10
    assert assessment.threshold == 0.62
    assert assessment.proposed_action is ProposedAction.HOLD
    assert raw["htf_gate_would_pass"] is False


def test_low_score_buy_is_not_a_score_veto() -> None:
    result, assessment = _evaluate(action=ProposedAction.BUY, score=0.01)
    assert result.passed is True
    assert assessment.score == 0.01


def test_no_candidate_allows_only_data_quality_codes() -> None:
    clean, _ = _evaluate(side=Side.NONE, vol_raw={}, session_raw={})
    assert _codes(clean) == (VetoCode.NO_CANDIDATE,)
    trapped, _ = _evaluate(
        side=Side.NONE,
        action=ProposedAction.BUY,
        score=0.99,
        kill=True,
        rank=None,
        stale=True,
        reasons=(VetoCode.GAP_DATA.value,),
        missing=2,
        closed=1,
        params=_params(window_15m=2, window_1h=2, window_4h=2, hard_skip_buckets=("asia",)),
        vol_raw={"atr_pct": 0.0, "in_band": False, "vol_n": 1},
        session_raw={"session_bucket": "asia", "hard_skip": True, "in_funding_window": True},
        bias_4h=StructureBias.DOWN,
        bias_1h=StructureBias.DOWN,
        positions=(_position(),),
        count=1,
        signals=(_signal(SignalType.SECOND_BUY, T0, signal_id="old-buy"),),
    )
    assert _codes(trapped) == (
        VetoCode.STALE_DATA,
        VetoCode.GAP_DATA,
        VetoCode.INSUFFICIENT_HISTORY,
        VetoCode.NO_CANDIDATE,
    )
    assert _RISK.isdisjoint(_codes(trapped))


def test_old_confirmed_signals_are_not_a_candidate() -> None:
    result, _ = _evaluate(
        side=Side.NONE,
        signals=(
            _signal(SignalType.SECOND_BUY, T0, signal_id="old-buy"),
            _signal(SignalType.THIRD_SELL, T0, signal_id="old-sell"),
        ),
        bias_4h=StructureBias.DOWN,
        rank=None,
    )
    assert _codes(result) == (VetoCode.NO_CANDIDATE,)


def test_a_signal_on_the_bar_does_not_override_side_none() -> None:
    result, _ = _evaluate(
        side=Side.NONE,
        signals=(_signal(SignalType.THIRD_BUY, T1, signal_id="on-bar"),),
        bias_4h=StructureBias.DOWN,
        rank=None,
    )
    assert _codes(result) == (VetoCode.NO_CANDIDATE,)


def test_first_buy_and_first_sell_are_not_ambiguous() -> None:
    result, _ = _evaluate(
        side=Side.NONE,
        signals=(
            _signal(SignalType.FIRST_BUY, T1, signal_id="first-buy"),
            _signal(SignalType.FIRST_SELL, T1, signal_id="first-sell"),
        ),
    )
    assert _codes(result) == (VetoCode.NO_CANDIDATE,)


def test_both_operational_sides_are_ambiguous_without_no_candidate() -> None:
    pair = (
        _signal(SignalType.THIRD_BUY, T1, signal_id="buy"),
        _signal(SignalType.SECOND_SELL, T1, signal_id="sell"),
    )
    clean, _ = _evaluate(side=Side.LONG, action=ProposedAction.BUY, score=0.99, signals=pair)
    assert _codes(clean) == (VetoCode.AMBIGUOUS_SIGNAL,)
    same_side, _ = _evaluate(
        signals=(
            _signal(SignalType.THIRD_BUY, T1, signal_id="third"),
            _signal(SignalType.SECOND_BUY, T1, signal_id="second"),
        )
    )
    assert same_side.passed is True
    older_sell, _ = _evaluate(
        signals=(
            _signal(SignalType.SECOND_BUY, T1, signal_id="buy"),
            _signal(SignalType.SECOND_SELL, T0, signal_id="old-sell"),
        )
    )
    assert older_sell.passed is True
    trapped, _ = _evaluate(
        side=Side.LONG,
        action=ProposedAction.BUY,
        score=0.99,
        kill=True,
        rank=None,
        stale=True,
        reasons=(VetoCode.GAP_DATA.value,),
        closed=0,
        params=_params(hard_skip_buckets=("asia",)),
        vol_raw={"atr_pct": 0.0},
        session_raw={"session_bucket": "asia", "hard_skip": True},
        bias_4h=StructureBias.DOWN,
        bias_1h=StructureBias.DOWN,
        positions=(_position(),),
        count=1,
        signals=pair,
    )
    assert _codes(trapped) == (
        VetoCode.STALE_DATA,
        VetoCode.GAP_DATA,
        VetoCode.INSUFFICIENT_HISTORY,
        VetoCode.AMBIGUOUS_SIGNAL,
    )
    assert VetoCode.NO_CANDIDATE not in _codes(trapped)
    assert VetoCode.OUTSIDE_UNIVERSE not in _codes(trapped)
    assert VetoCode.HTF_DIRECTION not in _codes(trapped)
    assert VetoCode.KILL_SWITCH not in _codes(trapped)


def test_other_timeframes_do_not_create_ambiguity() -> None:
    foreign = (
        _signal(SignalType.SECOND_BUY, T1, timeframe=Timeframe.H1, signal_id="h1-buy"),
        _signal(SignalType.SECOND_SELL, T1, timeframe=Timeframe.H1, signal_id="h1-sell"),
    )
    on_1h, _ = _evaluate(side=Side.NONE, h1_signals=foreign)
    assert _codes(on_1h) == (VetoCode.NO_CANDIDATE,)
    mistyped, _ = _evaluate(side=Side.NONE, signals=foreign)
    assert _codes(mistyped) == (VetoCode.NO_CANDIDATE,)


def test_reverse_4h_fails_and_the_score_stays() -> None:
    raw = {"htf_gate_would_pass": True}
    result, assessment = _evaluate(
        action=ProposedAction.BUY,
        score=0.99,
        bias_4h=StructureBias.DOWN,
        bias_1h=StructureBias.NEUTRAL,
        resonance_raw=raw,
    )
    assert result.passed is False
    assert _codes(result) == (VetoCode.HTF_DIRECTION,)
    assert result.vetoes[0].measured == "down"
    assert result.vetoes[0].threshold == "up,breakout_up"
    assert assessment.score == 0.99
    assert raw["htf_gate_would_pass"] is True
    short, _ = _evaluate(
        side=Side.SHORT,
        action=ProposedAction.SELL,
        score=0.99,
        bias_4h=StructureBias.UP,
        bias_1h=StructureBias.DOWN,
    )
    assert _codes(short) == (VetoCode.HTF_DIRECTION,)
    assert short.vetoes[0].threshold == "down,breakout_down"


@pytest.mark.parametrize(
    ("side", "bias_4h", "bias_1h", "expected"),
    [
        (Side.LONG, StructureBias.UP, StructureBias.NEUTRAL, ()),
        (Side.LONG, StructureBias.BREAKOUT_UP, StructureBias.UP, ()),
        (Side.LONG, StructureBias.BREAKOUT_UP, StructureBias.BREAKOUT_UP, ()),
        (Side.LONG, StructureBias.DOWN, StructureBias.NEUTRAL, (VetoCode.HTF_DIRECTION,)),
        (Side.LONG, StructureBias.BREAKOUT_DOWN, StructureBias.UP, (VetoCode.HTF_DIRECTION,)),
        (Side.LONG, StructureBias.NEUTRAL, StructureBias.NEUTRAL, (VetoCode.HTF_DIRECTION,)),
        (Side.LONG, StructureBias.UP, StructureBias.DOWN, (VetoCode.MTF_1H_CONFLICT,)),
        (Side.LONG, StructureBias.UP, StructureBias.BREAKOUT_DOWN, (VetoCode.MTF_1H_CONFLICT,)),
        (
            Side.LONG,
            StructureBias.DOWN,
            StructureBias.DOWN,
            (VetoCode.HTF_DIRECTION, VetoCode.MTF_1H_CONFLICT),
        ),
        (Side.SHORT, StructureBias.DOWN, StructureBias.NEUTRAL, ()),
        (Side.SHORT, StructureBias.BREAKOUT_DOWN, StructureBias.DOWN, ()),
        (Side.SHORT, StructureBias.BREAKOUT_DOWN, StructureBias.BREAKOUT_DOWN, ()),
        (Side.SHORT, StructureBias.UP, StructureBias.NEUTRAL, (VetoCode.HTF_DIRECTION,)),
        (Side.SHORT, StructureBias.BREAKOUT_UP, StructureBias.DOWN, (VetoCode.HTF_DIRECTION,)),
        (Side.SHORT, StructureBias.NEUTRAL, StructureBias.DOWN, (VetoCode.HTF_DIRECTION,)),
        (Side.SHORT, StructureBias.DOWN, StructureBias.UP, (VetoCode.MTF_1H_CONFLICT,)),
        (Side.SHORT, StructureBias.DOWN, StructureBias.BREAKOUT_UP, (VetoCode.MTF_1H_CONFLICT,)),
        (
            Side.SHORT,
            StructureBias.UP,
            StructureBias.UP,
            (VetoCode.HTF_DIRECTION, VetoCode.MTF_1H_CONFLICT),
        ),
    ],
)
def test_htf_and_1h_follow_the_candidate_side(side, bias_4h, bias_1h, expected) -> None:
    action = ProposedAction.BUY if side is Side.LONG else ProposedAction.SELL
    result, assessment = _evaluate(
        side=side,
        action=action,
        score=0.99,
        bias_4h=bias_4h,
        bias_1h=bias_1h,
    )
    assert _codes(result) == expected
    assert assessment.score == 0.99


@pytest.mark.parametrize(
    ("side", "action", "kill", "expected"),
    [
        (Side.LONG, ProposedAction.BUY, True, (VetoCode.KILL_SWITCH,)),
        (Side.SHORT, ProposedAction.SELL, True, (VetoCode.KILL_SWITCH,)),
        (Side.LONG, ProposedAction.HOLD, True, ()),
        (Side.SHORT, ProposedAction.HOLD, True, ()),
        (Side.LONG, ProposedAction.SELL, True, ()),
        (Side.SHORT, ProposedAction.BUY, True, ()),
        (Side.LONG, ProposedAction.BUY, False, ()),
        (Side.SHORT, ProposedAction.SELL, False, ()),
    ],
)
def test_kill_switch_only_when_that_side_would_add(side, action, kill, expected) -> None:
    bias_4h = StructureBias.UP if side is Side.LONG else StructureBias.DOWN
    result, _ = _evaluate(side=side, action=action, kill=kill, bias_4h=bias_4h, score=0.99)
    assert _codes(result) == expected


def test_vol_band_is_the_atr_pct_range_not_the_sample_count() -> None:
    params = _params(atr_pct_min=0.002, atr_pct_max=0.020)
    low_edge, _ = _evaluate(
        params=params,
        vol_raw={"atr_pct": params.atr_pct_min, "in_band": False, "vol_n": 0},
    )
    high_edge, _ = _evaluate(
        params=params,
        vol_raw={"atr_pct": params.atr_pct_max, "in_band": False, "vol_n": 0},
    )
    assert low_edge.passed is True
    assert high_edge.passed is True
    inside, _ = _evaluate(vol_raw={"atr_pct": 0.01, "in_band": False, "vol_n": 1})
    assert inside.passed is True
    flat, _ = _evaluate(
        params=params,
        vol_raw={"atr_pct": 0.0, "in_band": True, "vol_n": 500},
    )
    assert _codes(flat) == (VetoCode.VOL_BAND,)
    assert flat.vetoes[0].measured == format(0.0, ".8f")
    assert flat.vetoes[0].threshold == f"{format(params.atr_pct_min, '.8f')},{format(params.atr_pct_max, '.8f')}"
    wild, _ = _evaluate(params=params, vol_raw={"atr_pct": 1.0, "in_band": False, "vol_n": 500})
    assert _codes(wild) == (VetoCode.VOL_BAND,)
    missing, _ = _evaluate(vol_raw={"atr_pct": True, "vol_n": 1})
    assert _codes(missing) == (VetoCode.VOL_BAND,)
    assert missing.vetoes[0].message == "atr_pct missing"


def test_session_skip_uses_the_bucket_list_and_funding_is_not_a_veto() -> None:
    skipped, _ = _evaluate(
        params=_params(hard_skip_buckets=("late", "us")),
        session_raw={"session_bucket": "late", "hard_skip": False, "in_funding_window": False},
    )
    assert _codes(skipped) == (VetoCode.SESSION_SKIP,)
    assert skipped.vetoes[0].measured == "late"
    assert skipped.vetoes[0].threshold == "late,us"
    funded, _ = _evaluate(
        session_raw={"session_bucket": "asia", "hard_skip": True, "in_funding_window": True},
    )
    assert funded.passed is True
    absent, _ = _evaluate(vol_raw={"atr_pct": 0.01}, session_raw={})
    assert _codes(absent) == (VetoCode.SESSION_SKIP,)
    assert absent.vetoes[0].message == "session bucket missing"


def test_position_open_is_this_symbol_only() -> None:
    short, _ = _evaluate(positions=(_position(qty=Decimal("-1")),), count=1)
    assert _codes(short) == (VetoCode.POSITION_OPEN,)
    assert short.vetoes[0].measured == "-1"
    assert short.vetoes[0].threshold == "0"
    other, _ = _evaluate(
        positions=(
            _position(symbol="ETH/USDT", qty=Decimal("3")),
            _position(qty=Decimal("0")),
        ),
        orders=("ord-exit",),
        count=3,
    )
    assert other.passed is True


def test_outside_universe_only_on_a_unique_candidate() -> None:
    unique, _ = _evaluate(rank=None)
    assert _codes(unique) == (VetoCode.OUTSIDE_UNIVERSE,)
    assert unique.vetoes[0].measured == "none"
    empty, _ = _evaluate(side=Side.NONE, rank=None)
    assert _codes(empty) == (VetoCode.NO_CANDIDATE,)
    ambiguous, _ = _evaluate(
        side=Side.NONE,
        rank=None,
        signals=(
            _signal(SignalType.SECOND_BUY, T1, signal_id="buy"),
            _signal(SignalType.THIRD_SELL, T1, signal_id="sell"),
        ),
    )
    assert _codes(ambiguous) == (VetoCode.AMBIGUOUS_SIGNAL,)


def test_stale_follows_the_flag_and_gap_follows_the_reason() -> None:
    labeled, _ = _evaluate(stale=False, reasons=(VetoCode.STALE_DATA.value,), missing=4)
    assert labeled.passed is True
    stale, _ = _evaluate(stale=True, reasons=())
    assert _codes(stale) == (VetoCode.STALE_DATA,)
    gap, _ = _evaluate(reasons=(VetoCode.GAP_DATA.value,), missing=0)
    assert _codes(gap) == (VetoCode.GAP_DATA,)
    hole, _ = _evaluate(reasons=(), missing=3)
    assert hole.passed is True


def test_unclosed_bars_do_not_fill_the_window() -> None:
    params = _params(window_15m=3, window_1h=2, window_4h=4)
    result, _ = _evaluate(params=params, closed=1, unclosed=1)
    assert _codes(result) == (VetoCode.INSUFFICIENT_HISTORY,)
    assert result.vetoes[0].measured == "15m=1,1h=1,4h=1"
    assert result.vetoes[0].threshold == "15m=3,1h=2,4h=4"
    enough, _ = _evaluate(params=_params(window_15m=1, window_1h=1, window_4h=1), closed=1, unclosed=5)
    assert enough.passed is True


def test_missing_measurements_fail_closed_in_section_6_order() -> None:
    result, _ = _evaluate(vol_raw={}, session_raw={})
    assert _codes(result) == (VetoCode.SESSION_SKIP, VetoCode.VOL_BAND)


def test_unique_candidate_returns_every_veto_in_section_6_order() -> None:
    params = _params(window_15m=2, window_1h=2, window_4h=2, hard_skip_buckets=("late",))
    result, assessment = _evaluate(
        action=ProposedAction.BUY,
        score=0.99,
        kill=True,
        stale=True,
        reasons=(VetoCode.GAP_DATA.value,),
        session_raw={"session_bucket": "late", "hard_skip": True},
        bias_4h=StructureBias.DOWN,
        bias_1h=StructureBias.BREAKOUT_DOWN,
        vol_raw={"atr_pct": 0.0, "in_band": False, "vol_n": 1},
        rank=None,
        params=params,
        closed=1,
        positions=(_position(qty=Decimal("1.5")),),
        count=1,
    )
    assert _codes(result) == (
        VetoCode.KILL_SWITCH,
        VetoCode.STALE_DATA,
        VetoCode.GAP_DATA,
        VetoCode.SESSION_SKIP,
        VetoCode.HTF_DIRECTION,
        VetoCode.MTF_1H_CONFLICT,
        VetoCode.VOL_BAND,
        VetoCode.OUTSIDE_UNIVERSE,
        VetoCode.INSUFFICIENT_HISTORY,
        VetoCode.POSITION_OPEN,
    )
    assert result.passed is False
    assert assessment.score == 0.99
    assert _RISK.isdisjoint(_codes(result))
    for veto in result.vetoes:
        assert isinstance(veto.message, str)
        assert isinstance(veto.measured, str)
        assert isinstance(veto.threshold, str)


def test_a_second_evaluate_does_not_keep_earlier_vetoes() -> None:
    gate = RuleGate(_params())
    blocked = gate.evaluate(_context(stale=True), _assessment(), _account(), _safety())
    assert _codes(blocked) == (VetoCode.STALE_DATA,)
    clean = gate.evaluate(_context(), _assessment(), _account(), _safety())
    assert clean.passed is True
    assert clean.vetoes == ()


def _codes(result: HardRuleResult) -> tuple[VetoCode, ...]:
    return tuple(item.code for item in result.vetoes)


def _params(**overrides: object) -> RuleParams:
    values: dict[str, object] = {
        "window_15m": 1,
        "window_1h": 1,
        "window_4h": 1,
        "atr_pct_min": 0.001,
        "atr_pct_max": 0.030,
        "hard_skip_buckets": (),
    }
    values.update(overrides)
    return RuleParams(**values)  # type: ignore[arg-type]


def _evaluate(
    *,
    params: RuleParams | None = None,
    side: Side = Side.LONG,
    action: ProposedAction = ProposedAction.HOLD,
    score: float = 0.10,
    bias_4h: StructureBias = StructureBias.UP,
    bias_1h: StructureBias = StructureBias.NEUTRAL,
    signals: tuple[ChanSignal, ...] = (),
    h1_signals: tuple[ChanSignal, ...] = (),
    rank: int | None = 1,
    stale: bool = False,
    reasons: tuple[str, ...] = (),
    missing: int = 0,
    closed: int = 1,
    unclosed: int = 0,
    positions: tuple[PositionState, ...] = (),
    orders: tuple[str, ...] = (),
    count: int = 0,
    kill: bool = False,
    vol_raw: dict[str, float | int | str | bool | None] | None = None,
    session_raw: dict[str, float | int | str | bool | None] | None = None,
    resonance_raw: dict[str, float | int | str | bool | None] | None = None,
) -> tuple[HardRuleResult, JevAssessment]:
    assessment = _assessment(
        side=side,
        action=action,
        score=score,
        vol_raw=vol_raw,
        session_raw=session_raw,
        resonance_raw=resonance_raw,
    )
    context = _context(
        bias_4h=bias_4h,
        bias_1h=bias_1h,
        signals=signals,
        h1_signals=h1_signals,
        rank=rank,
        stale=stale,
        reasons=reasons,
        missing=missing,
        closed=closed,
        unclosed=unclosed,
    )
    result = RuleGate(params or _params()).evaluate(context, assessment, _account(positions, orders, count), _safety(kill))
    return result, assessment


def _assessment(
    *,
    side: Side = Side.LONG,
    action: ProposedAction = ProposedAction.HOLD,
    score: float = 0.10,
    vol_raw: dict[str, float | int | str | bool | None] | None = None,
    session_raw: dict[str, float | int | str | bool | None] | None = None,
    resonance_raw: dict[str, float | int | str | bool | None] | None = None,
) -> JevAssessment:
    if vol_raw is None:
        vol_raw = {"atr_pct": 0.01, "in_band": True, "vol_n": 1}
    if session_raw is None:
        session_raw = {"session_bucket": "asia", "hard_skip": False, "in_funding_window": False}
    if resonance_raw is None:
        resonance_raw = {}
    components: dict[str, ComponentScore] = {}
    for name in CHANNEL_NAMES:
        raw: dict[str, float | int | str | bool | None] = {}
        if name == "volatility_volume":
            raw = vol_raw
        elif name == "session":
            raw = session_raw
        elif name == "resonance":
            raw = resonance_raw
        components[name] = ComponentScore(
            channel=name,
            subscore=0.0,
            penalty=0.0,
            adjusted=0.0,
            weight=0.0,
            contribution=0.0,
            skip=False,
            raw=raw,
        )
    return JevAssessment(
        jev_version="weighted-v1",
        calibrated=False,
        candidate_side=side,
        score=score,
        p_buy=0.0,
        p_sell=0.0,
        p_hold=1.0,
        components=components,
        reasons=(),
        threshold=0.62,
        proposed_action=action,
    )


def _context(
    *,
    bias_4h: StructureBias = StructureBias.UP,
    bias_1h: StructureBias = StructureBias.NEUTRAL,
    signals: tuple[ChanSignal, ...] = (),
    h1_signals: tuple[ChanSignal, ...] = (),
    rank: int | None = 1,
    stale: bool = False,
    reasons: tuple[str, ...] = (),
    missing: int = 0,
    closed: int = 1,
    unclosed: int = 0,
) -> MultiTimeframeContext:
    return MultiTimeframeContext(
        context_id="ctx-1",
        symbol="BTC/USDT",
        decision_time=T1,
        bars=_bars(closed, unclosed),
        snapshots={
            Timeframe.M15: _snapshot(Timeframe.M15, StructureBias.NEUTRAL, signals),
            Timeframe.H1: _snapshot(Timeframe.H1, bias_1h, h1_signals),
            Timeframe.H4: _snapshot(Timeframe.H4, bias_4h, ()),
        },
        data_quality=DataQuality(
            stale=stale,
            max_gap_bars=1,
            missing_bar_count=missing,
            reasons=reasons,
        ),
        instrument=_instrument(),
        universe_date=date(2024, 1, 1),
        universe_rank=rank,
    )


def _bars(closed: int, unclosed: int) -> dict[Timeframe, tuple[Bar, ...]]:
    bars: dict[Timeframe, tuple[Bar, ...]] = {}
    for timeframe in Timeframe:
        step = timeframe_duration(timeframe)
        items = [
            _bar(timeframe, T0 + index * step, closed=index < closed)
            for index in range(closed + unclosed)
        ]
        bars[timeframe] = tuple(items)
    return bars


def _bar(timeframe: Timeframe, open_time: datetime, *, closed: bool) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe_duration(timeframe),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
        is_closed=closed,
        source="binanceusdm",
    )


def _snapshot(
    timeframe: Timeframe,
    bias: StructureBias,
    signals: tuple[ChanSignal, ...],
) -> ChanSnapshot:
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
        fenxings=(),
        bis=(),
        segments=(),
        zhongshus=(),
        signals=signals,
        structure_bias=bias,
    )


def _signal(
    kind: SignalType,
    when: datetime,
    *,
    timeframe: Timeframe = Timeframe.M15,
    signal_id: str,
) -> ChanSignal:
    buy = kind in (SignalType.SECOND_BUY, SignalType.THIRD_BUY, SignalType.FIRST_BUY)
    return ChanSignal(
        id=signal_id,
        timeframe=timeframe,
        type=kind,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=100.5,
        direction=Direction.UP if buy else Direction.DOWN,
        defending_fx_id="fx-end",
        defending_price=100.0,
        related_bi_id="bi-1",
        bar_open_time=when,
    )


def _instrument() -> Instrument:
    return Instrument(
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
    )


def _position(symbol: str = "BTC/USDT", qty: Decimal = Decimal("1")) -> PositionState:
    return PositionState(
        symbol=symbol,
        qty=qty,
        avg_price=100.0,
        stop_price=99.0,
        plan=RiskPlan(
            symbol=symbol,
            side=Side.LONG,
            risk_fraction=Decimal("0.005"),
            target_risk_fraction=Decimal("0.005"),
            equity_quote=Decimal("10000"),
            qty=Decimal("0"),
            notional=Decimal("0"),
            max_notional=Decimal("20000"),
            rejected=True,
            reject_reason=VetoCode.INSTRUMENT_SPEC,
        ),
        entry_decision_id="dec-1",
        entry_decision_time=T1,
        entry_bar_open_time=T0,
    )


def _account(
    positions: tuple[PositionState, ...] = (),
    orders: tuple[str, ...] = (),
    count: int = 0,
) -> AccountView:
    return AccountView(
        equity_quote=Decimal("10000"),
        positions=positions,
        open_order_ids=orders,
        open_position_count=count,
        gross_notional_quote=Decimal("0"),
    )


def _safety(kill: bool = False) -> SafetyState:
    return SafetyState(kill_switch=kill, mode=RuntimeMode.PAPER)
