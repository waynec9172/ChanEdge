"""Backtest loop: match, exit group, entry group, report directory."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from chanedge.app.bind import feature_params, jev_params, risk_params, rule_params
from chanedge.app.pipeline import PipelineServices, run_pipeline
from chanedge.backtest.loop import run_backtest
from chanedge.chanlun.engine import window_hash
from chanedge.chanlun.version import ENGINE_VERSION
from chanedge.config.load import load_settings
from chanedge.domain.bars import Bar, DataQuality, Instrument, timeframe_duration
from chanedge.domain.chanlun import ChanSignal, ChanSnapshot
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
from chanedge.domain.records import UniverseName, UniverseUnavailable
from chanedge.domain.risk import (
    AccountView,
    InvalidationSpec,
    PositionState,
    RiskPlan,
    SafetyState,
    TrailRule,
)
from chanedge.execution.paper import InMemoryLedger, PaperBroker
from chanedge.features.builder import FeatureBuilder
from chanedge.features.version import FEATURE_VERSION
from chanedge.jev.model import JevModel
from chanedge.journal.book import ReportJournal
from chanedge.marketdata.version import MARKETDATA_VERSION
from chanedge.risk.size import RiskManager
from chanedge.rules.gate import RuleGate

UTC = timezone.utc
DAY = date(2024, 1, 1)
NEXT = date(2024, 1, 2)
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
T30 = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
CFG = "cfg-pr11"
ENGINE = "engine-v1"
FEATURE = "feature-v1"
MARKET = "marketdata-v1"
ZERO = Decimal("0")


def test_opposite_signal_fills_once_at_the_next_open(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=101.0, low=94.0, close=100.0),
        _candle(symbol, Timeframe.M15, T15, open_=95.0, high=96.0, low=80.0, close=95.0),
    ]
    broker = _broker()
    broker.seed(_held(symbol, entry=100.0, stop=90.0, avg=100.0))
    result, _engine, _sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        broker=broker,
        signals={(symbol, T15): _signal(symbol, T15, SignalType.SECOND_SELL, defending=101.0)},
    )
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.price == Decimal("95.00000000")
    assert fill.bar_seq == 0
    assert fill.exit_reason == "opposite_signal"
    assert fill.reduce_only is True


def test_entry_open_through_the_stop_then_flattened(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=101.0, low=99.5, close=100.0),
        _candle(symbol, Timeframe.M15, T15, open_=98.0, high=99.0, low=97.0, close=98.0),
    ]
    result, engine, sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        signals={(symbol, T15): _signal(symbol, T15, defending=99.0)},
        instruments={symbol: _instrument(symbol)},
    )
    assert [fill.bar_seq for fill in result.fills] == [0, 1]
    assert [fill.price for fill in result.fills] == [Decimal("98.00000000"), Decimal("98.00000000")]
    assert result.fills[0].qty == Decimal("50.00000000")
    assert result.fills[1].exit_reason == "structure_stop"
    assert result.fills[1].client_order_id.endswith(":stop")
    flattened = [item for item in result.decisions if item.decision_time == T30]
    assert len(flattened) == 1
    assert flattened[0].action == DecisionAction.HOLD.value
    assert flattened[0].reason_chain_json is not None
    assert "FLATTENED_THIS_BAR" in flattened[0].reason_chain_json
    h4 = [call for call in engine.calls if call[1] is Timeframe.H4]
    assert h4[0][2] == T0
    shadows = pq.read_table(result.directory / "shadows.parquet")
    assert shadows.num_rows >= 1
    assert shadows.column("shadow")[0].as_py() is True
    assert result.synchronous == 0
    assert result.chart_frames == 0
    assert sink.repo is not None
    assert sink.repo.schema_version == 1


def test_breakeven_adverse_classifies_the_arm_bar(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=100.34, low=99.70, close=99.8),
        _candle(symbol, Timeframe.M15, T15, open_=99.5, high=100.0, low=99.4, close=99.6),
    ]
    broker = _broker()
    broker.seed(_held(symbol, entry=100.0, stop=99.66, avg=90.0))
    result, _engine, _sink = _drive(tmp_path / "reports", bars, {DAY: (_name(symbol, 1),)}, broker=broker)
    assert len(result.fills) == 1
    assert result.fills[0].price == Decimal("99.50000000")
    assert result.fills[0].exit_reason == "breakeven_adverse"


def test_position_limits_and_a_dropped_name_cannot_add(tmp_path: Path) -> None:
    symbol = "NEW/USDT"
    bars = [*_higher(symbol), _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.5)]
    signal = {(symbol, T15): _signal(symbol, T15, defending=99.0)}
    crowded = _broker()
    for name in ("AAA/USDT", "BBB/USDT", "CCC/USDT"):
        crowded.seed(_held(name, qty=Decimal("1")))
    fourth, _engine, _sink = _drive(
        tmp_path / "fourth",
        bars,
        {DAY: (_name(symbol, 1),)},
        broker=crowded,
        signals=signal,
        symbols=(symbol,),
    )
    plan = _plan_of(fourth, symbol)
    assert plan["reject_reason"] == VetoCode.MAX_OPEN_POSITIONS.value
    assert plan["cost_r"] is None

    sided = _broker()
    sided.seed(_held("AAA/USDT", qty=Decimal("0.001"), avg=1.0))
    sided.seed(_held("BBB/USDT", qty=Decimal("0.001"), avg=1.0))
    third, _engine, _sink = _drive(
        tmp_path / "third",
        bars,
        {DAY: (_name(symbol, 1),)},
        broker=sided,
        signals=signal,
        symbols=(symbol,),
    )
    same = _plan_of(third, symbol)
    assert same["reject_reason"] == VetoCode.MAX_SAME_DIRECTION.value
    assert same["cost_r"] is None

    invalid = _broker()
    for name in ("AAA/USDT", "BBB/USDT", "CCC/USDT"):
        invalid.seed(_held(name))
    spec, _engine, _sink = _drive(
        tmp_path / "spec",
        bars,
        {DAY: (_name(symbol, 1),)},
        broker=invalid,
        signals=signal,
        symbols=(symbol,),
        instruments={symbol: _instrument(symbol, tick=None)},
    )
    broken = _plan_of(spec, symbol)
    assert broken["reject_reason"] == VetoCode.INSTRUMENT_SPEC.value
    assert broken["cost_r"] is None

    dropped_broker = _broker()
    dropped_broker.seed(_held(symbol, stop=50.0))
    dropped, _engine, _sink = _drive(
        tmp_path / "dropped",
        bars,
        {DAY: ()},
        broker=dropped_broker,
        symbols=(symbol,),
    )
    assert dropped.decisions
    assert all(item.action == DecisionAction.HOLD.value for item in dropped.decisions)
    assert all(item.risk_plan_json is None for item in dropped.decisions)
    assert all(item.hard_rule_json is None for item in dropped.decisions)
    assert dropped.fills == ()


def test_missing_or_unreadable_universe_stops_before_a_directory(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0),
        _candle(
            symbol,
            Timeframe.M15,
            datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
            close=100.0,
            high=101.0,
            low=99.0,
        ),
    ]
    calls: list[object] = []

    def pipeline(request, services):
        calls.append(request)
        return run_pipeline(request, services)

    root = tmp_path / "missing"
    with pytest.raises(UniverseUnavailable, match="universe --reconstruct"):
        _drive(
            root,
            bars,
            {DAY: (_name(symbol, 1),)},
            pipeline=pipeline,
            history_end=NEXT,
        )
    assert calls == []
    assert not root.exists()

    root = tmp_path / "bad"
    with pytest.raises(UniverseUnavailable, match="delete it") as caught:
        _drive(
            root,
            bars,
            {DAY: ValueError("not a universe file"), NEXT: (_name(symbol, 1),)},
            history_end=NEXT,
        )
    assert "universe --reconstruct" in str(caught.value)
    assert not root.exists()


def test_first_decision_is_history_start_0015(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, datetime(2023, 12, 31, 23, 45, tzinfo=UTC), close=100.0),
        _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0),
    ]
    calls: list[datetime] = []

    def pipeline(request, services):
        calls.append(request.decision_time)
        return run_pipeline(request, services)

    _result, _engine, _sink, source = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        pipeline=pipeline,
        with_source=True,
    )
    assert calls == [T15]
    assert source.loaded == [DAY]


def test_two_runs_share_decision_ids_and_not_the_run_id(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [*_higher(symbol), _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0)]
    board = {DAY: (_name(symbol, 1),)}
    first, _engine, sink = _drive(
        tmp_path / "reports",
        bars,
        board,
        clock=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    )
    second, _engine, _sink = _drive(
        sink.root,
        bars,
        board,
        clock=datetime(2024, 6, 1, 12, 0, 1, tzinfo=UTC),
    )
    assert first.run_id != second.run_id
    assert [item.decision_id for item in first.decisions] == [item.decision_id for item in second.decisions]
    assert first.decisions[0].decision_id == decision_id(
        symbol, T15, DecisionAction.HOLD, CFG, ENGINE, FEATURE, MARKET
    )
    assert first.decisions[0].created_at == T15
    assert "2024-06-01T12-00-00" in first.run_id
    assert "2024-06-01T12-00-01" in second.run_id
    timing = json.loads((first.directory / "timing.json").read_text(encoding="utf-8"))
    assert set(timing) == {"elapsed_ms", "decision_count", "mean_decision_ms"}
    summary = json.loads((first.directory / "summary.json").read_text(encoding="utf-8"))
    for key in (
        "endpoint_replaced_ratio",
        "second_buy_reemit_count",
        "inside_low_broke_prior_end",
        "overlap_term_mean",
        "overlap_penalty_fraction",
        "cost_r_by_symbol",
        "inferred_fill_count",
        "instrument_spec_count",
        "min_qty_count",
        "veto_histogram",
        "missing_funding_months",
    ):
        assert key in summary
    for name in ("trades.parquet", "shadows.parquet", "equity.parquet", "journal.sqlite"):
        assert (first.directory / name).is_file()
    assert first.directory.joinpath("journal.sqlite").name == "journal.sqlite"
    assert "chanedge.sqlite" not in first.directory.parts
    assert not any(path.name == "chanedge.sqlite" for path in first.directory.rglob("*"))
    blob = json.dumps([item.reason_chain_json for item in first.decisions])
    assert "pipeline_timeout" not in blob
    assert pq.read_table(first.directory / "shadows.parquet").num_rows == 0
    assert first.synchronous == 0
    assert first.chart_frames == 0


def test_long_version_strings_still_create_the_report(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [*_higher(symbol), _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0)]
    result, _engine, sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        versions=(ENGINE_VERSION, FEATURE_VERSION, MARKETDATA_VERSION),
    )
    assert len(result.run_id) > 255
    relative = result.directory.relative_to(sink.root)
    assert len(relative.parts) == 1
    assert len(relative.name) <= 96
    assert relative.name.endswith(result.run_id[-41:])
    assert json.loads((result.directory / "run.json").read_text(encoding="utf-8")) == {"run_id": result.run_id}
    assert (result.directory / "journal.sqlite").is_file()
    assert result.synchronous == 0


def test_kill_switch_rejects_the_entry_and_the_stop_still_fills(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=101.0, low=99.5, close=100.0),
    ]
    broker = _broker(kill_switch=True)
    result, _engine, _sink = _drive(
        tmp_path / "entry",
        bars,
        {DAY: (_name(symbol, 1),)},
        broker=broker,
        signals={(symbol, T15): _signal(symbol, T15, defending=99.0)},
        safety=SafetyState(kill_switch=False, mode=RuntimeMode.PAPER),
    )
    assert result.decisions[0].action == DecisionAction.HOLD.value
    assert result.decisions[0].decision_id == decision_id(
        symbol, T15, DecisionAction.HOLD, CFG, ENGINE, FEATURE, MARKET
    )
    assert result.decisions[0].decision_id != decision_id(
        symbol, T15, DecisionAction.ENTER_LONG, CFG, ENGINE, FEATURE, MARKET
    )
    assert result.fills == ()
    assert broker.pending_for(symbol) == ()

    stopped = _broker(kill_switch=True)
    stopped.seed(_held(symbol, entry=100.0, stop=99.0))
    pierced = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=101.0, low=98.0, close=100.0),
    ]
    result, _engine, _sink = _drive(
        tmp_path / "stop",
        pierced,
        {DAY: (_name(symbol, 1),)},
        broker=stopped,
    )
    assert len(result.fills) == 1
    assert result.fills[0].exit_reason == "structure_stop"
    assert result.fills[0].price == Decimal("99.00000000")


def test_stale_is_cleared_and_a_gap_reason_remains(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [*_higher(symbol), _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0)]

    def quality(symbol_name, decision_time, window):
        del symbol_name, window
        return DataQuality(
            stale=True,
            max_gap_bars=2,
            missing_bar_count=1,
            last_bar_close=decision_time,
            reasons=("gap_data",),
        )

    result, _engine, _sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        quality=quality,
    )
    text = result.decisions[0].hard_rule_json or ""
    assert "gap_data" in text
    assert "stale_data" not in text


def test_halt_on_flushes_this_bar_and_does_not_start_the_next(tmp_path: Path) -> None:
    symbol = "BTC/USDT"
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, T0, open_=100.0, high=101.0, low=99.5, close=100.0),
        _candle(symbol, Timeframe.M15, T15, open_=100.0, high=101.0, low=99.5, close=100.0),
    ]
    seen: list[datetime] = []

    def pipeline(request, services):
        seen.append(request.decision_time)
        return run_pipeline(request, services)

    result, _engine, sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        pipeline=pipeline,
        halt_on=lambda _result: True,
    )
    assert result.incomplete is True
    assert seen == [T15]
    assert sink.chart_frame_count() == 0


def test_backtest_source_does_not_emit_a_timeout_or_copy_the_locks() -> None:
    root = ROOT / "src" / "chanedge" / "backtest"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pipeline_timeout" not in text
        assert "0.62" not in text
        assert "0.35" not in text


class ScriptedEngine:
    def __init__(self, signals: dict[tuple[str, datetime], ChanSignal]) -> None:
        self.signals = signals
        self.calls: list[tuple[str, Timeframe, datetime]] = []

    def compute(self, bars, *, timeframe: Timeframe, as_of: datetime) -> ChanSnapshot:
        symbol = bars[0].symbol
        self.calls.append((symbol, timeframe, as_of))
        bias = StructureBias.NEUTRAL
        if timeframe is Timeframe.H4:
            bias = StructureBias.UP
        found = ()
        if timeframe is Timeframe.M15:
            signal = self.signals.get((symbol, as_of))
            if signal is not None:
                found = (signal,)
        return ChanSnapshot(
            snapshot_id=f"cs-{symbol}-{timeframe.value}-{as_of.strftime('%H%M%S')}",
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            config_hash=CFG,
            engine_version=ENGINE,
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


class MapBars:
    def __init__(self, bars: list[Bar]) -> None:
        grouped: dict[tuple[str, Timeframe], list[Bar]] = {}
        for item in bars:
            grouped.setdefault((item.symbol, item.timeframe), []).append(item)
        self.rows = {key: tuple(value) for key, value in grouped.items()}

    def load(self, symbol: str, timeframe: Timeframe) -> tuple[Bar, ...]:
        return self.rows.get((symbol, timeframe), ())


class MapUniverse:
    def __init__(self, days: dict) -> None:
        self.days = days
        self.loaded: list[date] = []

    def load(self, day: date):
        self.loaded.append(day)
        if day not in self.days:
            raise UniverseUnavailable(
                f"missing {day.isoformat()}; run chanedge universe --reconstruct"
            )
        found = self.days[day]
        if isinstance(found, BaseException):
            raise found
        return found


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


def _drive(
    root: Path,
    bars: list[Bar],
    universe: dict,
    *,
    broker: PaperBroker | None = None,
    signals: dict | None = None,
    clock: datetime | None = None,
    symbols: tuple[str, ...] | None = None,
    history_start: date = DAY,
    history_end: date = DAY,
    instruments: dict[str, Instrument] | None = None,
    safety: SafetyState | None = None,
    pipeline=None,
    versions: tuple[str, str, str] | None = None,
    quality=None,
    with_source: bool = False,
    halt_on=None,
):
    names = symbols
    if names is None:
        names = tuple(sorted({item.symbol for item in bars if item.timeframe is Timeframe.M15}))
    book = broker or _broker()
    engine = ScriptedEngine(signals or {})
    services = _services(book, engine)
    source = MapUniverse(universe)
    sink = ReportJournal(root)
    versions = versions or (ENGINE, FEATURE, MARKET)
    settings = load_settings(ROOT / "config" / "default.yaml")
    structure = settings.jev.channels.structure
    weights = settings.jev.weights
    result = run_backtest(
        pipeline=pipeline or run_pipeline,
        services=services,
        broker=book,
        clock=FixedClock(clock or datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)),
        bar_source=MapBars(bars),
        universe_source=source,
        report_sink=sink,
        instruments=instruments or {symbol: _instrument(symbol) for symbol in names},
        symbols=names,
        history_start=history_start,
        history_end=history_end,
        refresh_minute=5,
        fee_bps=ZERO,
        slippage_bps=ZERO,
        initial_equity=Decimal("10000"),
        safety=safety or SafetyState(kill_switch=False, mode=RuntimeMode.PAPER),
        config_hash=CFG,
        engine_version=versions[0],
        feature_version=versions[1],
        marketdata_version=versions[2],
        shadow_sizer=_shadow_sizer(),
        overlap_peak=structure.overlap_peak,
        overlap_width=structure.overlap_width,
        overlap_penalty_above=structure.overlap_penalty_above,
        jev_weights={
            "structure": weights.structure,
            "location": weights.location,
            "resonance": weights.resonance,
            "volatility_volume": weights.volatility_volume,
            "signal_bar": weights.signal_bar,
            "session": weights.session,
        },
        quality=quality,
        halt_on=halt_on,
    )
    if with_source:
        return result, engine, sink, source
    return result, engine, sink


def _services(broker: PaperBroker, engine: ScriptedEngine) -> PipelineServices:
    settings = load_settings(ROOT / "config" / "default.yaml")
    feature = feature_params(settings)
    feature = feature.model_copy(
        update={"session": feature.session.model_copy(update={"hard_skip_buckets": ()})}
    )
    gate = rule_params(settings).model_copy(
        update={
            "window_15m": 1,
            "window_1h": 1,
            "window_4h": 1,
            "atr_pct_min": 0.0,
            "atr_pct_max": 1.0,
            "hard_skip_buckets": (),
        }
    )
    return PipelineServices(
        engine=engine,
        features=FeatureBuilder(feature),
        jev=JevModel(jev_params(settings).model_copy(update={"enter_threshold": 0.0})),
        rules=RuleGate(gate),
        risk=RiskManager(risk_params(settings)),
        broker=broker,
        rule_params=gate,
    )


def _shadow_sizer():
    settings = load_settings(ROOT / "config" / "default.yaml")
    params = risk_params(settings).model_copy(
        update={
            "max_notional_quote": Decimal("1000000000"),
            "max_gross_notional_quote": Decimal("1000000000"),
            "max_open_positions": 1000,
            "max_same_direction": 1000,
            "max_leverage": 1000,
        }
    )
    manager = RiskManager(params)

    def size(context, features, assessment, rules):
        account = AccountView(
            equity_quote=Decimal("10000"),
            open_position_count=0,
            gross_notional_quote=ZERO,
        )
        return manager.plan_entry(context, features, assessment, rules, account)

    return size


def _plan_of(result, symbol: str) -> dict:
    chosen = [item for item in result.decisions if item.symbol == symbol and item.risk_plan_json]
    assert chosen
    return json.loads(chosen[0].risk_plan_json)


def _broker(kill_switch: bool = False) -> PaperBroker:
    return PaperBroker(InMemoryLedger(), initial_equity=Decimal("10000"), kill_switch=kill_switch)


def _name(symbol: str, rank: int) -> UniverseName:
    return UniverseName(symbol=symbol, rank=rank)


def _higher(symbol: str) -> list[Bar]:
    return [
        _candle(symbol, Timeframe.H1, datetime(2023, 12, 31, 23, 0, tzinfo=UTC)),
        _candle(symbol, Timeframe.H4, datetime(2023, 12, 31, 20, 0, tzinfo=UTC)),
    ]


def _candle(
    symbol: str,
    timeframe: Timeframe,
    open_time: datetime,
    *,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe_duration(timeframe),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        is_closed=True,
        source="binanceusdm",
    )


def _signal(
    symbol: str,
    when: datetime,
    kind: SignalType = SignalType.SECOND_BUY,
    defending: float = 99.0,
) -> ChanSignal:
    buy = kind in (SignalType.SECOND_BUY, SignalType.THIRD_BUY)
    return ChanSignal(
        id=f"sig-{symbol}-{kind.value}",
        timeframe=Timeframe.M15,
        type=kind,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=100.0,
        direction=Direction.UP if buy else Direction.DOWN,
        defending_fx_id="fx-def",
        defending_price=defending,
        related_bi_id="bi-1",
        bar_open_time=when - timedelta(minutes=15),
    )


def _instrument(symbol: str, tick: Decimal | None = Decimal("0.01")) -> Instrument:
    return Instrument(
        symbol=symbol,
        venue="binanceusdm",
        venue_symbol=f"{symbol}:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=tick,
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        margin_asset="USDT",
        leverage_max=20,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _held(
    symbol: str,
    *,
    entry: float = 100.0,
    stop: float = 90.0,
    avg: float = 100.0,
    qty: Decimal = Decimal("1"),
) -> PositionState:
    opened = datetime(2023, 12, 31, tzinfo=UTC)
    plan = RiskPlan(
        symbol=symbol,
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=qty,
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=entry,
        atr=0.0,
        structure_stop_price=stop,
        stop_buffer=0.15,
        defending_fx_id="fx-def",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL, SignalType.THIRD_SELL),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=stop,
            defending_fx_id="fx-def",
            effective_after=opened,
        ),
        realized_risk_fraction=Decimal("0.005"),
        cost_r=Decimal("0.10"),
        binding_constraint="risk_fraction",
        trail=TrailRule(
            kind=TrailKind.STRUCTURE_FENXING,
            arm_r=1.0,
            breakeven_price=entry,
            buffer=0.15,
        ),
    )
    return PositionState(
        symbol=symbol,
        qty=qty,
        avg_price=avg,
        stop_price=stop,
        plan=plan,
        entry_decision_id=f"dec-{symbol}",
        entry_decision_time=opened,
        entry_bar_open_time=opened,
    )


def test_backtest_quality_vetoes_a_gapped_window(tmp_path: Path) -> None:
    from chanedge.app.paper_loop import backtest_quality

    symbol = "BTC/USDT"
    early = T0 - timedelta(minutes=45)
    bars = [
        *_higher(symbol),
        _candle(symbol, Timeframe.M15, early),
        _candle(symbol, Timeframe.M15, T0, close=100.0, high=101.0, low=99.0),
    ]
    settings = load_settings(ROOT / "config" / "default.yaml")
    result, _engine, _sink = _drive(
        tmp_path / "reports",
        bars,
        {DAY: (_name(symbol, 1),)},
        quality=backtest_quality(settings),
    )
    rules = json.loads(result.decisions[0].hard_rule_json or "{}")
    assert "gap_data" in [veto["code"] for veto in rules["vetoes"]]
    assert "stale_data" not in [veto["code"] for veto in rules["vetoes"]]


def test_marks_use_the_last_close_when_the_decision_bar_is_missing() -> None:
    from chanedge.backtest.loop import _marks, _Series

    symbol = "BTC/USDT"
    earlier = _candle(symbol, Timeframe.M15, T0 - timedelta(minutes=15), close=104.0, high=105.0)
    marks = _marks({symbol: _Series([earlier])}, T15)
    assert marks == {symbol: 104.0}


def test_two_shadows_on_one_symbol_each_run_to_their_own_exit() -> None:
    from chanedge.backtest.shadow import ShadowBook

    symbol = "BTC/USDT"
    book = ShadowBook()
    plan = _held(symbol, entry=100.0, stop=95.0).plan
    first = _signal(symbol, T15)
    second = _signal(symbol, T15 + timedelta(minutes=15), SignalType.THIRD_BUY)
    book.open_shadow(symbol, plan, first, T15)
    book.match(symbol, _candle(symbol, Timeframe.M15, T15, low=99.0), fee_bps=ZERO, slippage_bps=ZERO)
    later = T15 + timedelta(minutes=15)
    book.open_shadow(symbol, plan.model_copy(update={"structure_stop_price": 90.0}), second, later)
    book.match(symbol, _candle(symbol, Timeframe.M15, later, low=99.0), fee_bps=ZERO, slippage_bps=ZERO)
    assert len(book.reviewable(symbol)) == 2
    stop_bar = T15 + timedelta(minutes=30)
    book.match(symbol, _candle(symbol, Timeframe.M15, stop_bar, open_=96.0, high=96.0, low=94.0, close=95.0), fee_bps=ZERO, slippage_bps=ZERO)
    assert len(book.reviewable(symbol)) == 1
    book.finish()
    assert [row["signal_id"] for row in book.rows] == [first.id, second.id]
    assert book.rows[0]["closed"] is True and book.rows[0]["exit_reason"] == "structure_stop"
    assert book.rows[1]["unfinished"] is True
