"""15m backtest clock. Decision order stays in the injected pipeline.

The loop matches, then runs the exit group, then the entry group. It does not
import app, marketdata, or journal, and it does not call the exchange port.
"""

from __future__ import annotations

import os
import pickle
import time
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.backtest.matcher import match_bar
from chanedge.backtest.report import (
    DecisionStats,
    ResearchTracker,
    attach_funding,
    build_summary,
    build_trades,
    write_report,
)
from chanedge.backtest.shadow import ShadowBook
from chanedge.domain.accounting import mark_pnl, quantize
from chanedge.domain.bars import DataQuality, Instrument, timeframe_duration
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


class BacktestInterrupted(RuntimeError):
    """Raised by stop_after_bars after a checkpoint, so tests can resume like a crash."""


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    directory: Path
    decisions: Sequence[DecisionRecord]
    fills: tuple[FillRecord, ...]
    cash: Decimal
    synchronous: int
    chart_frames: int
    incomplete: bool = False


@dataclass
class _Progress:
    """Everything after the last checkpoint that a resumed run needs."""

    run_id: str
    fingerprint: dict
    cursor: datetime | None = None
    bars_done: int = 0
    elapsed_ms: int = 0
    fills: list = field(default_factory=list)
    overlaps: list = field(default_factory=list)
    equity: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    seeds: dict = field(default_factory=dict)
    fee_drag: Decimal = Decimal("0")
    inferred: int = 0
    exposure: int = 0
    research: ResearchTracker = field(default_factory=ResearchTracker)
    stats: DecisionStats | None = None
    shadow: ShadowBook = field(default_factory=ShadowBook)


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
    resume: Path | None = None,
    checkpoint_bars: int = 96,
    stop_after_bars: int | None = None,
) -> BacktestResult:
    """Bars are read a window at a time and only for symbols in play, and every
    checkpoint_bars committed bars the run state is saved next to the report.
    resume points at that report directory and continues after the checkpoint;
    the outputs match a run that was never interrupted.
    """
    del initial_equity  # the broker already replayed or seeded cash
    limits = dict(_DEFAULT_WINDOWS if windows is None else windows)
    source = bar_source if hasattr(bar_source, "index") else _EagerSource(bar_source)
    times = _times_from_source(source, symbols, history_start, history_end, refresh_minute)
    boards = _preload(universe_source, times, refresh_minute)
    fingerprint = {
        "config_hash": config_hash,
        "engine_version": engine_version,
        "feature_version": feature_version,
        "marketdata_version": marketdata_version,
        "history_start": history_start.isoformat(),
        "history_end": history_end.isoformat(),
    }
    if resume is None:
        run_id = _run_id(
            config_hash=config_hash,
            engine_version=engine_version,
            feature_version=feature_version,
            marketdata_version=marketdata_version,
            history_start=history_start,
            history_end=history_end,
            started_at=clock.now(),
        )
        directory = report_sink.begin_run(run_id)
        progress = _Progress(run_id=run_id, fingerprint=fingerprint, seeds=_seeds(broker))
        progress.stats = DecisionStats(jev_weights)
    else:
        directory = report_sink.resume_run(resume)
        saved = _load_checkpoint(directory)
        progress = saved["progress"]
        if progress.fingerprint != fingerprint:
            raise ValueError("checkpoint was written with other settings or versions; start a new run")
        broker.__dict__.update(saved["broker"])
        report_sink.restore_point(saved["point"])
        run_id = progress.run_id
    if "chanedge.sqlite" in directory.parts or (directory / "chanedge.sqlite").exists():
        raise ValueError("report directory is not the paper database")
    stats = progress.stats
    research = progress.research
    shadow = progress.shadow
    cache = _BarCache(source, limits)
    previous: dict[str, dict] = {}
    can_checkpoint = hasattr(report_sink, "save_point") and checkpoint_bars > 0
    started = time.perf_counter() - progress.elapsed_ms / 1000
    halted = False
    since_checkpoint = 0
    for decision_time in times:
        if progress.cursor is not None and decision_time <= progress.cursor:
            continue
        day = _universe_date(decision_time, refresh_minute)
        board = boards[day]
        in_play = set(board) | set(broker.open_symbols()) | set(broker.pending_symbols()) | shadow.active_symbols()
        cache.retain(in_play)
        for symbol in [name for name in previous if name not in in_play]:
            del previous[symbol]
        # Pending entries fill at this bar's open, so they need a mark as well.
        marks = _marks(cache, set(broker.open_symbols()) | set(broker.pending_symbols()), decision_time)
        flattened: set[str] = set()
        match_names = set(broker.open_symbols()) | set(broker.pending_symbols()) | shadow.active_symbols()
        for symbol in sorted(match_names):
            bar = cache.at(symbol, decision_time)
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
            progress.exposure += 1
        jobs = _jobs(broker, shadow, board, lambda name: cache.at(name, decision_time) is not None, flattened)
        effective = effective_positions(broker)
        sequence = 0
        bar_decisions: list[DecisionRecord] = []
        for group, symbol, is_flat in jobs:
            account = _view(broker, effective, marks)
            request_bars = {
                timeframe: cache.window(symbol, timeframe, decision_time, limits[timeframe])
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
                # Only 1H and 4H are reused; a 15m window slides every bar.
                kept = {timeframe: snap for timeframe, snap in result.snapshots.items() if timeframe is not Timeframe.M15}
                if kept:
                    merged = dict(previous.get(symbol, {}))
                    merged.update(kept)
                    previous[symbol] = merged
                snap = result.snapshots.get(Timeframe.M15)
                if snap is not None:
                    research.observe(symbol, snap)
            for (key, _item), review in zip(open_shadows, result.shadow_reviews):
                shadow.apply_review(key, review, result.bar_close, decision_time)
            if recorded:
                stats.add(result)
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
                _remember(progress.meta, progress.overlaps, research, shadow, shadow_sizer, result, decision_time)
                if halted:
                    break
            elif halted:
                break
        flush = broker.take_flush()
        report_sink.commit_bar(_commit(tuple(bar_decisions), flush))
        for fill in flush.fills:
            progress.fills.append(fill)
            progress.fee_drag += fill.fee_quote
            source_spec = instruments.get(fill.symbol)
            if source_spec is not None and source_spec.instrument_source is InstrumentSource.INFERRED:
                progress.inferred += 1
        progress.equity.append(
            {
                "time": decision_time.isoformat(),
                "equity": format(_view(broker, list(broker.open_positions()), marks).equity_quote, ".8f"),
                "cash": format(broker.cash, ".8f"),
            }
        )
        progress.cursor = decision_time
        progress.bars_done += 1
        if halted:
            break
        since_checkpoint += 1
        if can_checkpoint and since_checkpoint >= checkpoint_bars:
            progress.elapsed_ms = int((time.perf_counter() - started) * 1000)
            _save_checkpoint(directory, progress, broker, report_sink.save_point())
            since_checkpoint = 0
            if stop_after_bars is not None and progress.bars_done >= stop_after_bars:
                raise BacktestInterrupted(f"stopped after {progress.bars_done} bars")
    shadow.finish()
    trades = build_trades(progress.fills, progress.meta, progress.seeds, instruments)
    missing = attach_funding(trades, funding_source)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    count = stats.count
    summary = build_summary(
        stats=stats,
        trades=trades,
        overlaps=progress.overlaps,
        research=research,
        overlap_peak=overlap_peak,
        overlap_width=overlap_width,
        overlap_penalty_above=overlap_penalty_above,
        missing_funding_months=missing,
        fee_drag=progress.fee_drag,
        exposure_bars=progress.exposure,
        equity=progress.equity,
        inferred_fill_count=progress.inferred,
    )
    write_report(
        directory,
        trades=trades,
        shadows=list(shadow.rows),
        equity=progress.equity,
        summary=summary,
        timing={
            "elapsed_ms": elapsed_ms,
            "decision_count": count,
            "mean_decision_ms": 0.0 if count == 0 else elapsed_ms / count,
        },
    )
    (directory / _CHECKPOINT).unlink(missing_ok=True)
    decisions = report_sink.decisions() if hasattr(report_sink, "decisions") else ()
    return BacktestResult(
        run_id=run_id,
        directory=directory,
        decisions=decisions,
        fills=tuple(progress.fills),
        cash=broker.cash,
        synchronous=report_sink.synchronous(),
        chart_frames=report_sink.chart_frame_count(),
        incomplete=halted,
    )


_CHECKPOINT = "checkpoint.pkl"
# Broker fields that hold a connection; the resumed broker keeps its own.
_LIVE_FIELDS = frozenset({"_ledger"})


def _save_checkpoint(directory: Path, progress: _Progress, broker, point: dict) -> None:
    """pickle, written to a tmp file and renamed, so a crash mid-write keeps the last one.
    Only load checkpoints this program wrote: unpickling runs code from the file."""
    state = {key: value for key, value in broker.__dict__.items() if key not in _LIVE_FIELDS}
    payload = pickle.dumps({"progress": progress, "broker": state, "point": point})
    target = directory / _CHECKPOINT
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, target)


