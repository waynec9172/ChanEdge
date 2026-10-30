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
    """Walk fills in time order. A flat quantity closes one trade.

    pnl adds every exit leg (TP1 and the final exit) and subtracts every fee,
    entry included. r_multiple is that pnl over opened qty times the entry R.
    """
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
            sign = Decimal(1) if qty > _ZERO else Decimal(-1)
            state["realized"] += (quantize(fill.price) - state["avg"]) * sign * fill.qty
            state["fees"] += fill.fee_quote
            qty = quantize(qty - fill.qty) if qty > _ZERO else quantize(qty + fill.qty)
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


class DecisionStats:
    """Summary counts gathered one decision at a time, so the run does not keep the decisions."""

    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = weights
        self.count = 0
        self.vetoes: dict[str, int] = {}
        self.risk: dict[str, int] = {}
        self.risk_by_symbol: dict[str, dict[str, int]] = {}
        self.session_diffs = 0

    def add(self, result) -> None:
        self.count += 1
        if result.rules is not None:
            for veto in result.rules.vetoes:
                self.vetoes[veto.code.value] = self.vetoes.get(veto.code.value, 0) + 1
        plan = result.plan
        if plan is not None and plan.reject_reason is not None:
            code = plan.reject_reason.value
            self.risk[code] = self.risk.get(code, 0) + 1
            by_symbol = self.risk_by_symbol.setdefault(code, {})
            symbol = result.decision.symbol
            by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        assessment = result.assessment
        if assessment is not None and result.group == "entry" and _action_changes(assessment, self.weights):
            self.session_diffs += 1

    def by_symbol(self, code: str) -> dict[str, int]:
        return dict(self.risk_by_symbol.get(code, {}))


def build_summary(
    *,
    stats: DecisionStats,
    trades: list[dict],
    overlaps: list[float],
    research: ResearchTracker,
    overlap_peak: float,
    overlap_width: float,
    overlap_penalty_above: float,
    missing_funding_months: int,
    fee_drag: Decimal,
    exposure_bars: int,
    equity: list[dict],
    inferred_fill_count: int,
) -> dict:
    tracked = research.summary()
    terms = [_tent(value, overlap_peak, overlap_width) for value in overlaps]
    above = [value for value in overlaps if value > overlap_penalty_above]
    return {
        **tracked,
        "overlap_term_mean": None if not terms else sum(terms) / len(terms),
        "overlap_penalty_fraction": None if not overlaps else len(above) / len(overlaps),
        "cost_r_by_symbol": stats.by_symbol(VetoCode.COST_R.value),
        "inferred_fill_count": inferred_fill_count,
        "instrument_spec_count": sum(stats.by_symbol(VetoCode.INSTRUMENT_SPEC.value).values()),
        "min_qty_count": sum(stats.by_symbol(VetoCode.MIN_QTY.value).values()),
        "veto_histogram": dict(stats.vetoes),
        "risk_reject_histogram": dict(stats.risk),
        "by_signal": {name: _stats([row for row in trades if row.get("signal_type") == name]) for name in _SIGNAL_TYPES},
        "by_exit_reason": {name: _stats([row for row in trades if row.get("exit_reason") == name]) for name in _EXIT_REASONS},
        "partial_then_remainder": _partial_split(trades),
        "session_weight_zero_action_diffs": stats.session_diffs,
        "missing_funding_months": missing_funding_months,
        "fee_drag": format(quantize(fee_drag), ".8f"),
        "max_drawdown": _drawdown(equity),
        "exposure_bars": exposure_bars,
    }


def _seed_state(seed: dict | None) -> dict | None:
    if seed is None:
        return None
    qty = quantize(seed["qty"])
    return {
        "qty": qty,
        "opened_qty": abs(qty),
        "avg": quantize(seed["avg"]),
        "opened_at": seed["opened_at"],
        "side": "long" if qty > _ZERO else "short",
        "signal_type": seed.get("signal_type"),
        "target_risk_fraction": seed.get("target_risk_fraction"),
        "realized_risk_fraction": seed.get("realized_risk_fraction"),
        "binding_constraint": seed.get("binding_constraint"),
        "cost_r": seed.get("cost_r"),
        "risk_per_unit": seed.get("risk_per_unit"),
        "defending_atr": seed.get("defending_atr"),
        "entry_price": quantize(seed["avg"]),
        "realized": _ZERO,
        "fees": _ZERO,
    }


def _open_state(fill: FillRecord, meta: dict) -> dict:
    qty = fill.qty if fill.side == "buy" else -fill.qty
    return {
        "qty": quantize(qty),
        "opened_qty": quantize(fill.qty),
        "avg": quantize(fill.price),
        "opened_at": fill.fill_time,
        "side": "long" if qty > _ZERO else "short",
        "signal_type": meta.get("signal_type"),
        "target_risk_fraction": meta.get("target_risk_fraction"),
        "realized_risk_fraction": meta.get("realized_risk_fraction"),
        "binding_constraint": meta.get("binding_constraint"),
        "cost_r": meta.get("cost_r"),
        "risk_per_unit": meta.get("risk_per_unit"),
        "defending_atr": meta.get("defending_atr"),
        "entry_price": quantize(fill.price),
        "realized": _ZERO,
        "fees": quantize(fill.fee_quote),
    }


