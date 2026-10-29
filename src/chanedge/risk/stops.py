"""Tick rounding, the frozen structure stop, and the TP1 price. No second ATR."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN

from chanedge.domain.chanlun import ChanSnapshot
from chanedge.domain.enums import Direction, PartialReason, Side, Timeframe
from chanedge.domain.risk import PartialTarget

_BPS_UNIT = Decimal("0.0001")


def price_decimal(value: float) -> Decimal:
    return Decimal(format(value, ".8f"))


def floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def floor_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def ceil_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return (price / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def structure_stop(side: Side, defending: Decimal, buffer: Decimal, tick: Decimal) -> Decimal:
    if side is Side.LONG:
        return floor_to_tick(defending - buffer, tick)
    return ceil_to_tick(defending + buffer, tick)


def round_trip(fee_bps: Decimal, slippage_bps: Decimal) -> Decimal:
    return (fee_bps + slippage_bps) * 2 * _BPS_UNIT


def partial_target(
    *,
    side: Side,
    entry: Decimal,
    stop: Decimal,
    fraction: Decimal,
    r_fallback: Decimal,
    snapshot: ChanSnapshot,
    decision_time: datetime,
) -> PartialTarget:
    """Last favorable bi endpoint, or entry ± r_fallback * R. R is absolute."""
    distance = abs(entry - stop)
    favorable = Direction.UP if side is Side.LONG else Direction.DOWN
    endpoint = _last_endpoint(snapshot, favorable, decision_time)
    if side is Side.LONG and endpoint is not None and endpoint > entry:
        price = endpoint
        reason = PartialReason.PRIOR_SWING
    elif side is Side.SHORT and endpoint is not None and endpoint < entry:
        price = endpoint
        reason = PartialReason.PRIOR_SWING
    elif side is Side.LONG:
        price = entry + r_fallback * distance
        reason = PartialReason.R_MULTIPLE
    else:
        price = entry - r_fallback * distance
        reason = PartialReason.R_MULTIPLE
    return PartialTarget(fraction=float(fraction), price=float(price), reason=reason)


def _last_endpoint(snapshot: ChanSnapshot, direction: Direction, decision_time: datetime) -> Decimal | None:
    """Last confirmed M15 endpoint in tuple order whose fenxing time is already known."""
    chosen: Decimal | None = None
    fenxings = {item.id: item for item in snapshot.fenxings}
    for bi in snapshot.bis:
        if bi.timeframe is not Timeframe.M15 or not bi.confirmed or bi.direction is not direction:
            continue
        fenxing = fenxings.get(bi.end_fx_id)
        if fenxing is None or fenxing.time > decision_time:
            continue
        chosen = price_decimal(bi.end_price)
    return chosen
