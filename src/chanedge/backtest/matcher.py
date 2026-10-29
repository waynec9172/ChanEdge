"""Pure bar matching. The loop calls this. The paper broker only records fills.

Step 1 fills leftover next-open orders at this bar's open. A reduce that
flattens the position is the only fill. Step 2 runs only while the position
is still open, and a stop fills before TP1.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chanedge.domain.accounting import quantize, update_cash
from chanedge.domain.bars import Bar
from chanedge.domain.enums import ExitReason, OrderSide
from chanedge.domain.records import MatchFill, PendingOrder
from chanedge.domain.risk import PositionState, RiskPlan

_BPS = Decimal("0.0001")
_ZERO = Decimal("0")


@dataclass
class _State:
    qty: Decimal
    avg: Decimal
    stop: Decimal
    plan: RiskPlan | None
    entry_decision_id: str
    symbol: str


def match_bar(
    position: PositionState | None,
    pending: tuple[PendingOrder, ...] | list[PendingOrder],
    bar: Bar,
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal,
    arm_close: float | None,
) -> tuple[MatchFill, ...]:
    """Return fills for one symbol. Inputs are not mutated."""
    state = _from_position(position)
    ordered = sorted(pending, key=lambda order: (0 if order.reduce_only else 1, order.group_order, order.symbol))
    fills: list[MatchFill] = []
    for order in ordered:
        if order.reduce_only and state.qty == _ZERO:
            continue
        if not order.reduce_only and state.qty != _ZERO:
            continue
        fill_qty = quantize(order.qty)
        if order.reduce_only:
            fill_qty = min(fill_qty, abs(state.qty))
        if fill_qty <= _ZERO:
            continue
        raw = quantize(bar.open)
        price = _slipped(raw, order.side, slippage_bps)
        fill = _fill(
            client_order_id=order.client_order_id,
            decision_id=order.decision_id,
            symbol=order.symbol,
            side=order.side,
            qty=fill_qty,
            raw=raw,
            price=price,
            fee_bps=fee_bps,
            fill_time=bar.open_time,
            bar_seq=0,
            reduce_only=order.reduce_only,
            exit_reason=order.exit_reason,
            partial_reason=None,
        )
        fills.append(fill)
        state = _apply(state, order, fill)
        if order.reduce_only and state.qty == _ZERO:
            return tuple(fills)
    if state.qty == _ZERO or state.plan is None or state.plan.structure_stop_price is None:
        return tuple(fills)
    stop_fill = _stop(state, bar, fee_bps=fee_bps, slippage_bps=slippage_bps, arm_close=arm_close)
    if stop_fill is not None:
        fills.append(stop_fill)
        return tuple(fills)
    target_fill = _target(state, bar, fee_bps=fee_bps, slippage_bps=slippage_bps)
    if target_fill is not None:
        fills.append(target_fill)
    return tuple(fills)


def _from_position(position: PositionState | None) -> _State:
    if position is None:
        return _State(_ZERO, _ZERO, _ZERO, None, "", "")
    return _State(
        quantize(position.qty),
        quantize(position.avg_price),
        quantize(position.stop_price),
        position.plan,
        position.entry_decision_id,
        position.symbol,
    )


def _apply(state: _State, order: PendingOrder, fill: MatchFill) -> _State:
    _cash, qty, avg = update_cash(
        _ZERO,
        state.qty,
        state.avg,
        fill_qty=fill.qty,
        fill_price=fill.price,
        fee=fill.fee_quote,
        side=fill.side,
        reduce_only=fill.reduce_only,
    )
    if fill.reduce_only:
        return _State(qty, avg, state.stop, state.plan, state.entry_decision_id, state.symbol)
    plan = order.plan
    if plan is None or plan.structure_stop_price is None:
        raise ValueError("entry fill is missing a structure stop")
    return _State(qty, avg, quantize(plan.structure_stop_price), plan, order.decision_id, order.symbol)


def _stop(
    state: _State,
    bar: Bar,
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal,
    arm_close: float | None,
) -> MatchFill | None:
    long = state.qty > _ZERO
    side = OrderSide.SELL if long else OrderSide.BUY
    raw = _touch(bar, state.stop, long=long, target=False)
    if raw is None:
        return None
    price = _slipped(raw, side, slippage_bps)
    client = state.entry_decision_id + ":stop"
    return _fill(
        client_order_id=client,
        decision_id=state.entry_decision_id,
        symbol=state.symbol,
        side=side,
        qty=abs(state.qty),
        raw=raw,
        price=price,
        fee_bps=fee_bps,
        fill_time=bar.open_time,
        bar_seq=1,
        reduce_only=True,
        exit_reason=_classify(state, arm_close),
        partial_reason=None,
    )


def _target(
    state: _State,
    bar: Bar,
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal,
) -> MatchFill | None:
    plan = state.plan
    if plan is None or not plan.partial_targets:
        return None
    target = plan.partial_targets[0]
    fraction = quantize(target.fraction)
    qty = quantize(abs(state.qty) * fraction)
    if qty <= _ZERO or qty > abs(state.qty):
        return None
    long = state.qty > _ZERO
    level = quantize(target.price)
    raw = _touch(bar, level, long=long, target=True)
    if raw is None:
        return None
    side = OrderSide.SELL if long else OrderSide.BUY
    price = _slipped(raw, side, slippage_bps)
    client = state.entry_decision_id + ":tp1"
    return _fill(
        client_order_id=client,
        decision_id=state.entry_decision_id,
        symbol=state.symbol,
        side=side,
        qty=qty,
        raw=raw,
        price=price,
        fee_bps=fee_bps,
        fill_time=bar.open_time,
        bar_seq=1,
        reduce_only=True,
        exit_reason=None,
        partial_reason=str(target.reason),
    )


def _touch(bar: Bar, level: Decimal, *, long: bool, target: bool) -> Decimal | None:
    """Long stop and short target use the low. The other two use the high."""
    opened = quantize(bar.open)
    if long == target:
        extreme = quantize(bar.high)
        if opened >= level:
            return opened
        if extreme >= level:
            return level
        return None
    extreme = quantize(bar.low)
    if opened <= level:
        return opened
    if extreme <= level:
        return level
    return None


def _classify(state: _State, arm_close: float | None) -> ExitReason:
    plan = state.plan
    if plan is None or plan.entry_reference is None or plan.structure_stop_price is None:
        return ExitReason.STRUCTURE_STOP
    stop = state.stop
    entry = quantize(plan.entry_reference)
    structure = quantize(plan.structure_stop_price)
    if stop == structure:
        return ExitReason.STRUCTURE_STOP
    long = state.qty > _ZERO
    if long and stop > entry:
        return ExitReason.RATCHET_STOP
    if not long and stop < entry:
        return ExitReason.RATCHET_STOP
    if stop == entry:
        if arm_close is None:
            return ExitReason.BREAKEVEN_STOP
        close = quantize(arm_close)
        favorable = close >= entry if long else close <= entry
        if favorable:
            return ExitReason.BREAKEVEN_STOP
        return ExitReason.BREAKEVEN_ADVERSE
    return ExitReason.STRUCTURE_STOP


def _slipped(raw: Decimal, side: OrderSide, slippage_bps: Decimal) -> Decimal:
    slip = quantize(slippage_bps) * _BPS
    if side is OrderSide.BUY:
        return quantize(raw * (Decimal(1) + slip))
    return quantize(raw * (Decimal(1) - slip))


def _fill(
    *,
    client_order_id: str,
    decision_id: str,
    symbol: str,
    side: OrderSide,
    qty: Decimal,
    raw: Decimal,
    price: Decimal,
    fee_bps: Decimal,
    fill_time: object,
    bar_seq: int,
    reduce_only: bool,
    exit_reason: ExitReason | None,
    partial_reason: str | None,
) -> MatchFill:
    fee = quantize(price * qty * quantize(fee_bps) * _BPS)
    slip_quote = quantize(abs(price - raw) * qty)
    return MatchFill(
        fill_id=f"{client_order_id}:{bar_seq}",
        client_order_id=client_order_id,
        decision_id=decision_id,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        fee_quote=fee,
        slippage_quote=slip_quote,
        fill_time=fill_time,  # type: ignore[arg-type]
        bar_seq=bar_seq,
        reduce_only=reduce_only,
        exit_reason=exit_reason,
        partial_reason=partial_reason,
    )
