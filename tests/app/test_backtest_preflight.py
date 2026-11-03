"""Backtest refuses an empty parquet store and flags a run with no decisions."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.app.cli import main
from chanedge.config.load import load_settings
from chanedge.domain.bars import Bar, timeframe_duration
from chanedge.domain.enums import Timeframe
from chanedge.marketdata.parquet_store import ParquetBarStore
from chanedge.marketdata.universe import UniverseMember, universe_path, write_universe_file
from chanedge.marketdata.vision import store_bar

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)
VENUE = "binanceusdm"
WINDOWS = {
    Timeframe(key): value
    for key, value in load_settings(ROOT / "config" / "default.yaml").marketdata.windows.items()
}


class _Boom:
    def __getitem__(self, key):
        raise AssertionError(key)

    def __contains__(self, key):
        raise AssertionError(key)

    def get(self, key, default=None):
        raise AssertionError(key)


class _Clock:
    def now(self) -> datetime:
        return datetime(2024, 1, 2, 12, tzinfo=UTC)


class _Exchange:
    def fetch_tickers(self):
        raise AssertionError("tickers")

    def create_order(self, *args, **kwargs):
        raise AssertionError("create_order")

    def fetch_ohlcv(self, *args, **kwargs):
        raise AssertionError("ohlcv")


def _member(symbol: str, rank: int) -> UniverseMember:
    opened = datetime(2023, 12, 31, tzinfo=UTC)
    return UniverseMember(
        rank=rank,
        symbol=symbol,
        venue_symbol=f"{symbol}:USDT",
        quote_volume=Decimal("1000"),
        as_of=T0,
        source="daily_kline",
        bar_open_time=opened,
        bar_close_time=opened + timedelta(days=1),
        fallback_from=None,
    )


def _bar(symbol: str, timeframe: Timeframe, close: datetime) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=close - timeframe_duration(timeframe),
        close_time=close,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1.0,
        is_closed=True,
        source=VENUE,
    )


def _write(root: Path, symbol: str, timeframe: Timeframe, count: int, last_close: datetime = T0) -> None:
    step = timeframe_duration(timeframe)
    bars = [_bar(symbol, timeframe, last_close - step * i) for i in reversed(range(count))]
    ParquetBarStore(root).write_closed(VENUE, symbol, timeframe, [store_bar(b) for b in bars])


def _full(root: Path, symbol: str) -> None:
    for timeframe, need in WINDOWS.items():
        _write(root, symbol, timeframe, need)


def _universe(root: Path, symbols: list[str]) -> None:
    members = tuple(_member(symbol, rank) for rank, symbol in enumerate(symbols, start=1))
    write_universe_file(universe_path(root, VENUE, date(2024, 1, 1)), members)


def _run(root: Path) -> int:
    argv = ["backtest", "--config", str(ROOT / "config" / "default.yaml"), "--root", str(root), "--end", "2024-01-01"]
    return main(argv, exchange=_Exchange(), clock=_Clock(), environ=_Boom())


def test_no_bars_at_all_exits_1_without_a_report(tmp_path: Path, capsys) -> None:
    _universe(tmp_path, ["BTC/USDT", "ETH/USDT"])
    assert _run(tmp_path) == 1
    assert not (tmp_path / "data" / "reports").exists()
    err = capsys.readouterr().err
    assert "parquet_root" in err
    assert str(tmp_path / "data" / "bars" / VENUE) in err
    for label in ("15m", "1h", "4h"):
        assert label in err


def test_some_symbols_missing_still_runs_and_lists_them(tmp_path: Path, capsys) -> None:
    _universe(tmp_path, ["BTC/USDT", "ETH/USDT"])
    _full(tmp_path, "BTC/USDT")
    extra = [_bar("BTC/USDT", Timeframe.M15, T0 + timedelta(minutes=15 * i)) for i in range(1, 5)]
    ParquetBarStore(tmp_path).write_closed(VENUE, "BTC/USDT", Timeframe.M15, [store_bar(b) for b in extra])
    assert _run(tmp_path) == 0
    lines = capsys.readouterr().err.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("warning: 1 of 2 symbols lack"))
    listed = [line for line in lines[start + 1 :] if line.startswith("  ")]
    assert any("ETH/USDT" in line for line in listed)
    assert not any("BTC/USDT" in line for line in listed)
    reports = list((tmp_path / "data" / "reports").iterdir())
    assert len(reports) == 1
    timing = json.loads((reports[0] / "timing.json").read_text(encoding="utf-8"))
    assert timing["decision_count"] > 0
    assert "incomplete" not in json.loads((reports[0] / "run.json").read_text(encoding="utf-8"))


def test_data_but_no_decisions_marks_run_json_incomplete(tmp_path: Path, capsys) -> None:
    _universe(tmp_path, ["BTC/USDT"])
    _full(tmp_path, "BTC/USDT")
    assert _run(tmp_path) == 1
    reports = list((tmp_path / "data" / "reports").iterdir())
    assert len(reports) == 1
    run = json.loads((reports[0] / "run.json").read_text(encoding="utf-8"))
    assert run["incomplete"] is True
    assert run["incomplete_reason"] == "no_decisions"
    assert "run_id" in run
    timing = json.loads((reports[0] / "timing.json").read_text(encoding="utf-8"))
    assert timing["decision_count"] == 0
    assert "no_decisions" in capsys.readouterr().err
