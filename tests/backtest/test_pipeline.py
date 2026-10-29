"""run_pipeline order: exit group, slim hold, then a full entry row."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from chanedge.app.bind import feature_params, jev_params, risk_params, rule_params
from chanedge.app.pipeline import PipelineServices, run_pipeline
from chanedge.chanlun.engine import window_hash
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
from chanedge.domain.records import PipelineRequest
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
from chanedge.jev.model import JevModel
from chanedge.risk.size import RiskManager
from chanedge.rules.gate import RuleGate

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
SYMBOL = "BTC/USDT"
CFG = "cfg-pr11"
ENGINE = "engine-v1"
FEATURE = "feature-v1"
MARKET = "marketdata-v1"


def test_slim_and_full_log_share_the_hold_id_and_the_quality_order() -> None:
    engine = ScriptedEngine({})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1500)
    quality = DataQuality(
        stale=True,
        max_gap_bars=2,
        missing_bar_count=1,
        last_bar_close=T15,
        reasons=("gap_data",),
    )
    slim = run_pipeline(_request(full_log=False, data_quality=quality), services)
    full = run_pipeline(_request(full_log=True, data_quality=quality), services)
    assert slim.decision.decision_id == full.decision.decision_id
    assert slim.decision.action == DecisionAction.HOLD.value
    assert slim.decision.snapshot_id_m15 is None
    assert slim.features is None
    assert [item.code for item in slim.rules.vetoes] == [  # type: ignore[union-attr]
        VetoCode.STALE_DATA,
        VetoCode.GAP_DATA,
        VetoCode.INSUFFICIENT_HISTORY,
        VetoCode.NO_CANDIDATE,
    ]
    assert [item.code for item in full.rules.vetoes] == [item.code for item in slim.rules.vetoes]  # type: ignore[union-attr]
    assert full.features is not None
    assert full.decision.snapshot_id_h4 is not None


def test_exit_group_reviews_without_the_gate_or_a_plan() -> None:
    engine = ScriptedEngine({})
    broker = _broker()
    risk = SpyRisk(RiskManager(risk_params(load_settings(ROOT / "config" / "default.yaml"))))
    rules = SpyRules(RuleGate(_rules(windows=1)))
    services = _services(broker, engine, threshold=0.0, windows=1, risk=risk, rules=rules)
    held = _position(_accepted_plan(entry=100.0, stop=90.0), stop_price=90.0)
    result = run_pipeline(_request(group="exit", position=held, full_log=False), services)
    assert risk.plans == 0
    assert rules.calls == 0
    assert risk.reviews == 1
    assert result.action is DecisionAction.HOLD
    assert result.rules is None
    assert result.plan is None
    assert result.features is not None


def test_passed_hold_does_not_call_plan_entry() -> None:
    when = T15
    signal = _signal(when)
    engine = ScriptedEngine({(SYMBOL, when): signal})
    broker = _broker()
    risk = SpyRisk(RiskManager(risk_params(load_settings(ROOT / "config" / "default.yaml"))))
    services = _services(broker, engine, threshold=1.01, windows=1, risk=risk)
    result = run_pipeline(_request(), services)
    assert result.rules is not None and result.rules.passed is True
    assert result.assessment is not None
    assert result.assessment.proposed_action.value == "HOLD"
    assert result.action is DecisionAction.HOLD
    assert risk.plans == 0
    assert result.plan is None


def test_higher_timeframe_as_of_is_reused_and_is_not_the_15m_close() -> None:
    engine = ScriptedEngine({})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1)
    first = run_pipeline(_request(full_log=True), services)
    second = run_pipeline(_request(full_log=True, previous=first.snapshots), services)
    h1 = [call for call in engine.calls if call[1] is Timeframe.H1]
    h4 = [call for call in engine.calls if call[1] is Timeframe.H4]
    assert len(h1) == 1
    assert len(h4) == 1
    assert h4[0][2] == T0
    assert second.snapshots[Timeframe.H1].snapshot_id == first.snapshots[Timeframe.H1].snapshot_id


def test_empty_windows_follow_the_slim_and_full_rules() -> None:
    engine = ScriptedEngine({})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1)
    slim = run_pipeline(_request(bars={timeframe: () for timeframe in Timeframe}), services)
    assert engine.calls == []
    assert slim.action is DecisionAction.HOLD
    assert any(item.code is VetoCode.NO_CANDIDATE for item in slim.rules.vetoes)  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="15m window is empty"):
        run_pipeline(_request(full_log=True, bars={timeframe: () for timeframe in Timeframe}), services)
    bars = _bars()
    bars[Timeframe.H1] = ()
    with pytest.raises(ValueError, match="higher timeframe window is empty"):
        run_pipeline(_request(full_log=True, bars=bars), services)


def test_flattened_skips_the_engine_and_plan_entry() -> None:
    engine = ScriptedEngine({(SYMBOL, T15): _signal(T15)})
    broker = _broker()
    risk = SpyRisk(RiskManager(risk_params(load_settings(ROOT / "config" / "default.yaml"))))
    services = _services(broker, engine, threshold=0.0, windows=1, risk=risk)
    result = run_pipeline(_request(flattened=True), services)
    assert engine.calls == []
    assert risk.plans == 0
    assert result.action is DecisionAction.HOLD
    assert result.reason_steps[0].code == "FLATTENED_THIS_BAR"
    assert result.decision.created_at == T15


def test_instrument_spec_returns_before_the_open_count() -> None:
    signal = _signal(T15)
    engine = ScriptedEngine({(SYMBOL, T15): signal})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1)
    account = AccountView(
        equity_quote=Decimal("10000"),
        open_position_count=3,
        gross_notional_quote=Decimal("0"),
    )
    result = run_pipeline(
        _request(account=account, instrument=_instrument(tick=None)),
        services,
    )
    assert result.plan is not None
    assert result.plan.reject_reason is VetoCode.INSTRUMENT_SPEC
    assert result.plan.cost_r is None
    assert result.action is DecisionAction.HOLD


def test_open_count_and_same_direction_reject_before_a_stop() -> None:
    signal = _signal(T15)
    engine = ScriptedEngine({(SYMBOL, T15): signal})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1)
    crowded = run_pipeline(
        _request(
            account=AccountView(
                equity_quote=Decimal("10000"),
                open_position_count=3,
                gross_notional_quote=Decimal("0"),
            )
        ),
        services,
    )
    assert crowded.plan is not None
    assert crowded.plan.reject_reason is VetoCode.MAX_OPEN_POSITIONS
    assert crowded.plan.cost_r is None
    tiny = _position(_accepted_plan(), qty=Decimal("0.001"), avg_price=1.0, symbol="ETH/USDT")
    tiny_book = (
        tiny,
        tiny.model_copy(update={"symbol": "SOL/USDT"}),
    )
    same = run_pipeline(
        _request(
            account=AccountView(
                equity_quote=Decimal("10000"),
                positions=tiny_book,
                open_position_count=2,
                gross_notional_quote=Decimal("0.002"),
            )
        ),
        services,
    )
    assert same.plan is not None
    assert same.plan.reject_reason is VetoCode.MAX_SAME_DIRECTION
    assert same.plan.cost_r is None


def test_entry_preflight_skips_the_model_on_kill_and_on_no_candidate() -> None:
    engine = ScriptedEngine({(SYMBOL, T15): _signal(T15)})
    broker = _broker()
    counter = _CountingJev()
    services = _services(broker, engine, threshold=0.0, windows=1)
    services.jev = counter
    services.score_after_preflight = True
    killed = run_pipeline(
        _request(safety=SafetyState(kill_switch=True, mode=RuntimeMode.PAPER)),
        services,
    )
    assert counter.calls == 0
    assert killed.plan is None
    assert killed.action is DecisionAction.HOLD
    assert killed.rules is not None
    assert any(item.code is VetoCode.KILL_SWITCH for item in killed.rules.vetoes)
    assert killed.assessment is not None
    assert killed.assessment.systemone_status == "skipped_veto"

    empty = ScriptedEngine({})
    services.engine = empty
    quiet = run_pipeline(_request(full_log=True), services)
    assert counter.calls == 0
    assert quiet.rules is not None
    assert any(item.code is VetoCode.NO_CANDIDATE for item in quiet.rules.vetoes)


def test_scored_path_gates_twice_and_a_failure_does_not() -> None:
    from chanedge.domain.systemone import SystemOneFailure
    from chanedge.jev.compose import TypeSafeJev
    from chanedge.jev.questions import MODEL_PIN

    signal = _signal(T15)
    engine = ScriptedEngine({(SYMBOL, T15): signal})
    broker = _broker()
    risk = SpyRisk(RiskManager(risk_params(load_settings(ROOT / "config" / "default.yaml"))))
    rules = SpyRules(RuleGate(_rules(windows=1)))
    settings = load_settings(ROOT / "config" / "default.yaml")
    port = _ScriptPort(_remote(1.0))
    services = _services(broker, engine, threshold=0.0, windows=1, risk=risk, rules=rules)
    services.jev = TypeSafeJev(jev_params(settings), port, model_pin=MODEL_PIN)
    services.score_after_preflight = True
    opened = run_pipeline(_request(), services)
    assert rules.calls == 2
    assert risk.plans == 1
    assert opened.assessment is not None
    assert opened.assessment.systemone_status == "scored"
    assert opened.assessment.p_buy is None
    assert "p_buy" not in (opened.decision.jev_json or "")

    rules.calls = 0
    risk.plans = 0
    services.jev = TypeSafeJev(
        jev_params(settings),
        _ScriptPort(error=SystemOneFailure("cache_miss", 1.0)),
        model_pin=MODEL_PIN,
    )
    missed = run_pipeline(_request(), services)
    assert rules.calls == 1
    assert risk.plans == 0
    assert missed.plan is None
    assert missed.rules is None
    assert missed.reason_steps[0].code == "JEV_CACHE_MISS"
    assert missed.reason_steps[0].stage.value == "jev"


def test_local_rows_keep_probabilities_and_exit_uses_the_log_model() -> None:
    engine = ScriptedEngine({(SYMBOL, T15): _signal(T15)})
    broker = _broker()
    services = _services(broker, engine, threshold=0.0, windows=1)
    local = run_pipeline(_request(), services)
    assert local.assessment is not None
    assert local.assessment.p_buy is not None
    text = local.decision.jev_json or ""
    assert "p_buy" in text
    assert "systemone_status" not in text

    counter = _CountingJev()
    logger = JevModel(jev_params(load_settings(ROOT / "config" / "default.yaml")))
    services.score_after_preflight = True
    services.jev = counter
    services.log_jev = logger
    held = _position(_accepted_plan(entry=100.0, stop=90.0), stop_price=90.0)
    reviewed = run_pipeline(_request(group="exit", position=held), services)
    assert counter.calls == 0
    assert reviewed.assessment is not None
    assert reviewed.assessment.jev_version == "weighted-v1"
    assert reviewed.assessment.systemone_status is None
    assert reviewed.rules is None


class _CountingJev:
    def __init__(self) -> None:
        self.calls = 0

    def assess(self, features):
        del features
        self.calls += 1
        raise AssertionError("the model was called")


class _ScriptPort:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error

    def system_one(self, *, state, questions, model):
        del state, questions, model
        if self.error is not None:
            raise self.error
        return self.result


def _remote(subscore: float):
    from chanedge.domain.systemone import ChoiceAnswer, ScoreAnswer, SystemOneResult
    from chanedge.jev.questions import MODEL_PIN, QUESTIONS

    scores = {}
    for name, spec in QUESTIONS.items():
        if not isinstance(spec, dict) or spec.get("type") != "score":
            continue
        criteria = spec["criteria"]
        assert isinstance(criteria, list)
        top = len(criteria) - 1
        scores[name] = ScoreAnswer(
            score=subscore * top,
            probabilities={str(index): (1.0 if index == 0 else 0.0) for index in range(top + 1)},
            confidence=0.5,
        )
    return SystemOneResult(
        model=MODEL_PIN,
        scores=scores,
        choices={
            "final_decision": ChoiceAnswer(
                choice="GO",
                probabilities={"GO": 1.0, "NO_GO": 0.0},
                confidence=0.9,
            )
        },
        elapsed_ms=5.0,
    )


def test_pipeline_source_does_not_copy_the_locks() -> None:
    text = (ROOT / "src" / "chanedge" / "app" / "pipeline.py").read_text(encoding="utf-8")
    bind = (ROOT / "src" / "chanedge" / "app" / "bind.py").read_text(encoding="utf-8")
    for source in (text, bind):
        assert "0.62" not in source
        assert "0.35" not in source
        assert "pipeline_timeout" not in source


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
            snapshot_id=f"cs-{timeframe.value}-{as_of.strftime('%H%M%S')}",
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


class SpyRisk:
    def __init__(self, inner: RiskManager) -> None:
        self.inner = inner
        self.plans = 0
        self.reviews = 0

    def plan_entry(self, context, features, assessment, rules, account):
        self.plans += 1
        return self.inner.plan_entry(context, features, assessment, rules, account)

    def review_open(self, context, position):
        self.reviews += 1
        return self.inner.review_open(context, position)


class SpyRules:
    def __init__(self, inner: RuleGate) -> None:
        self.inner = inner
        self.calls = 0

    def evaluate(self, context, assessment, account, safety):
        self.calls += 1
        return self.inner.evaluate(context, assessment, account, safety)


def _services(broker, engine, *, threshold: float, windows: int, risk=None, rules=None) -> PipelineServices:
    settings = load_settings(ROOT / "config" / "default.yaml")
    feature = feature_params(settings)
    feature = feature.model_copy(
        update={"session": feature.session.model_copy(update={"hard_skip_buckets": ()})}
    )
    gate = _rules(windows=windows)
    return PipelineServices(
        engine=engine,
        features=FeatureBuilder(feature),
        jev=JevModel(jev_params(settings).model_copy(update={"enter_threshold": threshold})),
        rules=rules or RuleGate(gate),
        risk=risk or RiskManager(risk_params(settings)),
        broker=broker,
        rule_params=gate,
    )


def _rules(windows: int):
    settings = load_settings(ROOT / "config" / "default.yaml")
    return rule_params(settings).model_copy(
        update={
            "window_15m": windows,
            "window_1h": windows,
            "window_4h": windows,
            "atr_pct_min": 0.0,
            "atr_pct_max": 1.0,
            "hard_skip_buckets": (),
        }
    )


def _request(**overrides: object) -> PipelineRequest:
    values: dict[str, object] = {
        "symbol": SYMBOL,
        "decision_time": T15,
        "universe_date": T15.date(),
        "universe_rank": 1,
        "group": "entry",
        "full_log": False,
        "flattened": False,
        "bars": _bars(),
        "data_quality": DataQuality(
            stale=False,
            max_gap_bars=0,
            missing_bar_count=0,
            last_bar_close=T15,
            reasons=(),
        ),
        "instrument": _instrument(),
        "account": AccountView(
            equity_quote=Decimal("10000"),
            open_position_count=0,
            gross_notional_quote=Decimal("0"),
        ),
        "safety": SafetyState(kill_switch=False, mode=RuntimeMode.PAPER),
        "position": None,
        "previous": {},
        "config_hash": CFG,
        "engine_version": ENGINE,
        "feature_version": FEATURE,
        "marketdata_version": MARKET,
        "order_type": "market",
        "group_order": 0,
        "record": True,
    }
    values.update(overrides)
    return PipelineRequest(**values)  # type: ignore[arg-type]


def _bars() -> dict[Timeframe, tuple[Bar, ...]]:
    return {
        Timeframe.M15: (_candle(SYMBOL, Timeframe.M15, T0, close=100.0, high=101.0, low=99.5),),
        Timeframe.H1: (
            _candle(SYMBOL, Timeframe.H1, datetime(2023, 12, 31, 23, 0, tzinfo=UTC), close=100.0),
        ),
        Timeframe.H4: (
            _candle(SYMBOL, Timeframe.H4, datetime(2023, 12, 31, 20, 0, tzinfo=UTC), close=100.0),
        ),
    }


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


def _signal(when: datetime, kind: SignalType = SignalType.SECOND_BUY, defending: float = 99.0) -> ChanSignal:
    return ChanSignal(
        id=f"sig-{kind.value}",
        timeframe=Timeframe.M15,
        type=kind,
        status=SignalStatus.CONFIRMED,
        time=when,
        price=100.0,
        direction=Direction.UP,
        defending_fx_id="fx-def",
        defending_price=defending,
        related_bi_id="bi-1",
        bar_open_time=when - timedelta(minutes=15),
    )


def _instrument(tick: Decimal | None = Decimal("0.01")) -> Instrument:
    return Instrument(
        symbol=SYMBOL,
        venue="binanceusdm",
        venue_symbol="BTC/USDT:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=tick,
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        margin_asset="USDT",
        leverage_max=20,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _broker() -> PaperBroker:
    return PaperBroker(InMemoryLedger(), initial_equity=Decimal("10000"))


def _accepted_plan(entry: float = 100.0, stop: float = 99.0) -> RiskPlan:
    return RiskPlan(
        symbol=SYMBOL,
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=Decimal("1"),
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=entry,
        atr=0.0,
        structure_stop_price=stop,
        stop_buffer=0.0,
        defending_fx_id="fx-def",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL, SignalType.THIRD_SELL),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=stop,
            defending_fx_id="fx-def",
            effective_after=datetime(2023, 12, 31, tzinfo=UTC),
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


def _position(plan: RiskPlan, **overrides: object) -> PositionState:
    values: dict[str, object] = {
        "symbol": plan.symbol,
        "qty": Decimal("1"),
        "avg_price": 100.0,
        "stop_price": plan.structure_stop_price if plan.structure_stop_price is not None else 99.0,
        "plan": plan,
        "entry_decision_id": "dec-held",
        "entry_decision_time": datetime(2023, 12, 31, tzinfo=UTC),
        "entry_bar_open_time": datetime(2023, 12, 31, tzinfo=UTC),
    }
    values.update(overrides)
    symbol = values.get("symbol", plan.symbol)
    if symbol != plan.symbol:
        plan = plan.model_copy(update={"symbol": symbol})
        values["plan"] = plan
    return PositionState(**values)  # type: ignore[arg-type]
