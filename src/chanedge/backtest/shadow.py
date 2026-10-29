"""Shadow book. Same matcher, separate from cash and the real position.

Every candidate gets its own shadow. Two shadows on one symbol run side by
side, each to its own exit, and neither is cut short by the other or by a real
entry on that symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from chanedge.backtest.matcher import match_bar
from chanedge.domain.accounting import quantize, update_cash
from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.enums import AmendReason, OrderSide, Side
from chanedge.domain.records import PendingOrder
from chanedge.domain.risk import PositionReview, PositionState, RiskPlan

_ZERO = Decimal("0")


@dataclass
class _Shadow:
    key: str
    symbol: str
    row: dict[str, object]
    position: PositionState | None = None
    pending: dict[str, PendingOrder] = field(default_factory=dict)
    arm: float | None = None


class ShadowBook:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self._shadows: dict[str, _Shadow] = {}
        self._count = 0

    def active_symbols(self) -> set[str]:
        return {shadow.symbol for shadow in self._shadows.values()}

    def reviewable(self, symbol: str) -> tuple[tuple[str, PositionState], ...]:
        """(key, position) for every filled shadow on symbol, in opening order."""
        return tuple(
            (shadow.key, shadow.position)
            for shadow in self._shadows.values()
            if shadow.symbol == symbol and shadow.position is not None
        )

    def open_shadow(
        self,
        symbol: str,
        plan: RiskPlan,
        signal: ChanSignal,
        decision_time: datetime,
    ) -> None:
        reported = None
        if plan.structure_stop_price is not None and not plan.rejected and plan.qty > _ZERO:
            reported = plan.qty
        row = _row(
            symbol,
            signal,
            decision_time,
            qty=None if reported is None else format(reported, ".8f"),
            closed=plan.structure_stop_price is None,
        )
        self.rows.append(row)
        if plan.structure_stop_price is None or plan.entry_reference is None:
            return
        internal = plan.qty if not plan.rejected and plan.qty > _ZERO else Decimal("1")
        side = OrderSide.BUY if plan.side is Side.LONG else OrderSide.SELL
        self._count += 1
        key = f"shadow:{self._count}:{signal.id}"
        shadow = _Shadow(key=key, symbol=symbol, row=row)
        shadow.pending[key] = PendingOrder(
            client_order_id=key,
            decision_id=key,
            symbol=symbol,
            side=side,
            qty=quantize(internal),
            reduce_only=False,
            group_order=0,
            exit_reason=None,
            plan=plan,
            entry_decision_time=decision_time,
            submitted_at=decision_time,
        )
        self._shadows[key] = shadow

    def apply_review(
        self,
        key: str,
        review: PositionReview,
        bar_close: float | None,
        decision_time: datetime,
    ) -> None:
        shadow = self._shadows.get(key)
        if shadow is None or shadow.position is None:
            return
        position = shadow.position
        if review.exit is not None:
            side = OrderSide.SELL if position.qty > 0 else OrderSide.BUY
            client = f"{key}:exit:{decision_time.isoformat()}"
            shadow.pending[client] = PendingOrder(
                client_order_id=client,
                decision_id=client,
                symbol=shadow.symbol,
                side=side,
                qty=abs(position.qty),
                reduce_only=True,
                group_order=0,
                exit_reason=review.exit.reason,
                plan=None,
                entry_decision_time=None,
                submitted_at=decision_time,
            )
            return
        if review.amend_stop is not None:
            amend = review.amend_stop
            shadow.position = position.model_copy(update={"stop_price": amend.new_stop_price})
            if amend.reason is AmendReason.BREAKEVEN:
                shadow.arm = bar_close

    def match(
        self,
        symbol: str,
        bar: Bar,
        *,
        fee_bps: Decimal,
        slippage_bps: Decimal,
    ) -> None:
        for shadow in [item for item in self._shadows.values() if item.symbol == symbol]:
            fills = match_bar(
                shadow.position,
                tuple(shadow.pending.values()),
                bar,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                arm_close=shadow.arm,
            )
            for fill in fills:
                self._apply(shadow, fill)

    def finish(self) -> None:
        for shadow in self._shadows.values():
            if shadow.row.get("closed"):
                continue
            shadow.row["unfinished"] = True
            shadow.row["exit_reason"] = None
            shadow.row["closed"] = False
        self._shadows = {}

    def _apply(self, shadow: _Shadow, fill) -> None:
        position = shadow.position
        qty = position.qty if position is not None else _ZERO
        avg = quantize(position.avg_price) if position is not None else _ZERO
        _cash, new_qty, new_avg = update_cash(
            _ZERO,
            qty,
            avg,
            fill_qty=fill.qty,
            fill_price=fill.price,
            fee=fill.fee_quote,
            side=fill.side,
            reduce_only=fill.reduce_only,
        )
        pending = shadow.pending.pop(fill.client_order_id, None)
        row = shadow.row
        if not fill.reduce_only:
            if pending is None or pending.plan is None or pending.entry_decision_time is None:
                return
            if pending.plan.structure_stop_price is None:
                return
            shadow.position = PositionState(
                symbol=fill.symbol,
                qty=new_qty,
                avg_price=float(new_avg),
                stop_price=float(pending.plan.structure_stop_price),
                plan=pending.plan,
                entry_decision_id=pending.decision_id,
                entry_decision_time=pending.entry_decision_time,
                entry_bar_open_time=fill.fill_time,
            )
            row["entry_price"] = format(fill.price, ".8f")
            return
        if position is None:
            return
        if new_qty == _ZERO:
            row["closed"] = True
            row["unfinished"] = False
            row["exit_price"] = format(fill.price, ".8f")
            row["exit_reason"] = None if fill.exit_reason is None else str(fill.exit_reason)
            row["r_multiple"] = _r(position, fill.price)
            self._shadows.pop(shadow.key, None)
            return
        updated = position.model_copy(update={"qty": new_qty, "avg_price": float(new_avg)})
        if fill.partial_reason is not None:
            plan = updated.plan.model_copy(update={"partial_targets": ()})
            updated = updated.model_copy(update={"plan": plan})
        shadow.position = updated


def _row(symbol: str, signal: ChanSignal, decision_time: datetime, *, qty: str | None, closed: bool) -> dict[str, object]:
    return {
        "shadow": True,
        "symbol": symbol,
        "decision_time": decision_time.isoformat(),
        "signal_id": signal.id,
        "signal_type": signal.type.value,
        "qty": qty,
        "entry_price": None,
        "exit_price": None,
        "exit_reason": None,
        "closed": closed,
        "unfinished": False,
        "r_multiple": None,
    }


def _r(position: PositionState, exit_price: Decimal) -> str | None:
    plan = position.plan
    if plan.entry_reference is None or plan.structure_stop_price is None:
        return None
    distance = abs(quantize(plan.entry_reference) - quantize(plan.structure_stop_price))
    if distance == _ZERO:
        return None
    sign = Decimal(1) if position.qty > _ZERO else Decimal(-1)
    pnl = (exit_price - quantize(position.avg_price)) * sign
    return format(pnl / distance, ".8f")
