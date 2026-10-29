"""SQLite adapter for the paper ledger and the backtest report.

The backtest loop does not import this module. Callers in app and tests pass
an instance in. Report connections set synchronous=OFF. Paper connections do
not.
"""

from __future__ import annotations

import json
from pathlib import Path

from chanedge.domain.canon import format_fixed8, format_time_z
from chanedge.domain.enums import OrderSide
from chanedge.domain.records import (
    BarCommit,
    BookFlush,
    DecisionRecord,
    FillRecord,
    JoinedFill,
    OrderRecord,
    PendingOrder,
    StoredPosition,
)
from chanedge.domain.risk import PositionState, RiskPlan
from chanedge.journal.repository import (
    PENDING_ORDER_STATUS,
    DecisionDraft,
    FillRow,
    JournalRepository,
    OrderRow,
    PositionRow,
)


class JournalLedger:
    """Paper ledger. synchronous stays at the connection default."""

    def __init__(self, path: Path | str) -> None:
        self.repo = JournalRepository(path, synchronous_off=False)

    def load_open_positions(self) -> tuple[StoredPosition, ...]:
        loaded: list[StoredPosition] = []
        for row in self.repo.load_open_positions():
            state, arm = _decode_position(row.risk_plan_json, row)
            loaded.append(
                StoredPosition(state=state, arm_close=arm, updated_at=row.updated_at)
            )
        return tuple(loaded)

    def load_pending_orders(self) -> tuple[PendingOrder, ...]:
        pending: list[PendingOrder] = []
        for row in self.repo.load_pending_orders():
            pending.append(
                PendingOrder(
                    client_order_id=row.client_order_id,
                    decision_id=row.decision_id,
                    symbol=row.symbol,
                    side=OrderSide(row.side),
                    qty=row.qty,
                    reduce_only=row.reduce_only,
                    group_order=0,
                    exit_reason=None,
                    plan=None,
                    entry_decision_time=None,
                    submitted_at=row.submitted_at,
                )
            )
        return tuple(pending)

    def load_joined_fills(self) -> tuple[JoinedFill, ...]:
        return self.repo.load_joined_fills()

    def get_cash(self):
        return self.repo.get_cash()

    def set_cash(self, cash_quote) -> None:
        self.repo.set_cash(cash_quote)

    def commit(self, flush: BookFlush) -> None:
        _write_book(self.repo, flush.orders, flush.fills, flush.positions, flush.cash)

    def commit_bar(self, commit: BarCommit) -> None:
        """Decisions, orders, fills, positions, and cash in one transaction."""
        with self.repo.batch():
            for decision in commit.decisions:
                self.repo.upsert_decision(_draft(decision))
            _write_rows(self.repo, commit.orders, commit.fills, commit.positions, commit.cash)

    def close(self) -> None:
        self.repo.close()


# A Windows path component cannot exceed 255 characters. The version
# strings inside run_id are longer than that, so the directory is a chain
# of segments that concatenate back to the run_id.
_COMPONENT = 180


def _report_directory(root: Path, run_id: str) -> Path:
    if len(run_id) <= _COMPONENT:
        return root / run_id
    parts = [run_id[index : index + _COMPONENT] for index in range(0, len(run_id), _COMPONENT)]
    return root.joinpath(*parts)


class ReportJournal:
    """One report directory. Refuses the paper database and a second run."""

    def __init__(self, root: Path | str, *, paper_path: Path | str | None = None) -> None:
        self.root = Path(root)
        self.paper_path = None if paper_path is None else Path(paper_path)
        self.repo: JournalRepository | None = None
        self.directory: Path | None = None

    def begin_run(self, run_id: str) -> Path:
        if any(char in run_id for char in '|:<>"/\\?*'):
            raise ValueError("run_id is not a directory name")
        directory = _report_directory(self.root, run_id)
        journal = directory / "journal.sqlite"
        if directory.exists():
            raise FileExistsError(f"report already exists: {directory}")
        if journal.name == "chanedge.sqlite" or "chanedge.sqlite" in journal.parts:
            raise ValueError("report journal is not chanedge.sqlite")
        if self.paper_path is not None and journal.resolve() == self.paper_path.resolve():
            raise ValueError("report journal is not the paper ledger")
        directory.mkdir(parents=True)
        self.repo = JournalRepository(journal, synchronous_off=True)
        self.directory = directory
        return directory

    def commit_bar(self, commit: BarCommit) -> None:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        with self.repo.batch():
            for decision in commit.decisions:
                self.repo.upsert_decision(_draft(decision))
            _write_rows(self.repo, commit.orders, commit.fills, commit.positions, commit.cash)

    def synchronous(self) -> int:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        return self.repo.synchronous()

    def chart_frame_count(self) -> int:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        return len(self.repo.load_chart_frames())

    def close(self) -> None:
        if self.repo is not None:
            self.repo.close()


