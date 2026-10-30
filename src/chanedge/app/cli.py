"""chanedge download, universe, backtest, and paper. Live mode exits before any client."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.app.bind import risk_params
from chanedge.app.compose import SystemClock, build_exchange, compose
from chanedge.app.jev_warm import run_jev_warm, summarize_decisions
from chanedge.app.paper_loop import (
    FileUniverse,
    backtest_quality,
    ParquetBars,
    VisionFunding,
    download_history,
    ensure_daily_file,
    inferred_instrument,
    reconcile_report,
    reconstruct_history,
    run_paper_bar,
    serve,
    startup_target,
)
from chanedge.app.paper_loop import _kline_text, _symbols_in_files, _windows
from chanedge.backtest.loop import checkpoint_end, run_backtest
from chanedge.config.load import load_settings
from chanedge.domain.risk import AccountView
from chanedge.execution.paper import InMemoryLedger, PaperBroker
from chanedge.typesafe.cache import cache_digest
from chanedge.journal.book import ReportJournal
from chanedge.marketdata.universe import universe_date
from chanedge.risk.size import RiskManager

_UTC = timezone.utc


def main(argv: list[str] | None = None, *, environ=None, exchange=None, clock=None, sleep=None) -> int:
    parser = _parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        settings = load_settings(args.config, args.overlay)
        if settings.runtime.mode == "live":
            print("live mode is not implemented", file=sys.stderr)
            return 1
        if args.command == "monitor":
            return run_monitor(settings, Path(args.root))
        if args.command != "paper" and settings.universe.mode == "pin":
            print("pin does not run download, universe, backtest, or jev-warm", file=sys.stderr)
            return 1
        if args.command == "jev-warm" and not settings.systemone.enabled:
            print("systemone.enabled is false", file=sys.stderr)
            return 1
        if settings.systemone.enabled != (settings.jev.version == "typesafe-v1"):
            print("jev.version does not match systemone.enabled", file=sys.stderr)
            return 1
        network = args.command in {"paper", "jev-warm"}
        api_key = None
        attempts = 1
        if settings.systemone.enabled and network:
            source = os.environ if environ is None else environ
            api_key = source.get("TYPESAFE_API_KEY") or ""
            if not api_key:
                print("TYPESAFE_API_KEY is required", file=sys.stderr)
                return 1
            if args.command == "jev-warm":
                attempts = 3
        app = compose(
            settings,
            root=Path(args.root),
            exchange=exchange if exchange is not None else build_exchange(),
            clock=clock if clock is not None else SystemClock(),
            environ=environ,
            network=network,
            api_key=api_key,
            systemone_attempts=attempts,
            markets_required=args.command == "paper",
        )
        vision = Path(args.vision) if args.vision else app.root
        resume = Path(args.resume) if getattr(args, "resume", None) else None
        if resume is not None and not args.end:
            end = checkpoint_end(resume)
        else:
            end = _end(args.end, app.clock.now())
        if args.command == "download":
            download_history(app, vision_root=vision, end=end)
        elif args.command == "universe":
            if args.reconstruct:
                reconstruct_history(app, vision_root=vision, end=end)
            else:
                day = universe_date(app.clock.now(), settings.universe.refresh_minute)
                ensure_daily_file(app, day)
        elif args.command == "backtest":
            if settings.safety.kill_switch:
                print(
                    "warning: safety.kill_switch is true, so every entry is vetoed and the report "
                    "will have no trades. Pass --overlay config/paper.yaml to backtest entries.",
                    file=sys.stderr,
                )
            outcome = run_backtest_command(app, vision_root=vision, end=end, resume=resume)
            if outcome.incomplete:
                return 3
        elif args.command == "jev-warm":
            code = run_jev_warm(app, vision_root=vision, end=end)
            if code:
                return code
        elif args.command == "paper":
            waiter = time.sleep if sleep is None else sleep
            if args.once:
                target = startup_target(app.clock.now(), settings.marketdata.close_wait_seconds)
                delay = (target - app.clock.now()).total_seconds()
                if delay > 0:
                    waiter(delay)
                run_paper_bar(app, decision_time=target, sleep=waiter)
            else:
                serve(app, sleep=waiter)
        else:
            print(f"unknown command {args.command}", file=sys.stderr)
            return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def run_monitor(settings, root: Path, *, call=None) -> int:
    """Start the read-only monitor as its own process. app does not import its drawing code."""
    import subprocess

    host = settings.monitor.host
    if host != "127.0.0.1":
        print(f"monitor.host must be 127.0.0.1, not {host}", file=sys.stderr)
        return 1
    command = [
        sys.executable,
        "-m",
        "chanedge.monitor",
        "--db",
        str(root / settings.journal.sqlite_path),
        "--host",
        host,
        "--port",
        str(settings.monitor.port),
    ]
    return (call or subprocess.call)(command)


def run_backtest_command(app, *, vision_root: Path, end: date, resume: Path | None = None):
    """Inject the PR-11 loop. This path does not sleep and does not read the paper book."""
    settings = app.settings
    history = date.fromisoformat(settings.marketdata.history_start)
    symbols = tuple(_symbols_in_files(app.root, settings.runtime.venue, history, end))
    instruments = {}
    for symbol in symbols:
        text = _kline_text(vision_root, symbol)
        instruments[symbol] = app.instruments.get(symbol) or inferred_instrument(settings, symbol, text)
    broker = PaperBroker(
        InMemoryLedger(),
        initial_equity=settings.risk.initial_equity_quote,
        kill_switch=settings.safety.kill_switch,
        order_type=settings.execution.order_type,
    )
    report = ReportJournal(app.root / "data" / "reports", paper_path=app.ledger.repo.path)
    channel = settings.jev.channels.structure
    weights = settings.jev.weights.model_dump(mode="python")
    halt = _cache_miss_halt if settings.systemone.enabled else None
    result = run_backtest(
        pipeline=app.pipeline,
        services=_services_for_broker(app, broker),
        broker=broker,
        clock=app.clock,
        bar_source=ParquetBars(app.store, settings.runtime.venue),
        universe_source=FileUniverse(app.root, settings.runtime.venue),
        report_sink=report,
        instruments=instruments,
        symbols=symbols,
        history_start=history,
        history_end=end,
        refresh_minute=settings.universe.refresh_minute,
        fee_bps=settings.execution.fee_bps,
        slippage_bps=settings.execution.slippage_bps,
        initial_equity=settings.risk.initial_equity_quote,
        safety=app.safety,
        config_hash=app.config_hash,
        engine_version=app.engine_version,
        feature_version=app.feature_version,
        marketdata_version=app.marketdata_version,
        shadow_sizer=_shadow_sizer(settings),
        overlap_peak=channel.overlap_peak,
        overlap_width=channel.overlap_width,
        overlap_penalty_above=channel.overlap_penalty_above,
        jev_weights=weights,
        funding_source=VisionFunding(vision_root),
        quality=backtest_quality(settings),
        windows=_windows(settings),
        full_log=False,
        halt_on=halt,
        resume=resume,
    )
    if settings.systemone.enabled:
        _write_systemone(result, app.systemone_reader)
    reconcile_report(app.ledger.repo.path, result.directory, result.decisions)
    return result


def _cache_miss_halt(result) -> bool:
    return any(step.code == "JEV_CACHE_MISS" for step in result.reason_steps)


def _write_systemone(result, reader) -> None:
    lookups = [] if reader is None else list(reader.lookups)
    payload = summarize_decisions(result.decisions)
    payload["cache_digest"] = cache_digest(lookups)
    payload["incomplete"] = bool(result.incomplete)
    path = result.directory / "systemone.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _services_for_broker(app, broker):
    services = app.services
    return type(services)(
        engine=services.engine,
        features=services.features,
        jev=services.jev,
        rules=services.rules,
        risk=services.risk,
        broker=broker,
        rule_params=services.rule_params,
        log_jev=services.log_jev,
        score_after_preflight=services.score_after_preflight,
        warm=services.warm,
    )


def _shadow_sizer(settings):
    risk = RiskManager(risk_params(settings))

    def size(context, features, assessment, rules):
        account = AccountView(
            equity_quote=settings.risk.initial_equity_quote,
            open_position_count=0,
            gross_notional_quote=Decimal("0"),
        )
        return risk.plan_entry(context, features, assessment, rules, account)

    return size


def _end(text: str | None, now: datetime) -> date:
    if text:
        return date.fromisoformat(text)
    return now.astimezone(_UTC).date()


def _parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", default="config/default.yaml")
    parent.add_argument("--overlay", default=None)
    parent.add_argument("--root", default=".")
    parent.add_argument("--vision", default=None)
    parent.add_argument("--end", default=None)
    parser = argparse.ArgumentParser(prog="chanedge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download", parents=[parent])
    universe = commands.add_parser("universe", parents=[parent])
    universe.add_argument("--reconstruct", action="store_true")
    backtest = commands.add_parser("backtest", parents=[parent])
    backtest.add_argument("--resume", default=None, help="report directory of an interrupted run")
    paper = commands.add_parser("paper", parents=[parent])
    paper.add_argument("--once", action="store_true")
    commands.add_parser("jev-warm", parents=[parent])
    commands.add_parser("monitor", parents=[parent])
    return parser
