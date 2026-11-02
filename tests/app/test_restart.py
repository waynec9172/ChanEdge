"""Restart loads the paper book. A flat cash balance is the next entry equity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.app.bind import feature_params, jev_params, risk_params, rule_params
from chanedge.app.compose import compose
from chanedge.app.paper_loop import run_paper_bar
from chanedge.app.pipeline import PipelineServices
from chanedge.chanlun.engine import window_hash
from chanedge.config.load import load_settings
from chanedge.config.model import PinSymbol
from chanedge.domain.bars import Bar, Instrument, timeframe_duration
from chanedge.domain.chanlun import ChanSignal, ChanSnapshot
from chanedge.domain.decision import OrderIntent
from chanedge.domain.enums import (
    DecisionAction,
    Direction,
    InstrumentSource,
    OrderSide,
    PartialReason,
    ProductType,
    RuntimeMode,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
)
from chanedge.domain.risk import (
    InvalidationSpec,
    PartialTarget,
    PositionState,
    RiskPlan,
    SafetyState,
    TrailRule,
)
from chanedge.execution.paper import PaperBroker
from chanedge.features.builder import FeatureBuilder
from chanedge.jev.model import JevModel
from chanedge.marketdata.vision import store_bar
from chanedge.risk.size import RiskManager
from chanedge.rules.gate import RuleGate

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
T30 = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
H1_OPEN = datetime(2023, 12, 31, 23, tzinfo=UTC)
H4_OPEN = datetime(2023, 12, 31, 20, tzinfo=UTC)
SYMBOL = "BTC/USDT"
OTHER = "ETH/USDT"


class _Boom:
    def __getitem__(self, key):
        raise AssertionError(key)

    def get(self, key, default=None):
        raise AssertionError(key)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now_value = now

    def now(self) -> datetime:
        return self.now_value


class _Exchange:
    def create_order(self, *args, **kwargs):
        raise AssertionError("create_order")

    def fetch_tickers(self):
        raise AssertionError("tickers")


class ScriptedEngine:
    def __init__(self, signals: dict[tuple[str, datetime], ChanSignal]) -> None:
        self.signals = signals

    def compute(self, bars, *, timeframe: Timeframe, as_of: datetime) -> ChanSnapshot:
        symbol = bars[0].symbol
        bias = StructureBias.UP if timeframe is Timeframe.H4 else StructureBias.NEUTRAL
        found = ()
        if timeframe is Timeframe.M15:
            signal = self.signals.get((symbol, as_of))
            if signal is not None:
                found = (signal,)
        return ChanSnapshot(
            snapshot_id=f"cs-{timeframe.value}",
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


def _pin_settings(symbols: tuple[str, ...] = (SYMBOL,)):
    base = load_settings(ROOT / "config" / "default.yaml")
    pin = [PinSymbol(symbol=symbol, venue_symbol=f"{symbol}:USDT") for symbol in symbols]
    return base.model_copy(
        update={
            "universe": base.universe.model_copy(update={"mode": "pin", "pin": pin}),
            "safety": base.safety.model_copy(update={"kill_switch": False}),
        }
    )


def _app(tmp_path: Path, symbols: tuple[str, ...] = (SYMBOL,)):
    app = compose(
        _pin_settings(symbols),
        root=tmp_path,
        exchange=_Exchange(),
        clock=_Clock(T15),
        environ=_Boom(),
    )
    app.listed = lambda: set()
    app.instruments[SYMBOL] = _instrument()
    _store(app)
    return app


def _arm(app, engine, spy: SpyRisk) -> None:
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
    app.services = PipelineServices(
        engine=engine,
        features=FeatureBuilder(feature),
        jev=JevModel(jev_params(app.settings).model_copy(update={"enter_threshold": 0.0})),
        rules=RuleGate(gate),
        risk=spy,
        broker=app.broker,
        rule_params=gate,
    )
    app.safety = SafetyState(kill_switch=False, mode=RuntimeMode.PAPER)
    app.broker.kill_switch = False


def _restart(app) -> PaperBroker:
    broker = PaperBroker(
        app.ledger,
        initial_equity=app.settings.risk.initial_equity_quote,
        kill_switch=False,
        order_type=app.settings.execution.order_type,
    )
    app.broker = broker
    return broker


def _candle(
    timeframe: Timeframe,
    open_time: datetime,
    *,
    low: float = 99.0,
    high: float = 101.0,
    symbol: str = SYMBOL,
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


def _store(app, symbol: str = SYMBOL) -> None:
    bars = [
        _candle(Timeframe.H1, H1_OPEN, symbol=symbol),
        _candle(Timeframe.H4, H4_OPEN, symbol=symbol),
        _candle(Timeframe.M15, T0, low=99.5, symbol=symbol),
    ]
    _write(app, bars)


def _write(app, bars) -> None:
    grouped: dict[tuple[str, Timeframe], list] = {}
    for bar in bars:
        grouped.setdefault((bar.symbol, bar.timeframe), []).append(store_bar(bar))
    for (symbol, timeframe), stored in grouped.items():
        app.store.write_closed("binanceusdm", symbol, timeframe, stored)


def _instrument() -> Instrument:
    return Instrument(
        symbol=SYMBOL,
        venue="binanceusdm",
        venue_symbol=f"{SYMBOL}:USDT",
        product=ProductType.USDT_PERP,
        contract_size=Decimal("1"),
        price_tick=Decimal("0.01"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        margin_asset="USDT",
        leverage_max=20,
        instrument_source=InstrumentSource.EXCHANGE,
    )


def _signal() -> ChanSignal:
    return ChanSignal(
        id="sig-btc",
        timeframe=Timeframe.M15,
        type=SignalType.SECOND_BUY,
        status=SignalStatus.CONFIRMED,
        time=T15,
        price=100.0,
        direction=Direction.UP,
        defending_fx_id="fx-def",
        defending_price=99.0,
        related_bi_id="bi-1",
        bar_open_time=T0,
    )


def _held() -> PositionState:
    opened = datetime(2023, 12, 31, tzinfo=UTC)
    plan = RiskPlan(
        symbol=SYMBOL,
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
        symbol=SYMBOL,
        qty=Decimal("1"),
        avg_price=100.0,
        stop_price=90.0,
        plan=plan,
        entry_decision_id="dec-held",
        entry_decision_time=opened,
        entry_bar_open_time=opened,
    )


def test_open_position_is_reloaded_and_not_entered_again(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.broker.seed(_held())
    app.ledger.commit(app.broker.take_flush())
    broker = _restart(app)
    assert broker.position(SYMBOL) is not None
    assert broker.open_symbols() == (SYMBOL,)
    spy = SpyRisk(RiskManager(risk_params(app.settings)))
    _arm(app, ScriptedEngine({}), spy)
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.started is True
    assert spy.reviews >= 1
    assert spy.plans == 0
    assert result.decisions[0].action != DecisionAction.ENTER_LONG.value
    assert broker.position(SYMBOL) is not None


def test_restart_plan_entry_uses_the_stored_cash(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.ledger.set_cash(Decimal("10009.895"))
    broker = _restart(app)
    assert broker.cash == Decimal("10009.89500000")
    assert broker.open_symbols() == ()
    spy = SpyRisk(RiskManager(risk_params(app.settings)))
    _arm(app, ScriptedEngine({(SYMBOL, T15): _signal()}), spy)
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert result.decisions[0].action == DecisionAction.ENTER_LONG.value
    assert spy.plans == 1
    assert spy.equities == [Decimal("10009.89500000")]


def test_pending_entry_survives_a_restart_and_fills(tmp_path: Path) -> None:
    app = _app(tmp_path)
    spy = SpyRisk(RiskManager(risk_params(app.settings)))
    _arm(app, ScriptedEngine({(SYMBOL, T15): _signal()}), spy)
    entered = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert entered.decisions[0].action == DecisionAction.ENTER_LONG.value
    broker = _restart(app)
    (pending,) = broker.pending_for(SYMBOL)
    assert pending.plan is not None
    assert pending.entry_decision_time == T15
    _write(app, [_candle(Timeframe.M15, T15, low=99.5)])
    app.clock.now_value = T30
    _arm(app, ScriptedEngine({}), SpyRisk(RiskManager(risk_params(app.settings))))
    run_paper_bar(app, decision_time=T30, sleep=lambda _seconds: None)
    position = broker.position(SYMBOL)
    assert position is not None
    assert position.entry_decision_id == pending.decision_id
    assert broker.pending_for(SYMBOL) == ()


def test_tp1_is_not_taken_again_after_a_restart(tmp_path: Path) -> None:
    app = _app(tmp_path)
    target = PartialTarget(fraction=0.5, price=100.5, reason=PartialReason.R_MULTIPLE)
    plan = _held().plan.model_copy(update={"qty": Decimal("8"), "partial_targets": (target,)})
    # The entry fills at the T0 open and TP1 touches on the same bar.
    app.broker.queue_order(
        OrderIntent(
            intent_id="dec-held",
            decision_id="dec-held",
            symbol=SYMBOL,
            side=OrderSide.BUY,
            order_type="market",
            qty=Decimal("8"),
            reduce_only=False,
            client_order_id="dec-held",
        ),
        group_order=0,
        plan=plan,
        entry_decision_time=T0,
    )
    _arm(app, ScriptedEngine({}), SpyRisk(RiskManager(risk_params(app.settings))))
    run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    assert app.broker.position(SYMBOL).qty == Decimal("4")
    broker = _restart(app)
    assert broker.tp1_filled(SYMBOL) is True
    _write(app, [_candle(Timeframe.M15, T15, low=99.5)])
    app.clock.now_value = T30
    _arm(app, ScriptedEngine({}), SpyRisk(RiskManager(risk_params(app.settings))))
    run_paper_bar(app, decision_time=T30, sleep=lambda _seconds: None)
    assert broker.position(SYMBOL).qty == Decimal("4")
    tp1 = [fill for fill in app.ledger.load_joined_fills() if fill.client_order_id.endswith(":tp1")]
    assert len(tp1) == 1


def test_a_stale_symbol_does_not_hold_back_other_stops(tmp_path: Path) -> None:
    app = _app(tmp_path, (SYMBOL, OTHER))
    app.broker.seed(_held().model_copy(update={"stop_price": 99.7}))
    app.ledger.commit(app.broker.take_flush())
    _arm(app, ScriptedEngine({}), SpyRisk(RiskManager(risk_params(app.settings))))
    waited: list[float] = []

    def sleep(seconds: float) -> None:
        waited.append(seconds)
        app.clock.now_value += timedelta(seconds=seconds)

    result = run_paper_bar(app, decision_time=T15, sleep=sleep)
    marketdata = app.settings.marketdata
    assert result.stale is True
    assert sum(waited) <= marketdata.stale_grace_seconds + 2 * marketdata.close_wait_seconds
    assert app.broker.position(SYMBOL) is None
    stops = [fill for fill in app.ledger.load_joined_fills() if fill.client_order_id.endswith(":stop")]
    assert len(stops) == 1
    by_symbol = {decision.symbol: decision for decision in result.decisions}
    assert "stale_data" in (by_symbol[OTHER].hard_rule_json or "")
    assert "stale_data" not in (by_symbol[SYMBOL].hard_rule_json or "")


def test_a_pending_entry_off_the_board_still_fills(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _store(app, OTHER)
    plan = _held().plan.model_copy(update={"symbol": OTHER})
    ack = app.broker.queue_order(
        OrderIntent(
            intent_id="dec-other",
            decision_id="dec-other",
            symbol=OTHER,
            side=OrderSide.BUY,
            order_type="market",
            qty=Decimal("1"),
            reduce_only=False,
            client_order_id="dec-other",
        ),
        group_order=0,
        plan=plan,
        entry_decision_time=T0,
    )
    assert ack.accepted is True
    _arm(app, ScriptedEngine({}), SpyRisk(RiskManager(risk_params(app.settings))))
    result = run_paper_bar(app, decision_time=T15, sleep=lambda _seconds: None)
    position = app.broker.position(OTHER)
    assert position is not None
    assert position.entry_decision_id == "dec-other"
    exits = [decision for decision in result.decisions if decision.symbol == OTHER]
    assert len(exits) == 1
    assert exits[0].rank is None
