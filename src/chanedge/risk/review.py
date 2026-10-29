"""Open-position review. Full next-open exits and stop amendments."""

from __future__ import annotations

from decimal import Decimal

from chanedge.domain.bars import Bar, MultiTimeframeContext
from chanedge.domain.enums import (
    AmendReason,
    Direction,
    ExitKind,
    ExitReason,
    FillModel,
    Side,
    SignalStatus,
    Timeframe,
)
from chanedge.domain.risk import (
    AmendStop,
    ExitInstruction,
    InvalidationSpec,
    PositionReview,
    PositionState,
)
from chanedge.risk.stops import ceil_to_tick, floor_to_tick


def review_position(context: MultiTimeframeContext, position: PositionState) -> PositionReview:
    invalidation = position.plan.invalidation
    if invalidation is not None:
        instruction = _structural_exit(context, position, invalidation)
        if instruction is not None:
            return PositionReview(exit=instruction)
    amend = _amend(context, position)
    if amend is None:
        return PositionReview()
    return PositionReview(amend_stop=amend)


def _structural_exit(
    context: MultiTimeframeContext,
    position: PositionState,
    spec: InvalidationSpec,
) -> ExitInstruction | None:
    opposite = _opposite(context, position, spec)
    if opposite is not None:
        return opposite
    bias = _bias(context, position, spec)
    if bias is not None:
        return bias
    short = position.plan.side is Side.SHORT
    failed = _level_break(
        context,
        position,
        spec.zhongshu_fail_price,
        short=short,
        reason=ExitReason.ZHONGSHU_FAIL,
    )
    if failed is not None:
        return failed
    return _level_break(
        context,
        position,
        spec.swing_fail_price,
        short=short,
        reason=ExitReason.SWING_FAIL,
    )


def _opposite(
    context: MultiTimeframeContext,
    position: PositionState,
    spec: InvalidationSpec,
) -> ExitInstruction | None:
    chosen = None
    for signal in context.snapshots[Timeframe.M15].signals:
        if signal.timeframe is not Timeframe.M15 or signal.status is not SignalStatus.CONFIRMED:
            continue
        if signal.type not in spec.opposite_signal_types:
            continue
        if not signal.time > position.entry_decision_time:
            continue
        if chosen is None or signal.time < chosen.time:
            chosen = signal
    if chosen is None:
        return None
    return _exit(position, ExitReason.OPPOSITE_SIGNAL, chosen.price)


def _bias(
    context: MultiTimeframeContext,
    position: PositionState,
    spec: InvalidationSpec,
) -> ExitInstruction | None:
    bias = context.snapshots[Timeframe.H1].structure_bias
    if bias not in spec.htf_bias_exit:
        return None
    return _exit(position, ExitReason.BIAS_1H, _decision_close(context, position))


def _level_break(
    context: MultiTimeframeContext,
    position: PositionState,
    level: float | None,
    *,
    short: bool,
    reason: ExitReason,
) -> ExitInstruction | None:
    if level is None:
        return None
    frozen = _decimal(level)
    chosen: Bar | None = None
    for bar in context.bars[Timeframe.M15]:
        if not bar.is_closed or bar.open_time < position.entry_bar_open_time:
            continue
        close = _decimal(bar.close)
        failed = close > frozen if short else close < frozen
        if not failed:
            continue
        if chosen is None or bar.open_time < chosen.open_time:
            chosen = bar
    if chosen is None:
        return None
    return _exit(position, reason, chosen.close)


def _amend(context: MultiTimeframeContext, position: PositionState) -> AmendStop | None:
    plan = position.plan
    trail = plan.trail
    if trail is None or plan.entry_reference is None or plan.structure_stop_price is None:
        return None
    bar = _decision_bar(context)
    # The caller runs this once per closed bar, so only that bar can arm.
    if bar is None or bar.open_time < position.entry_bar_open_time:
        return None
    entry = _decimal(plan.entry_reference)
    distance = abs(entry - _decimal(plan.structure_stop_price))
    reach = _decimal(trail.arm_r) * distance
    live = _decimal(position.stop_price)
    short = plan.side is Side.SHORT
    if short:
        armed = live <= entry
        reached = _decimal(bar.low) <= entry - reach
    else:
        armed = live >= entry
        reached = _decimal(bar.high) >= entry + reach
    if not armed:
        if not reached:
            return None
        return AmendStop(new_stop_price=plan.entry_reference, reason=AmendReason.BREAKEVEN)
    return _ratchet(context, position, live, short=short)


def _ratchet(
    context: MultiTimeframeContext,
    position: PositionState,
    live: Decimal,
    *,
    short: bool,
) -> AmendStop | None:
    plan = position.plan
    if plan.stop_buffer is None:
        return None
    tick = context.instrument.price_tick
    if tick is None or tick <= 0:
        return None
    endpoint = _confirming_end(context, Direction.UP if short else Direction.DOWN)
    if endpoint is None:
        return None
    cushion = _decimal(plan.stop_buffer)
    if short:
        if not endpoint < live:
            return None
        moved = ceil_to_tick(endpoint + cushion, tick)
        if not moved < live:
            return None
    else:
        if not endpoint > live:
            return None
        moved = floor_to_tick(endpoint - cushion, tick)
        if not moved > live:
            return None
    return AmendStop(new_stop_price=float(moved), reason=AmendReason.RATCHET)


def _confirming_end(context: MultiTimeframeContext, direction: Direction) -> Decimal | None:
    """Last bi newly established on this decision bar. A replaced endpoint is not one."""
    snapshot = context.snapshots[Timeframe.M15]
    fenxings = {item.id: item for item in snapshot.fenxings}
    chosen: Decimal | None = None
    for bi in snapshot.bis:
        if bi.timeframe is not Timeframe.M15 or not bi.confirmed or bi.direction is not direction:
            continue
        fenxing = fenxings.get(bi.end_fx_id)
        if fenxing is None or fenxing.time != context.decision_time:
            continue
        if bi.established_at is not None and bi.established_at != context.decision_time:
            continue
        chosen = _decimal(bi.end_price)
    return chosen


def _decision_bar(context: MultiTimeframeContext) -> Bar | None:
    for bar in context.bars[Timeframe.M15]:
        if bar.is_closed and bar.close_time == context.decision_time:
            return bar
    return None


def _decision_close(context: MultiTimeframeContext, position: PositionState) -> float:
    bar = _decision_bar(context)
    if bar is not None:
        return bar.close
    reference = position.plan.entry_reference
    if reference is None:
        return position.avg_price
    return reference


def _exit(position: PositionState, reason: ExitReason, trigger: float) -> ExitInstruction:
    return ExitInstruction(
        kind=ExitKind.EXIT,
        reason=reason,
        qty=abs(position.qty),
        trigger_price=trigger,
        fill_model=FillModel.NEXT_OPEN,
    )


def _decimal(value: float) -> Decimal:
    return Decimal(format(value, ".8f"))
