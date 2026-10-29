"""SQLite migration 001. Later migrations only move forward."""

from __future__ import annotations

from sqlalchemy import Connection

SCHEMA_VERSION = 1

_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE decisions (
        decision_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        decision_time TEXT NOT NULL,
        config_hash TEXT NOT NULL,
        universe_date TEXT NOT NULL,
        rank INTEGER,
        engine_version TEXT NOT NULL,
        feature_version TEXT NOT NULL,
        marketdata_version TEXT NOT NULL,
        action TEXT NOT NULL,
        proposed_jev_action TEXT,
        size_qty TEXT,
        stop_price TEXT,
        snapshot_id_m15 TEXT,
        snapshot_id_h1 TEXT,
        snapshot_id_h4 TEXT,
        feature_json TEXT,
        jev_json TEXT,
        hard_rule_json TEXT,
        risk_plan_json TEXT,
        reason_chain_json TEXT,
        order_ids_json TEXT,
        calibrated INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE orders (
        client_order_id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL,
        venue_order_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        qty TEXT NOT NULL,
        reduce_only INTEGER NOT NULL,
        status TEXT NOT NULL,
        paper INTEGER NOT NULL,
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE fills (
        fill_id TEXT PRIMARY KEY,
        client_order_id TEXT NOT NULL,
        price TEXT NOT NULL,
        qty TEXT NOT NULL,
        fee_quote TEXT NOT NULL,
        slippage_quote TEXT NOT NULL,
        fill_time TEXT NOT NULL,
        bar_seq INTEGER NOT NULL CHECK (bar_seq IN (0, 1))
    )
    """,
    """
    CREATE TABLE positions (
        symbol TEXT PRIMARY KEY,
        qty TEXT NOT NULL,
        avg_price TEXT NOT NULL,
        stop_price TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_decision_id TEXT NOT NULL,
        entry_bar_open_time TEXT NOT NULL,
        risk_plan_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE accounts (
        account_id INTEGER PRIMARY KEY CHECK (account_id = 1),
        cash_quote TEXT
    )
    """,
    """
    CREATE TABLE chart_frames (
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        frame_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (symbol, timeframe)
    )
    """,
)


class JournalSchemaError(RuntimeError):
    """The file's schema_meta.version is not one this process can open."""


def apply_migrations(connection: Connection) -> None:
    """Create 001 on an empty file. Version 1 is left alone. A newer version raises."""
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL PRIMARY KEY)"
    )
    row = connection.exec_driver_sql("SELECT MAX(version) FROM schema_meta").fetchone()
    current = 0 if row is None or row[0] is None else int(row[0])
    if current == SCHEMA_VERSION:
        return
    if current > SCHEMA_VERSION:
        raise JournalSchemaError(
            f"schema_meta.version is {current}; this build only opens version {SCHEMA_VERSION}"
        )
    if current != 0:
        raise JournalSchemaError("migrations only move forward")
    for statement in _TABLES:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql("INSERT INTO accounts (account_id, cash_quote) VALUES (1, NULL)")
    connection.exec_driver_sql("INSERT INTO schema_meta (version) VALUES (1)")
