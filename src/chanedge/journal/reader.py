"""Read-only access to chart_frames for the monitor process.

The connection is opened with SQLite's mode=ro, so the monitor cannot write
the paper ledger, run migrations, or change journal_mode. A missing file is
an empty read, not an error: the paper loop may not have written frames yet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFrame:
    symbol: str
    timeframe: str
    frame_json: str
    updated_at: str


class ChartFrameReader:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def frames(self) -> tuple[StoredFrame, ...]:
        rows = self._query(
            "SELECT symbol, timeframe, frame_json, updated_at FROM chart_frames ORDER BY symbol, timeframe",
            (),
        )
        return tuple(StoredFrame(*row) for row in rows)

    def frame(self, symbol: str, timeframe: str) -> StoredFrame | None:
        rows = self._query(
            "SELECT symbol, timeframe, frame_json, updated_at FROM chart_frames "
            "WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe),
        )
        return StoredFrame(*rows[0]) if rows else None

    def _query(self, sql: str, params: tuple) -> list[tuple]:
        if not self.path.is_file():
            return []
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            try:
                return connection.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc):
                    return []
                raise
        finally:
            connection.close()
