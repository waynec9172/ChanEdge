"""15m backtest clock. Decision order stays in the injected pipeline.

The loop matches, then runs the exit group, then the entry group. It does not
import app, marketdata, or journal, and it does not call the exchange port.
"""

from __future__ import annotations

import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.backtest.matcher import match_bar
from chanedge.backtest.report import attach_funding, build_summary, build_trades, write_report
from chanedge.backtest.shadow import ShadowBook
from chanedge.domain.accounting import mark_pnl, quantize
from chanedge.domain.bars import DataQuality, Instrument
from chanedge.domain.enums import AmendReason, DecisionAction, InstrumentSource, Side, Timeframe
from chanedge.domain.records import (
    DecisionRecord,
    FillRecord,
    PipelineRequest,
    UniverseUnavailable,
)
from chanedge.domain.risk import AccountView, PositionState

_UTC = timezone.utc
_TOP = 20
_DEFAULT_WINDOWS = {Timeframe.M15: 1500, Timeframe.H1: 1000, Timeframe.H4: 500}


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    directory: Path
    decisions: tuple[DecisionRecord, ...]
    fills: tuple[FillRecord, ...]
    cash: Decimal
    synchronous: int
    chart_frames: int
    incomplete: bool = False


def run_backtest(
    *,
    pipeline,
    services,
    broker,
    clock,
    bar_source,
    universe_source,
    report_sink,
    instruments: dict[str, Instrument],
    symbols: tuple[str, ...],
    history_start: date,
    history_end: date,
    refresh_minute: int,
    fee_bps: Decimal,
    slippage_bps: Decimal,
    initial_equity: Decimal,
    safety,
    config_hash: str,
    engine_version: str,
    feature_version: str,
    marketdata_version: str,
    shadow_sizer,
    overlap_peak: float,
    overlap_width: float,
    overlap_penalty_above: float,
    jev_weights: dict[str, float],
    funding_source=None,
    quality=None,
    order_type: str = "market",
    full_log: bool = False,
    windows: dict[Timeframe, int] | None = None,
    halt_on=None,
) -> BacktestResult:
    del initial_equity  # the broker already replayed or seeded cash
    limits = dict(_DEFAULT_WINDOWS if windows is None else windows)
    store = {
        timeframe: {symbol: _Series(bar_source.load(symbol, timeframe)) for symbol in symbols}
        for timeframe in Timeframe
    }
    times = _decision_times(
        {symbol: series.bars for symbol, series in store[Timeframe.M15].items()},
        history_start,
        history_end,
        refresh_minute,
    )
    boards = _preload(universe_source, times, refresh_minute)
    started_at = clock.now()
    run_id = _run_id(
        config_hash=config_hash,
        engine_version=engine_version,
        feature_version=feature_version,
        marketdata_version=marketdata_version,
        history_start=history_start,
        history_end=history_end,
        started_at=started_at,
    )
    directory = report_sink.begin_run(run_id)
    if "chanedge.sqlite" in directory.parts or (directory / "chanedge.sqlite").exists():
        raise ValueError("report directory is not the paper database")
    shadow = ShadowBook()
    previous: dict[str, dict] = {}
    latest: dict = {}
    # Slim copies only: a full PipelineResult keeps its context and 15m snapshot,
    # about 1 MiB each, which a multi-year run cannot hold in memory.
    results = []
    fills: list[FillRecord] = []
    overlaps: list[float] = []
    signals: list[dict] = []
    equity: list[dict] = []
    meta: dict[str, dict] = {}
    seeds = _seeds(broker)
    fee_drag = Decimal("0")
    inferred = 0
    exposure = 0
    started = time.perf_counter()
    halted = False
    for decision_time in times:
        day = _universe_date(decision_time, refresh_minute)
        board = boards[day]
        marks = _marks(store[Timeframe.M15], decision_time)
        flattened: set[str] = set()
        match_names = set(broker.open_symbols()) | set(broker.pending_symbols()) | shadow.active_symbols()
        for symbol in sorted(match_names):
            bar = _at(store[Timeframe.M15], symbol, decision_time)
            if bar is None:
                continue
            was_open = broker.position(symbol) is not None
            matched = match_bar(
                broker.position(symbol),
                broker.pending_for(symbol),
                bar,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                arm_close=broker.arm_close(symbol),
            )
            if matched:
                broker.apply(matched)
            if broker.position(symbol) is None and (was_open or any(item.reduce_only for item in matched)):
                flattened.add(symbol)
            shadow.match(symbol, bar, fee_bps=fee_bps, slippage_bps=slippage_bps)
        if broker.open_symbols():
            exposure += 1
        jobs = _jobs(broker, shadow, board, store[Timeframe.M15], decision_time, flattened)
        effective = effective_positions(broker)
        sequence = 0
        bar_decisions: list[DecisionRecord] = []
        for group, symbol, is_flat in jobs:
            account = _view(broker, effective, marks)
            request_bars = {
                timeframe: _windowed(store[timeframe], symbol, decision_time, limits[timeframe])
                for timeframe in Timeframe
            }
            recorded = group != "shadow"
            open_shadows = shadow.reviewable(symbol)
            position = broker.position(symbol) if group == "exit" else None
            if group == "shadow":
                # The exit group needs one position to build its context. Every
                # shadow, this one included, is reviewed through shadow_positions.
                position = open_shadows[0][1]
            request = PipelineRequest(
                symbol=symbol,
                decision_time=decision_time,
                universe_date=day,
                universe_rank=board.get(symbol),
                group="exit" if group != "entry" else "entry",
                full_log=full_log,
                flattened=is_flat,
                bars=request_bars,
                data_quality=_quality(quality, symbol, decision_time, request_bars),
                instrument=instruments[symbol],
                account=account,
                safety=safety,
                position=position,
                previous=previous.get(symbol, {}),
                config_hash=config_hash,
                engine_version=engine_version,
                feature_version=feature_version,
                marketdata_version=marketdata_version,
                order_type=order_type,
                group_order=sequence,
                record=recorded,
                shadow_positions=tuple(item for _key, item in open_shadows),
            )
            result = pipeline(request, services)
            sequence += 1
            if halt_on is not None and halt_on(result):
                halted = True
            if result.snapshots:
                merged = dict(previous.get(symbol, {}))
                merged.update(result.snapshots)
                previous[symbol] = merged
                snap = result.snapshots.get(Timeframe.M15)
                if snap is not None:
                    latest[symbol] = snap
            for (key, _item), review in zip(open_shadows, result.shadow_reviews):
                shadow.apply_review(key, review, result.bar_close, decision_time)
            if recorded:
                results.append(_slim_result(result))
                bar_decisions.append(result.decision)
                if result.amend is not None:
                    broker.amend(
                        symbol,
                        result.amend.new_stop_price,
                        arm_close=result.bar_close,
                        replace_arm=result.amend.reason is AmendReason.BREAKEVEN,
                        updated_at=decision_time,
                    )
                effective = _apply_effective(effective, result)
                _remember(meta, overlaps, signals, shadow, shadow_sizer, result, decision_time)
                if halted:
                    break
            elif halted:
                break
        flush = broker.take_flush()
        report_sink.commit_bar(
            _commit(tuple(bar_decisions), flush)
        )
        for fill in flush.fills:
            fills.append(fill)
            fee_drag += fill.fee_quote
            source = instruments.get(fill.symbol)
            if source is not None and source.instrument_source is InstrumentSource.INFERRED:
                inferred += 1
        equity.append(
            {
                "time": decision_time.isoformat(),
                "equity": format(_view(broker, list(broker.open_positions()), marks).equity_quote, ".8f"),
                "cash": format(broker.cash, ".8f"),
            }
        )
        if halted:
            break
    shadow.finish()
    trades = build_trades(fills, meta, seeds, instruments)
    missing = attach_funding(trades, funding_source)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    count = len(results)
    summary = build_summary(
        decisions=results,
        trades=trades,
        overlaps=overlaps,
        signals=signals,
        snapshots=latest,
        weights=jev_weights,
        overlap_peak=overlap_peak,
        overlap_width=overlap_width,
        overlap_penalty_above=overlap_penalty_above,
        missing_funding_months=missing,
        fee_drag=fee_drag,
        exposure_bars=exposure,
        equity=equity,
        inferred_fill_count=inferred,
    )
    write_report(
        directory,
        trades=trades,
        shadows=list(shadow.rows),
        equity=equity,
        summary=summary,
        timing={
            "elapsed_ms": elapsed_ms,
            "decision_count": count,
            "mean_decision_ms": 0.0 if count == 0 else elapsed_ms / count,
        },
    )
    return BacktestResult(
        run_id=run_id,
        directory=directory,
        decisions=tuple(item.decision for item in results),
        fills=tuple(fills),
        cash=broker.cash,
        synchronous=report_sink.synchronous(),
        chart_frames=report_sink.chart_frame_count(),
        incomplete=halted,
    )


