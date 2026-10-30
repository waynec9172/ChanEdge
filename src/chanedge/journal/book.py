"""SQLite adapter for the paper ledger and the backtest report.

The backtest loop does not import this module. Callers in app and tests pass
an instance in. Report connections set synchronous=OFF. Paper connections do
not.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from chanedge.domain.canon import format_fixed8, format_time_z
from chanedge.domain.enums import ExitReason, OrderSide
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
        """Rebuild next_open orders. The plan and exit reason come from the decision row.

        An entry whose decision row has no plan cannot be filled. It is marked
        cancelled instead of crashing the first bar after every restart.
        """
        pending: list[PendingOrder] = []
        for row in self.repo.load_pending_orders():
            decision = self.repo.get_decision(row.decision_id)
            plan = _decision_plan(decision)
            exit_reason = _decision_exit_reason(decision) if row.reduce_only else None
            if not row.reduce_only and (decision is None or plan is None or plan.rejected):
                self.repo.set_order_status(row.client_order_id, "cancelled")
                continue
            pending.append(
                PendingOrder(
                    client_order_id=row.client_order_id,
                    decision_id=row.decision_id,
                    symbol=row.symbol,
                    side=OrderSide(row.side),
                    qty=row.qty,
                    reduce_only=row.reduce_only,
                    group_order=0,
                    exit_reason=exit_reason,
                    plan=None if row.reduce_only else plan,
                    entry_decision_time=None if row.reduce_only or decision is None else decision.decision_time,
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


# The full run_id is over 800 characters with the real version strings. SQLite's
# unix VFS refuses database paths over 512 bytes, so a long run_id gets a short
# directory name: its head, a digest of the whole id, and its window/timestamp
# tail. run.json inside the directory records the full run_id.
_SHORT_NAME = 96
_HEAD = 16
_TAIL = 41


def report_directory_name(run_id: str) -> str:
    if len(run_id) <= _SHORT_NAME:
        return run_id
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return f"{run_id[:_HEAD]}_{digest}_{run_id[-_TAIL:]}"


def _report_directory(root: Path, run_id: str) -> Path:
    return root / report_directory_name(run_id)


class StoredDecisions(Sequence):
    """The run's decisions, read back from the report journal in pipeline order.

    A multi-year backtest writes millions of rows; this reads them in pages
    instead of keeping them in memory.
    """

    _PAGE = 5000

    def __init__(self, repo: JournalRepository) -> None:
        self._repo = repo

    def __len__(self) -> int:
        return self._repo.decision_count()

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self[item] for item in range(*index.indices(len(self))))
        size = len(self)
        if index < 0:
            index += size
        if not 0 <= index < size:
            raise IndexError("decision index out of range")
        return _record(self._repo.decisions_in_order(index, 1)[0])

    def __iter__(self) -> Iterator[DecisionRecord]:
        offset = 0
        while True:
            page = self._repo.decisions_in_order(offset, self._PAGE)
            if not page:
                return
            yield from (_record(row) for row in page)
            offset += len(page)


def _record(row) -> DecisionRecord:
    return DecisionRecord(
        symbol=row.symbol,
        decision_time=row.decision_time,
        action=row.action,
        config_hash=row.config_hash,
        engine_version=row.engine_version,
        feature_version=row.feature_version,
        marketdata_version=row.marketdata_version,
        universe_date=row.universe_date,
        created_at=row.created_at,
        decision_id=row.decision_id,
        rank=row.rank,
        proposed_jev_action=row.proposed_jev_action,
        size_qty=row.size_qty,
        stop_price=row.stop_price,
        snapshot_id_m15=row.snapshot_id_m15,
        snapshot_id_h1=row.snapshot_id_h1,
        snapshot_id_h4=row.snapshot_id_h4,
        feature_json=row.feature_json,
        jev_json=row.jev_json,
        hard_rule_json=row.hard_rule_json,
        risk_plan_json=row.risk_plan_json,
        reason_chain_json=row.reason_chain_json,
        order_ids_json=row.order_ids_json,
        calibrated=row.calibrated,
    )


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
        (directory / "run.json").write_text(
            json.dumps({"run_id": run_id}, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.repo = JournalRepository(journal, synchronous_off=True)
        self.directory = directory
        return directory

    def resume_run(self, directory: Path | str) -> Path:
        """Reopen a report directory that holds a checkpoint. restore_point trims it."""
        directory = Path(directory)
        journal = directory / "journal.sqlite"
        if not journal.is_file():
            raise FileNotFoundError(f"no report journal in {directory}")
        if self.paper_path is not None and journal.resolve() == self.paper_path.resolve():
            raise ValueError("report journal is not the paper ledger")
        self.repo = JournalRepository(journal, synchronous_off=True)
        self.directory = directory
        return directory

    def save_point(self) -> dict[str, object]:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        return self.repo.save_point()

    def restore_point(self, point: dict[str, object]) -> None:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        self.repo.restore_point(point)

    def decisions(self) -> StoredDecisions:
        if self.repo is None:
            raise RuntimeError("report run has not started")
        return StoredDecisions(self.repo)

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


def _decision_plan(decision) -> RiskPlan | None:
    if decision is None or not decision.risk_plan_json:
        return None
    try:
        return RiskPlan.model_validate_json(decision.risk_plan_json)
    except ValueError:
        return None


def _decision_exit_reason(decision) -> ExitReason | None:
    if decision is None or not decision.reason_chain_json:
        return None
    try:
        steps = json.loads(decision.reason_chain_json)
    except json.JSONDecodeError:
        return None
    known = {reason.value for reason in ExitReason}
    for step in steps if isinstance(steps, list) else ():
        code = step.get("code") if isinstance(step, dict) else None
        if code in known:
            return ExitReason(code)
    return None


def _parse_z(value: str):
    from datetime import datetime, timezone

    if not value.endswith("Z"):
        raise ValueError("time must end with Z")
    return datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
