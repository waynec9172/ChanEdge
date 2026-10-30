"""Paper book. Records fills and queues next-open orders. Does not price them.

Match prices stay in the backtest matcher. This module copies a stop that the
caller already chose and applies the shared cash transition.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from chanedge.domain.accounting import quantize, update_cash
from chanedge.domain.decision import CancelAck, OrderAck, OrderIntent
from chanedge.domain.enums import OrderSide
from chanedge.domain.ports import Ledger
from chanedge.domain.records import (
    BookFlush,
    FillRecord,
    JoinedFill,
    MatchFill,
    OrderRecord,
    PendingOrder,
    StoredPosition,
)
from chanedge.domain.risk import PositionState

_ZERO = Decimal("0")


class InMemoryLedger:
    """Ledger kept in the process. The report sqlite is a separate sink."""

    def __init__(
        self,
        *,
        fills: tuple[JoinedFill, ...] | list[JoinedFill] = (),
        cash: Decimal | None = None,
        positions: tuple[StoredPosition, ...] | list[StoredPosition] = (),
        pending: tuple[PendingOrder, ...] | list[PendingOrder] = (),
    ) -> None:
        self._fills = list(fills)
        self._cash = cash
        self._positions = list(positions)
        self._pending = list(pending)

    def load_open_positions(self) -> tuple[StoredPosition, ...]:
        return tuple(item for item in self._positions if item.state.qty != _ZERO)

    def load_pending_orders(self) -> tuple[PendingOrder, ...]:
        return tuple(self._pending)

    def load_joined_fills(self) -> tuple[JoinedFill, ...]:
        return tuple(self._fills)

    def get_cash(self) -> Decimal | None:
        return self._cash

    def set_cash(self, cash_quote: Decimal) -> None:
        self._cash = quantize(cash_quote)

    def commit(self, flush: BookFlush) -> None:
        self._cash = quantize(flush.cash)
        known = {item.client_order_id for item in self._pending}
        for order in flush.orders:
            if order.update_only:
                self._pending = [
                    item for item in self._pending if item.client_order_id != order.client_order_id
                ]
                continue
            if order.client_order_id not in known and order.status == "next_open":
                known.add(order.client_order_id)
        for fill in flush.fills:
            self._fills.append(
                JoinedFill(
                    fill_id=fill.fill_id,
                    client_order_id=fill.client_order_id,
                    price=fill.price,
                    qty=fill.qty,
                    fee_quote=fill.fee_quote,
                    slippage_quote=fill.slippage_quote,
                    fill_time=fill.fill_time,
                    bar_seq=fill.bar_seq,
                    symbol=fill.symbol,
                    side=fill.side,
                    reduce_only=fill.reduce_only,
                )
            )
        for position in flush.positions:
            self._positions = [item for item in self._positions if item.state.symbol != position.state.symbol]
            self._positions.append(position)


class PaperBroker:
    """submit, cancel, and fetch_position, plus the queue used by the pipeline."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        initial_equity: Decimal,
        kill_switch: bool = False,
        order_type: str = "market",
    ) -> None:
        self._ledger = ledger
        self._initial = quantize(initial_equity)
        self.kill_switch = kill_switch
        self.order_type = order_type
        self._positions: dict[str, PositionState] = {}
        self._arm: dict[str, float | None] = {}
        self._pending: dict[str, PendingOrder] = {}
        self._orders: list[OrderRecord] = []
        self._fills: list[FillRecord] = []
        self._dirty: dict[str, StoredPosition] = {}
        self._load()

    def submit(self, intent: OrderIntent) -> OrderAck:
        return self.queue_order(intent, group_order=0)

    def queue_order(
        self,
        intent: OrderIntent,
        *,
        group_order: int,
        exit_reason: object = None,
        plan: object = None,
        entry_decision_time: datetime | None = None,
        submitted_at: datetime | None = None,
    ) -> OrderAck:
        if self.kill_switch and not intent.reduce_only:
            return OrderAck(client_order_id=intent.client_order_id, accepted=False)
        when = submitted_at or entry_decision_time
        if when is None:
            raise ValueError("queued order needs a timestamp")
        pending = PendingOrder(
            client_order_id=intent.client_order_id,
            decision_id=intent.decision_id,
            symbol=intent.symbol,
            side=intent.side,
            qty=quantize(intent.qty),
            reduce_only=intent.reduce_only,
            group_order=group_order,
            exit_reason=exit_reason,  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            entry_decision_time=entry_decision_time,
            submitted_at=when,
        )
        self._pending[intent.client_order_id] = pending
        self._orders.append(
            OrderRecord(
                client_order_id=intent.client_order_id,
                decision_id=intent.decision_id,
                symbol=intent.symbol,
                side=str(intent.side),
                qty=pending.qty,
                reduce_only=intent.reduce_only,
                status="next_open",
                submitted_at=when,
                update_only=False,
            )
        )
        return OrderAck(client_order_id=intent.client_order_id, accepted=True)

    def cancel(self, client_order_id: str) -> CancelAck:
        pending = self._pending.pop(client_order_id, None)
        if pending is None:
            return CancelAck(client_order_id=client_order_id, accepted=False)
        kept: list[OrderRecord] = []
        removed = False
        for order in self._orders:
            if order.client_order_id == client_order_id and not order.update_only:
                removed = True
                continue
            kept.append(order)
        self._orders = kept
        if not removed:
            self._orders.append(
                OrderRecord(
                    client_order_id=client_order_id,
                    decision_id=pending.decision_id,
                    symbol=pending.symbol,
                    side=str(pending.side),
                    qty=pending.qty,
                    reduce_only=pending.reduce_only,
                    status="cancelled",
                    submitted_at=pending.submitted_at,
                    update_only=True,
                )
            )
        return CancelAck(client_order_id=client_order_id, accepted=True)

    def fetch_position(self, symbol: str) -> PositionState:
        position = self._positions.get(symbol)
        if position is None:
            raise ValueError(f"no position for {symbol}")
        return position

    def position(self, symbol: str) -> PositionState | None:
        return self._positions.get(symbol)

    def open_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._positions))

    def open_positions(self) -> tuple[PositionState, ...]:
        return tuple(self._positions[symbol] for symbol in self.open_symbols())

    def pending_for(self, symbol: str) -> tuple[PendingOrder, ...]:
        return tuple(order for order in self._pending.values() if order.symbol == symbol)

    def pending_symbols(self) -> tuple[str, ...]:
        return tuple(sorted({order.symbol for order in self._pending.values()}))

    def arm_close(self, symbol: str) -> float | None:
        return self._arm.get(symbol)

    def seed(self, position: PositionState, *, arm_close: float | None = None) -> None:
        self._positions[position.symbol] = position
        if arm_close is not None:
            self._arm[position.symbol] = arm_close
        self._dirty[position.symbol] = StoredPosition(
            state=position,
            arm_close=self._arm.get(position.symbol),
            updated_at=position.entry_bar_open_time,
        )

    def amend(
        self,
        symbol: str,
        stop_price: float,
        *,
        arm_close: float | None = None,
        replace_arm: bool = False,
        updated_at: datetime | None = None,
    ) -> None:
        position = self._positions[symbol]
        updated = position.model_copy(update={"stop_price": stop_price})
        self._positions[symbol] = updated
        if replace_arm:
            self._arm[symbol] = arm_close
        when = updated_at or position.entry_decision_time
        self._dirty[symbol] = StoredPosition(
            state=updated,
            arm_close=self._arm.get(symbol),
            updated_at=when,
        )

    def apply(self, fills: tuple[MatchFill, ...] | list[MatchFill]) -> None:
        for fill in fills:
            self._apply_one(fill)

    def take_flush(self) -> BookFlush:
        flush = BookFlush(
            orders=tuple(self._orders),
            fills=tuple(self._fills),
            positions=tuple(self._dirty.values()),
            cash=self.cash,
        )
        self._orders = []
        self._fills = []
        self._dirty = {}
        return flush

    def _apply_one(self, fill: MatchFill) -> None:
        position = self._positions.get(fill.symbol)
        qty = position.qty if position is not None else _ZERO
        avg = quantize(position.avg_price) if position is not None else _ZERO
        self.cash, new_qty, new_avg = update_cash(
            self.cash,
            qty,
            avg,
            fill_qty=fill.qty,
            fill_price=fill.price,
            fee=fill.fee_quote,
            side=fill.side,
            reduce_only=fill.reduce_only,
        )
        pending = self._pending.get(fill.client_order_id)
        if fill.reduce_only:
            if position is None:
                raise ValueError("reduce without a position")
            updated = position.model_copy(update={"qty": new_qty, "avg_price": float(new_avg)})
            if fill.partial_reason is not None:
                updated = _tp1_done(updated)
        else:
            if pending is None or pending.plan is None or pending.entry_decision_time is None:
                raise ValueError("entry fill is missing its plan")
            if pending.plan.structure_stop_price is None:
                raise ValueError("entry fill is missing a structure stop")
            updated = PositionState(
                symbol=fill.symbol,
                qty=new_qty,
                avg_price=float(new_avg),
                stop_price=float(pending.plan.structure_stop_price),
                plan=pending.plan,
                entry_decision_id=pending.decision_id,
                entry_decision_time=pending.entry_decision_time,
                entry_bar_open_time=fill.fill_time,
            )
        self._dirty[fill.symbol] = StoredPosition(
            state=updated,
            arm_close=self._arm.get(fill.symbol),
            updated_at=fill.fill_time,
        )
        if new_qty == _ZERO:
            self._positions.pop(fill.symbol, None)
            self._arm.pop(fill.symbol, None)
        else:
            self._positions[fill.symbol] = updated
        if pending is not None:
            self._pending.pop(fill.client_order_id, None)
            self._orders.append(
                OrderRecord(
                    client_order_id=fill.client_order_id,
                    decision_id=fill.decision_id,
                    symbol=fill.symbol,
                    side=str(fill.side),
                    qty=fill.qty,
                    reduce_only=fill.reduce_only,
                    status="filled",
                    submitted_at=pending.submitted_at,
                    update_only=True,
                )
            )
        else:
            self._orders.append(
                OrderRecord(
                    client_order_id=fill.client_order_id,
                    decision_id=fill.decision_id,
                    symbol=fill.symbol,
                    side=str(fill.side),
                    qty=fill.qty,
                    reduce_only=fill.reduce_only,
                    status="filled",
                    submitted_at=fill.fill_time,
                    update_only=False,
                )
            )
        self._fills.append(
            FillRecord(
                fill_id=fill.fill_id,
                client_order_id=fill.client_order_id,
                decision_id=fill.decision_id,
                symbol=fill.symbol,
                side=str(fill.side),
                qty=fill.qty,
                price=fill.price,
                fee_quote=fill.fee_quote,
                slippage_quote=fill.slippage_quote,
                fill_time=fill.fill_time,
                bar_seq=fill.bar_seq,
                reduce_only=fill.reduce_only,
                exit_reason=None if fill.exit_reason is None else str(fill.exit_reason),
                partial_reason=fill.partial_reason,
            )
        )

    def _load(self) -> None:
        for stored in self._ledger.load_open_positions():
            self._positions[stored.state.symbol] = stored.state
            if stored.arm_close is not None:
                self._arm[stored.state.symbol] = stored.arm_close
        for order in self._ledger.load_pending_orders():
            self._pending[order.client_order_id] = order
        fills = self._ledger.load_joined_fills()
        if fills:
            cash = _replay(self._initial, fills)
            stored_cash = self._ledger.get_cash()
            if stored_cash != cash:
                self._ledger.set_cash(cash)
            self.cash = cash
            return
        stored_cash = self._ledger.get_cash()
        self.cash = self._initial if stored_cash is None else quantize(stored_cash)


def _tp1_done(position: PositionState) -> PositionState:
    """TP1 is one partial. Dropping the target from the stored plan keeps it from firing again."""
    plan = position.plan.model_copy(update={"partial_targets": ()})
    return position.model_copy(update={"plan": plan})


def _replay(initial: Decimal, fills: tuple[JoinedFill, ...] | list[JoinedFill]) -> Decimal:
    """Cash from the initial equity. A flat quantity does not restore that equity."""
    ordered = sorted(
        fills,
        key=lambda fill: (fill.fill_time, fill.bar_seq, 0 if fill.reduce_only else 1, fill.symbol),
    )
    cash = quantize(initial)
    books: dict[str, tuple[Decimal, Decimal]] = {}
    for fill in ordered:
        qty, avg = books.get(fill.symbol, (_ZERO, _ZERO))
        cash, qty, avg = update_cash(
            cash,
            qty,
            avg,
            fill_qty=fill.qty,
            fill_price=fill.price,
            fee=fill.fee_quote,
            side=OrderSide(fill.side),
            reduce_only=fill.reduce_only,
        )
        books[fill.symbol] = (qty, avg)
    return cash
