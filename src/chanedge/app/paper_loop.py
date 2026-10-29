"""One paper bar. Decision order stays in run_pipeline. Prices stay in match_bar.

The wall clock starts when the symbol loop starts. Backtest does not call this
module, so it does not wait close_wait_seconds and does not emit PIPELINE_TIMEOUT.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.app.compose import PaperApp
from chanedge.app.pipeline import PipelineServices
from chanedge.backtest.matcher import match_bar
from chanedge.domain.accounting import mark_pnl, quantize
from chanedge.domain.bars import DataQuality, Instrument, timeframe_duration
from chanedge.domain.decision import ChartFrame, HardRuleResult, ReasonStep, Veto
from chanedge.domain.enums import (
    AmendReason,
    DecisionAction,
    InstrumentSource,
    ProductType,
    ReasonStage,
    Side,
    Timeframe,
    VetoCode,
)
from chanedge.domain.ids import decision_id
from chanedge.domain.records import (
    BarCommit,
    DecisionRecord,
    FundingMonth,
    FundingPoint,
    PipelineRequest,
    UniverseName,
    UniverseUnavailable,
)
from chanedge.domain.risk import AccountView, PositionState
from chanedge.domain.serialize import dump_model, dump_models
from chanedge.journal.repository import ChartFrameRow
from chanedge.marketdata.ccxt_adapter import (
    CcxtMarketData,
    paper_daily_quotes,
    sync_closed_bars,
)
from chanedge.marketdata.infer import infer_spec_from_csv
from chanedge.marketdata.quality import assess_quality, is_stale
from chanedge.marketdata.universe import (
    load_universe,
    reconstruct_dates,
    universe_date,
    universe_path,
    write_fallback,
    write_universe_file,
)
from chanedge.marketdata.universe import members_from_selection, select_universe
from chanedge.marketdata.vision import (
    download_start,
    funding_month_csv,
    kline_files_for_month,
    ranking_open_time,
    read_daily_for_month,
    read_funding_month,
    read_klines_for_month,
)

_UTC = timezone.utc
_WALL_SECONDS = 60
_FRAME_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.H4)


@dataclass(frozen=True)
class PaperBarResult:
    started: bool
    decisions: tuple[DecisionRecord, ...]
    stale: bool


def run_paper_bar(app: PaperApp, *, decision_time: datetime, sleep) -> PaperBarResult:
    """Wait out the close, sync bars, match, then exit group and entry group."""
    board = _board(app, decision_time)
    if board is None:
        return PaperBarResult(started=False, decisions=(), stale=False)
    watched = tuple(sorted(set(board) | set(app.broker.open_symbols())))
    expected_open = decision_time - timeframe_duration(Timeframe.M15)
    sleep(app.settings.marketdata.close_wait_seconds)
    while True:
        for symbol in watched:
            _sync_symbol(app, symbol, decision_time)
        if not watched or _bars_arrived(app, watched, decision_time, expected_open):
            break
        now = app.clock.now()
        last_close = _last_close(app, watched, decision_time)
        if is_stale(now, last_close, stale_grace_seconds=app.settings.marketdata.stale_grace_seconds):
            decisions = _stale_holds(app, watched, decision_time, board)
            _commit(app, decisions)
            return PaperBarResult(started=True, decisions=tuple(decisions), stale=True)
        sleep(app.settings.marketdata.close_wait_seconds)
    loaded = _load_windows(app, watched, decision_time)
    flattened = _match_all(app, loaded[Timeframe.M15], decision_time)
    decisions: list[DecisionRecord] = []
    ran = []
    started = app.clock.now()
    jobs = _jobs(app, board, loaded[Timeframe.M15], decision_time, flattened)
    effective = list(app.broker.open_positions())
    marks = _marks(loaded[Timeframe.M15], decision_time)
    sequence = 0
    for group, symbol, is_flat in jobs:
        if (app.clock.now() - started).total_seconds() > _WALL_SECONDS:
            decisions.append(
                _hold(app, symbol, decision_time, board.get(symbol), VetoCode.PIPELINE_TIMEOUT)
            )
            _log_decision(app, decisions[-1], {})
            sequence += 1
            continue
        bucket: dict[str, float] = {}
        services = _timed(app.services, bucket)
        request_bars = {timeframe: loaded[timeframe].get(symbol, ()) for timeframe in Timeframe}
        request = PipelineRequest(
            symbol=symbol,
            decision_time=decision_time,
            universe_date=universe_date(decision_time, app.settings.universe.refresh_minute),
            universe_rank=board.get(symbol),
            group=group,
            full_log=True,
            flattened=is_flat,
            bars=request_bars,
            data_quality=_quality(app, request_bars),
            instrument=_instrument(app, symbol),
            account=_view(app, effective, marks),
            safety=app.safety,
            position=app.broker.position(symbol) if group == "exit" else None,
            previous=app.previous.get(symbol, {}),
            config_hash=app.config_hash,
            engine_version=app.engine_version,
            feature_version=app.feature_version,
            marketdata_version=app.marketdata_version,
            order_type=app.settings.execution.order_type,
            group_order=sequence,
            record=True,
        )
        result = app.pipeline(request, services)
        sequence += 1
        if result.snapshots:
            merged = dict(app.previous.get(symbol, {}))
            merged.update(result.snapshots)
            app.previous[symbol] = merged
        if result.amend is not None:
            app.broker.amend(
                symbol,
                result.amend.new_stop_price,
                arm_close=result.bar_close,
                replace_arm=result.amend.reason is AmendReason.BREAKEVEN,
                updated_at=decision_time,
            )
        effective = _apply_effective(effective, result)
        decisions.append(result.decision)
        ran.append((result, request_bars))
        _log_decision(app, result.decision, bucket)
    _commit(app, decisions)
    _frames(app, ran, board, decision_time)
    return PaperBarResult(started=True, decisions=tuple(decisions), stale=False)


def serve(app: PaperApp, *, sleep=time.sleep) -> None:
    """Sleep until each 15m close, then run that bar. The caller stops the process."""
    last: datetime | None = None
    while True:
        now = app.clock.now()
        if last is None:
            target = startup_target(now, app.settings.marketdata.close_wait_seconds)
        else:
            target = last + timeframe_duration(Timeframe.M15)
        delay = (target - now).total_seconds()
        if delay > 0:
            sleep(delay)
        run_paper_bar(app, decision_time=target, sleep=sleep)
        last = target


def startup_target(now: datetime, close_wait_seconds: int) -> datetime:
    """The close we still owe. Inside the post-close wait, that close. Otherwise the next one."""
    floor = _floor_15(now)
    if now <= floor + timedelta(seconds=close_wait_seconds):
        return floor
    return floor + timeframe_duration(Timeframe.M15)


def ensure_daily_file(app: PaperApp, day: date) -> bool:
    """Write today's file only when the final name is absent. Return whether it exists."""
    path = universe_path(app.root, app.settings.runtime.venue, day)
    if path.exists():
        return True
    try:
        _write_daily(app, day, path)
    except Exception as exc:
        write_fallback(
            app.root,
            app.settings.runtime.venue,
            day,
            as_of=app.clock.now(),
            error=str(exc),
        )
    return path.exists()