def _commit(decisions, flush):
    from chanedge.domain.records import BarCommit

    return BarCommit(
        decisions=decisions,
        orders=flush.orders,
        fills=flush.fills,
        positions=flush.positions,
        cash=flush.cash,
    )


def _remember(meta, overlaps, signals, shadow, shadow_sizer, result, decision_time) -> None:
    if result.group == "entry" and result.features is not None:
        overlaps.append(result.features.structure.consecutive_bi_overlap_ratio)
    if result.group != "entry" or result.candidate is None:
        return
    signals.append(
        {
            "symbol": result.decision.symbol,
            "signal_type": result.candidate.type.value,
            "defending_fx_id": result.candidate.defending_fx_id,
            "related_bi_id": result.candidate.related_bi_id,
        }
    )
    if (
        result.context is None
        or result.features is None
        or result.assessment is None
        or result.rules is None
    ):
        return
    sized = shadow_sizer(result.context, result.features, result.assessment, result.rules)
    shadow.open_shadow(result.decision.symbol, sized, result.candidate, decision_time)
    if result.submitted and result.plan is not None:
        meta[result.decision.decision_id] = {
            "signal_type": result.candidate.type.value,
            "target_risk_fraction": result.plan.target_risk_fraction,
            "realized_risk_fraction": result.plan.realized_risk_fraction,
            "binding_constraint": result.plan.binding_constraint,
            "cost_r": result.plan.cost_r,
        }


