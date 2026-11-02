"""Pure match_bar. One exit per position per bar, stop before TP1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from chanedge.backtest.matcher import match_bar
from chanedge.domain.bars import Bar
from chanedge.domain.enums import (
    ExitReason,
    OrderSide,
    PartialReason,
    Side,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
)
from chanedge.domain.records import PendingOrder
from chanedge.domain.risk import InvalidationSpec, PartialTarget, PositionState, RiskPlan, TrailRule

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
ZERO = Decimal("0")
FEE = Decimal("5")


def test_opposite_exit_fills_once_at_the_open_plus_slippage() -> None:
    held = _position(_plan(stop=90.0), stop_price=90.0)
    exiting = _pending(
        client_order_id="exit-1",
        decision_id="dec-exit",
        side=OrderSide.SELL,
        reduce_only=True,
        exit_reason=ExitReason.OPPOSITE_SIGNAL,
        plan=None,
    )
    # Open is still above the stop. The low would have been a stop fill.
    candle = _bar(T15, open_=95.0, high=96.0, low=80.0, close=95.0)
    fills = match_bar(
        held,
        (exiting,),
        candle,
        fee_bps=FEE,
        slippage_bps=Decimal("10"),
        arm_close=None,
    )
    assert len(fills) == 1
    assert fills[0].bar_seq == 0
    assert fills[0].price == Decimal("94.90500000")
    assert fills[0].exit_reason is ExitReason.OPPOSITE_SIGNAL
    assert fills[0].reduce_only is True


def test_entry_that_opens_through_the_stop_fills_then_stops() -> None:
    entering = _pending(plan=_plan(entry=100.0, stop=99.0), side=OrderSide.BUY, reduce_only=False)
    candle = _bar(T15, open_=98.0, high=99.0, low=97.0, close=98.0)
    fills = match_bar(
        None,
        (entering,),
        candle,
        fee_bps=ZERO,
        slippage_bps=ZERO,
        arm_close=None,
    )
    assert [fill.bar_seq for fill in fills] == [0, 1]
    assert [fill.price for fill in fills] == [Decimal("98.00000000"), Decimal("98.00000000")]
    assert fills[0].reduce_only is False
    assert fills[1].reduce_only is True
    assert fills[1].exit_reason is ExitReason.STRUCTURE_STOP
    assert fills[1].client_order_id.endswith(":stop")


def test_breakeven_adverse_uses_the_arm_bar_close() -> None:
    held = _position(
        _plan(entry=100.0, stop=99.66),
        avg_price=90.0,
        stop_price=100.0,
    )
    candle = _bar(T15, open_=99.5, high=100.0, low=99.4, close=99.6)
    fills = match_bar(held, (), candle, fee_bps=ZERO, slippage_bps=ZERO, arm_close=99.8)
    assert len(fills) == 1
    assert fills[0].price == Decimal("99.50000000")
    assert fills[0].exit_reason is ExitReason.BREAKEVEN_ADVERSE
    assert fills[0].bar_seq == 1


def test_a_flattening_exit_is_the_only_fill_on_that_bar() -> None:
    held = _position(_plan(stop=90.0), stop_price=90.0)
    exiting = _pending(
        client_order_id="exit-1",
        side=OrderSide.SELL,
        reduce_only=True,
        exit_reason=ExitReason.OPPOSITE_SIGNAL,
        group_order=1,
    )
    entering = _pending(
        client_order_id="entry-1",
        side=OrderSide.BUY,
        reduce_only=False,
        plan=_plan(),
        group_order=0,
    )
    candle = _bar(T15, open_=95.0, high=96.0, low=80.0, close=94.0)
    fills = match_bar(
        held,
        (entering, exiting),
        candle,
        fee_bps=ZERO,
        slippage_bps=ZERO,
        arm_close=None,
    )
    assert len(fills) == 1
    assert fills[0].client_order_id == "exit-1"
    assert fills[0].price == Decimal("95.00000000")


def test_stop_beats_tp1_when_both_are_touched() -> None:
    target = PartialTarget(fraction=0.5, price=101.0, reason=PartialReason.R_MULTIPLE)
    held = _position(_plan(stop=99.0, targets=(target,)), stop_price=99.0)
    candle = _bar(T15, open_=100.0, high=102.0, low=98.0, close=100.0)
    fills = match_bar(held, (), candle, fee_bps=ZERO, slippage_bps=ZERO, arm_close=None)
    assert len(fills) == 1
    assert fills[0].exit_reason is ExitReason.STRUCTURE_STOP
    assert fills[0].client_order_id.endswith(":stop")


def test_tp1_fills_once_per_position() -> None:
    target = PartialTarget(fraction=0.5, price=101.0, reason=PartialReason.R_MULTIPLE)
    held = _position(_plan(stop=99.0, qty=Decimal("8"), targets=(target,)), stop_price=99.0)
    candle = _bar(T15, open_=100.0, high=102.0, low=99.5, close=100.0)
    first = match_bar(held, (), candle, fee_bps=ZERO, slippage_bps=ZERO, arm_close=None)
    assert [fill.qty for fill in first] == [Decimal("4")]
    assert first[0].client_order_id.endswith(":tp1")
    reduced = held.model_copy(update={"qty": Decimal("4")})
    later = _bar(T15 + timedelta(minutes=15), open_=100.0, high=102.0, low=99.5, close=100.0)
    again = match_bar(reduced, (), later, fee_bps=ZERO, slippage_bps=ZERO, arm_close=None, tp1_filled=True)
    assert again == ()
    # The stop still fills after TP1.
    stopped = _bar(T15 + timedelta(minutes=30), open_=100.0, high=102.0, low=98.0, close=100.0)
    exits = match_bar(reduced, (), stopped, fee_bps=ZERO, slippage_bps=ZERO, arm_close=None, tp1_filled=True)
    assert [fill.qty for fill in exits] == [Decimal("4")]
    assert exits[0].client_order_id.endswith(":stop")


def _plan(
    *,
    entry: float = 100.0,
    stop: float = 99.0,
    qty: Decimal = Decimal("1"),
    targets: tuple[PartialTarget, ...] = (),
) -> RiskPlan:
    return RiskPlan(
        symbol="BTC/USDT",
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=qty,
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=entry,
        atr=0.0,
        structure_stop_price=stop,
        stop_buffer=0.0,
        defending_fx_id="fx-def",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL, SignalType.THIRD_SELL),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=stop,
            defending_fx_id="fx-def",
            effective_after=T0,
        ),
        realized_risk_fraction=Decimal("0.005"),
        cost_r=Decimal("0.10"),
        binding_constraint="risk_fraction",
        partial_targets=targets,
        trail=TrailRule(
            kind=TrailKind.STRUCTURE_FENXING,
            arm_r=1.0,
            breakeven_price=entry,
            buffer=0.15,
        ),
    )


def _position(plan: RiskPlan, **overrides: object) -> PositionState:
    values: dict[str, object] = {
        "symbol": plan.symbol,
        "qty": plan.qty,
        "avg_price": 100.0,
        "stop_price": plan.structure_stop_price,
        "plan": plan,
        "entry_decision_id": "dec-entry",
        "entry_decision_time": T0,
        "entry_bar_open_time": T0,
    }
    values.update(overrides)
    return PositionState(**values)  # type: ignore[arg-type]


def _pending(**overrides: object) -> PendingOrder:
    values: dict[str, object] = {
        "client_order_id": "entry-1",
        "decision_id": "dec-entry",
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "qty": Decimal("1"),
        "reduce_only": False,
        "group_order": 0,
        "exit_reason": None,
        "plan": None,
        "entry_decision_time": T0,
        "submitted_at": T0,
    }
    values.update(overrides)
    return PendingOrder(**values)  # type: ignore[arg-type]


def _bar(open_time: datetime, **overrides: object) -> Bar:
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "timeframe": Timeframe.M15,
        "open_time": open_time,
        "close_time": open_time + timedelta(minutes=15),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1.0,
        "is_closed": True,
        "source": "binanceusdm",
    }
    if "open_" in overrides:
        values["open"] = overrides.pop("open_")
    values.update(overrides)
    return Bar(**values)  # type: ignore[arg-type]