def download_history(app: PaperApp, *, vision_root: Path, end: date) -> int:
    """Copy vision klines into Parquet and funding CSVs next to the data root."""
    history = date.fromisoformat(app.settings.marketdata.history_start)
    windows = _windows(app.settings)
    start = download_start(history, windows)
    symbols = _symbols_in_files(app.root, app.settings.runtime.venue, history, end)
    written = 0
    clock = datetime(end.year, end.month, end.day, 23, 59, tzinfo=_UTC)
    for symbol in symbols:
        compact = symbol.replace("/", "")
        for timeframe, _window in windows.items():
            for year, month in _months(start, clock):
                bars = read_klines_for_month(
                    vision_root,
                    compact,
                    timeframe.value,
                    year,
                    month,
                    symbol=symbol,
                    source=app.settings.runtime.venue,
                    clock=clock,
                )
                if bars:
                    app.store.write_closed(app.settings.runtime.venue, symbol, timeframe, bars)
                    written += len(bars)
        for year, month in _months(start, clock):
            _copy_funding(vision_root, app.root, compact, year, month)
    return written


def reconstruct_history(app: PaperApp, *, vision_root: Path, end: date):
    """Fill universe dates that do not already have a file. Existing files stay put."""
    history = date.fromisoformat(app.settings.marketdata.history_start)
    dates = []
    day = history
    while day <= end:
        dates.append(day)
        day += timedelta(days=1)
    quotes: dict[date, list] = {item: [] for item in dates}
    symbols = _vision_compacts(vision_root)
    if dates:
        start = ranking_open_time(dates[0])
        stop = ranking_open_time(dates[-1])
        for compact in symbols:
            for year, month in _months(start, stop):
                for quote in read_daily_for_month(vision_root, compact, year, month):
                    file_day = (quote.open_time.astimezone(_UTC) + timedelta(days=1)).date()
                    if file_day in quotes:
                        quotes[file_day].append(quote)
    return reconstruct_dates(
        app.root,
        app.settings.runtime.venue,
        dates,
        quotes,
        size=app.settings.universe.size,
        exclude_bases=app.settings.universe.exclude_bases,
        as_of=app.clock.now(),
    )


