from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from chanedge.domain.ids import decision_id
from chanedge.journal.repository import (
    PENDING_ORDER_STATUS,
    ChartFrameRow,
    DecisionDraft,
    FillRow,
    JournalRepository,
    OrderRow,
    PositionRow,
)
from chanedge.journal.schema import JournalSchemaError

UTC = timezone.utc
WHEN = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
CREATED = datetime(2024, 1, 1, 0, 15, 1, tzinfo=UTC)
CONFIG = "a" * 64


def _draft(**overrides: object) -> DecisionDraft:
    values: dict[str, object] = {
        "symbol": "BTC/USDT",
        "decision_time": WHEN,
        "action": "HOLD",
        "config_hash": CONFIG,
        "engine_version": "engine-v1",
        "feature_version": "feature-v1",
        "marketdata_version": "marketdata-v1",
        "universe_date": date(2024, 1, 1),
        "created_at": CREATED,
        "size_qty": Decimal("1"),
        "stop_price": Decimal("99.5"),
        "hard_rule_json": '{"passed":true}',
    }
    values.update(overrides)
    return DecisionDraft(**values)


def _position(qty: str, symbol: str = "BTC/USDT") -> PositionRow:
    return PositionRow(
        symbol=symbol,
        qty=Decimal(qty),
        avg_price=Decimal("100"),
        stop_price=Decimal("99"),
        side="long" if Decimal(qty) >= 0 else "short",
        entry_decision_id="dec_entry",
        entry_bar_open_time=WHEN,
        risk_plan_json="{}",
        updated_at=CREATED,
    )


def test_same_decision_id_upserts_and_a_new_version_inserts(tmp_path) -> None:
    path = tmp_path / "data" / "chanedge.sqlite"
    repo = JournalRepository(path)
    try:
        first = repo.upsert_decision(_draft())
        second = repo.upsert_decision(_draft(size_qty=Decimal("2.5")))
        assert first == second
        assert first == decision_id(
            "BTC/USDT", WHEN, "HOLD", CONFIG, "engine-v1", "feature-v1", "marketdata-v1"
        )
        assert len(repo.list_decisions()) == 1
        stored = repo.get_decision(first)
        assert stored is not None
        assert stored.size_qty == Decimal("2.5")

        other = repo.upsert_decision(_draft(engine_version="engine-v2", size_qty=Decimal("9")))
        assert other != first
        rows = repo.list_decisions()
        assert len(rows) == 2
        assert repo.get_decision(first).size_qty == Decimal("2.5")
        assert repo.get_decision(other).engine_version == "engine-v2"
    finally:
        repo.close()


def test_slim_hold_row_keeps_empty_json_and_snapshot_columns(tmp_path) -> None:
    repo = JournalRepository(tmp_path / "journal.sqlite")
    try:
        row_id = repo.upsert_decision(
            _draft(
                action="HOLD",
                size_qty=None,
                stop_price=None,
                rank=None,
                proposed_jev_action=None,
                feature_json=None,
                jev_json=None,
                risk_plan_json=None,
                snapshot_id_m15=None,
                snapshot_id_h1=None,
                snapshot_id_h4=None,
                hard_rule_json='["no_candidate"]',
            )
        )
        stored = repo.get_decision(row_id)
        assert stored is not None
        assert stored.feature_json is None
        assert stored.jev_json is None
        assert stored.risk_plan_json is None
        assert stored.snapshot_id_m15 is None
        assert stored.hard_rule_json == '["no_candidate"]'
        assert stored.universe_date == date(2024, 1, 1)
        assert stored.decision_time == WHEN
    finally:
        repo.close()


def test_chart_frame_overwrite_keeps_one_row_per_symbol_timeframe(tmp_path) -> None:
    repo = JournalRepository(tmp_path / "journal.sqlite")
    try:
        frame = ChartFrameRow("BTC/USDT", "15m", '{"last_action":"HOLD"}', CREATED)
        repo.upsert_chart_frame(frame)
        repo.upsert_chart_frame(
            ChartFrameRow("BTC/USDT", "15m", '{"last_action":"ENTER_LONG"}', CREATED)
        )
        repo.upsert_chart_frame(ChartFrameRow("BTC/USDT", "1h", '{"last_action":"HOLD"}', CREATED))
        frames = repo.load_chart_frames()
        assert len(frames) == 2
        by_tf = {item.timeframe: item.frame_json for item in frames}
        assert by_tf["15m"] == '{"last_action":"ENTER_LONG"}'
        assert by_tf["1h"] == '{"last_action":"HOLD"}'
    finally:
        repo.close()


