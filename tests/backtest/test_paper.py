"""PaperBroker records fills. It does not price stops, and it has no live twin."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chanedge.backtest.matcher import match_bar
from chanedge.domain.bars import Bar
from chanedge.domain.decision import OrderIntent
from chanedge.domain.enums import (
    OrderSide,
    Side,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
)
from chanedge.domain.records import JoinedFill
from chanedge.domain.risk import InvalidationSpec, PositionState, RiskPlan, TrailRule
from chanedge.execution.paper import InMemoryLedger, PaperBroker

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T15 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
SYMBOL = "BTC/USDT"


def test_round_trip_cash_keeps_the_fee_and_not_the_notional() -> None:
    broker = PaperBroker(InMemoryLedger(), initial_equity=Decimal("10000"))
    _queue(broker, side=OrderSide.BUY, qty=Decimal("1"), reduce_only=False, plan=_plan())
    buy = _bar(T0, open_=100.0, high=101.0, low=99.5, close=100.0)
    broker.apply(
        match_bar(
            None,
            broker.pending_for(SYMBOL),
            buy,
            fee_bps=Decimal("5"),
            slippage_bps=Decimal("0"),
            arm_close=None,
        )
    )
    assert broker.cash == Decimal("9999.95000000")
    _queue(
        broker,
        client_order_id="exit-1",
        side=OrderSide.SELL,
        qty=Decimal("1"),
        reduce_only=True,
        plan=None,
    )
    sell = _bar(T15, open_=110.0, high=111.0, low=109.0, close=110.0)
    broker.apply(
        match_bar(
            broker.position(SYMBOL),
            broker.pending_for(SYMBOL),
            sell,
            fee_bps=Decimal("5"),
            slippage_bps=Decimal("0"),
            arm_close=None,
        )
    )
    assert broker.cash == Decimal("10009.89500000")
    assert broker.position(SYMBOL) is None


def test_replay_overwrites_disagreed_cash_and_flat_rows_do_not_restore_equity() -> None:
    buy = JoinedFill(
        fill_id="buy:0",
        client_order_id="buy",
        price=Decimal("100"),
        qty=Decimal("1"),
        fee_quote=Decimal("0.05"),
        slippage_quote=Decimal("0"),
        fill_time=T0,
        bar_seq=0,
        symbol=SYMBOL,
        side="buy",
        reduce_only=False,
    )
    sell = JoinedFill(
        fill_id="sell:0",
        client_order_id="sell",
        price=Decimal("110"),
        qty=Decimal("1"),
        fee_quote=Decimal("0.055"),
        slippage_quote=Decimal("0"),
        fill_time=T15,
        bar_seq=0,
        symbol=SYMBOL,
        side="sell",
        reduce_only=True,
    )
    flat = PositionState(
        symbol=SYMBOL,
        qty=Decimal("0"),
        avg_price=100.0,
        stop_price=99.0,
        plan=_plan(qty=Decimal("0"), rejected=True),
        entry_decision_id="dec-flat",
        entry_decision_time=T0,
        entry_bar_open_time=T0,
    )
    from chanedge.domain.records import StoredPosition

    ledger = InMemoryLedger(
        fills=(buy, sell),
        cash=Decimal("1"),
        positions=(StoredPosition(state=flat, arm_close=None, updated_at=T0),),
    )
    broker = PaperBroker(ledger, initial_equity=Decimal("10000"))
    assert broker.cash == Decimal("10009.89500000")
    assert ledger.get_cash() == Decimal("10009.89500000")
    assert broker.position(SYMBOL) is None

    fresh = PaperBroker(InMemoryLedger(), initial_equity=Decimal("10000"))
    assert fresh.cash == Decimal("10000.00000000")
    stored = PaperBroker(
        InMemoryLedger(cash=Decimal("50")),
        initial_equity=Decimal("10000"),
    )
    assert stored.cash == Decimal("50.00000000")


def test_kill_switch_blocks_entries_and_still_queues_a_reduce() -> None:
    broker = PaperBroker(InMemoryLedger(), initial_equity=Decimal("10000"), kill_switch=True)
    refused = _queue(broker, side=OrderSide.BUY, qty=Decimal("1"), reduce_only=False, plan=_plan())
    assert refused.accepted is False
    assert broker.pending_for(SYMBOL) == ()
    accepted = _queue(
        broker,
        client_order_id="exit-1",
        side=OrderSide.SELL,
        qty=Decimal("1"),
        reduce_only=True,
        plan=None,
    )
    assert accepted.accepted is True
    assert len(broker.pending_for(SYMBOL)) == 1


def test_paper_does_not_price_stops_and_live_broker_is_absent() -> None:
    source = (ROOT / "src" / "chanedge" / "execution" / "paper.py").read_text(encoding="utf-8")
    assert "slippage_bps" not in source
    assert "match_bar" not in source
    assert not (ROOT / "src" / "chanedge" / "execution" / "live.py").exists()
    names = [path.name for path in (ROOT / "src" / "chanedge" / "execution").glob("*.py")]
    assert "live.py" not in names


def _queue(broker: PaperBroker, **overrides: object):
    values: dict[str, object] = {
        "intent_id": "entry-1",
        "decision_id": "dec-entry",
        "symbol": SYMBOL,
        "side": OrderSide.BUY,
        "order_type": "market",
        "qty": Decimal("1"),
        "reduce_only": False,
        "client_order_id": "entry-1",
        "limit_price": None,
    }
    plan = overrides.pop("plan", _plan())
    client = overrides.get("client_order_id", values["client_order_id"])
    values.update(overrides)
    values["intent_id"] = client
    values["decision_id"] = client
    return broker.queue_order(
        OrderIntent(**values),  # type: ignore[arg-type]
        group_order=0,
        plan=plan,
        entry_decision_time=T0,
        submitted_at=T0,
    )


def _plan(*, qty: Decimal = Decimal("1"), rejected: bool = False) -> RiskPlan:
    if rejected:
        from chanedge.domain.enums import VetoCode

        return RiskPlan(
            symbol=SYMBOL,
            side=Side.LONG,
            risk_fraction=Decimal("0.005"),
            target_risk_fraction=Decimal("0.005"),
            equity_quote=Decimal("10000"),
            qty=Decimal("0"),
            notional=Decimal("0"),
            max_notional=Decimal("20000"),
            rejected=True,
            reject_reason=VetoCode.INSTRUMENT_SPEC,
        )
    return RiskPlan(
        symbol=SYMBOL,
        side=Side.LONG,
        risk_fraction=Decimal("0.005"),
        target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"),
        qty=qty,
        notional=Decimal("100"),
        max_notional=Decimal("20000"),
        rejected=False,
        entry_reference=100.0,
        atr=0.0,
        structure_stop_price=99.0,
        stop_buffer=0.0,
        defending_fx_id="fx-def",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL, SignalType.THIRD_SELL),
            htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN, StructureBias.BREAKOUT_DOWN),
            stop_price=99.0,
            defending_fx_id="fx-def",
            effective_after=T0,
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


def _bar(open_time: datetime, **overrides: object) -> Bar:
    values: dict[str, object] = {
        "symbol": SYMBOL,
        "timeframe": Timeframe.M15,
        "open_time": open_time,
        "close_time": open_time + timedelta(minutes=15),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1.0,
        "is_closed": True,
        "source": "binanceusdm",
    }
    if "open_" in overrides:
        values["open"] = overrides.pop("open_")
    values.update(overrides)
    return Bar(**values)  # type: ignore[arg-type]