def _load_checkpoint(directory: Path) -> dict:
    path = directory / _CHECKPOINT
    if not path.is_file():
        raise FileNotFoundError(f"no checkpoint in {directory}; nothing to resume")
    return pickle.loads(path.read_bytes())


def checkpoint_end(directory: Path) -> date:
    """history_end the interrupted run was started with, so resume needs no --end."""
    progress = _load_checkpoint(Path(directory))["progress"]
    return date.fromisoformat(progress.fingerprint["history_end"])


def _commit(decisions, flush):
    from chanedge.domain.records import BarCommit

    return BarCommit(
        decisions=decisions,
        orders=flush.orders,
        fills=flush.fills,
        positions=flush.positions,
        cash=flush.cash,
    )


def _remember(meta, overlaps, research, shadow, shadow_sizer, result, decision_time) -> None:
    if result.group == "entry" and result.features is not None:
        overlaps.append(result.features.structure.consecutive_bi_overlap_ratio)
    if result.group != "entry" or result.candidate is None:
        return
    candidate = result.candidate
    symbol = result.decision.symbol
    research.add_signal(symbol, candidate.type.value, candidate.defending_fx_id, _bi_key(result, symbol))
    if (
        result.context is None
        or result.features is None
        or result.assessment is None
        or result.rules is None
    ):
        return
    sized = shadow_sizer(result.context, result.features, result.assessment, result.rules)
    shadow.open_shadow(symbol, sized, candidate, decision_time)
    if result.submitted and result.plan is not None:
        plan = result.plan
        meta[result.decision.decision_id] = {
            "signal_type": candidate.type.value,
            "target_risk_fraction": plan.target_risk_fraction,
            "realized_risk_fraction": plan.realized_risk_fraction,
            "binding_constraint": plan.binding_constraint,
            "cost_r": plan.cost_r,
            "risk_per_unit": _risk_per_unit(plan),
            "defending_atr": _defending_atr(plan, candidate),
        }