def _slim_result(result):
    """What the summary and the returned decisions read. Context, snapshots, and features are dropped."""
    return result.model_copy(
        update={
            "context": None,
            "snapshots": {},
            "features": None,
            "decision": result.decision.model_copy(update={"feature_json": None}),
        }
    )


class _Series:
    """Closed bars of one symbol and timeframe, indexed by close_time."""

    def __init__(self, bars) -> None:
        self.bars = tuple(sorted((bar for bar in bars if bar.is_closed), key=lambda bar: bar.close_time))
        self.closes = [bar.close_time for bar in self.bars]
        self.by_close = {bar.close_time: bar for bar in self.bars}

    def at(self, decision_time: datetime):
        return self.by_close.get(decision_time)

    def window(self, decision_time: datetime, limit: int):
        end = bisect_right(self.closes, decision_time)
        if limit < 1:
            return self.bars[:end]
        return self.bars[max(0, end - limit) : end]

    def last_at_or_before(self, decision_time: datetime):
        end = bisect_right(self.closes, decision_time)
        return None if end == 0 else self.bars[end - 1]


_EMPTY = _Series(())


def _at(series_by_symbol, symbol: str, decision_time: datetime):
    return series_by_symbol.get(symbol, _EMPTY).at(decision_time)


def _windowed(series_by_symbol, symbol: str, decision_time: datetime, limit: int):
    return series_by_symbol.get(symbol, _EMPTY).window(decision_time, limit)


def _jobs(broker, shadow, board, bars, decision_time, flattened: set[str]):
    def has_bar(symbol: str) -> bool:
        return _at(bars, symbol, decision_time) is not None

    open_names = [symbol for symbol in broker.open_symbols() if has_bar(symbol)]
    dropped = sorted(symbol for symbol in open_names if symbol not in board)
    ranked = sorted((board[symbol], symbol) for symbol in open_names if symbol in board)
    jobs = [("exit", symbol, False) for symbol in dropped]
    jobs.extend(("exit", symbol, False) for _rank, symbol in ranked)
    used = {symbol for _group, symbol, _flat in jobs}
    entries = sorted(
        (rank, symbol)
        for symbol, rank in board.items()
        if symbol not in used and broker.position(symbol) is None and has_bar(symbol)
    )
    jobs.extend(("entry", symbol, symbol in flattened) for _rank, symbol in entries)
    used.update(symbol for _group, symbol, _flat in jobs)
    for symbol in sorted(shadow.active_symbols()):
        if symbol in used or not shadow.reviewable(symbol) or not has_bar(symbol):
            continue
        jobs.append(("shadow", symbol, False))
    return jobs


def _view(broker, effective, marks) -> AccountView:
    equity = broker.cash
    for position in broker.open_positions():
        mark = marks.get(position.symbol)
        if mark is None:
            continue
        equity += mark_pnl(position.qty, quantize(position.avg_price), quantize(mark))
    gross = Decimal("0")
    count = 0
    for position in effective:
        if position.qty == 0:
            continue
        count += 1
        gross += abs(quantize(position.qty)) * quantize(position.avg_price)
    return AccountView(
        equity_quote=quantize(equity),
        positions=tuple(effective),
        open_order_ids=(),
        open_position_count=count,
        gross_notional_quote=quantize(gross),
    )


