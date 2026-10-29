"""RiskManager.plan_entry sizes one order. review_open delegates to review.py."""

from __future__ import annotations

import math
from decimal import Decimal

from chanedge.domain.bars import MultiTimeframeContext
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.decision import FeatureVector, HardRuleResult, JevAssessment
from chanedge.domain.enums import Side, SignalType, StructureBias, Timeframe, TrailKind, VetoCode
from chanedge.domain.params import RiskParams
from chanedge.domain.risk import (
    AccountView,
    InvalidationSpec,
    PositionReview,
    PositionState,
    RiskPlan,
    TrailRule,
)
from chanedge.risk.review import review_position
from chanedge.risk.stops import floor_to_step, partial_target, price_decimal, round_trip, structure_stop

_LONG_OPPOSITE = (SignalType.SECOND_SELL, SignalType.THIRD_SELL)
_SHORT_OPPOSITE = (SignalType.SECOND_BUY, SignalType.THIRD_BUY)
_LONG_EXIT = (StructureBias.DOWN, StructureBias.BREAKOUT_DOWN)
_SHORT_EXIT = (StructureBias.UP, StructureBias.BREAKOUT_UP)


class RiskManager:
    def __init__(self, params: RiskParams) -> None:
        if not isinstance(params, RiskParams):
            raise TypeError("params must be RiskParams")
        self._params = params

    def plan_entry(
        self,
        context: MultiTimeframeContext,
        features: FeatureVector,
        assessment: JevAssessment,
        rules: HardRuleResult,
        account: AccountView,
    ) -> RiskPlan:
        del rules  # passed and proposed_action belong to the caller
        params = self._params
        equity = account.equity_quote
        side = assessment.candidate_side
        instrument = context.instrument
        tick = instrument.price_tick
        step = instrument.qty_step
        min_qty = instrument.min_qty
        if not _positive(tick) or not _positive(step) or not _positive(min_qty):
            return _reject(context, params, equity, side, VetoCode.INSTRUMENT_SPEC)

        if account.open_position_count >= params.max_open_positions:
            return _reject(context, params, equity, side, VetoCode.MAX_OPEN_POSITIONS)

        if _same_direction(account.positions, side) >= params.max_same_direction:
            return _reject(context, params, equity, side, VetoCode.MAX_SAME_DIRECTION)

        entry = _price(features.signal_bar.close)
        atr = _price(features.volatility_volume.atr)
        signal = _match_signal(context, features.candidate_signal_id)
        stop: Decimal | None = None
        buffer: Decimal | None = None
        defending_id: str | None = None
        if (
            side in (Side.LONG, Side.SHORT)
            and entry is not None
            and atr is not None
            and atr >= 0
            and signal is not None
        ):
            buffer = params.stop_buffer_atr * atr
            stop = structure_stop(side, price_decimal(signal.defending_price), buffer, tick)
            defending_id = signal.defending_fx_id

        stop_dist = _stop_distance(side, entry, stop)
        known = _known(entry, atr, stop, buffer, defending_id)
        if stop_dist <= 0 or equity <= 0 or entry is None or entry <= 0:
            return _reject(context, params, equity, side, VetoCode.RISK_CAP, **known)

        assert entry is not None and stop is not None and atr is not None and buffer is not None
        assert signal is not None
        cost = round_trip(params.fee_bps, params.slippage_bps) / (stop_dist / entry)
        if cost > params.max_cost_r:
            return _reject(context, params, equity, side, VetoCode.COST_R, cost_r=cost, **known)

        min_notional = instrument.min_notional
        risk_quote = equity * params.risk_fraction
        qty = floor_to_step(risk_quote / stop_dist, step)
        if _below_floor(qty, entry, min_qty, min_notional):
            return _reject(context, params, equity, side, VetoCode.RISK_CAP, cost_r=cost, **known)
        qty_risk = qty

        single_cap = _single_cap(params, equity)
        if qty * entry > single_cap:
            qty = floor_to_step(single_cap / entry, step)
            if _below_floor(qty, entry, min_qty, min_notional):
                return _reject(
                    context, params, equity, side, VetoCode.MAX_NOTIONAL, cost_r=cost, **known
                )
        qty_single = qty

        gross_cap = min(params.max_gross_notional_quote, equity * params.max_leverage)
        remaining = gross_cap - account.gross_notional_quote
        if remaining <= 0:
            return _reject(
                context, params, equity, side, VetoCode.MAX_GROSS_NOTIONAL, cost_r=cost, **known
            )
        if qty * entry > remaining:
            qty = floor_to_step(remaining / entry, step)
            if _below_floor(qty, entry, min_qty, min_notional):
                return _reject(
                    context,
                    params,
                    equity,
                    side,
                    VetoCode.MAX_GROSS_NOTIONAL,
                    cost_r=cost,
                    **known,
                )
        if qty < qty_single:
            binding = "max_gross_notional"
        elif qty_single < qty_risk and equity * params.max_leverage < params.max_notional_quote:
            binding = "max_leverage"
        elif qty_single < qty_risk:
            binding = "max_notional"
        else:
            binding = "risk_fraction"

        entry_price = float(entry)
        stop_price = float(stop)
        return RiskPlan(
            symbol=context.symbol,
            side=side,
            risk_fraction=params.risk_fraction,
            target_risk_fraction=params.risk_fraction,
            equity_quote=equity,
            qty=qty,
            notional=qty * entry,
            max_notional=single_cap,
            rejected=False,
            entry_reference=entry_price,
            atr=float(atr),
            structure_stop_price=stop_price,
            stop_buffer=float(buffer),
            defending_fx_id=defending_id,
            invalidation=_invalidation(side, signal, context, stop_price),
            realized_risk_fraction=qty * stop_dist / equity,
            cost_r=cost,
            binding_constraint=binding,
            partial_targets=(
                partial_target(
                    side=side,
                    entry=entry,
                    stop=stop,
                    fraction=params.partial_fraction,
                    r_fallback=params.r_fallback,
                    snapshot=context.snapshots[Timeframe.M15],
                    decision_time=context.decision_time,
                ),
            ),
            trail=TrailRule(
                kind=TrailKind.STRUCTURE_FENXING,
                arm_r=float(params.arm_r),
                breakeven_price=entry_price,
                buffer=float(buffer),
            ),
        )

    def review_open(
        self,
        context: MultiTimeframeContext,
        position: PositionState,
    ) -> PositionReview:
        return review_position(context, position)


