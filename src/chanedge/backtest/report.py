"""Parquet, timing, and summary for one backtest directory.

SQLite stays on the injected report sink. This module does not import journal.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from chanedge.domain.accounting import quantize
from chanedge.domain.chanlun import ChanSnapshot
from chanedge.domain.enums import Direction, ExitReason, Side, SignalType, VetoCode
from chanedge.domain.records import FillRecord

_ZERO = Decimal("0")
_EXIT_REASONS = tuple(reason.value for reason in ExitReason)
_SIGNAL_TYPES = (
    SignalType.SECOND_BUY.value,
    SignalType.THIRD_BUY.value,
    SignalType.SECOND_SELL.value,
    SignalType.THIRD_SELL.value,
)


def write_report(directory: Path, *, trades: list[dict], shadows: list[dict], equity: list[dict], summary: dict, timing: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_table(directory / "trades.parquet", trades, _TRADE_FIELDS)
    _write_table(directory / "shadows.parquet", shadows, _SHADOW_FIELDS)
    _write_table(directory / "equity.parquet", equity, _EQUITY_FIELDS)
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    (directory / "timing.json").write_text(
        json.dumps(
            {
                "elapsed_ms": timing["elapsed_ms"],
                "decision_count": timing["decision_count"],
                "mean_decision_ms": timing["mean_decision_ms"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_trades(
    fills: list[FillRecord],
    meta: dict[str, dict],
    seeds: dict[str, dict],
    instruments: dict,
) -> list[dict]:
    """Walk fills in time order. A flat quantity closes one trade."""
    grouped: dict[str, list[FillRecord]] = {}
    for fill in fills:
        grouped.setdefault(fill.symbol, []).append(fill)
    trades: list[dict] = []
    for symbol, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: (item.fill_time, item.bar_seq, 0 if item.reduce_only else 1))
        state = _seed_state(seeds.get(symbol))
        partial = None
        events: list[tuple[datetime, Decimal, Decimal]] = []
        for fill in ordered:
            if state is None and not fill.reduce_only:
                state = _open_state(fill, meta.get(fill.decision_id, {}))
                partial = None
                events = [(fill.fill_time, state["qty"], state["avg"])]
                continue
            if state is None or not fill.reduce_only:
                continue
            qty = state["qty"]
            if qty > _ZERO:
                qty = quantize(qty - fill.qty)
            else:
                qty = quantize(qty + fill.qty)
            if fill.partial_reason:
                partial = fill.partial_reason
            events.append((fill.fill_time, qty, state["avg"]))
            if qty != _ZERO:
                state["qty"] = qty
                continue
            source = instruments.get(symbol)
            trades.append(
                _trade_row(
                    symbol,
                    state,
                    fill,
                    partial,
                    events,
                    None if source is None else source.instrument_source.value,
                )
            )
            state = None
            partial = None
            events = []
    return trades


def attach_funding(trades: list[dict], source) -> int:
    """None source leaves the column empty and counts no missing months."""
    if source is None:
        for trade in trades:
            trade["funding_estimate_quote"] = None
        return 0
    missing: set[tuple[str, int, int]] = set()
    for trade in trades:
        months = source.months(trade["symbol"], trade["_entry_at"], trade["_exit_at"])
        absent = [month for month in months if not month.present]
        if absent:
            trade["funding_estimate_quote"] = None
            for month in absent:
                missing.add((trade["symbol"], month.year, month.month))
            continue
        total = _ZERO
        for month in months:
            for point in month.points:
                if not trade["_entry_at"] < point.calc_time <= trade["_exit_at"]:
                    continue
                open_qty = _qty_before(trade["_events"], point.calc_time)
                if open_qty is None or open_qty[0] == _ZERO:
                    continue
                qty, avg = open_qty
                signed = abs(qty) * avg * quantize(point.rate)
                if trade["side"] == "short":
                    signed = -signed
                total += signed
        trade["funding_estimate_quote"] = format(quantize(total), ".8f")
    return len(missing)


def build_summary(
    *,
    decisions: list,
    trades: list[dict],
    overlaps: list[float],
    signals: list[dict],
    snapshots: dict[str, ChanSnapshot],
    weights: dict[str, float],
    overlap_peak: float,
    overlap_width: float,
    overlap_penalty_above: float,
    missing_funding_months: int,
    fee_drag: Decimal,
    exposure_bars: int,
    equity: list[dict],
    inferred_fill_count: int,
) -> dict:
    replaced = _endpoint_ratios(signals, snapshots)
    terms = [_tent(value, overlap_peak, overlap_width) for value in overlaps]
    above = [value for value in overlaps if value > overlap_penalty_above]
    return {
        "endpoint_replaced_ratio": replaced,
        "second_buy_reemit_count": _reemit(signals),
        "inside_low_broke_prior_end": _inside_low(snapshots),
        "overlap_term_mean": None if not terms else sum(terms) / len(terms),
        "overlap_penalty_fraction": None if not overlaps else len(above) / len(overlaps),
        "cost_r_by_symbol": _reason_counts(decisions, VetoCode.COST_R.value),
        "inferred_fill_count": inferred_fill_count,
        "instrument_spec_count": sum(_reason_counts(decisions, VetoCode.INSTRUMENT_SPEC.value).values()),
        "min_qty_count": sum(_reason_counts(decisions, VetoCode.MIN_QTY.value).values()),
        "veto_histogram": _veto_histogram(decisions),
        "risk_reject_histogram": _risk_histogram(decisions),
        "by_signal": {name: _stats([row for row in trades if row.get("signal_type") == name]) for name in _SIGNAL_TYPES},
        "by_exit_reason": {name: _stats([row for row in trades if row.get("exit_reason") == name]) for name in _EXIT_REASONS},
        "partial_then_remainder": _partial_split(trades),
        "session_weight_zero_action_diffs": _session_diffs(decisions, weights),
        "missing_funding_months": missing_funding_months,
        "fee_drag": format(quantize(fee_drag), ".8f"),
        "max_drawdown": _drawdown(equity),
        "exposure_bars": exposure_bars,
    }


def _seed_state(seed: dict | None) -> dict | None:
    if seed is None:
        return None
    return {
        "qty": quantize(seed["qty"]),
        "avg": quantize(seed["avg"]),
        "opened_at": seed["opened_at"],
        "side": "long" if quantize(seed["qty"]) > _ZERO else "short",
        "signal_type": seed.get("signal_type"),
        "target_risk_fraction": seed.get("target_risk_fraction"),
        "realized_risk_fraction": seed.get("realized_risk_fraction"),
        "binding_constraint": seed.get("binding_constraint"),
        "cost_r": seed.get("cost_r"),
        "entry_price": quantize(seed["avg"]),
    }


def _open_state(fill: FillRecord, meta: dict) -> dict:
    qty = fill.qty if fill.side == "buy" else -fill.qty
    return {
        "qty": quantize(qty),
        "avg": quantize(fill.price),
        "opened_at": fill.fill_time,
        "side": "long" if qty > _ZERO else "short",
        "signal_type": meta.get("signal_type"),
        "target_risk_fraction": meta.get("target_risk_fraction"),
        "realized_risk_fraction": meta.get("realized_risk_fraction"),
        "binding_constraint": meta.get("binding_constraint"),
        "cost_r": meta.get("cost_r"),
        "entry_price": quantize(fill.price),
    }


def _trade_row(symbol, state, fill, partial, events, instrument_source) -> dict:
    entry = state["entry_price"]
    side = state["side"]
    sign = Decimal(1) if side == "long" else Decimal(-1)
    pnl = (quantize(fill.price) - entry) * sign * abs(state["qty"] if state["qty"] != _ZERO else fill.qty)
    # state qty was just moved to zero; the closed quantity is the fill when it flattens the remainder.
    closed_qty = fill.qty
    pnl = (quantize(fill.price) - entry) * sign * closed_qty
    return {
        "symbol": symbol,
        "side": side,
        "qty": format(closed_qty, ".8f"),
        "entry_price": format(entry, ".8f"),
        "exit_price": format(fill.price, ".8f"),
        "entry_time": state["opened_at"].isoformat(),
        "exit_time": fill.fill_time.isoformat(),
        "exit_reason": fill.exit_reason,
        "signal_type": state["signal_type"],
        "target_risk_fraction": _text(state["target_risk_fraction"]),
        "realized_risk_fraction": _text(state["realized_risk_fraction"]),
        "binding_constraint": state["binding_constraint"],
        "cost_r": _text(state["cost_r"]),
        "instrument_source": instrument_source,
        "funding_estimate_quote": None,
        "partial_reason": partial,
        "pnl": format(quantize(pnl), ".8f"),
        "r_multiple": None,
        "_entry_at": state["opened_at"],
        "_exit_at": fill.fill_time,
        "_events": list(events),
    }


def _qty_before(events, calc_time: datetime):
    current = None
    for when, qty, avg in events:
        if when < calc_time:
            current = (qty, avg)
    return current


def _endpoint_ratios(signals: list[dict], snapshots: dict[str, ChanSnapshot]) -> dict[str, float | None]:
    buckets: dict[str, list[bool]] = {name: [] for name in _SIGNAL_TYPES}
    for signal in signals:
        name = signal.get("signal_type")
        if name not in buckets:
            continue
        snapshot = snapshots.get(signal["symbol"])
        replaced = True
        if snapshot is not None:
            ends = {bi.start_fx_id for bi in snapshot.bis} | {bi.end_fx_id for bi in snapshot.bis}
            replaced = signal.get("defending_fx_id") not in ends
        buckets[name].append(replaced)
    return {name: None if not rows else sum(1 for row in rows if row) / len(rows) for name, rows in buckets.items()}


def _reemit(signals: list[dict]) -> int:
    counts: dict[str, int] = {}
    for signal in signals:
        if signal.get("signal_type") != SignalType.SECOND_BUY.value:
            continue
        bi_id = signal.get("related_bi_id")
        if not bi_id:
            continue
        counts[bi_id] = counts.get(bi_id, 0) + 1
    return sum(max(0, count - 1) for count in counts.values())


def _inside_low(snapshots: dict[str, ChanSnapshot]) -> dict[str, float | int | None]:
    comparable = 0
    broken = 0
    for snapshot in snapshots.values():
        downs = [bi for bi in snapshot.bis if bi.direction is Direction.DOWN and bi.confirmed]
        downs.sort(key=lambda bi: bi.end_time)
        for index, bi in enumerate(downs):
            if index == 0:
                continue
            prior = downs[index - 1]
            comparable += 1
            if bi.end_price > prior.end_price and bi.low < prior.end_price:
                broken += 1
    return {
        "count": broken,
        "comparable": comparable,
        "ratio": None if comparable == 0 else broken / comparable,
    }


def _reason_counts(decisions: list, code: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        plan = decision.plan
        if plan is None or plan.reject_reason is None or plan.reject_reason.value != code:
            continue
        counts[decision.decision.symbol] = counts.get(decision.decision.symbol, 0) + 1
    return counts


def _veto_histogram(decisions: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        rules = decision.rules
        if rules is None:
            continue
        for veto in rules.vetoes:
            counts[veto.code.value] = counts.get(veto.code.value, 0) + 1
    return counts


def _risk_histogram(decisions: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        plan = decision.plan
        if plan is None or plan.reject_reason is None:
            continue
        code = plan.reject_reason.value
        counts[code] = counts.get(code, 0) + 1
    return counts


def _partial_split(trades: list[dict]) -> dict[str, dict[str, int]]:
    split = {name: {reason: 0 for reason in _EXIT_REASONS} for name in ("prior_swing", "r_multiple")}
    for trade in trades:
        kind = trade.get("partial_reason")
        reason = trade.get("exit_reason")
        if kind in split and reason in split[kind]:
            split[kind][reason] += 1
    return split


def _session_diffs(decisions: list, weights: dict[str, float]) -> int:
    diffs = 0
    for decision in decisions:
        assessment = decision.assessment
        if assessment is None or decision.group != "entry":
            continue
        if _action_changes(assessment, weights):
            diffs += 1
    return diffs


def _action_changes(assessment, weights: dict[str, float]) -> bool:
    rest = 1.0 - float(weights["session"])
    score = 0.0
    if rest > 0:
        for name in ("structure", "location", "resonance", "volatility_volume", "signal_bar"):
            score += (float(weights[name]) / rest) * assessment.components[name].adjusted
    if assessment.candidate_side is Side.LONG and score >= assessment.threshold:
        proposed = "BUY"
    elif assessment.candidate_side is Side.SHORT and score >= assessment.threshold:
        proposed = "SELL"
    else:
        proposed = "HOLD"
    return proposed != assessment.proposed_action.value


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "profit_factor": None, "win_rate": None, "mean_r": None}
    pnls = [Decimal(row["pnl"]) for row in rows]
    wins = [value for value in pnls if value > _ZERO]
    losses = [value for value in pnls if value < _ZERO]
    gross_loss = -sum(losses, _ZERO)
    factor = None if gross_loss == _ZERO else float(sum(wins, _ZERO) / gross_loss)
    rs = [Decimal(row["r_multiple"]) for row in rows if row.get("r_multiple")]
    return {
        "count": len(rows),
        "profit_factor": factor,
        "win_rate": len(wins) / len(rows),
        "mean_r": None if not rs else float(sum(rs, _ZERO) / Decimal(len(rs))),
    }


def _drawdown(equity: list[dict]) -> str:
    peak = None
    worst = 0.0
    for point in equity:
        value = float(point["equity"])
        if peak is None or value > peak:
            peak = value
        if peak:
            worst = max(worst, (peak - value) / peak)
    return format(worst, ".8f")


def _tent(value: float, peak: float, width: float) -> float:
    if width <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - abs(value - peak) / width))


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(quantize(value), ".8f")
    return str(value)


def _json_default(value):
    if isinstance(value, Decimal):
        return format(value, ".8f")
    raise TypeError(f"cannot encode {type(value).__name__}")


def _write_table(path: Path, rows: list[dict], fields: list[tuple[str, pa.DataType]]) -> None:
    schema = pa.schema(fields)
    public = [{name: row.get(name) for name, _kind in fields} for row in rows]
    table = pa.Table.from_pylist(public, schema=schema)
    pq.write_table(table, path)


_TRADE_FIELDS = [
    ("symbol", pa.string()),
    ("side", pa.string()),
    ("qty", pa.string()),
    ("entry_price", pa.string()),
    ("exit_price", pa.string()),
    ("entry_time", pa.string()),
    ("exit_time", pa.string()),
    ("exit_reason", pa.string()),
    ("signal_type", pa.string()),
    ("target_risk_fraction", pa.string()),
    ("realized_risk_fraction", pa.string()),
    ("binding_constraint", pa.string()),
    ("cost_r", pa.string()),
    ("instrument_source", pa.string()),
    ("funding_estimate_quote", pa.string()),
    ("partial_reason", pa.string()),
    ("pnl", pa.string()),
    ("r_multiple", pa.string()),
]

_SHADOW_FIELDS = [
    ("shadow", pa.bool_()),
    ("symbol", pa.string()),
    ("decision_time", pa.string()),
    ("signal_id", pa.string()),
    ("signal_type", pa.string()),
    ("qty", pa.string()),
    ("entry_price", pa.string()),
    ("exit_price", pa.string()),
    ("exit_reason", pa.string()),
    ("closed", pa.bool_()),
    ("unfinished", pa.bool_()),
    ("r_multiple", pa.string()),
]

_EQUITY_FIELDS = [
    ("time", pa.string()),
    ("equity", pa.string()),
    ("cash", pa.string()),
]