def reconcile_report(paper_path: Path, directory: Path, backtest_decisions) -> Path | None:
    """Diff decision ids. Timeout and stale rows are not strategy divergence."""
    if not paper_path.is_file():
        return None
    from chanedge.journal.repository import JournalRepository

    paper_rows = JournalRepository(paper_path).list_decisions()
    paper = {row.decision_id: _codes(row.hard_rule_json) for row in paper_rows}
    backtest = {item.decision_id: _codes(item.hard_rule_json) for item in backtest_decisions}
    paper_reasons = {row.decision_id: _reason_codes(row.reason_chain_json) for row in paper_rows}
    backtest_reasons = {
        item.decision_id: _reason_codes(item.reason_chain_json) for item in backtest_decisions
    }
    only_paper = set(paper) - set(backtest)
    only_backtest = set(backtest) - set(paper)
    timeout: list[str] = []
    stale: list[str] = []
    paper_strategy: list[str] = []
    backtest_strategy: list[str] = []
    paper_system: list[str] = []
    backtest_system: list[str] = []
    for ident in sorted(only_paper):
        kind = _kind(paper[ident], paper_reasons.get(ident, set()))
        if kind == "pipeline_timeout":
            timeout.append(ident)
        elif kind == "stale_data":
            stale.append(ident)
        elif kind == "systemone":
            paper_system.append(ident)
        else:
            paper_strategy.append(ident)
    for ident in sorted(only_backtest):
        kind = _kind(backtest[ident], backtest_reasons.get(ident, set()))
        if kind == "pipeline_timeout":
            timeout.append(ident)
        elif kind == "stale_data":
            stale.append(ident)
        elif kind == "systemone":
            backtest_system.append(ident)
        else:
            backtest_strategy.append(ident)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "reconcile.json"
    payload = {
        "paper_only": paper_strategy,
        "backtest_only": backtest_strategy,
        "pipeline_timeout": timeout,
        "stale_data": stale,
        "systemone": paper_system,
        "systemone_counterpart": backtest_system,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class VisionFunding:
    """domain FundingMonth rows read from vision CSVs. A missing file is present=False."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def months(self, symbol: str, start: datetime, end: datetime) -> tuple[FundingMonth, ...]:
        compact = symbol.replace("/", "")
        loaded: list[FundingMonth] = []
        for year, month in _months(start, end):
            found = read_funding_month(funding_month_csv(self.root, compact, year, month))
            if found.missing:
                loaded.append(FundingMonth(year=year, month=month, present=False))
                continue
            points = tuple(
                FundingPoint(calc_time=row.calc_time, rate=row.last_funding_rate) for row in found.rows
            )
            loaded.append(FundingMonth(year=year, month=month, present=True, points=points))
        return tuple(loaded)


class ParquetBars:
    def __init__(self, store, venue: str) -> None:
        self.store = store
        self.venue = venue

    def load(self, symbol: str, timeframe: Timeframe):
        return tuple(item.bar for item in self.store.read(self.venue, symbol, timeframe))


class FileUniverse:
    def __init__(self, root: Path, venue: str) -> None:
        self.root = root
        self.venue = venue

    def load(self, day: date) -> tuple[UniverseName, ...]:
        path = universe_path(self.root, self.venue, day)
        if not path.exists():
            raise UniverseUnavailable(
                f"universe file {path} is missing; run chanedge universe --reconstruct"
            )
        return tuple(
            UniverseName(symbol=member.symbol, rank=member.rank) for member in load_universe(path)
        )


def inferred_instrument(settings, symbol: str, text: str | None) -> Instrument:
    spec = None if text is None else infer_spec_from_csv(text)
    failed = spec is None or spec.failed or spec.price_tick is None
    return Instrument(
        symbol=symbol,
        venue=settings.runtime.venue,
        venue_symbol=f"{symbol}:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=None if failed or spec is None else spec.price_tick,
        qty_step=None if failed or spec is None else spec.qty_step,
        min_qty=None if failed or spec is None else spec.min_qty,
        min_notional=None,
        margin_asset="USDT",
        leverage_max=settings.risk.max_leverage,
        instrument_source=InstrumentSource.INFERRED,
    )


def _board(app: PaperApp, decision_time: datetime) -> dict[str, int] | None:
    if app.settings.universe.mode == "pin":
        pins = app.settings.universe.pin or []
        return {item.symbol: index for index, item in enumerate(pins, start=1)}
    day = universe_date(decision_time, app.settings.universe.refresh_minute)
    if not ensure_daily_file(app, day):
        if not app.broker.open_symbols():
            return None
        return {}
    path = universe_path(app.root, app.settings.runtime.venue, day)
    return {member.symbol: member.rank for member in load_universe(path) if member.rank >= 1}


def _write_daily(app: PaperApp, day: date, path: Path) -> None:
    load = getattr(app.exchange, "load_markets", None)
    markets = [] if load is None else list(load().values())
    market = CcxtMarketData(app.exchange, clock=app.clock.now(), venue=app.settings.runtime.venue)
    start = ranking_open_time(day)
    end = start + timedelta(days=1)
    quotes = []
    for item in markets:
        if not isinstance(item, dict):
            continue
        venue_symbol = item.get("symbol")
        if not isinstance(venue_symbol, str):
            continue
        quotes.extend(market.fetch_daily_klines(venue_symbol, start, end))
    selected_quotes = paper_daily_quotes(markets, quotes, app.settings.universe.exclude_bases)
    selected = select_universe(
        selected_quotes,
        file_date=day,
        size=app.settings.universe.size,
        exclude_bases=app.settings.universe.exclude_bases,
        require_positive_min_qty=True,
    )
    members = members_from_selection(selected, source="daily_kline", as_of=app.clock.now())
    write_universe_file(path, members)


def _sync_symbol(app: PaperApp, symbol: str, decision_time: datetime) -> None:
    if symbol not in _listed(app):
        return
    instrument = app.instruments.get(symbol)
    if instrument is None:
        return
    market = CcxtMarketData(app.exchange, clock=app.clock.now(), venue=app.settings.runtime.venue)
    history = date.fromisoformat(app.settings.marketdata.history_start)
    for timeframe, window in _windows(app.settings).items():
        try:
            sync_closed_bars(
                app.store,
                market,
                instrument,
                timeframe,
                history_start=history,
                window=window,
                end=decision_time,
            )
        except Exception as exc:
            _log_error(app, "bar_sync", symbol, exc)


def _listed(app: PaperApp) -> set[str]:
    if app.listed is not None:
        return set(app.listed())
    return set(app.instruments)


def _bars_arrived(app: PaperApp, symbols, decision_time: datetime, expected_open: datetime) -> bool:
    for symbol in symbols:
        if _latest_open(app, symbol, decision_time) != expected_open:
            return False
    return True


def _latest_open(app: PaperApp, symbol: str, decision_time: datetime) -> datetime | None:
    latest = None
    for bar in _stored(app, symbol, Timeframe.M15):
        if bar.is_closed and bar.close_time <= decision_time and (latest is None or bar.open_time > latest):
            latest = bar.open_time
    return latest


def _last_close(app: PaperApp, symbols, decision_time: datetime) -> datetime:
    latest = None
    for symbol in symbols:
        for bar in _stored(app, symbol, Timeframe.M15):
            if bar.is_closed and (latest is None or bar.close_time > latest):
                latest = bar.close_time
    return decision_time if latest is None else latest


def _stored(app: PaperApp, symbol: str, timeframe: Timeframe):
    return tuple(item.bar for item in app.store.read(app.settings.runtime.venue, symbol, timeframe))


def _load_windows(app: PaperApp, symbols, decision_time: datetime):
    limits = _windows(app.settings)
    loaded = {timeframe: {} for timeframe in Timeframe}
    for symbol in symbols:
        for timeframe in Timeframe:
            closed = [
                bar
                for bar in _stored(app, symbol, timeframe)
                if bar.is_closed and bar.close_time <= decision_time
            ]
            limit = limits[timeframe]
            loaded[timeframe][symbol] = tuple(closed if limit < 1 else closed[-limit:])
    return loaded


def _match_all(app: PaperApp, bars, decision_time: datetime) -> set[str]:
    """Fill the open and the stop before any pipeline call. Return symbols flattened here."""
    names = set(app.broker.open_symbols()) | set(app.broker.pending_symbols())
    fee = app.settings.execution.fee_bps
    slip = app.settings.execution.slippage_bps
    flattened: set[str] = set()
    for symbol in sorted(names):
        bar = _bar_at(bars.get(symbol, ()), decision_time)
        if bar is None:
            continue
        was_open = app.broker.position(symbol) is not None
        matched = match_bar(
            app.broker.position(symbol),
            app.broker.pending_for(symbol),
            bar,
            fee_bps=fee,
            slippage_bps=slip,
            arm_close=app.broker.arm_close(symbol),
        )
        if matched:
            app.broker.apply(matched)
        if app.broker.position(symbol) is None and (
            was_open or any(item.reduce_only for item in matched)
        ):
            flattened.add(symbol)
    return flattened


def _jobs(app: PaperApp, board: dict[str, int], bars, decision_time: datetime, flattened: set[str]):
    def has_bar(symbol: str) -> bool:
        return _bar_at(bars.get(symbol, ()), decision_time) is not None

    open_names = [symbol for symbol in app.broker.open_symbols() if has_bar(symbol)]
    dropped = sorted(symbol for symbol in open_names if symbol not in board)
    ranked = sorted((board[symbol], symbol) for symbol in open_names if symbol in board)
    jobs = [("exit", symbol, False) for symbol in dropped]
    jobs.extend(("exit", symbol, False) for _rank, symbol in ranked)
    used = {symbol for _group, symbol, _flat in jobs}
    entries = sorted(
        (rank, symbol)
        for symbol, rank in board.items()
        if symbol not in used and app.broker.position(symbol) is None and has_bar(symbol)
    )
    jobs.extend(("entry", symbol, symbol in flattened) for _rank, symbol in entries)
    return jobs


def _stale_holds(app: PaperApp, symbols, decision_time: datetime, board: dict[str, int]):
    decisions = []
    for symbol in symbols:
        decisions.append(_hold(app, symbol, decision_time, board.get(symbol), VetoCode.STALE_DATA))
        _log_decision(app, decisions[-1], {})
    return decisions


def _hold(app: PaperApp, symbol: str, decision_time: datetime, rank: int | None, code: VetoCode):
    action = DecisionAction.HOLD.value
    rules = HardRuleResult(
        passed=False,
        vetoes=(Veto(code=code, message=code.value, measured=code.value, threshold=code.value),),
    )
    step = ReasonStep(stage=ReasonStage.DATA, code=code.value, detail=code.value)
    return DecisionRecord(
        symbol=symbol,
        decision_time=decision_time,
        action=action,
        config_hash=app.config_hash,
        engine_version=app.engine_version,
        feature_version=app.feature_version,
        marketdata_version=app.marketdata_version,
        universe_date=universe_date(decision_time, app.settings.universe.refresh_minute),
        created_at=decision_time,
        decision_id=decision_id(
            symbol,
            decision_time,
            action,
            app.config_hash,
            app.engine_version,
            app.feature_version,
            app.marketdata_version,
        ),
        rank=rank,
        hard_rule_json=dump_model(rules),
        reason_chain_json=dump_models((step,)),
        calibrated=False,
    )


def _commit(app: PaperApp, decisions) -> None:
    flush = app.broker.take_flush()
    app.ledger.commit_bar(
        BarCommit(
            decisions=tuple(decisions),
            orders=flush.orders,
            fills=flush.fills,
            positions=flush.positions,
            cash=flush.cash,
        )
    )


def _frames(app: PaperApp, ran, board: dict[str, int], decision_time: datetime) -> None:
    seen: set[str] = set()
    for result, bars in ran:
        symbol = result.decision.symbol
        seen.add(symbol)
        rank = board.get(symbol)
        if app.broker.position(symbol) is None and rank is None:
            _delete_frames(app, symbol)
            continue
        if not result.snapshots:
            continue
        _write_frames(app, result, bars, rank, decision_time)
    for row in app.ledger.repo.load_chart_frames():
        if row.symbol in seen:
            continue
        if app.broker.position(row.symbol) is None and row.symbol not in board:
            _delete_frames(app, row.symbol)


def _write_frames(app: PaperApp, result, bars, rank: int | None, decision_time: datetime) -> None:
    position = app.broker.position(result.decision.symbol)
    tail = app.settings.monitor.bar_tail
    vetoes = () if result.rules is None else tuple(item.code for item in result.rules.vetoes)
    for timeframe in _FRAME_TIMEFRAMES:
        snapshot = result.snapshots.get(timeframe)
        if snapshot is None:
            continue
        series = tuple(bars.get(timeframe, ())[-tail:])
        frame = ChartFrame(
            symbol=result.decision.symbol,
            timeframe=timeframe,
            as_of=snapshot.as_of,
            snapshot_id=snapshot.snapshot_id,
            structure_bias=snapshot.structure_bias,
            bars=series,
            bis=snapshot.bis,
            zhongshus=snapshot.zhongshus,
            signals=snapshot.signals,
            last_action=result.action,
            position=position,
            stop_price=None if position is None else position.stop_price,
            assessment=result.assessment if timeframe is Timeframe.M15 else None,
            veto_codes=vetoes if timeframe is Timeframe.M15 else (),
            universe_rank=rank,
        )
        try:
            app.ledger.repo.upsert_chart_frame(
                ChartFrameRow(
                    symbol=frame.symbol,
                    timeframe=frame.timeframe.value,
                    frame_json=dump_model(frame),
                    updated_at=decision_time,
                )
            )
        except Exception as exc:
            _log_error(app, "chart_frame", frame.symbol, exc)


def _delete_frames(app: PaperApp, symbol: str) -> None:
    try:
        app.ledger.repo.delete_chart_frames(symbol)
    except Exception as exc:
        _log_error(app, "chart_frame", symbol, exc)


def _quality(app: PaperApp, bars) -> DataQuality:
    gaps = _gaps(app.settings)
    return assess_quality(
        bars,
        max_gap_bars=gaps,
        now=app.clock.now(),
        stale_grace_seconds=app.settings.marketdata.stale_grace_seconds,
        backtest=False,
    )


def _instrument(app: PaperApp, symbol: str) -> Instrument:
    found = app.instruments.get(symbol)
    if found is not None:
        return found
    return inferred_instrument(app.settings, symbol, None)


def _view(app: PaperApp, effective, marks) -> AccountView:
    equity = app.broker.cash
    for position in app.broker.open_positions():
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
        positions=tuple(position for position in effective if position.qty != 0),
        open_order_ids=(),
        open_position_count=count,
        gross_notional_quote=quantize(gross),
    )


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


def _marks(bars, decision_time: datetime) -> dict[str, float]:
    marks = {}
    for symbol, series in bars.items():
        bar = _bar_at(series, decision_time)
        if bar is not None:
            marks[symbol] = bar.close
    return marks


def _bar_at(bars, decision_time: datetime):
    for bar in bars:
        if bar.is_closed and bar.close_time == decision_time:
            return bar
    return None


class _Timed:
    def __init__(self, inner, bucket: dict[str, float], label: str) -> None:
        self._inner = inner
        self._bucket = bucket
        self._label = label

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            try:
                return attr(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                self._bucket[self._label] = self._bucket.get(self._label, 0.0) + elapsed

        return wrapped


def _timed(services: PipelineServices, bucket: dict[str, float]) -> PipelineServices:
    log_jev = None if services.log_jev is None else _Timed(services.log_jev, bucket, "jev_ms")
    return PipelineServices(
        engine=_Timed(services.engine, bucket, "chanlun_ms"),
        features=_Timed(services.features, bucket, "features_ms"),
        jev=_Timed(services.jev, bucket, "jev_ms"),
        rules=_Timed(services.rules, bucket, "rules_ms"),
        risk=_Timed(services.risk, bucket, "risk_ms"),
        broker=services.broker,
        rule_params=services.rule_params,
        log_jev=log_jev,
        score_after_preflight=services.score_after_preflight,
        warm=services.warm,
    )


def _log_decision(app: PaperApp, decision: DecisionRecord, bucket: dict[str, float]) -> None:
    try:
        fields = {
            "symbol": decision.symbol,
            "rank": decision.rank,
            "decision_id": decision.decision_id,
            "chanlun_ms": bucket.get("chanlun_ms", 0.0),
            "features_ms": bucket.get("features_ms", 0.0),
            "jev_ms": bucket.get("jev_ms", 0.0),
            "rules_ms": bucket.get("rules_ms", 0.0),
            "risk_ms": bucket.get("risk_ms", 0.0),
        }
        fields.update(_systemone_log(decision.jev_json))
        app.log.info("decision", **fields)
    except Exception:
        return


def _log_error(app: PaperApp, event: str, symbol: str, exc: Exception) -> None:
    try:
        app.log.error(event, symbol=symbol, error=str(exc))
    except Exception:
        return


def _windows(settings) -> dict[Timeframe, int]:
    mapping = {"15m": Timeframe.M15, "1h": Timeframe.H1, "4h": Timeframe.H4}
    return {mapping[key]: value for key, value in settings.marketdata.windows.items()}


def _gaps(settings) -> dict[Timeframe, int]:
    mapping = {"15m": Timeframe.M15, "1h": Timeframe.H1, "4h": Timeframe.H4}
    return {mapping[key]: value for key, value in settings.marketdata.max_gap_bars.items()}


def _floor_15(now: datetime) -> datetime:
    utc = now.astimezone(_UTC).replace(second=0, microsecond=0)
    slot = (utc.minute // 15) * 15
    return utc.replace(minute=slot)


def _months(start: datetime, end: datetime):
    year, month = start.year, start.month
    last = (end.year, end.month)
    while (year, month) <= last:
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def _symbols_in_files(root: Path, venue: str, start: date, end: date) -> list[str]:
    folder = root / "data" / "universe" / venue
    found: list[str] = []
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        for member in load_universe(path):
            if member.symbol not in found:
                found.append(member.symbol)
    return found


def _vision_compacts(root: Path) -> list[str]:
    names: set[str] = set()
    for folder in (
        root / "data" / "futures" / "um" / "monthly" / "klines",
        root / "data" / "futures" / "um" / "daily" / "klines",
    ):
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if child.is_dir():
                names.add(child.name)
    return sorted(names)


def _copy_funding(vision_root: Path, data_root: Path, compact: str, year: int, month: int) -> None:
    source = funding_month_csv(vision_root, compact, year, month)
    if not source.is_file():
        return
    target = funding_month_csv(data_root, compact, year, month)
    if source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def _codes(payload: str | None) -> set[str]:
    if not payload:
        return set()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    vetoes = parsed.get("vetoes", ()) if isinstance(parsed, dict) else parsed
    found: set[str] = set()
    if not isinstance(vetoes, list):
        return found
    for item in vetoes:
        if isinstance(item, dict) and "code" in item:
            found.add(str(item["code"]))
        elif isinstance(item, str):
            found.add(item)
    return found


_SYSTEMONE_CODES = frozenset(
    {
        "JEV_TIMEOUT",
        "JEV_HTTP_ERROR",
        "JEV_MALFORMED",
        "JEV_MODEL_MISMATCH",
        "JEV_CACHE_MISS",
        "JEV_NO_KEY",
    }
)


def _reason_codes(payload: str | None) -> set[str]:
    if not payload:
        return set()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, list):
        return set()
    found: set[str] = set()
    for item in parsed:
        if isinstance(item, dict) and "code" in item:
            found.add(str(item["code"]))
    return found


def _systemone_log(payload: str | None) -> dict[str, object]:
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    fields: dict[str, object] = {}
    status = parsed.get("systemone_status")
    if status is not None:
        fields["systemone_status"] = status
    choice = parsed.get("quality_choice")
    if choice is not None:
        fields["quality_choice"] = choice
    elapsed = parsed.get("systemone_ms")
    if elapsed is not None:
        fields["systemone_ms"] = elapsed
    return fields


def _kind(codes: set[str], reasons: set[str] | None = None) -> str:
    if codes == {VetoCode.PIPELINE_TIMEOUT.value}:
        return "pipeline_timeout"
    if VetoCode.STALE_DATA.value in codes:
        return "stale_data"
    if reasons and reasons & _SYSTEMONE_CODES:
        return "systemone"
    return "strategy"


def _kline_text(root: Path, symbol: str) -> str | None:
    compact = symbol.replace("/", "")
    for interval in ("15m", "1h", "4h"):
        folder = root / "data" / "futures" / "um" / "monthly" / "klines" / compact / interval
        if not folder.is_dir():
            continue
        files = sorted(folder.glob("*.csv"))
        if files:
            return files[0].read_text(encoding="utf-8")
        found = kline_files_for_month(root, compact, interval, 2024, 1)
        if found:
            return found[0].read_text(encoding="utf-8")
    return None