def _reject(
    context: MultiTimeframeContext,
    params: RiskParams,
    equity: Decimal,
    side: Side,
    code: VetoCode,
    *,
    cost_r: Decimal | None = None,
    entry: Decimal | None = None,
    atr: Decimal | None = None,
    stop: Decimal | None = None,
    buffer: Decimal | None = None,
    defending_fx_id: str | None = None,
) -> RiskPlan:
    return RiskPlan(
        symbol=context.symbol,
        side=side if side in (Side.LONG, Side.SHORT) else Side.NONE,
        risk_fraction=params.risk_fraction,
        target_risk_fraction=params.risk_fraction,
        equity_quote=equity,
        qty=Decimal(0),
        notional=Decimal(0),
        max_notional=_single_cap(params, equity),
        rejected=True,
        reject_reason=code,
        binding_constraint=code.value,
        entry_reference=None if entry is None else float(entry),
        atr=None if atr is None else float(atr),
        structure_stop_price=None if stop is None else float(stop),
        stop_buffer=None if buffer is None else float(buffer),
        defending_fx_id=defending_fx_id,
        cost_r=cost_r,
    )


def _known(
    entry: Decimal | None,
    atr: Decimal | None,
    stop: Decimal | None,
    buffer: Decimal | None,
    defending_fx_id: str | None,
) -> dict[str, Decimal | str | None]:
    return {
        "entry": entry,
        "atr": atr,
        "stop": stop,
        "buffer": buffer,
        "defending_fx_id": defending_fx_id,
    }


def _single_cap(params: RiskParams, equity: Decimal) -> Decimal:
    if equity <= 0:
        return params.max_notional_quote
    return min(params.max_notional_quote, equity * params.max_leverage)


def _same_direction(positions: tuple[PositionState, ...], side: Side) -> int:
    """Count filled qty signs. Order ids carry no side, so they are not counted."""
    if side is Side.LONG:
        return sum(1 for position in positions if position.qty > 0)
    if side is Side.SHORT:
        return sum(1 for position in positions if position.qty < 0)
    return 0


def _match_signal(context: MultiTimeframeContext, signal_id: str | None) -> ChanSignal | None:
    if signal_id is None:
        return None
    for signal in context.snapshots[Timeframe.M15].signals:
        if signal.id == signal_id and signal.timeframe is Timeframe.M15:
            return signal
    return None


def _stop_distance(side: Side, entry: Decimal | None, stop: Decimal | None) -> Decimal:
    if entry is None or stop is None:
        return Decimal(0)
    if side is Side.LONG:
        return entry - stop
    if side is Side.SHORT:
        return stop - entry
    return Decimal(0)


def _invalidation(
    side: Side,
    signal: ChanSignal,
    context: MultiTimeframeContext,
    stop_price: float,
) -> InvalidationSpec:
    if side is Side.LONG:
        opposite = _LONG_OPPOSITE
        bias = _LONG_EXIT
    else:
        opposite = _SHORT_OPPOSITE
        bias = _SHORT_EXIT
    zhongshu_id = signal.related_zhongshu_id
    zhongshu_fail: float | None = None
    swing_fail: float | None = None
    if signal.type is SignalType.THIRD_BUY:
        zhongshu_fail = _zhongshu_level(context, zhongshu_id, high=True)
    elif signal.type is SignalType.THIRD_SELL:
        zhongshu_fail = _zhongshu_level(context, zhongshu_id, high=False)
    elif signal.type in (SignalType.SECOND_BUY, SignalType.SECOND_SELL):
        swing_fail = signal.prior_extreme
    return InvalidationSpec(
        opposite_signal_types=opposite,
        htf_timeframe=Timeframe.H1,
        htf_bias_exit=bias,
        stop_price=stop_price,
        defending_fx_id=signal.defending_fx_id,
        effective_after=context.decision_time,
        zhongshu_id=zhongshu_id,
        zhongshu_fail_price=zhongshu_fail,
        swing_fail_price=swing_fail,
    )


def _zhongshu_level(context: MultiTimeframeContext, zhongshu_id: str | None, *, high: bool) -> float | None:
    if zhongshu_id is None:
        return None
    for zhongshu in context.snapshots[Timeframe.M15].zhongshus:
        if zhongshu.id == zhongshu_id:
            return zhongshu.zg if high else zhongshu.zd
    return None


def _below_floor(
    qty: Decimal,
    entry: Decimal,
    min_qty: Decimal,
    min_notional: Decimal | None,
) -> bool:
    if qty < min_qty:
        return True
    return min_notional is not None and qty * entry < min_notional


def _positive(value: Decimal | None) -> bool:
    return isinstance(value, Decimal) and value > 0


def _price(value: float) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return price_decimal(float(value))
