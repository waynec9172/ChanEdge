"""Score path-independent candidates into the System One cache. No orders and no decisions."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from chanedge.app.paper_loop import (
    FileUniverse,
    ParquetBars,
    _kline_text,
    _symbols_in_files,
    _windows,
    inferred_instrument,
)
from chanedge.app.pipeline import PipelineServices
from chanedge.backtest.loop import _bar_at, _decision_times, _preload, _quality, _universe_date, _window
from chanedge.domain.canon import format_fixed8
from chanedge.domain.enums import RuntimeMode, Timeframe
from chanedge.domain.records import PipelineRequest
from chanedge.domain.risk import AccountView, SafetyState

_CODES = (
    "JEV_TIMEOUT",
    "JEV_HTTP_ERROR",
    "JEV_MALFORMED",
    "JEV_MODEL_MISMATCH",
    "JEV_CACHE_MISS",
    "JEV_NO_KEY",
)


def enable_floor(above: int, below: int) -> bool:
    """Both sides need 30 scored rows and at least 10 percent of the scored rows."""
    total = above + below
    if total == 0 or above < 30 or below < 30:
        return False
    return above / total >= 0.1 and below / total >= 0.1


def summarize_decisions(decisions) -> dict[str, int]:
    counts = {code: 0 for code in _CODES}
    counts["skipped_veto"] = 0
    counts["scored"] = 0
    for decision in decisions:
        payload = _load(getattr(decision, "jev_json", None))
        if isinstance(payload, dict):
            status = payload.get("systemone_status")
            if status == "skipped_veto":
                counts["skipped_veto"] += 1
            elif status == "scored":
                counts["scored"] += 1
        chain = _load(getattr(decision, "reason_chain_json", None))
        if isinstance(chain, list):
            for step in chain:
                if isinstance(step, dict) and step.get("code") in counts:
                    counts[str(step["code"])] += 1
    return counts


def run_jev_warm(app, *, vision_root: Path, end: date) -> int:
    settings = app.settings
    history = date.fromisoformat(settings.marketdata.history_start)
    symbols = tuple(_symbols_in_files(app.root, settings.runtime.venue, history, end))
    instruments = {}
    for symbol in symbols:
        text = _kline_text(vision_root, symbol)
        instruments[symbol] = app.instruments.get(symbol) or inferred_instrument(settings, symbol, text)
    source = ParquetBars(app.store, settings.runtime.venue)
    store = {
        timeframe: {symbol: tuple(source.load(symbol, timeframe)) for symbol in symbols}
        for timeframe in Timeframe
    }
    refresh = settings.universe.refresh_minute
    times = _decision_times(store[Timeframe.M15], history, end, refresh)
    boards = _preload(FileUniverse(app.root, settings.runtime.venue), times, refresh)
    limits = _windows(settings)
    services = _warm_services(app.services)
    account = AccountView(
        equity_quote=Decimal("0"),
        open_position_count=0,
        gross_notional_quote=Decimal("0"),
    )
    safety = SafetyState(kill_switch=False, mode=RuntimeMode.PAPER)
    previous: dict = {}
    above = 0
    below = 0
    threshold = Decimal(format_fixed8(settings.jev.enter_threshold))
    for decision_time in times:
        day = _universe_date(decision_time, refresh)
        board = boards[day]
        for symbol, rank in sorted(board.items(), key=lambda item: (item[1], item[0])):
            bars_15 = store[Timeframe.M15].get(symbol, ())
            if _bar_at(bars_15, decision_time) is None:
                continue
            request = PipelineRequest(
                symbol=symbol,
                decision_time=decision_time,
                universe_date=day,
                universe_rank=rank,
                group="entry",
                full_log=False,
                flattened=False,
                bars={
                    timeframe: _window(store[timeframe].get(symbol, ()), decision_time, limits[timeframe])
                    for timeframe in Timeframe
                },
                data_quality=_quality(None, symbol, decision_time, bars_15),
                instrument=instruments[symbol],
                account=account,
                safety=safety,
                position=None,
                previous=previous.get(symbol, {}),
                config_hash=app.config_hash,
                engine_version=app.engine_version,
                feature_version=app.feature_version,
                marketdata_version=app.marketdata_version,
                order_type=settings.execution.order_type,
                group_order=0,
                record=False,
            )
            result = app.pipeline(request, services)
            if result.snapshots:
                merged = dict(previous.get(symbol, {}))
                merged.update(result.snapshots)
                previous[symbol] = merged
            assessment = result.assessment
            if assessment is None or assessment.systemone_status != "scored":
                continue
            quantized = Decimal(format_fixed8(assessment.score))
            if quantized >= threshold:
                above += 1
            else:
                below += 1
    met = enable_floor(above, below)
    print(
        f"scored={above + below} above={above} below={below} enable_floor={str(met).lower()}",
    )
    failed = () if app.systemone_client is None else tuple(app.systemone_client.failed_keys)
    for key in failed:
        print(f"missing {key}")
    if failed:
        return 1
    return 0


def _warm_services(services: PipelineServices) -> PipelineServices:
    return PipelineServices(
        engine=services.engine,
        features=services.features,
        jev=services.jev,
        rules=services.rules,
        risk=services.risk,
        broker=services.broker,
        rule_params=services.rule_params,
        log_jev=services.log_jev,
        score_after_preflight=True,
        warm=True,
    )


def _load(payload: str | None):
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
