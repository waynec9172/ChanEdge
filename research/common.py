"""Paths, constants, sample split, universe helpers, bar readers. Everything else imports from here."""

from __future__ import annotations

import functools
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "research" / "cache"
OUT = ROOT / "research" / "out"
EXPERIMENTS = ROOT / "research" / "experiments"
VENUE = "binanceusdm"
HISTORY_START = date(2024, 1, 1)
HISTORY_END = date(2026, 10, 27)
IS_START = date(2024, 1, 1)
IS_END = date(2025, 6, 30)
OOS_START = date(2025, 7, 1)
OOS_END = date(2026, 10, 27)
WINDOWS = {"15m": 1500, "1h": 1000, "4h": 500}
REFRESH_MINUTE = 5
TAKER_BPS = 5.0
MAKER_BPS = 2.0
SLIPPAGE_BPS = 1.0
BASELINE_DIR = (
    ROOT
    / "data/reports/b78fb5ba0ff45dde_921628697ec40df8_2024-01-01_2026-10-27_2026-10-30T19-33-48"
)
TFS = ("15m", "1h", "4h")
TF_DELTA = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}
DONCHIAN_TFS = ("1h", "4h", "1d")
_UTC = timezone.utc


@functools.lru_cache(maxsize=1)
def settings():
    from chanedge.config.load import load_settings

    s = load_settings(ROOT / "config" / "default.yaml")
    got = {k: int(v) for k, v in s.marketdata.windows.items()}
    assert got == WINDOWS, got
    assert s.universe.refresh_minute == REFRESH_MINUTE
    return s


def config_digest() -> str:
    from chanedge.config.hash import config_hash

    digest = config_hash(settings())
    assert digest.startswith("b78fb5ba0ff45dde"), digest
    return digest


def universe_date(ts) -> date:
    """UTC date of (ts - refresh_minute). Same rule as backtest/loop.py::_universe_date."""
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    return (ts - timedelta(minutes=REFRESH_MINUTE)).astimezone(_UTC).date()


def universe_dates(series: pd.Series) -> pd.Series:
    """Vectorised universe_date for a tz-aware datetime Series -> Series of datetime.date."""
    return (series - pd.Timedelta(minutes=REFRESH_MINUTE)).dt.tz_convert("UTC").dt.date


def sample_of(signal_time) -> str | None:
    day = signal_time.astimezone(_UTC).date() if isinstance(signal_time, datetime) else signal_time
    if isinstance(signal_time, pd.Timestamp):
        day = signal_time.tz_convert("UTC").date()
    if IS_START <= day <= IS_END:
        return "IS"
    if OOS_START <= day <= OOS_END:
        return "OOS"
    return None


def sample_of_series(series: pd.Series) -> pd.Series:
    days = series.dt.tz_convert("UTC").dt.date
    out = pd.Series([None] * len(series), index=series.index, dtype=object)
    out[(days >= IS_START) & (days <= IS_END)] = "IS"
    out[(days >= OOS_START) & (days <= OOS_END)] = "OOS"
    return out


def read_yaml(path) -> dict:
    from chanedge.config.load import _read_mapping

    return dict(_read_mapping(path))


def load_universe() -> pd.DataFrame:
    """Columns date, symbol, rank for ranks 1..20 over HISTORY range. Cached."""
    cache = CACHE / "universe.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    import json

    rows = []
    folder = ROOT / "data" / "universe" / VENUE
    day = HISTORY_START
    while day <= HISTORY_END:
        for item in json.loads((folder / f"{day.isoformat()}.json").read_text()):
            rank = int(item["rank"])
            if 1 <= rank <= 20:
                rows.append((day, item["symbol"], rank))
        day += timedelta(days=1)
    df = pd.DataFrame(rows, columns=["date", "symbol", "rank"])
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def union_symbols() -> list[str]:
    return sorted(load_universe()["symbol"].unique())


def active_segments(symbol: str) -> list[tuple[date, date]]:
    """Runs of consecutive in-top-20 days, each extended 30 days, merged, clipped to HISTORY_END."""
    uni = load_universe()
    days = sorted(uni.loc[uni["symbol"] == symbol, "date"].unique())
    segs: list[list[date]] = []
    for d in days:
        if segs and (d - segs[-1][1]).days <= 1:
            segs[-1][1] = d
        else:
            segs.append([d, d])
    ext = [(a, min(b + timedelta(days=30), HISTORY_END)) for a, b in segs]
    merged: list[list[date]] = []
    for a, b in ext:
        if merged and a <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def bars_path(symbol: str, tf: str) -> Path:
    base, quote = symbol.split("/")
    return ROOT / "data" / "bars" / VENUE / base / quote / f"{tf}.parquet"


def load_bars_df(symbol: str, tf: str) -> pd.DataFrame:
    df = pq.read_table(bars_path(symbol, tf)).to_pandas()
    df = df[df["is_closed"]].sort_values("open_time").reset_index(drop=True)
    return df


def load_bar_objects(symbol: str, tf: str):
    from chanedge.domain.enums import Timeframe
    from chanedge.marketdata.parquet_store import ParquetBarStore

    stored = ParquetBarStore(ROOT).read(VENUE, symbol.replace("/USDT", "/USDT"), Timeframe(tf))
    return tuple(item.bar for item in stored)


def instrument(symbol: str):
    from chanedge.app.paper_loop import _kline_text, inferred_instrument

    return inferred_instrument(settings(), symbol, _kline_text(ROOT, symbol))


# --------------------------------------------------------------------------- phase 1 constants (plan section 3.1)
IS_QUARTERS = ("2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2")
TRADFI_BASES = (
    "XAU", "XAG", "XAUT", "PAXG", "CL", "BZ", "GOOGL", "INTC", "MRVL", "MSTR", "MU", "NVDA", "TSLA",
    "SAMSUNG", "SKHY", "SKHYNIX", "SNDK", "SOXL", "SOXS", "CRCL", "EWY", "SPCX", "DRAM", "KORU", "SNXX",
)
MAJORS = ("BTC/USDT", "ETH/USDT")
TF_US = {"15m": 900_000_000, "1h": 3_600_000_000, "4h": 14_400_000_000, "1d": 86_400_000_000}
BARS_PER_TF = {"15m": 1, "1h": 4, "4h": 16, "1d": 96}
CORE_MIN_DAYS = 274


def quarter_of_series(signal_time: pd.Series) -> pd.Series:
    """UTC quarter label such as '2024Q1'."""
    t = signal_time.dt.tz_convert("UTC")
    return t.dt.year.astype(str) + "Q" + t.dt.quarter.astype(str)


@functools.lru_cache(maxsize=1)
def core_symbols() -> tuple[str, ...]:
    """In-sample (2024-01-01..2025-06-30) days in the top 20 >= 274, minus the majors."""
    uni = load_universe()
    d = uni[(uni["date"] >= IS_START) & (uni["date"] <= IS_END)]
    assert d["date"].nunique() == 547, d["date"].nunique()
    days = d.groupby("symbol")["date"].nunique()
    return tuple(sorted(s for s, n in days.items() if n >= CORE_MIN_DAYS and s not in MAJORS))


def symbol_group(symbol: str) -> str:
    if symbol in MAJORS:
        return "major"
    if symbol.split("/")[0] in TRADFI_BASES:
        return "tradfi"
    if symbol in core_symbols():
        return "core"
    return "other"