def _write_book(repo: JournalRepository, orders, fills, positions, cash) -> None:
    with repo.batch():
        _write_rows(repo, orders, fills, positions, cash)


def _write_rows(repo: JournalRepository, orders, fills, positions, cash) -> None:
    for order in orders:
        if order.update_only:
            repo.set_order_status(order.client_order_id, order.status)
        else:
            repo.insert_order(_order_row(order))
    for fill in fills:
        repo.insert_fill(_fill_row(fill))
    for position in positions:
        repo.upsert_position(_position_row(position))
    repo.set_cash(cash)


def _draft(decision: DecisionRecord) -> DecisionDraft:
    return DecisionDraft(
        symbol=decision.symbol,
        decision_time=decision.decision_time,
        action=decision.action,
        config_hash=decision.config_hash,
        engine_version=decision.engine_version,
        feature_version=decision.feature_version,
        marketdata_version=decision.marketdata_version,
        universe_date=decision.universe_date,
        created_at=decision.created_at,
        rank=decision.rank,
        proposed_jev_action=decision.proposed_jev_action,
        size_qty=decision.size_qty,
        stop_price=decision.stop_price,
        snapshot_id_m15=decision.snapshot_id_m15,
        snapshot_id_h1=decision.snapshot_id_h1,
        snapshot_id_h4=decision.snapshot_id_h4,
        feature_json=decision.feature_json,
        jev_json=decision.jev_json,
        hard_rule_json=decision.hard_rule_json,
        risk_plan_json=decision.risk_plan_json,
        reason_chain_json=decision.reason_chain_json,
        order_ids_json=decision.order_ids_json,
        calibrated=decision.calibrated,
    )


def _order_row(order: OrderRecord) -> OrderRow:
    return OrderRow(
        client_order_id=order.client_order_id,
        decision_id=order.decision_id,
        venue_order_id=None,
        symbol=order.symbol,
        side=order.side,
        qty=order.qty,
        reduce_only=order.reduce_only,
        status=order.status or PENDING_ORDER_STATUS,
        paper=True,
        submitted_at=order.submitted_at,
    )


def _fill_row(fill: FillRecord) -> FillRow:
    return FillRow(
        fill_id=fill.fill_id,
        client_order_id=fill.client_order_id,
        price=fill.price,
        qty=fill.qty,
        fee_quote=fill.fee_quote,
        slippage_quote=fill.slippage_quote,
        fill_time=fill.fill_time,
        bar_seq=fill.bar_seq,
    )


def _position_row(stored: StoredPosition) -> PositionRow:
    state = stored.state
    side = state.plan.side.value
    return PositionRow(
        symbol=state.symbol,
        qty=state.qty,
        avg_price=format_decimal(state.avg_price),
        stop_price=format_decimal(state.stop_price),
        side=side,
        entry_decision_id=state.entry_decision_id,
        entry_bar_open_time=state.entry_bar_open_time,
        risk_plan_json=_encode_position(stored),
        updated_at=stored.updated_at,
    )


def format_decimal(value: float) -> object:
    return _decimal_text(value)


def _decimal_text(value: float):
    from decimal import Decimal

    return Decimal(format_fixed8(value))


def _encode_position(stored: StoredPosition) -> str:
    arm = None if stored.arm_close is None else format_fixed8(stored.arm_close)
    payload = {
        "arm_close": arm,
        "entry_decision_time": format_time_z(stored.state.entry_decision_time),
        "plan": stored.state.plan.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode_position(payload: str, row: PositionRow) -> tuple[PositionState, float | None]:
    parsed = json.loads(payload)
    plan = RiskPlan.model_validate(parsed["plan"])
    when = _parse_z(str(parsed["entry_decision_time"]))
    arm = parsed.get("arm_close")
    arm_close = None if arm is None else float(arm)
    state = PositionState(
        symbol=row.symbol,
        qty=row.qty,
        avg_price=float(row.avg_price),
        stop_price=float(row.stop_price),
        plan=plan,
        entry_decision_id=row.entry_decision_id,
        entry_decision_time=when,
        entry_bar_open_time=row.entry_bar_open_time,
    )
    return state, arm_close


def _parse_z(value: str):
    from datetime import datetime, timezone

    if not value.endswith("Z"):
        raise ValueError("time must end with Z")
    return datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
