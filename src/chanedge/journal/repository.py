"""Paper and report SQLite. The caller passes the path.

Paper files open in WAL mode and do not set synchronous=OFF. Report files use
the same repository for now; PR-11 is what separates them and sets the pragma.
decision_id is domain.ids.decision_id. This package does not import chanlun,
features, or marketdata.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from chanedge.domain.canon import format_fixed8, format_time_z
from chanedge.domain.ids import decision_id
from chanedge.domain.records import JoinedFill
from chanedge.journal.schema import apply_migrations

PENDING_ORDER_STATUS = "next_open"
_UTC = timezone.utc


@dataclass(frozen=True)
class DecisionDraft:
    symbol: str
    decision_time: datetime
    action: str
    config_hash: str
    engine_version: str
    feature_version: str
    marketdata_version: str
    universe_date: date
    created_at: datetime
    rank: int | None = None
    proposed_jev_action: str | None = None
    size_qty: Decimal | None = None
    stop_price: Decimal | None = None
    snapshot_id_m15: str | None = None
    snapshot_id_h1: str | None = None
    snapshot_id_h4: str | None = None
    feature_json: str | None = None
    jev_json: str | None = None
    hard_rule_json: str | None = None
    risk_plan_json: str | None = None
    reason_chain_json: str | None = None
    order_ids_json: str | None = None
    calibrated: bool = False


@dataclass(frozen=True)
class DecisionRow:
    decision_id: str
    symbol: str
    decision_time: datetime
    action: str
    config_hash: str
    engine_version: str
    feature_version: str
    marketdata_version: str
    universe_date: date
    created_at: datetime
    rank: int | None
    proposed_jev_action: str | None
    size_qty: Decimal | None
    stop_price: Decimal | None
    snapshot_id_m15: str | None
    snapshot_id_h1: str | None
    snapshot_id_h4: str | None
    feature_json: str | None
    jev_json: str | None
    hard_rule_json: str | None
    risk_plan_json: str | None
    reason_chain_json: str | None
    order_ids_json: str | None
    calibrated: bool


@dataclass(frozen=True)
class OrderRow:
    client_order_id: str
    decision_id: str
    venue_order_id: str | None
    symbol: str
    side: str
    qty: Decimal
    reduce_only: bool
    status: str
    paper: bool
    submitted_at: datetime


@dataclass(frozen=True)
class FillRow:
    fill_id: str
    client_order_id: str
    price: Decimal
    qty: Decimal
    fee_quote: Decimal
    slippage_quote: Decimal
    fill_time: datetime
    bar_seq: int


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    qty: Decimal
    avg_price: Decimal
    stop_price: Decimal
    side: str
    entry_decision_id: str
    entry_bar_open_time: datetime
    risk_plan_json: str
    updated_at: datetime


@dataclass(frozen=True)
class ChartFrameRow:
    symbol: str
    timeframe: str
    frame_json: str
    updated_at: datetime


class JournalRepository:
    def __init__(self, path: Path | str, *, synchronous_off: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._batch = None
        self._engine = _engine(self.path, synchronous_off=synchronous_off)
        with self._write() as connection:
            apply_migrations(connection)

    @contextmanager
    def batch(self) -> Iterator[None]:
        """One transaction for every write made inside the block."""
        if self._batch is not None:
            raise RuntimeError("nested batch")
        with self._engine.begin() as connection:
            self._batch = connection
            try:
                yield
            finally:
                self._batch = None

    @contextmanager
    def _write(self) -> Iterator[object]:
        if self._batch is not None:
            yield self._batch
            return
        with self._engine.begin() as connection:
            yield connection

    @contextmanager
    def _read(self) -> Iterator[object]:
        if self._batch is not None:
            yield self._batch
            return
        with self._engine.connect() as connection:
            yield connection

    @property
    def schema_version(self) -> int:
        with self._read() as connection:
            row = connection.exec_driver_sql("SELECT MAX(version) FROM schema_meta").fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("schema_meta is empty")
        return int(row[0])

    def upsert_decision(self, draft: DecisionDraft) -> str:
        """Insert or replace the row whose id is the seven-field decision_id."""
        row_id = decision_id(
            draft.symbol,
            draft.decision_time,
            draft.action,
            draft.config_hash,
            draft.engine_version,
            draft.feature_version,
            draft.marketdata_version,
        )
        params = {
            "decision_id": row_id,
            "symbol": draft.symbol,
            "decision_time": format_time_z(draft.decision_time),
            "config_hash": draft.config_hash,
            "universe_date": draft.universe_date.isoformat(),
            "rank": draft.rank,
            "engine_version": draft.engine_version,
            "feature_version": draft.feature_version,
            "marketdata_version": draft.marketdata_version,
            "action": str(draft.action),
            "proposed_jev_action": draft.proposed_jev_action,
            "size_qty": _money(draft.size_qty),
            "stop_price": _money(draft.stop_price),
            "snapshot_id_m15": draft.snapshot_id_m15,
            "snapshot_id_h1": draft.snapshot_id_h1,
            "snapshot_id_h4": draft.snapshot_id_h4,
            "feature_json": draft.feature_json,
            "jev_json": draft.jev_json,
            "hard_rule_json": draft.hard_rule_json,
            "risk_plan_json": draft.risk_plan_json,
            "reason_chain_json": draft.reason_chain_json,
            "order_ids_json": draft.order_ids_json,
            "calibrated": int(draft.calibrated),
            "created_at": format_time_z(draft.created_at),
        }
        assignments = ", ".join(
            f"{name} = excluded.{name}" for name in params if name != "decision_id"
        )
        sql = f"""
            INSERT INTO decisions ({", ".join(params)})
            VALUES ({", ".join(":" + name for name in params)})
            ON CONFLICT(decision_id) DO UPDATE SET {assignments}
        """
        with self._write() as connection:
            connection.execute(text(sql), params)
        return row_id

    def get_decision(self, row_id: str) -> DecisionRow | None:
        with self._read() as connection:
            found = connection.execute(
                text("SELECT * FROM decisions WHERE decision_id = :decision_id"),
                {"decision_id": row_id},
            ).mappings().fetchone()
        if found is None:
            return None
        return _decision_row(found)

    def list_decisions(self) -> tuple[DecisionRow, ...]:
        with self._read() as connection:
            rows = connection.execute(
                text("SELECT * FROM decisions ORDER BY decision_id")
            ).mappings()
            return tuple(_decision_row(row) for row in rows)

    def insert_order(self, row: OrderRow) -> None:
        _require_aware(row.submitted_at)
        with self._write() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO orders (
                        client_order_id, decision_id, venue_order_id, symbol, side,
                        qty, reduce_only, status, paper, submitted_at
                    ) VALUES (
                        :client_order_id, :decision_id, :venue_order_id, :symbol, :side,
                        :qty, :reduce_only, :status, :paper, :submitted_at
                    )
                    """
                ),
                {
                    "client_order_id": row.client_order_id,
                    "decision_id": row.decision_id,
                    "venue_order_id": row.venue_order_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "qty": format_fixed8(row.qty),
                    "reduce_only": int(row.reduce_only),
                    "status": row.status,
                    "paper": int(row.paper),
                    "submitted_at": format_time_z(row.submitted_at),
                },
            )

    def load_pending_orders(self) -> tuple[OrderRow, ...]:
        """Orders still waiting for the next open. Other statuses stay out."""
        with self._read() as connection:
            rows = connection.execute(
                text("SELECT * FROM orders WHERE status = :status ORDER BY client_order_id"),
                {"status": PENDING_ORDER_STATUS},
            ).mappings()
            return tuple(_order_row(row) for row in rows)

    def insert_fill(self, row: FillRow) -> None:
        if row.bar_seq not in (0, 1):
            raise ValueError("bar_seq is 0 or 1")
        _require_aware(row.fill_time)
        with self._write() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO fills (
                        fill_id, client_order_id, price, qty, fee_quote,
                        slippage_quote, fill_time, bar_seq
                    ) VALUES (
                        :fill_id, :client_order_id, :price, :qty, :fee_quote,
                        :slippage_quote, :fill_time, :bar_seq
                    )
                    """
                ),
                {
                    "fill_id": row.fill_id,
                    "client_order_id": row.client_order_id,
                    "price": format_fixed8(row.price),
                    "qty": format_fixed8(row.qty),
                    "fee_quote": format_fixed8(row.fee_quote),
                    "slippage_quote": format_fixed8(row.slippage_quote),
                    "fill_time": format_time_z(row.fill_time),
                    "bar_seq": row.bar_seq,
                },
            )

    def upsert_position(self, row: PositionRow) -> None:
        _require_aware(row.entry_bar_open_time)
        _require_aware(row.updated_at)
        params = {
            "symbol": row.symbol,
            "qty": format_fixed8(row.qty),
            "avg_price": format_fixed8(row.avg_price),
            "stop_price": format_fixed8(row.stop_price),
            "side": row.side,
            "entry_decision_id": row.entry_decision_id,
            "entry_bar_open_time": format_time_z(row.entry_bar_open_time),
            "risk_plan_json": row.risk_plan_json,
            "updated_at": format_time_z(row.updated_at),
        }
        assignments = ", ".join(f"{name} = excluded.{name}" for name in params if name != "symbol")
        sql = f"""
            INSERT INTO positions ({", ".join(params)})
            VALUES ({", ".join(":" + name for name in params)})
            ON CONFLICT(symbol) DO UPDATE SET {assignments}
        """
        with self._write() as connection:
            connection.execute(text(sql), params)

    def load_open_positions(self) -> tuple[PositionRow, ...]:
        """Rows with qty != 0. A flat row stays in the table and is not returned."""
        with self._read() as connection:
            rows = connection.execute(text("SELECT * FROM positions ORDER BY symbol")).mappings()
            loaded = tuple(_position_row(row) for row in rows)
        return tuple(row for row in loaded if row.qty != 0)

    def get_cash(self) -> Decimal | None:
        with self._read() as connection:
            row = connection.exec_driver_sql("SELECT cash_quote FROM accounts WHERE account_id = 1").fetchone()
        if row is None:
            raise RuntimeError("accounts row 1 is missing")
        if row[0] is None:
            return None
        return Decimal(row[0])

    def set_cash(self, cash_quote: Decimal) -> None:
        """Update the single account row. Flattening a position does not call this."""
        with self._write() as connection:
            result = connection.execute(
                text("UPDATE accounts SET cash_quote = :cash_quote WHERE account_id = 1"),
                {"cash_quote": format_fixed8(cash_quote)},
            )
            if result.rowcount != 1:
                raise RuntimeError("accounts row 1 is missing")

    def upsert_chart_frame(self, row: ChartFrameRow) -> None:
        """Replace the one frame for this symbol and timeframe."""
        _require_aware(row.updated_at)
        params = {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "frame_json": row.frame_json,
            "updated_at": format_time_z(row.updated_at),
        }
        with self._write() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO chart_frames (symbol, timeframe, frame_json, updated_at)
                    VALUES (:symbol, :timeframe, :frame_json, :updated_at)
                    ON CONFLICT(symbol, timeframe) DO UPDATE SET
                        frame_json = excluded.frame_json,
                        updated_at = excluded.updated_at
                    """
                ),
                params,
            )

    def load_chart_frames(self) -> tuple[ChartFrameRow, ...]:
        with self._read() as connection:
            rows = connection.execute(
                text("SELECT * FROM chart_frames ORDER BY symbol, timeframe")
            ).mappings()
            return tuple(_frame_row(row) for row in rows)

    def delete_chart_frames(self, symbol: str) -> None:
        """Drop every timeframe for one symbol. A missing symbol deletes nothing."""
        with self._write() as connection:
            connection.execute(
                text("DELETE FROM chart_frames WHERE symbol = :symbol"),
                {"symbol": symbol},
            )

    def synchronous(self) -> int:
        with self._read() as connection:
            row = connection.exec_driver_sql("PRAGMA synchronous").fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("synchronous pragma is missing")
        return int(row[0])

    def set_order_status(self, client_order_id: str, status: str) -> None:
        with self._write() as connection:
            connection.execute(
                text(
                    "UPDATE orders SET status = :status WHERE client_order_id = :client_order_id"
                ),
                {"status": status, "client_order_id": client_order_id},
            )

    def load_joined_fills(self) -> tuple[JoinedFill, ...]:
        """Fills with the order columns replay needs. fills itself has no symbol."""
        with self._read() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        f.fill_id, f.client_order_id, f.price, f.qty, f.fee_quote,
                        f.slippage_quote, f.fill_time, f.bar_seq,
                        o.symbol, o.side, o.reduce_only
                    FROM fills AS f
                    JOIN orders AS o ON o.client_order_id = f.client_order_id
                    """
                )
            ).mappings()
            return tuple(_joined_fill(row) for row in rows)

    def close(self) -> None:
        self._engine.dispose()


def _engine(path: Path, *, synchronous_off: bool = False) -> Engine:
    engine = create_engine("sqlite:///" + path.resolve().as_posix())

    @event.listens_for(engine, "connect")
    def _wal(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        if synchronous_off:
            cursor.execute("PRAGMA synchronous=OFF")
        cursor.close()

    return engine


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format_fixed8(value)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")


def _parse_time(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("time must end with Z")
    parsed = datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=_UTC)
    return parsed


def _dec(value: str) -> Decimal:
    return Decimal(value)


def _decision_row(row: object) -> DecisionRow:
    item = _mapping(row)
    rank = item["rank"]
    return DecisionRow(
        decision_id=str(item["decision_id"]),
        symbol=str(item["symbol"]),
        decision_time=_parse_time(str(item["decision_time"])),
        config_hash=str(item["config_hash"]),
        universe_date=date.fromisoformat(str(item["universe_date"])),
        created_at=_parse_time(str(item["created_at"])),
        rank=None if rank is None else int(rank),
        engine_version=str(item["engine_version"]),
        feature_version=str(item["feature_version"]),
        marketdata_version=str(item["marketdata_version"]),
        action=str(item["action"]),
        proposed_jev_action=_optional_str(item["proposed_jev_action"]),
        size_qty=None if item["size_qty"] is None else _dec(str(item["size_qty"])),
        stop_price=None if item["stop_price"] is None else _dec(str(item["stop_price"])),
        snapshot_id_m15=_optional_str(item["snapshot_id_m15"]),
        snapshot_id_h1=_optional_str(item["snapshot_id_h1"]),
        snapshot_id_h4=_optional_str(item["snapshot_id_h4"]),
        feature_json=_optional_str(item["feature_json"]),
        jev_json=_optional_str(item["jev_json"]),
        hard_rule_json=_optional_str(item["hard_rule_json"]),
        risk_plan_json=_optional_str(item["risk_plan_json"]),
        reason_chain_json=_optional_str(item["reason_chain_json"]),
        order_ids_json=_optional_str(item["order_ids_json"]),
        calibrated=bool(item["calibrated"]),
    )


def _order_row(row: object) -> OrderRow:
    item = _mapping(row)
    venue = item["venue_order_id"]
    return OrderRow(
        client_order_id=str(item["client_order_id"]),
        decision_id=str(item["decision_id"]),
        venue_order_id=None if venue is None else str(venue),
        symbol=str(item["symbol"]),
        side=str(item["side"]),
        qty=_dec(str(item["qty"])),
        reduce_only=bool(item["reduce_only"]),
        status=str(item["status"]),
        paper=bool(item["paper"]),
        submitted_at=_parse_time(str(item["submitted_at"])),
    )


def _position_row(row: object) -> PositionRow:
    item = _mapping(row)
    return PositionRow(
        symbol=str(item["symbol"]),
        qty=_dec(str(item["qty"])),
        avg_price=_dec(str(item["avg_price"])),
        stop_price=_dec(str(item["stop_price"])),
        side=str(item["side"]),
        entry_decision_id=str(item["entry_decision_id"]),
        entry_bar_open_time=_parse_time(str(item["entry_bar_open_time"])),
        risk_plan_json=str(item["risk_plan_json"]),
        updated_at=_parse_time(str(item["updated_at"])),
    )


def _frame_row(row: object) -> ChartFrameRow:
    item = _mapping(row)
    return ChartFrameRow(
        symbol=str(item["symbol"]),
        timeframe=str(item["timeframe"]),
        frame_json=str(item["frame_json"]),
        updated_at=_parse_time(str(item["updated_at"])),
    )


def _mapping(row: object) -> dict[str, object]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}  # type: ignore[index]
    raise TypeError("expected a mapping row")


def _joined_fill(row: object) -> JoinedFill:
    item = _mapping(row)
    return JoinedFill(
        fill_id=str(item["fill_id"]),
        client_order_id=str(item["client_order_id"]),
        price=_dec(str(item["price"])),
        qty=_dec(str(item["qty"])),
        fee_quote=_dec(str(item["fee_quote"])),
        slippage_quote=_dec(str(item["slippage_quote"])),
        fill_time=_parse_time(str(item["fill_time"])),
        bar_seq=int(item["bar_seq"]),  # type: ignore[arg-type]
        symbol=str(item["symbol"]),
        side=str(item["side"]),
        reduce_only=bool(item["reduce_only"]),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
