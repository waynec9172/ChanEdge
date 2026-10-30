"""Report rows: every exit leg counts, R is filled, research metrics follow the walk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from chanedge.backtest.report import ResearchTracker, build_trades
from chanedge.domain.chanlun import Bi, ChanSnapshot, Fenxing
from chanedge.domain.enums import Direction, Mark, StructureBias, Timeframe
from chanedge.domain.records import FillRecord

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _fill(fill_id: str, side: str, qty: str, price: str, *, minutes: int, reduce_only: bool, partial=None, reason=None) -> FillRecord:
    return FillRecord(
        fill_id=fill_id,
        client_order_id=fill_id,
        decision_id="dec-entry" if not reduce_only else fill_id,
        symbol="BTC/USDT",
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        fee_quote=Decimal("0.1"),
        slippage_quote=Decimal("0"),
        fill_time=T0 + timedelta(minutes=minutes),
        bar_seq=0,
        reduce_only=reduce_only,
        exit_reason=reason,
        partial_reason=partial,
    )


def test_trade_pnl_adds_the_tp1_leg_and_fees_and_fills_r() -> None:
    fills = [
        _fill("in", "buy", "10", "100", minutes=0, reduce_only=False),
        _fill("tp1", "sell", "5", "110", minutes=15, reduce_only=True, partial="prior_swing"),
        _fill("out", "sell", "5", "100", minutes=30, reduce_only=True, reason="breakeven_stop"),
    ]
    meta = {"dec-entry": {"signal_type": "second_buy", "risk_per_unit": Decimal("5"), "defending_atr": Decimal("1.5")}}
    (trade,) = build_trades(fills, meta, {}, {})
    assert trade["qty"] == "10.00000000"
    assert trade["pnl"] == "49.70000000"
    assert trade["fee_quote"] == "0.30000000"
    assert trade["r_multiple"] == "0.99400000"
    assert trade["defending_atr"] == "1.50000000"
    assert trade["exit_reason"] == "breakeven_stop"
    assert trade["partial_reason"] == "prior_swing"


def _fx(fx_id: str, minutes: int, price: float, mark: Mark) -> Fenxing:
    when = T0 + timedelta(minutes=minutes)
    return Fenxing(
        id=fx_id, timeframe=Timeframe.M15, mark=mark, index=0, time=when, price=price,
        bar_open_time=when, confirmed=True, k_index_left=0, k_index_mid=1, k_index_right=2,
    )


def _down(bi_id: str, start: str, end: str, end_price: float, low: float, minutes: int) -> Bi:
    return Bi(
        id=bi_id, timeframe=Timeframe.M15, direction=Direction.DOWN, start_fx_id=start, end_fx_id=end,
        start_time=T0, end_time=T0 + timedelta(minutes=minutes), start_price=120.0, end_price=end_price,
        high=120.0, low=low, bar_count=5, confirmed=True,
    )


def _snap(fenxings, bis) -> ChanSnapshot:
    return ChanSnapshot(
        snapshot_id="cs_0123456789abcdef", symbol="BTC/USDT", timeframe=Timeframe.M15, as_of=T0,
        config_hash="cfg", engine_version="eng", bar_window_hash="h", bars_start=T0, bars_end=T0,
        bar_count=1, fenxings=tuple(fenxings), bis=tuple(bis), segments=(), zhongshus=(), signals=(),
        structure_bias=StructureBias.NEUTRAL,
    )


def test_research_tracks_replacement_reemits_and_inside_lows_during_the_run() -> None:
    tracker = ResearchTracker()
    first_end = _fx("fx-l1", 30, 100.0, Mark.BOTTOM)
    tracker.add_signal("BTC/USDT", "second_buy", "fx-l1", "BTC/USDT|fx-top")
    tracker.observe("BTC/USDT", _snap([first_end], [_down("bi-a", "fx-top", "fx-l1", 100.0, 100.0, 30)]))
    lower = _fx("fx-l2", 60, 99.0, Mark.BOTTOM)
    # The same down bi, endpoint replaced: new bi id, same start fenxing.
    tracker.add_signal("BTC/USDT", "second_buy", "fx-l2", "BTC/USDT|fx-top")
    prior = _down("bi-prior", "fx-old", "fx-p", 95.0, 95.0, 0)
    tracker.observe(
        "BTC/USDT",
        _snap([first_end, lower], [prior, _down("bi-b", "fx-top", "fx-l2", 99.0, 94.0, 60)]),
    )
    summary = tracker.summary()
    assert summary["endpoint_replaced_ratio"]["second_buy"] == 0.5
    assert summary["second_buy_reemit_count"] == 1
    assert summary["second_buy_reemit_distribution"] == {"1": 1}
    assert summary["inside_low_broke_prior_end"] == {"count": 1, "comparable": 1, "ratio": 1.0}


def test_shadow_r_counts_the_tp1_leg() -> None:
    from chanedge.backtest.shadow import ShadowBook
    from chanedge.domain.bars import Bar
    from chanedge.domain.chanlun import ChanSignal
    from chanedge.domain.enums import PartialReason, Side, SignalStatus, SignalType, TrailKind
    from chanedge.domain.risk import InvalidationSpec, PartialTarget, RiskPlan, TrailRule

    plan = RiskPlan(
        symbol="BTC/USDT", side=Side.LONG, risk_fraction=Decimal("0.005"), target_risk_fraction=Decimal("0.005"),
        equity_quote=Decimal("10000"), qty=Decimal("10"), notional=Decimal("1000"), max_notional=Decimal("20000"),
        rejected=False, entry_reference=100.0, atr=1.0, structure_stop_price=95.0, stop_buffer=0.15,
        defending_fx_id="fx", realized_risk_fraction=Decimal("0.005"), cost_r=Decimal("0.1"),
        binding_constraint="risk_fraction",
        invalidation=InvalidationSpec(
            opposite_signal_types=(SignalType.SECOND_SELL,), htf_timeframe=Timeframe.H1,
            htf_bias_exit=(StructureBias.DOWN,), stop_price=95.0, defending_fx_id="fx", effective_after=T0,
        ),
        partial_targets=(PartialTarget(fraction=0.5, price=110.0, reason=PartialReason.PRIOR_SWING),),
        trail=TrailRule(kind=TrailKind.STRUCTURE_FENXING, arm_r=1.0, breakeven_price=100.0, buffer=0.15),
    )
    signal = ChanSignal(
        id="sig", timeframe=Timeframe.M15, type=SignalType.SECOND_BUY, status=SignalStatus.CONFIRMED, time=T0,
        price=100.0, direction=Direction.UP, defending_fx_id="fx", defending_price=96.0, related_bi_id="bi",
        bar_open_time=T0,
    )

    def bar(minutes: int, open_: float, high: float, low: float) -> Bar:
        when = T0 + timedelta(minutes=minutes)
        return Bar(symbol="BTC/USDT", timeframe=Timeframe.M15, open_time=when, close_time=when + timedelta(minutes=15),
                   open=open_, high=high, low=low, close=open_, volume=1, is_closed=True, source="t")

    book = ShadowBook()
    book.open_shadow("BTC/USDT", plan, signal, T0)
    book.match("BTC/USDT", bar(15, 100.0, 111.0, 99.0), fee_bps=Decimal(0), slippage_bps=Decimal(0))
    book.match("BTC/USDT", bar(30, 96.0, 96.0, 94.0), fee_bps=Decimal(0), slippage_bps=Decimal(0))
    # TP1: 5 x +10. Stop: open 96 is above 95, so 5 x -5 at 95. Total 25 over 10 x 5 risk.
    assert book.rows[0]["r_multiple"] == "0.50000000"
