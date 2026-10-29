"""Paper composition, one bar, and the four commands. Factories stay in this module."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from chanedge.app.bind import feature_params, jev_params, risk_params, rule_params
from chanedge.app.cli import main, run_backtest_command
from chanedge.app.compose import build_exchange, compose, drop_secrets
from chanedge.app.paper_loop import (
    ensure_daily_file,
    reconcile_report,
    reconstruct_history,
    run_paper_bar,
    startup_target,
)
from chanedge.app.pipeline import PipelineServices, run_pipeline
from chanedge.chanlun.engine import window_hash
from chanedge.config.load import load_settings
from chanedge.config.model import PinSymbol
from chanedge.domain.bars import Bar, Instrument, timeframe_duration
from chanedge.domain.chanlun import ChanSignal, ChanSnapshot
from chanedge.domain.decision import HardRuleResult, Veto
from chanedge.domain.enums import (
    DecisionAction,
    Direction,
    InstrumentSource,
    ProductType,
    RuntimeMode,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
    VetoCode,
)
from chanedge.domain.ids import decision_id
from chanedge.domain.records import BarCommit, DecisionRecord
from chanedge.domain.risk import InvalidationSpec, PositionState, RiskPlan, SafetyState, TrailRule
from chanedge.domain.serialize import dump_model
from chanedge.features.builder import FeatureBuilder
from chanedge.jev.model import JevModel
from chanedge.journal.book import JournalLedger
from chanedge.journal.repository import ChartFrameRow
from chanedge.marketdata.parquet_store import ParquetBarStore
from chanedge.marketdata.universe import load_universe, universe_date, universe_path, write_universe_file
from chanedge.marketdata.universe import UniverseMember
from chanedge.marketdata.vision import funding_month_csv, monthly_kline_csv, store_bar
from chanedge.risk.size import RiskManager
from chanedge.rules.gate import RuleGate

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
OLD = datetime(2023, 12, 31, 23, 45, tzinfo=UTC)
H1_OPEN = datetime(2023, 12, 31, 23, tzinfo=UTC)
H4_OPEN = datetime(2023, 12, 31, 20, tzinfo=UTC)
DAY = date(2024, 1, 1)
YESTERDAY = date(2023, 12, 31)


class _Boom:
    def __getitem__(self, key):
        raise AssertionError(key)

    def __contains__(self, key):
        raise AssertionError(key)

    def get(self, key, default=None):
        raise AssertionError(key)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class _Exchange:
    def __init__(self) -> None:
        self.orders = 0
        self.tickers = 0

    def fetch_tickers(self):
        self.tickers += 1
        raise AssertionError("tickers")

    def create_order(self, *args, **kwargs):
        self.orders += 1
        raise AssertionError("create_order")

    def fetch_ohlcv(self, *args, **kwargs):
        raise AssertionError("ohlcv")


class _Explode:
    def __getattr__(self, name):
        raise AssertionError(name)


class ScriptedEngine:
    def __init__(self, signals: dict[tuple[str, datetime], ChanSignal]) -> None:
        self.signals = signals
        self.calls: list[tuple[str, Timeframe, datetime]] = []

    def compute(self, bars, *, timeframe: Timeframe, as_of: datetime) -> ChanSnapshot:
        symbol = bars[0].symbol
        self.calls.append((symbol, timeframe, as_of))
        bias = StructureBias.UP if timeframe is Timeframe.H4 else StructureBias.NEUTRAL
        found = ()
        if timeframe is Timeframe.M15:
            signal = self.signals.get((symbol, as_of))
            if signal is not None:
                found = (signal,)
        return ChanSnapshot(
            snapshot_id=f"cs-{symbol}-{timeframe.value}",
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            config_hash="cfg",
            engine_version="eng",
            bar_window_hash=window_hash(bars),
            bars_start=bars[0].open_time,
            bars_end=bars[-1].close_time,
            bar_count=len(bars),
            fenxings=(),
            bis=(),
            segments=(),
            zhongshus=(),
            signals=found,
            structure_bias=bias,
        )


class SpyRisk:
    def __init__(self, inner: RiskManager) -> None:
        self.inner = inner
        self.plans = 0
        self.reviews = 0
        self.equities: list[Decimal] = []

    def plan_entry(self, context, features, assessment, rules, account):
        self.plans += 1
        self.equities.append(account.equity_quote)
        return self.inner.plan_entry(context, features, assessment, rules, account)

    def review_open(self, context, position):
        self.reviews += 1
        return self.inner.review_open(context, position)


def _settings(symbols: tuple[str, ...] = ("BTC/USDT",), *, kill_switch: bool = False):
    base = load_settings(ROOT / "config" / "default.yaml")
    pins = [PinSymbol(symbol=symbol, venue_symbol=f"{symbol}:USDT") for symbol in symbols]
    return base.model_copy(
        update={
            "universe": base.universe.model_copy(update={"mode": "pin", "pin": pins}),
            "safety": base.safety.model_copy(update={"kill_switch": kill_switch}),
        }
    )


def _quoted_settings():
    base = load_settings(ROOT / "config" / "default.yaml")
    return base.model_copy(
        update={"safety": base.safety.model_copy(update={"kill_switch": False})}
    )


def _app(tmp_path: Path, settings=None, exchange=None, clock=None):
    return compose(
        settings if settings is not None else _settings(),
        root=tmp_path,
        exchange=exchange if exchange is not None else _Exchange(),
        clock=clock if clock is not None else _Clock(T15),
        environ=_Boom(),
    )


def _arm(app, engine, risk=None) -> SpyRisk | None:
    feature = feature_params(app.settings)
    feature = feature.model_copy(
        update={"session": feature.session.model_copy(update={"hard_skip_buckets": ()})}
    )
    gate = rule_params(app.settings).model_copy(
        update={
            "window_15m": 1,
            "window_1h": 1,
            "window_4h": 1,
            "atr_pct_min": 0.0,
            "atr_pct_max": 1.0,
            "hard_skip_buckets": (),
        }
    )
    inner = RiskManager(risk_params(app.settings))
    spy = risk
    app.services = PipelineServices(
        engine=engine,
        features=FeatureBuilder(feature),
        jev=JevModel(jev_params(app.settings).model_copy(update={"enter_threshold": 0.0})),
        rules=RuleGate(gate),
        risk=spy if spy is not None else inner,
        broker=app.broker,
        rule_params=gate,
    )
    app.safety = SafetyState(kill_switch=False, mode=RuntimeMode.PAPER)
    app.broker.kill_switch = False
    return spy


def _candle(
    symbol: str,
    timeframe: Timeframe,
    open_time: datetime,
    *,
    low: float = 99.0,
    high: float = 101.0,
) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe_duration(timeframe),
        open=100.0,
        high=high,
        low=low,
        close=100.0,
        volume=1.0,
        is_closed=True,
        source="binanceusdm",
    )


def _pack(symbol: str) -> list[Bar]:
    return [
        _candle(symbol, Timeframe.H1, H1_OPEN),
        _candle(symbol, Timeframe.H4, H4_OPEN),
        _candle(symbol, Timeframe.M15, T0, low=99.5),
    ]


def _store(app, bars: list[Bar]) -> None:
    grouped: dict[tuple[str, Timeframe], list] = {}
    for bar in bars:
        grouped.setdefault((bar.symbol, bar.timeframe), []).append(store_bar(bar))
    for (symbol, timeframe), stored in grouped.items():
        app.store.write_closed(app.settings.runtime.venue, symbol, timeframe, stored)


def _instrument(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        venue="binanceusdm",
        venue_symbol=f"{symbol}:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=Decimal("0.01"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        margin_asset="USDT",
        leverage_max=20,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _signal(symbol: str, when: datetime = T15) -> ChanSignal:
    return ChanSignal(
        id=f"sig-{symbol}",
        timeframe=Timeframe.M15,
        type=SignalType.SECOND_BUY,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=100.0,
        direction=Direction.UP,
        defending_fx_id="fx-def",
        defending_price=99.0,
        related_bi_id="bi-1",
        bar_open_time=when - timedelta(minutes=15),
    )


def _held(symbol: str) -> PositionState:
    opened = datetime(2023, 12, 31, tzinfo=UTC)
    plan = RiskPlan(
        symbol=symbol,
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=Decimal("1"),
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=100.0,
        atr=0.0,
        structure_stop_price=90.0,
        stop_buffer=0.15,
        defending_fx_id="fx-def",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL, SignalType.THIRD_SELL),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=90.0,
            defending_fx_id="fx-def",
            effective_after=opened,
        ),
        realized_risk_fraction=Decimal("0.005"),
        cost_r=Decimal("0.10"),
        binding_constraint="risk_fraction",
        trail=TrailRule(
            kind=TrailKind.STRUCTURE_FENXING,
            arm_r=1.0,
            breakeven_price=100.0,
            buffer=0.15,
        ),
    )
    return PositionState(
        symbol=symbol,
        qty=Decimal("1"),
        avg_price=100.0,
        stop_price=90.0,
        plan=plan,
        entry_decision_id=f"dec-{symbol}",
        entry_decision_time=opened,
        entry_bar_open_time=opened,
    )


def _member(symbol: str, rank: int, source: str = "daily_kline", fallback: date | None = None) -> UniverseMember:
    opened = datetime(2023, 12, 31, tzinfo=UTC)
    return UniverseMember(
        rank=rank,
        symbol=symbol,
        venue_symbol=f"{symbol}:USDT",
        quote_volume=Decimal("1000"),
        as_of=T0,
        source=source,
        bar_open_time=opened,
        bar_close_time=opened + timedelta(days=1),
        fallback_from=fallback,
    )


def _ohlcv(open_time: datetime) -> list[object]:
    return [int(open_time.timestamp() * 1000), 100.0, 101.0, 99.5, 100.0, 1.0]


def _kline_row(open_time: datetime, quote: str = "12.5") -> str:
    millis = int(open_time.timestamp() * 1000)
    return f"{millis},100,100,100,100,1,{millis},{quote},3,0,0,0\n"


def _codes(payload: str | None) -> list[str]:
    parsed = json.loads(payload or "{}")
    return [item["code"] for item in parsed.get("vetoes", ())]


def _record(symbol: str, code: VetoCode | None, *, when: datetime = T15) -> DecisionRecord:
    action = DecisionAction.HOLD.value
    rules = None
    if code is not None:
        rules = dump_model(
            HardRuleResult(
                passed=False,
                vetoes=(Veto(code=code, message=code.value, measured="1", threshold="0"),),
            )
        )
    return DecisionRecord(
        symbol=symbol,
        decision_time=when,
        action=action,
        config_hash="cfg",
        engine_version="eng",
        feature_version="feat",
        marketdata_version="md",
        universe_date=DAY,
        created_at=when,
        decision_id=decision_id(symbol, when, action, "cfg", "eng", "feat", "md"),
        hard_rule_json=rules,
        calibrated=False,
    )


def test_paper_compose_does_not_read_keys_or_create_orders(tmp_path: Path) -> None:
    exchange = _Exchange()
    app = _app(tmp_path, exchange=exchange)
    assert exchange.orders == 0
    assert exchange.tickers == 0
    assert app.safety.mode is RuntimeMode.PAPER
    assert app.ledger.repo.schema_version == 1
    assert app.ledger.repo.synchronous() != 0


def test_live_mode_fails_before_keys_or_a_client(tmp_path: Path, capsys) -> None:
    base = load_settings(ROOT / "config" / "default.yaml")
    live = base.model_copy(update={"runtime": base.runtime.model_copy(update={"mode": "live"})})
    with pytest.raises(RuntimeError, match="live mode is not implemented"):
        compose(live, root=tmp_path, exchange=_Explode(), clock=_Clock(T15), environ=_Boom())
    overlay = tmp_path / "live.yaml"
    overlay.write_text("runtime:\n  mode: live\n", encoding="utf-8")
    code = main(
        [
            "paper",
            "--once",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--overlay",
            str(overlay),
            "--root",
            str(tmp_path / "run"),
        ],
        environ=_Boom(),
        exchange=_Explode(),
        clock=_Clock(T15),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep")),
    )
    assert code == 1
    assert "live mode is not implemented" in capsys.readouterr().err


def test_build_exchange_omits_api_credentials(monkeypatch) -> None:
    seen: dict[str, dict] = {}

    class Fake:
        def __init__(self, config) -> None:
            seen["config"] = config

    import ccxt

    monkeypatch.setattr(ccxt, "binanceusdm", Fake)
    build_exchange()
    config = seen["config"]
    assert "apiKey" not in config
    assert "secret" not in config
    assert "CHANEDGE_API_KEY" not in config
    assert "CHANEDGE_API_SECRET" not in config


def test_drop_secrets_removes_the_paper_key_names() -> None:
    event = {
        "event": "decision",
        "CHANEDGE_API_KEY": "k",
        "CHANEDGE_API_SECRET": "s",
        "TYPESAFE_API_KEY": "t",
        "symbol": "BTC/USDT",
    }
    cleaned = drop_secrets(None, "info", event)
    assert "CHANEDGE_API_KEY" not in cleaned
    assert "CHANEDGE_API_SECRET" not in cleaned
    assert "TYPESAFE_API_KEY" not in cleaned
    assert cleaned["symbol"] == "BTC/USDT"


def test_app_sources_do_not_bind_the_monitor_or_send_orders() -> None:
    root = ROOT / "src" / "chanedge" / "app"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "create_order" not in text
        assert "8765" not in text
        assert "telegram" not in text.lower()


def test_decision_log_carries_symbol_rank_and_stage_times(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.listed = lambda: set()
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    _store(app, _pack("BTC/USDT"))
    _arm(app, ScriptedEngine({("BTC/USDT", T15): _signal("BTC/USDT")}))
    with capture_logs() as logs:
        result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.started is True
    found = [item for item in logs if item.get("event") == "decision"]
    assert found
    row = found[0]
    assert row["symbol"] == "BTC/USDT"
    assert row["rank"] == 1
    for key in ("chanlun_ms", "features_ms", "jev_ms", "rules_ms", "risk_ms"):
        assert key in row


def test_close_wait_retries_until_the_expected_open(tmp_path: Path) -> None:
    exchange = _Exchange()
    calls = {"m15": 0}

    def fetch_ohlcv(_symbol, timeframe, _since=None, _limit=None):
        if timeframe == "15m":
            calls["m15"] += 1
            rows = [_ohlcv(OLD)]
            if calls["m15"] > 1:
                rows.append(_ohlcv(T0))
            return rows
        if timeframe == "1h":
            return [_ohlcv(H1_OPEN)]
        if timeframe == "4h":
            return [_ohlcv(H4_OPEN)]
        raise AssertionError(timeframe)

    exchange.fetch_ohlcv = fetch_ohlcv  # type: ignore[method-assign]
    app = _app(tmp_path, exchange=exchange)
    app.listed = lambda: {"BTC/USDT"}
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    slept: list[float] = []
    result = run_paper_bar(app, decision_time=T15, sleep=slept.append)
    assert slept == [3, 3]
    assert calls["m15"] == 2
    assert exchange.orders == 0
    assert exchange.tickers == 0
    assert result.started is True
    assert result.stale is False
    latest = app.store.last_open_time("binanceusdm", "BTC/USDT", Timeframe.M15)
    assert latest == T0


def test_stale_give_up_does_not_call_the_pipeline(tmp_path: Path) -> None:
    exchange = _Exchange()

    def fetch_ohlcv(_symbol, timeframe, _since=None, _limit=None):
        if timeframe == "15m":
            return [_ohlcv(OLD)]
        return []

    exchange.fetch_ohlcv = fetch_ohlcv  # type: ignore[method-assign]
    clock = _Clock(T15 + timedelta(seconds=91))
    app = _app(tmp_path, exchange=exchange, clock=clock)
    app.listed = lambda: {"BTC/USDT"}
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    calls: list[str] = []

    def pipeline(_request, _services):
        calls.append("run")
        raise AssertionError("pipeline")

    app.pipeline = pipeline
    slept: list[float] = []
    result = run_paper_bar(app, decision_time=T15, sleep=slept.append)
    assert calls == []
    assert slept == [3]
    assert result.started is True
    assert result.stale is True
    assert len(result.decisions) == 1
    assert _codes(result.decisions[0].hard_rule_json) == ["stale_data"]
    assert exchange.orders == 0


def test_backtest_command_does_not_sleep(tmp_path: Path, monkeypatch) -> None:
    def fail(seconds):
        raise AssertionError(f"slept {seconds}")

    monkeypatch.setattr("chanedge.backtest.loop.time.sleep", fail)
    monkeypatch.setattr("chanedge.app.paper_loop.time.sleep", fail)
    monkeypatch.setattr("chanedge.app.cli.time.sleep", fail)
    app = _app(tmp_path, settings=_quoted_settings())
    result = run_backtest_command(app, vision_root=tmp_path / "vision", end=date(2024, 1, 2))
    assert result.chart_frames == 0
    assert result.synchronous == 0


def test_existing_universe_file_is_not_overwritten(tmp_path: Path, capsys) -> None:
    exchange = _Exchange()
    app = _app(tmp_path, settings=_quoted_settings(), exchange=exchange)
    path = universe_path(tmp_path, "binanceusdm", DAY)
    write_universe_file(path, (_member("BTC/USDT", 1, source="reconstructed", fallback=YESTERDAY),))
    before = path.read_bytes()
    assert ensure_daily_file(app, DAY) is True
    assert path.read_bytes() == before
    assert exchange.tickers == 0
    clock = _Clock(datetime(2024, 1, 1, 12, tzinfo=UTC))
    code = main(
        [
            "universe",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--root",
            str(tmp_path),
        ],
        exchange=exchange,
        clock=clock,
        environ=_Boom(),
    )
    assert code == 0
    assert path.read_bytes() == before
    assert exchange.tickers == 0
    assert capsys.readouterr().err == ""


def test_daily_failure_copies_yesterday_without_tickers(tmp_path: Path) -> None:
    exchange = _Exchange()
    app = _app(tmp_path, settings=_quoted_settings(), exchange=exchange)
    previous = universe_path(tmp_path, "binanceusdm", YESTERDAY)
    write_universe_file(previous, (_member("BTC/USDT", 1, source="daily_kline"),))
    assert ensure_daily_file(app, DAY) is True
    copied = load_universe(universe_path(tmp_path, "binanceusdm", DAY))
    assert copied[0].fallback_from == YESTERDAY
    assert copied[0].source == "daily_kline"
    assert copied[0].symbol == "BTC/USDT"
    assert exchange.tickers == 0
    assert exchange.orders == 0


def test_no_file_and_no_position_does_not_start(tmp_path: Path) -> None:
    exchange = _Exchange()
    app = _app(tmp_path, settings=_quoted_settings(), exchange=exchange)
    calls: list[str] = []
    app.pipeline = lambda *_args: calls.append("run")
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.started is False
    assert result.decisions == ()
    assert calls == []
    assert not universe_path(tmp_path, "binanceusdm", DAY).exists()
    assert exchange.tickers == 0


def test_positions_without_a_file_still_run_the_exit_group(tmp_path: Path) -> None:
    app = _app(tmp_path, settings=_quoted_settings())
    app.broker.seed(_held("BTC/USDT"))
    app.ledger.commit(app.broker.take_flush())
    app.listed = lambda: set()
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    _store(app, _pack("BTC/USDT"))
    spy = SpyRisk(RiskManager(risk_params(app.settings)))
    _arm(app, ScriptedEngine({}), spy)
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.started is True
    assert spy.reviews >= 1
    assert spy.plans == 0
    assert result.decisions[0].rank is None
    assert result.decisions[0].action != DecisionAction.ENTER_LONG.value
    assert not universe_path(tmp_path, "binanceusdm", DAY).exists()


def test_pipeline_timeout_keeps_the_order_already_produced(tmp_path: Path) -> None:
    clock = _Clock(T15)
    app = _app(tmp_path, settings=_settings(("BTC/USDT", "ETH/USDT")), clock=clock)
    app.listed = lambda: set()
    for symbol in ("BTC/USDT", "ETH/USDT"):
        app.instruments[symbol] = _instrument(symbol)
        _store(app, _pack(symbol))
    calls: list[str] = []

    def pipeline(request, services):
        calls.append(request.symbol)
        result = run_pipeline(request, services)
        clock.now_value = clock.now_value + timedelta(seconds=61)
        return result

    app.pipeline = pipeline
    _arm(app, ScriptedEngine({("BTC/USDT", T15): _signal("BTC/USDT")}))
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert calls == ["BTC/USDT"]
    by_symbol = {item.symbol: item for item in result.decisions}
    assert by_symbol["BTC/USDT"].action == DecisionAction.ENTER_LONG.value
    assert _codes(by_symbol["ETH/USDT"].hard_rule_json) == ["pipeline_timeout"]
    pending = app.ledger.repo.load_pending_orders()
    assert [order.symbol for order in pending] == ["BTC/USDT"]


def test_chart_frames_follow_the_board_and_a_write_failure_keeps_the_order(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.listed = lambda: set()
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    _store(app, _pack("BTC/USDT"))
    for timeframe in ("15m", "1h", "4h"):
        app.ledger.repo.upsert_chart_frame(
            ChartFrameRow("ETH/USDT", timeframe, '{"last_action":"HOLD"}', T15)
        )
    _arm(app, ScriptedEngine({("BTC/USDT", T15): _signal("BTC/USDT")}))
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    frames = app.ledger.repo.load_chart_frames()
    assert {row.symbol for row in frames} == {"BTC/USDT"}
    assert {row.timeframe for row in frames} == {"15m", "1h", "4h"}
    for row in frames:
        payload = json.loads(row.frame_json)
        assert payload["last_action"] == DecisionAction.ENTER_LONG.value
    assert result.decisions[0].action == DecisionAction.ENTER_LONG.value


def test_chart_write_failure_does_not_roll_back_the_order(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.listed = lambda: set()
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    _store(app, _pack("BTC/USDT"))
    _arm(app, ScriptedEngine({("BTC/USDT", T15): _signal("BTC/USDT")}))

    def fail(_row):
        raise RuntimeError("chart down")

    app.ledger.repo.upsert_chart_frame = fail  # type: ignore[method-assign]
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.started is True
    assert result.decisions[0].action == DecisionAction.ENTER_LONG.value
    pending = app.ledger.repo.load_pending_orders()
    assert [order.symbol for order in pending] == ["BTC/USDT"]


def test_reconcile_splits_timeout_and_stale_from_strategy_diffs(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "chanedge.sqlite"
    assert reconcile_report(missing, tmp_path / "no-report", ()) is None
    assert not (tmp_path / "no-report" / "reconcile.json").exists()
    ledger = JournalLedger(tmp_path / "data" / "chanedge.sqlite")
    shared = _record("BOTH/USDT", None)
    paper_rows = (
        _record("TIME/USDT", VetoCode.PIPELINE_TIMEOUT),
        _record("STALE/USDT", VetoCode.STALE_DATA),
        _record("PAPER/USDT", VetoCode.NO_CANDIDATE),
        shared,
    )
    ledger.commit_bar(
        BarCommit(decisions=paper_rows, orders=(), fills=(), positions=(), cash=Decimal("10000"))
    )
    backtest_rows = (
        _record("BACK/USDT", VetoCode.NO_CANDIDATE),
        _record("LATE/USDT", VetoCode.PIPELINE_TIMEOUT, when=T15 + timedelta(minutes=15)),
        shared,
    )
    directory = tmp_path / "reports" / "run"
    path = reconcile_report(ledger.repo.path, directory, backtest_rows)
    assert path == directory / "reconcile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["paper_only"] == [paper_rows[2].decision_id]
    assert payload["backtest_only"] == [backtest_rows[0].decision_id]
    assert set(payload["pipeline_timeout"]) == {paper_rows[0].decision_id, backtest_rows[1].decision_id}
    assert payload["stale_data"] == [paper_rows[1].decision_id]
    assert shared.decision_id not in payload["paper_only"]
    assert shared.decision_id not in payload["backtest_only"]
    assert shared.decision_id not in payload["pipeline_timeout"]
    assert shared.decision_id not in payload["stale_data"]


def test_download_reads_local_vision_including_delisted_names(tmp_path: Path) -> None:
    exchange = _Exchange()
    app = _app(tmp_path, settings=_quoted_settings(), exchange=exchange)
    write_universe_file(
        universe_path(tmp_path, "binanceusdm", DAY),
        (_member("BTC/USDT", 1), _member("OLD/USDT", 2)),
    )
    vision = tmp_path / "vision"
    moment = T0
    for symbol in ("BTCUSDT", "OLDUSDT"):
        for interval in ("15m", "1h", "4h"):
            path = monthly_kline_csv(vision, symbol, interval, 2024, 1)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_kline_row(moment), encoding="utf-8")
        funding = funding_month_csv(vision, symbol, 2024, 1)
        funding.parent.mkdir(parents=True, exist_ok=True)
        funding.write_text("calc_time,last_funding_rate\n1704067200000,0.0001\n", encoding="utf-8")
    code = main(
        [
            "download",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--root",
            str(tmp_path),
            "--vision",
            str(vision),
            "--end",
            "2024-01-02",
        ],
        exchange=exchange,
        clock=_Clock(T15),
        environ=_Boom(),
    )
    assert code == 0
    for symbol in ("BTC/USDT", "OLD/USDT"):
        assert app.store.read("binanceusdm", symbol, Timeframe.M15)
    copied = funding_month_csv(tmp_path, "OLDUSDT", 2024, 1)
    assert copied.is_file()
    assert exchange.tickers == 0
    assert exchange.orders == 0


def test_reconstruct_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    base = load_settings(ROOT / "config" / "default.yaml")
    settings = base.model_copy(
        update={"marketdata": base.marketdata.model_copy(update={"history_start": "2024-01-02"})}
    )
    app = _app(tmp_path, settings=settings)
    vision = tmp_path / "vision"
    ranking = datetime(2024, 1, 3, tzinfo=UTC)
    for index in range(20):
        compact = f"N{index:02d}USDT"
        path = monthly_kline_csv(vision, compact, "1d", 2024, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_kline_row(ranking, quote=str(1000 + index)), encoding="utf-8")
    daily = universe_path(tmp_path, "binanceusdm", date(2024, 1, 2))
    rebuilt = universe_path(tmp_path, "binanceusdm", date(2024, 1, 3))
    write_universe_file(daily, (_member("BTC/USDT", 1, source="daily_kline", fallback=YESTERDAY),))
    write_universe_file(rebuilt, (_member("ETH/USDT", 1, source="reconstructed"),))
    daily_bytes = daily.read_bytes()
    rebuilt_bytes = rebuilt.read_bytes()
    written, skipped = reconstruct_history(app, vision_root=vision, end=date(2024, 1, 4))
    assert date(2024, 1, 4) in written
    assert date(2024, 1, 2) in skipped
    assert date(2024, 1, 3) in skipped
    assert daily.read_bytes() == daily_bytes
    assert rebuilt.read_bytes() == rebuilt_bytes
    created = load_universe(universe_path(tmp_path, "binanceusdm", date(2024, 1, 4)))
    assert len(created) == 20
    assert {member.source for member in created} == {"reconstructed"}
    assert all(member.fallback_from is None for member in created)


def test_pin_mode_refuses_download_universe_and_backtest(tmp_path: Path, capsys) -> None:
    overlay = tmp_path / "pin.yaml"
    overlay.write_text(
        "universe:\n  mode: pin\n  pin:\n    - {symbol: BTC/USDT, venue_symbol: BTC/USDT:USDT}\n",
        encoding="utf-8",
    )
    args = ["--config", str(ROOT / "config" / "default.yaml"), "--overlay", str(overlay), "--root", str(tmp_path / "run")]
    for command in ("download", "universe", "backtest"):
        code = main([command, *args, "--end", "2024-01-02"], exchange=_Explode(), clock=_Clock(T15), environ=_Boom())
        assert code == 1
    assert "pin does not run" in capsys.readouterr().err


def test_paper_once_waits_one_close_and_reads_the_parquet(tmp_path: Path) -> None:
    overlay = tmp_path / "pin.yaml"
    overlay.write_text(
        "universe:\n  mode: pin\n  pin:\n    - {symbol: BTC/USDT, venue_symbol: BTC/USDT:USDT}\n"
        "safety:\n  kill_switch: false\n",
        encoding="utf-8",
    )
    store = ParquetBarStore(tmp_path)
    for bar in _pack("BTC/USDT"):
        store.write_closed("binanceusdm", bar.symbol, bar.timeframe, (store_bar(bar),))
    slept: list[float] = []
    code = main(
        [
            "paper",
            "--once",
            "--config",
            str(ROOT / "config" / "default.yaml"),
            "--overlay",
            str(overlay),
            "--root",
            str(tmp_path),
        ],
        exchange=_Exchange(),
        clock=_Clock(T15),
        sleep=slept.append,
        environ=_Boom(),
    )
    assert code == 0
    assert slept == [3]


def test_startup_target_and_universe_date_follow_the_close(tmp_path: Path) -> None:
    del tmp_path
    assert startup_target(datetime(2024, 1, 1, 0, 15, 1, tzinfo=UTC), 3) == T15
    assert startup_target(datetime(2024, 1, 1, 0, 15, 4, tzinfo=UTC), 3) == datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
    assert universe_date(datetime(2024, 1, 1, 0, 4, tzinfo=UTC), 5) == YESTERDAY
    assert universe_date(datetime(2024, 1, 1, 0, 5, tzinfo=UTC), 5) == DAY


def test_instruments_from_real_ccxt_markets_keep_only_the_usdt_perp() -> None:
    import ccxt

    from chanedge.app.compose import instruments_from_exchange

    parser = ccxt.binanceusdm()

    def fapi(symbol: str, quote: str, contract_type: str, delivery: int) -> dict:
        return {
            "symbol": symbol,
            "pair": "BTC" + quote,
            "contractType": contract_type,
            "deliveryDate": delivery,
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": quote,
            "marginAsset": quote,
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "minPrice": "556.80", "maxPrice": "4529764", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "maxQty": "1000", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "100"},
            ],
        }

    raw = (
        fapi("BTCUSDT", "USDT", "PERPETUAL", 4133404800000),
        fapi("BTCUSDT_251226", "USDT", "CURRENT_QUARTER", 1766736000000),
        fapi("BTCUSDC", "USDC", "PERPETUAL", 4133404800000),
    )
    markets = {item["symbol"]: item for item in (parser.parse_market(entry) for entry in raw)}
    assert all(item["limits"]["leverage"]["max"] is None for item in markets.values())

    class _Markets:
        def load_markets(self):
            return markets

    found = instruments_from_exchange(_Markets(), "binanceusdm", default_leverage=2)
    assert set(found) == {"BTC/USDT"}
    assert found["BTC/USDT"].venue_symbol == "BTC/USDT:USDT"
    assert found["BTC/USDT"].leverage_max == 2
    assert found["BTC/USDT"].price_tick == Decimal("0.1")


def test_one_late_symbol_does_not_hold_back_the_others(tmp_path: Path) -> None:
    clock = _Clock(T15 + timedelta(seconds=91))
    app = _app(tmp_path, settings=_settings(("BTC/USDT", "ETH/USDT")), clock=clock)
    app.listed = lambda: set()
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    app.instruments["ETH/USDT"] = _instrument("ETH/USDT")
    late = [_candle("ETH/USDT", Timeframe.M15, OLD, low=99.5)]
    _store(app, _pack("BTC/USDT") + late)
    _arm(app, ScriptedEngine({("BTC/USDT", T15): _signal("BTC/USDT")}))
    slept: list[float] = []
    result = run_paper_bar(app, decision_time=T15, sleep=slept.append)
    by_symbol = {item.symbol: item for item in result.decisions}
    assert slept == [3]
    assert result.stale is True
    assert _codes(by_symbol["ETH/USDT"].hard_rule_json) == ["stale_data"]
    assert by_symbol["BTC/USDT"].action == DecisionAction.ENTER_LONG.value


def test_first_paper_fill_starts_at_the_window_before_now(tmp_path: Path) -> None:
    from chanedge.marketdata.ccxt_adapter import PAGE_LIMIT

    exchange = _Exchange()
    seen: list[tuple[str, int, int]] = []

    def fetch_ohlcv(_symbol, timeframe, since=None, limit=None):
        seen.append((timeframe, since, limit))
        if timeframe == "15m":
            return [_ohlcv(T0)]
        if timeframe == "1h":
            return [_ohlcv(H1_OPEN)]
        return [_ohlcv(H4_OPEN)]

    exchange.fetch_ohlcv = fetch_ohlcv  # type: ignore[method-assign]
    app = _app(tmp_path, exchange=exchange)
    app.listed = lambda: {"BTC/USDT"}
    app.instruments["BTC/USDT"] = _instrument("BTC/USDT")
    run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    first = {timeframe: (since, limit) for timeframe, since, limit in reversed(seen)}
    windows = app.settings.marketdata.windows
    assert first["15m"] == (int((T15 - timedelta(minutes=15) * windows["15m"]).timestamp() * 1000), PAGE_LIMIT)
    assert first["1h"][0] == int((T0 - timedelta(hours=1) * windows["1h"]).timestamp() * 1000)


def test_backtest_warns_when_the_kill_switch_vetoes_every_entry(tmp_path: Path, capsys) -> None:
    clock = _Clock(datetime(2024, 1, 2, 12, tzinfo=UTC))
    base = ["backtest", "--config", str(ROOT / "config" / "default.yaml"), "--root", str(tmp_path), "--end", "2024-01-01"]
    assert main(base, exchange=_Exchange(), clock=clock, environ=_Boom()) == 0
    assert "safety.kill_switch is true" in capsys.readouterr().err
    other = tmp_path / "with-overlay"
    overlay = [*base[:4], str(other), *base[5:], "--overlay", str(ROOT / "config" / "paper.yaml")]
    assert main(overlay, exchange=_Exchange(), clock=clock, environ=_Boom()) == 0
    assert "kill_switch" not in capsys.readouterr().err