def _trade_row(symbol, state, fill, partial, events, instrument_source) -> dict:
    pnl = quantize(state["realized"] - state["fees"])
    risk = state.get("risk_per_unit")
    r_multiple = None
    if risk is not None and Decimal(risk) > _ZERO and state["opened_qty"] > _ZERO:
        r_multiple = format(quantize(pnl / (Decimal(risk) * state["opened_qty"])), ".8f")
    return {
        "symbol": symbol,
        "side": state["side"],
        "qty": format(state["opened_qty"], ".8f"),
        "entry_price": format(state["entry_price"], ".8f"),
        "exit_price": format(fill.price, ".8f"),
        "entry_time": state["opened_at"].isoformat(),
        "exit_time": fill.fill_time.isoformat(),
        "exit_reason": fill.exit_reason,
        "signal_type": state["signal_type"],
        "target_risk_fraction": _text(state["target_risk_fraction"]),
        "realized_risk_fraction": _text(state["realized_risk_fraction"]),
        "binding_constraint": state["binding_constraint"],
        "cost_r": _text(state["cost_r"]),
        "defending_atr": _text(state.get("defending_atr")),
        "instrument_source": instrument_source,
        "funding_estimate_quote": None,
        "partial_reason": partial,
        "fee_quote": format(quantize(state["fees"]), ".8f"),
        "pnl": format(pnl, ".8f"),
        "r_multiple": r_multiple,
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


class ResearchTracker:
    """Signal and bi statistics gathered from every 15m snapshot during the run.

    The last snapshot alone only covers the final window, and a bi id changes
    when its endpoint is replaced, so these are tracked as the walk goes.
    """

    def __init__(self) -> None:
        self._watch: dict[str, list[dict]] = {}
        self._replaced: dict[str, list[bool]] = {name: [] for name in _SIGNAL_TYPES}
        self._second_buys: dict[str, int] = {}
        self._downs: dict[tuple[str, str], tuple[bool, bool]] = {}

    def add_signal(self, symbol: str, signal_type: str, defending_fx_id: str, bi_key: str | None) -> None:
        if signal_type in self._replaced:
            self._watch.setdefault(symbol, []).append(
                {"type": signal_type, "fx": defending_fx_id, "replaced": False}
            )
        if signal_type == SignalType.SECOND_BUY.value and bi_key is not None:
            self._second_buys[bi_key] = self._second_buys.get(bi_key, 0) + 1

    def observe(self, symbol: str, snapshot: ChanSnapshot) -> None:
        pending = self._watch.get(symbol)
        if pending:
            in_window = {fx.id for fx in snapshot.fenxings}
            ends = {bi.start_fx_id for bi in snapshot.bis} | {bi.end_fx_id for bi in snapshot.bis}
            kept = []
            for item in pending:
                if item["fx"] not in in_window:
                    self._replaced[item["type"]].append(item["replaced"])
                elif item["fx"] not in ends:
                    self._replaced[item["type"]].append(True)
                else:
                    kept.append(item)
            self._watch[symbol] = kept
        downs = [bi for bi in snapshot.bis if bi.direction is Direction.DOWN and bi.confirmed]
        downs.sort(key=lambda bi: bi.end_time)
        for prior, bi in zip(downs, downs[1:]):
            higher = bi.end_price > prior.end_price
            self._downs[(symbol, bi.start_fx_id)] = (higher, higher and bi.low < prior.end_price)

    def summary(self) -> dict:
        for pending in self._watch.values():
            for item in pending:
                self._replaced[item["type"]].append(item["replaced"])
        self._watch = {}
        distribution: dict[str, int] = {}
        for count in self._second_buys.values():
            key = str(count - 1)
            distribution[key] = distribution.get(key, 0) + 1
        comparable = sum(1 for higher, _broken in self._downs.values() if higher)
        broken = sum(1 for _higher, item in self._downs.values() if item)
        return {
            "endpoint_replaced_ratio": {
                name: None if not rows else sum(1 for row in rows if row) / len(rows)
                for name, rows in self._replaced.items()
            },
            "second_buy_reemit_count": sum(max(0, count - 1) for count in self._second_buys.values()),
            "second_buy_reemit_distribution": dict(sorted(distribution.items(), key=lambda pair: int(pair[0]))),
            "inside_low_broke_prior_end": {
                "count": broken,
                "comparable": comparable,
                "ratio": None if comparable == 0 else broken / comparable,
            },
        }


def _partial_split(trades: list[dict]) -> dict[str, dict[str, int]]:
    split = {name: {reason: 0 for reason in _EXIT_REASONS} for name in ("prior_swing", "r_multiple")}
    for trade in trades:
        kind = trade.get("partial_reason")
        reason = trade.get("exit_reason")
        if kind in split and reason in split[kind]:
            split[kind][reason] += 1
    return split


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
    ("fee_quote", pa.string()),
    ("pnl", pa.string()),
    ("r_multiple", pa.string()),
    ("defending_atr", pa.string()),
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