def test_open_positions_pending_orders_and_cash_are_independent(tmp_path) -> None:
    repo = JournalRepository(tmp_path / "journal.sqlite")
    try:
        repo.upsert_position(_position("1"))
        repo.upsert_position(_position("0", symbol="ETH/USDT"))
        repo.upsert_position(_position("-2", symbol="SOL/USDT"))
        repo.upsert_position(_position("0", symbol="ETH/USDT"))
        open_symbols = [row.symbol for row in repo.load_open_positions()]
        assert open_symbols == ["BTC/USDT", "SOL/USDT"]
        assert repo.load_open_positions()[1].entry_decision_id == "dec_entry"

        repo.insert_order(
            OrderRow(
                client_order_id="dec_a",
                decision_id="dec_a",
                venue_order_id=None,
                symbol="BTC/USDT",
                side="buy",
                qty=Decimal("1"),
                reduce_only=False,
                status=PENDING_ORDER_STATUS,
                paper=True,
                submitted_at=CREATED,
            )
        )
        repo.insert_order(
            OrderRow(
                client_order_id="dec_b",
                decision_id="dec_b",
                venue_order_id="42",
                symbol="ETH/USDT",
                side="sell",
                qty=Decimal("3"),
                reduce_only=True,
                status="filled",
                paper=True,
                submitted_at=CREATED,
            )
        )
        pending = repo.load_pending_orders()
        assert [row.client_order_id for row in pending] == ["dec_a"]
        assert pending[0].status == "next_open"

        repo.set_cash(Decimal("10000"))
        repo.upsert_position(_position("0"))
        assert repo.get_cash() == Decimal("10000")
        assert repo.load_open_positions()[0].symbol == "SOL/USDT"
    finally:
        repo.close()


def test_schema_is_migration_001_wal_and_not_synchronous_off(tmp_path) -> None:
    path = tmp_path / "reports" / "run" / "journal.sqlite"
    repo = JournalRepository(path)
    try:
        assert repo.schema_version == 1
        repo.insert_fill(
            FillRow(
                fill_id="dec_a:0",
                client_order_id="dec_a",
                price=Decimal("100"),
                qty=Decimal("1"),
                fee_quote=Decimal("0.05"),
                slippage_quote=Decimal("0.01"),
                fill_time=WHEN,
                bar_seq=0,
            )
        )
        with pytest.raises(ValueError):
            repo.insert_fill(
                FillRow(
                    fill_id="dec_a:2",
                    client_order_id="dec_a",
                    price=Decimal("1"),
                    qty=Decimal("1"),
                    fee_quote=Decimal("0"),
                    slippage_quote=Decimal("0"),
                    fill_time=WHEN,
                    bar_seq=2,
                )
            )
    finally:
        repo.close()

    with sqlite3.connect(path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "decisions",
            "orders",
            "fills",
            "positions",
            "accounts",
            "chart_frames",
            "schema_meta",
        } <= names
        position_cols = [row[1] for row in conn.execute("PRAGMA table_info(positions)")]
        assert "entry_decision_id" in position_cols
        assert "opened_decision_id" not in position_cols
        decision_cols = [row[1] for row in conn.execute("PRAGMA table_info(decisions)")]
        for column in (
            "engine_version",
            "feature_version",
            "marketdata_version",
            "snapshot_id_m15",
            "snapshot_id_h1",
            "snapshot_id_h4",
            "feature_json",
            "jev_json",
            "hard_rule_json",
            "risk_plan_json",
        ):
            assert column in decision_cols
        accounts = conn.execute("SELECT account_id, cash_quote FROM accounts").fetchall()
        assert accounts == [(1, None)]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] != 0
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 1

    again = JournalRepository(path)
    try:
        assert again.schema_version == 1
        assert again.get_cash() is None
    finally:
        again.close()

    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_meta SET version = 2")
    with pytest.raises(JournalSchemaError):
        JournalRepository(path)
