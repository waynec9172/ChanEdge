"""PR-13: the monitor only reads chart_frames and has no write route."""

from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chanedge.domain.bars import Bar
from chanedge.domain.decision import ChartFrame
from chanedge.domain.enums import DecisionAction, StructureBias, Timeframe
from chanedge.domain.serialize import dump_model
from chanedge.journal.reader import ChartFrameReader
from chanedge.journal.repository import ChartFrameRow, JournalRepository
from chanedge.monitor.server import NO_FRAME, build_server, symbol_rows

ROOT = Path(__file__).resolve().parents[2]
MONITOR = ROOT / "src" / "chanedge" / "monitor"
UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)
FORBIDDEN = {"chanlun", "jev", "execution", "risk", "features", "rules", "marketdata", "config", "app", "backtest", "typesafe"}


def _bar(timeframe: Timeframe) -> Bar:
    step = {Timeframe.M15: timedelta(minutes=15), Timeframe.H1: timedelta(hours=1), Timeframe.H4: timedelta(hours=4)}
    return Bar(
        symbol="BTC/USDT",
        timeframe=timeframe,
        open_time=T0,
        close_time=T0 + step[timeframe],
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
        is_closed=True,
        source="binanceusdm",
    )


def _frame(symbol: str, timeframe: Timeframe, *, rank: int | None, bias=StructureBias.UP, held: bool = False) -> str:
    frame = ChartFrame(
        symbol=symbol,
        timeframe=timeframe,
        as_of=T0 + timedelta(minutes=15),
        snapshot_id="cs_0123456789abcdef",
        structure_bias=bias,
        bars=(_bar(timeframe).model_copy(update={"symbol": symbol}),),
        bis=(),
        zhongshus=(),
        signals=(),
        last_action=DecisionAction.HOLD,
        universe_rank=rank,
    )
    payload = json.loads(dump_model(frame))
    if held:
        payload["position"] = {"symbol": symbol, "avg_price": 100.0}
        payload["stop_price"] = 95.0
    return json.dumps(payload)


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "chanedge.sqlite"
    repo = JournalRepository(path)
    rows = [
        ("ETH/USDT", 2, StructureBias.DOWN, False),
        ("BTC/USDT", 1, StructureBias.UP, False),
        ("OLD/USDT", None, StructureBias.NEUTRAL, True),
        ("GONE/USDT", None, StructureBias.NEUTRAL, False),
    ]
    for symbol, rank, bias, held in rows:
        for timeframe in Timeframe:
            repo.upsert_chart_frame(
                ChartFrameRow(
                    symbol=symbol,
                    timeframe=timeframe.value,
                    frame_json=_frame(symbol, timeframe, rank=rank, bias=bias, held=held),
                    updated_at=T0,
                )
            )
    repo.delete_chart_frames("GONE/USDT")
    repo.close()
    return path


@pytest.fixture
def served(tmp_path: Path):
    path = _ledger(tmp_path)
    server = build_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", path
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_monitor_imports_only_domain_and_journal() -> None:
    for path in MONITOR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                parts = name.split(".")
                if parts[0] == "chanedge" and len(parts) > 1:
                    assert parts[1] in {"domain", "journal", "monitor"}, (path.name, name)
                    assert parts[1] not in FORBIDDEN


def test_binds_loopback_only(tmp_path: Path) -> None:
    for host in ("0.0.0.0", "", "localhost", "192.168.1.2"):
        with pytest.raises(ValueError):
            build_server(tmp_path / "chanedge.sqlite", host=host, port=0)


def test_board_orders_ranked_names_then_held_names_off_the_board(tmp_path: Path) -> None:
    rows = symbol_rows(ChartFrameReader(_ledger(tmp_path)))
    assert [row.symbol for row in rows] == ["BTC/USDT", "ETH/USDT", "OLD/USDT"]
    assert rows[0].bias_4h == "up" and rows[0].last_action == "HOLD"
    assert rows[2].outside_universe is True and rows[2].holding is True
    assert all(row.symbol != "GONE/USDT" for row in rows)


def test_api_reads_frames_and_reports_no_frame(served) -> None:
    base, _path = served
    status, body = _get(base + "/api/symbols")
    assert status == 200
    assert [item["symbol"] for item in json.loads(body)] == ["BTC/USDT", "ETH/USDT", "OLD/USDT"]
    status, body = _get(base + "/api/frame?symbol=BTC/USDT&timeframe=1h")
    frame = json.loads(body)
    assert status == 200 and frame["timeframe"] == "1h" and frame["last_action"] == "HOLD"
    status, body = _get(base + "/api/frame?symbol=GONE/USDT&timeframe=15m")
    assert status == 404 and json.loads(body)["error"] == NO_FRAME
    status, _body = _get(base + "/api/frame?symbol=BTC/USDT&timeframe=1d")
    assert status == 400


def test_page_and_vendored_chart_library_are_served(served) -> None:
    base, _path = served
    status, body = _get(base + "/")
    assert status == 200 and NO_FRAME.encode("utf-8") in body
    status, body = _get(base + "/static/lightweight-charts.standalone.production.js")
    assert status == 200 and b"Licensed under Apache License 2.0" in body[:400]
    status, _body = _get(base + "/static/../server.py")
    assert status == 404


def test_every_write_method_is_refused_and_the_ledger_is_untouched(served) -> None:
    base, path = served
    before = path.read_bytes()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        request = urllib.request.Request(base + "/api/frame?symbol=BTC/USDT&timeframe=15m", data=b"{}", method=method)
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code == 405
    assert path.read_bytes() == before


def test_missing_ledger_is_an_empty_board(tmp_path: Path) -> None:
    reader = ChartFrameReader(tmp_path / "absent.sqlite")
    assert reader.frames() == ()
    assert not (tmp_path / "absent.sqlite").exists()


def test_cli_starts_the_monitor_as_a_separate_process(tmp_path: Path) -> None:
    from chanedge.app.cli import run_monitor
    from chanedge.config.load import load_settings

    settings = load_settings(ROOT / "config" / "default.yaml")
    seen: list[list[str]] = []
    assert run_monitor(settings, tmp_path, call=lambda command: seen.append(command) or 0) == 0
    command = seen[0]
    assert command[1:3] == ["-m", "chanedge.monitor"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == str(settings.monitor.port)
    assert command[command.index("--db") + 1] == str(tmp_path / settings.journal.sqlite_path)
    exposed = settings.model_copy(update={"monitor": settings.monitor.model_copy(update={"host": "0.0.0.0"})})
    assert run_monitor(exposed, tmp_path, call=lambda command: 0) == 1
