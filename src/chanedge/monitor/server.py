"""Read-only chart monitor. It serves frames that the paper loop already wrote.

There is no order route and no setting or kill-switch route: every method but
GET and HEAD gets 405. The process never computes chanlun; a missing frame is
shown as 尚無幀. It binds 127.0.0.1 only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from chanedge.domain.enums import Timeframe
from chanedge.journal.reader import ChartFrameReader

LOOPBACK = "127.0.0.1"
NO_FRAME = "尚無幀"
_TIMEFRAMES = tuple(item.value for item in Timeframe)
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/lightweight-charts.standalone.production.js": (
        "lightweight-charts.standalone.production.js",
        "text/javascript; charset=utf-8",
    ),
}


@dataclass(frozen=True)
class SymbolRow:
    symbol: str
    rank: int | None
    bias_4h: str | None
    last_action: str | None
    holding: bool
    outside_universe: bool


def symbol_rows(reader: ChartFrameReader) -> list[SymbolRow]:
    """Ranked names first by rank, then held names that left the board. Only stored frames count."""
    by_symbol: dict[str, dict[str, dict]] = {}
    for stored in reader.frames():
        try:
            payload = json.loads(stored.frame_json)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            by_symbol.setdefault(stored.symbol, {})[stored.timeframe] = payload
    rows: list[SymbolRow] = []
    for symbol, frames in by_symbol.items():
        main = frames.get(Timeframe.M15.value) or next(iter(frames.values()))
        rank = main.get("universe_rank")
        holding = main.get("position") is not None
        four_hour = frames.get(Timeframe.H4.value)
        rows.append(
            SymbolRow(
                symbol=symbol,
                rank=rank if isinstance(rank, int) else None,
                bias_4h=None if four_hour is None else four_hour.get("structure_bias"),
                last_action=main.get("last_action"),
                holding=holding,
                outside_universe=rank is None and holding,
            )
        )
    rows.sort(key=lambda row: (row.rank is None, row.rank or 0, row.symbol))
    return rows


def make_handler(reader: ChartFrameReader):
    class MonitorHandler(BaseHTTPRequestHandler):
        server_version = "chanedge-monitor"

        def do_GET(self) -> None:  # noqa: N802
            self._route(send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._route(send_body=False)

        def do_POST(self) -> None:  # noqa: N802
            self._refuse()

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _refuse(self) -> None:
            self._send(405, "application/json; charset=utf-8", b'{"error":"read-only"}', True, allow=True)

        def _route(self, *, send_body: bool) -> None:
            parts = urlsplit(self.path)
            if parts.path in _STATIC:
                name, kind = _STATIC[parts.path]
                self._send(200, kind, _asset(name), send_body)
                return
            if parts.path == "/api/symbols":
                payload = [row.__dict__ for row in symbol_rows(reader)]
                self._json(200, payload, send_body)
                return
            if parts.path == "/api/frame":
                query = parse_qs(parts.query)
                symbol = (query.get("symbol") or [""])[0]
                timeframe = (query.get("timeframe") or [""])[0]
                if timeframe not in _TIMEFRAMES:
                    self._json(400, {"error": "timeframe"}, send_body)
                    return
                stored = reader.frame(symbol, timeframe)
                if stored is None:
                    self._json(404, {"error": NO_FRAME}, send_body)
                    return
                body = stored.frame_json.encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body, send_body)
                return
            self._json(404, {"error": "not found"}, send_body)

        def _json(self, status: int, payload: object, send_body: bool) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body, send_body)

        def _send(self, status: int, kind: str, body: bytes, send_body: bool, allow: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if allow:
                self.send_header("Allow", "GET, HEAD")
            self.end_headers()
            if send_body:
                self.wfile.write(body)

    return MonitorHandler


def build_server(db_path: Path | str, *, host: str = LOOPBACK, port: int) -> ThreadingHTTPServer:
    """Refuse any host but 127.0.0.1. port 0 picks a free port (tests)."""
    if host != LOOPBACK:
        raise ValueError(f"monitor binds {LOOPBACK} only, not {host}")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an int between 0 and 65535")
    return ThreadingHTTPServer((host, port), make_handler(ChartFrameReader(db_path)))


def _asset(name: str) -> bytes:
    return resources.files("chanedge.monitor").joinpath("static", name).read_bytes()
