"""Shadow book. Same matcher, separate from cash and the real position."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from chanedge.backtest.matcher import match_bar
from chanedge.domain.accounting import quantize, update_cash
from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.enums import OrderSide, Side
from chanedge.domain.records import PendingOrder
from chanedge.domain.risk import AmendStop, PositionReview, PositionState, RiskPlan

_ZERO = Decimal("0")


class ShadowBook:
    def __init__(self) -> None:
        self.positions: dict[str, PositionState] = {}
        self.pending: dict[str, PendingOrder] = {}
        self.arm: dict[str, float | None] = {}
        self.rows: list[dict[str, object]] = []
        self._open: dict[str, dict[str, object]] = {}

    def position(self, symbol: str) -> PositionState | None:
        return self.positions.get(symbol)

    def active_symbols(self) -> set[str]:
        names = set(self.positions)
        names.update(order.symbol for order in self.pending.values())
        return names

    def pending_for(self, symbol: str) -> tuple[PendingOrder, ...]:
        return tuple(order for order in self.pending.values() if order.symbol == symbol)

    def open_shadow(
        self,
        symbol: str,
        plan: RiskPlan,
        signal: ChanSignal,
        decision_time: datetime,
    ) -> None:
        if symbol in self.positions or symbol in {order.symbol for order in self.pending.values()}:
            self.rows.append(_row(symbol, signal, decision_time, qty=None, closed=True))
            return
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
        client = f"shadow:{signal.id}"
        self.pending[client] = PendingOrder(
            client_order_id=client,
            decision_id=client,
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
        self._open[symbol] = row

    def add_pending(self, order: PendingOrder) -> None:
        self.pending[order.client_order_id] = order

    def amend(
        self,
        symbol: str,
        stop_price: float,
        *,
        arm_close: float | None = None,
        replace_arm: bool = False,
    ) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        self.positions[symbol] = position.model_copy(update={"stop_price": stop_price})
        if replace_arm:
            self.arm[symbol] = arm_close

    def apply_review(self, symbol: str, review: PositionReview, bar_close: float | None, decision_time: datetime) -> None:
        if review.exit is not None:
            position = self.positions.get(symbol)
            if position is None:
                return
            side = OrderSide.SELL if position.qty > 0 else OrderSide.BUY
            client = f"shadow-exit:{symbol}:{decision_time.isoformat()}"
            self.pending[client] = PendingOrder(
                client_order_id=client,
                decision_id=client,
                symbol=symbol,
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
            self._amend_reason(symbol, review.amend_stop, bar_close)

    def match(
        self,
        symbol: str,
        bar: Bar,
        *,
        fee_bps: Decimal,
        slippage_bps: Decimal,
    ) -> None:
        fills = match_bar(
            self.positions.get(symbol),
            self.pending_for(symbol),
            bar,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            arm_close=self.arm.get(symbol),
        )
        for fill in fills:
            self._apply(fill)

    def finish(self) -> None:
        for symbol, row in self._open.items():
            if row.get("closed"):
                continue
            row["unfinished"] = True
            row["exit_reason"] = None
            row["closed"] = False
        self._open = {}

    def _apply(self, fill) -> None:
        position = self.positions.get(fill.symbol)
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
        pending = self.pending.pop(fill.client_order_id, None)
        row = self._open.get(fill.symbol)
        if not fill.reduce_only:
            if pending is None or pending.plan is None or pending.entry_decision_time is None:
                return
            if pending.plan.structure_stop_price is None:
                return
            self.positions[fill.symbol] = PositionState(
                symbol=fill.symbol,
                qty=new_qty,
                avg_price=float(new_avg),
                stop_price=float(pending.plan.structure_stop_price),
                plan=pending.plan,
                entry_decision_id=pending.decision_id,
                entry_decision_time=pending.entry_decision_time,
                entry_bar_open_time=fill.fill_time,
            )
            if row is not None:
                row["entry_price"] = format(fill.price, ".8f")
            return
        if position is None:
            return
        updated = position.model_copy(update={"qty": new_qty, "avg_price": float(new_avg)})
        if new_qty == _ZERO:
            self.positions.pop(fill.symbol, None)
            self.arm.pop(fill.symbol, None)
            if row is not None:
                row["closed"] = True
                row["unfinished"] = False
                row["exit_price"] = format(fill.price, ".8f")
                row["exit_reason"] = None if fill.exit_reason is None else str(fill.exit_reason)
                row["r_multiple"] = _r(position, fill.price)
                self._open.pop(fill.symbol, None)
            return
        self.positions[fill.symbol] = updated

    def _amend_reason(self, symbol: str, amend: AmendStop, bar_close: float | None) -> None:
        replace = str(amend.reason) == "breakeven"
        self.amend(
            symbol,
            amend.new_stop_price,
            arm_close=bar_close if replace else None,
            replace_arm=replace,
        )


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
