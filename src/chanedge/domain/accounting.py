"""Cash and position quantity shared by the paper book and the pure matcher.

Entry fees leave the cash balance and do not deduct notional. A close adds
signed price PnL, then subtracts the fee. Flat rows keep the last average.
"""

from __future__ import annotations

from decimal import Decimal

from chanedge.domain.enums import OrderSide

_ZERO = Decimal("0")


def quantize(value: float | Decimal | int) -> Decimal:
    """Eight decimal places. Callers pass numbers, not bool."""
    return Decimal(format(value, ".8f"))


def update_cash(
    cash: Decimal,
    qty: Decimal,
    avg: Decimal,
    *,
    fill_qty: Decimal,
    fill_price: Decimal,
    fee: Decimal,
    side: OrderSide,
    reduce_only: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return the next cash, signed quantity, and average.

    Raising here means the matcher and the broker saw a second entry or a
    reduce that the open quantity cannot cover. Neither path flips a position.
    """
    cash = quantize(cash)
    qty = quantize(qty)
    avg = quantize(avg)
    fill_qty = quantize(fill_qty)
    fill_price = quantize(fill_price)
    fee = quantize(fee)
    if fill_qty <= _ZERO:
        raise ValueError("fill quantity must be positive")
    if not reduce_only:
        if qty != _ZERO:
            raise ValueError("entry while a position is open")
        signed = fill_qty if side is OrderSide.BUY else -fill_qty
        return quantize(cash - fee), signed, fill_price
    if qty == _ZERO:
        raise ValueError("reduce without a position")
    if fill_qty > abs(qty):
        raise ValueError("reduce more than the position")
    if qty > _ZERO:
        pnl = (fill_price - avg) * fill_qty
        new_qty = qty - fill_qty
    else:
        pnl = (avg - fill_price) * fill_qty
        new_qty = qty + fill_qty
    return quantize(cash + pnl - fee), quantize(new_qty), avg


def mark_pnl(qty: Decimal, avg: Decimal, mark: Decimal) -> Decimal:
    """Signed quantity: a short profits when the mark is below the average."""
    return quantize((quantize(mark) - quantize(avg)) * quantize(qty))