def effective_positions(broker) -> list[PositionState]:
    """Open positions plus next_open orders that matching could not fill yet.

    A pending exit takes its position out of the count. A pending entry counts
    at qty x entry_reference. Orders normally fill in step 1; this covers a
    symbol with no bar this decision and the first bar after a restart.
    """
    pending = [order for symbol in broker.pending_symbols() for order in broker.pending_for(symbol)]
    exiting = {order.symbol for order in pending if order.reduce_only}
    effective = [position for position in broker.open_positions() if position.symbol not in exiting]
    held = {position.symbol for position in effective}
    for order in pending:
        plan = order.plan
        if order.reduce_only or order.symbol in held or plan is None:
            continue
        if plan.entry_reference is None or plan.structure_stop_price is None or order.entry_decision_time is None:
            continue
        qty = order.qty if plan.side is Side.LONG else -order.qty
        effective.append(
            PositionState(
                symbol=order.symbol,
                qty=qty,
                avg_price=float(plan.entry_reference),
                stop_price=float(plan.structure_stop_price),
                plan=plan,
                entry_decision_id=order.decision_id,
                entry_decision_time=order.entry_decision_time,
                entry_bar_open_time=order.entry_decision_time,
            )
        )
        held.add(order.symbol)
    return effective


def _apply_effective(effective, result):
    symbol = result.decision.symbol
    if not result.submitted:
        return effective
    if result.action is DecisionAction.EXIT:
        return [item for item in effective if item.symbol != symbol]
    if result.action not in (DecisionAction.ENTER_LONG, DecisionAction.ENTER_SHORT) or result.plan is None:
        return effective
    plan = result.plan
    if plan.entry_reference is None or plan.structure_stop_price is None:
        return effective
    qty = plan.qty if plan.side is Side.LONG else -plan.qty
    synthetic = PositionState(
        symbol=symbol,
        qty=qty,
        avg_price=float(plan.entry_reference),
        stop_price=float(plan.structure_stop_price),
        plan=plan,
        entry_decision_id=result.decision.decision_id,
        entry_decision_time=result.decision.decision_time,
        entry_bar_open_time=result.decision.decision_time,
    )
    kept = [item for item in effective if item.symbol != symbol]
    kept.append(synthetic)
    return kept


def _seeds(broker) -> dict[str, dict]:
    seeds = {}
    for position in broker.open_positions():
        plan = position.plan
        seeds[position.symbol] = {
            "qty": position.qty,
            "avg": quantize(position.avg_price),
            "opened_at": position.entry_bar_open_time,
            "signal_type": None,
            "target_risk_fraction": plan.target_risk_fraction,
            "realized_risk_fraction": plan.realized_risk_fraction,
            "binding_constraint": plan.binding_constraint,
            "cost_r": plan.cost_r,
        }
    return seeds


def _quality(callback, symbol: str, decision_time: datetime, windows) -> DataQuality:
    """windows maps each timeframe to its engine window. The callback measures gaps."""
    if callback is None:
        quality = DataQuality(
            stale=False,
            max_gap_bars=0,
            missing_bar_count=0,
            last_bar_close=decision_time,
            reasons=(),
        )
    else:
        quality = callback(symbol, decision_time, windows)
    if quality.stale:
        return quality.model_copy(update={"stale": False})
    return quality


def _preload(source, times, refresh_minute: int) -> dict[date, dict[str, int]]:
    dates = sorted({_universe_date(moment, refresh_minute) for moment in times})
    boards: dict[date, dict[str, int]] = {}
    for day in dates:
        try:
            loaded = source.load(day)
        except UniverseUnavailable:
            raise
        except Exception as exc:
            raise UniverseUnavailable(
                f"universe file {day.isoformat()} cannot be parsed; delete it and run chanedge universe --reconstruct"
            ) from exc
        boards[day] = {item.symbol: item.rank for item in loaded if 1 <= item.rank <= _TOP}
    return boards


def _decision_times(bars_by_symbol, history_start: date, history_end: date, refresh_minute: int):
    found: set[datetime] = set()
    for bars in bars_by_symbol.values():
        for bar in bars:
            if not bar.is_closed:
                continue
            day = _universe_date(bar.close_time, refresh_minute)
            if history_start <= day <= history_end:
                found.add(bar.close_time)
    return tuple(sorted(found))


def _marks(series_by_symbol, decision_time: datetime) -> dict[str, float]:
    """Last closed price at or before decision_time. A missing bar does not drop the mark."""
    marks = {}
    for symbol, series in series_by_symbol.items():
        bar = series.last_at_or_before(decision_time)
        if bar is not None:
            marks[symbol] = bar.close
    return marks


def _universe_date(moment: datetime, refresh_minute: int) -> date:
    return (moment - timedelta(minutes=refresh_minute)).astimezone(_UTC).date()


def _run_id(
    *,
    config_hash: str,
    engine_version: str,
    feature_version: str,
    marketdata_version: str,
    history_start: date,
    history_end: date,
    started_at: datetime,
) -> str:
    stamp = started_at.astimezone(_UTC).strftime("%Y-%m-%dT%H-%M-%S")
    window = f"{history_start.isoformat()}_{history_end.isoformat()}"
    raw = "_".join(
        (config_hash, engine_version, feature_version, marketdata_version, window, stamp)
    )
    return "".join("-" if char in '|:<>"/\\?*' else char for char in raw)