def _bi_key(result, symbol: str) -> str | None:
    """A bi id changes when its endpoint is replaced. The start fenxing does not."""
    context = result.context
    if context is None:
        return None
    for bi in context.snapshots[Timeframe.M15].bis:
        if bi.id == result.candidate.related_bi_id:
            return f"{symbol}|{bi.start_fx_id}"
    return None


def _risk_per_unit(plan) -> Decimal | None:
    if plan.entry_reference is None or plan.structure_stop_price is None:
        return None
    return abs(quantize(plan.entry_reference) - quantize(plan.structure_stop_price))


def _defending_atr(plan, candidate) -> Decimal | None:
    """(entry_reference - defending_price) / ATR on the signal bar; the short side mirrors it."""
    if plan.entry_reference is None or not plan.atr:
        return None
    distance = quantize(plan.entry_reference) - quantize(candidate.defending_price)
    if plan.side is Side.SHORT:
        distance = -distance
    return quantize(distance / quantize(plan.atr))


class _EagerSource:
    """Adapter for a bar source that only has load(); it keeps every bar it loads."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._bars: dict[tuple[str, Timeframe], tuple] = {}

    def _all(self, symbol: str, timeframe: Timeframe):
        key = (symbol, timeframe)
        if key not in self._bars:
            loaded = (bar for bar in self._inner.load(symbol, timeframe) if bar.is_closed)
            self._bars[key] = tuple(sorted(loaded, key=lambda bar: bar.close_time))
        return self._bars[key]

    def index(self, symbol: str, timeframe: Timeframe):
        return [_millis(bar.close_time) for bar in self._all(symbol, timeframe)]

    def rows(self, symbol: str, timeframe: Timeframe, lo: int, hi: int):
        return self._all(symbol, timeframe)[lo:hi]

    def release(self, symbol: str) -> None:
        for timeframe in Timeframe:
            self._bars.pop((symbol, timeframe), None)


class _LazySeries:
    """One symbol and timeframe. Holds the close-time index and a slice of Bars:
    the window behind the current bar plus about 30 days ahead."""

    def __init__(self, source, symbol: str, timeframe: Timeframe, lookback: int) -> None:
        self._source = source
        self._symbol = symbol
        self._timeframe = timeframe
        self._closes = source.index(symbol, timeframe)
        self._lookback = lookback
        self._ahead = _AHEAD_DAYS * 24 * 60 // int(timeframe_duration(timeframe).total_seconds() // 60)
        self._bars: tuple = ()
        self._lo = 0
        self._hi = 0

    def _end(self, decision_time: datetime) -> int:
        """Rows [0, end) close at or before decision_time; [end - lookback, end) is loaded."""
        end = bisect_right(self._closes, _millis(decision_time))
        start = max(0, end - self._lookback)
        if start < self._lo or end > self._hi or (end and not self._bars):
            self._lo = start
            self._hi = min(len(self._closes), end + self._ahead)
            self._bars = tuple(self._source.rows(self._symbol, self._timeframe, self._lo, self._hi))
        return end

    def at(self, decision_time: datetime):
        end = self._end(decision_time)
        if end and self._closes[end - 1] == _millis(decision_time):
            return self._bars[end - 1 - self._lo]
        return None

    def last_at_or_before(self, decision_time: datetime):
        end = self._end(decision_time)
        return self._bars[end - 1 - self._lo] if end else None

    def window(self, decision_time: datetime, limit: int):
        end = self._end(decision_time)
        start = max(self._lo, end - limit)
        return self._bars[start - self._lo : end - self._lo]


class _BarCache:
    """Series for the symbols in play. retain() drops the rest and their memory."""

    def __init__(self, source, limits: dict[Timeframe, int]) -> None:
        self._source = source
        self._limits = limits
        self._series: dict[tuple[str, Timeframe], _LazySeries] = {}

    def _get(self, symbol: str, timeframe: Timeframe) -> _LazySeries:
        key = (symbol, timeframe)
        found = self._series.get(key)
        if found is None:
            found = _LazySeries(self._source, symbol, timeframe, max(1, self._limits[timeframe]))
            self._series[key] = found
        return found

    def at(self, symbol: str, decision_time: datetime):
        return self._get(symbol, Timeframe.M15).at(decision_time)

    def last_at_or_before(self, symbol: str, decision_time: datetime):
        return self._get(symbol, Timeframe.M15).last_at_or_before(decision_time)

    def window(self, symbol: str, timeframe: Timeframe, decision_time: datetime, limit: int):
        return self._get(symbol, timeframe).window(decision_time, limit)

    def retain(self, symbols: set[str]) -> None:
        dropped = {symbol for symbol, _timeframe in self._series if symbol not in symbols}
        for symbol in dropped:
            for timeframe in Timeframe:
                self._series.pop((symbol, timeframe), None)
            release = getattr(self._source, "release", None)
            if release is not None:
                release(symbol)


_AHEAD_DAYS = 30


def _millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _jobs(broker, shadow, board, has_bar, flattened: set[str]):
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
            "risk_per_unit": _risk_per_unit(plan),
            "defending_atr": None,
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


def _times_from_source(source, symbols, history_start: date, history_end: date, refresh_minute: int):
    """Every 15m close whose universe_date is in range, from the close-time index alone."""
    shift = refresh_minute * 60 * 1000
    first = _millis(datetime(history_start.year, history_start.month, history_start.day, tzinfo=_UTC)) + shift
    after = _millis(datetime(history_end.year, history_end.month, history_end.day, tzinfo=_UTC) + timedelta(days=1)) + shift
    found: set[int] = set()
    for symbol in symbols:
        found.update(value for value in source.index(symbol, Timeframe.M15) if first <= value < after)
        release = getattr(source, "release", None)
        if release is not None:
            release(symbol)
    return tuple(datetime.fromtimestamp(value / 1000, tz=_UTC) for value in sorted(found))


def _marks(cache, symbols, decision_time: datetime) -> dict[str, float]:
    """Last closed price at or before decision_time. A missing bar does not drop the mark."""
    marks = {}
    for symbol in symbols:
        bar = cache.last_at_or_before(symbol, decision_time)
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
