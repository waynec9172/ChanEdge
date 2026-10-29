"""RuleGate.evaluate(context, assessment, account, safety). Collect every veto."""

from __future__ import annotations

import math

from chanedge.domain.bars import MultiTimeframeContext
from chanedge.domain.decision import HardRuleResult, JevAssessment, Veto
from chanedge.domain.enums import (
    ProposedAction,
    Side,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
    VetoCode,
)
from chanedge.domain.params import RuleParams
from chanedge.domain.risk import AccountView, SafetyState

_BUY = (SignalType.SECOND_BUY, SignalType.THIRD_BUY)
_SELL = (SignalType.SECOND_SELL, SignalType.THIRD_SELL)
_LONG_HTF = (StructureBias.UP, StructureBias.BREAKOUT_UP)
_SHORT_HTF = (StructureBias.DOWN, StructureBias.BREAKOUT_DOWN)
_LONG_BLOCK_1H = (StructureBias.DOWN, StructureBias.BREAKOUT_DOWN)
_SHORT_BLOCK_1H = (StructureBias.UP, StructureBias.BREAKOUT_UP)


class RuleGate:
    def __init__(self, params: RuleParams) -> None:
        if not isinstance(params, RuleParams):
            raise TypeError("params must be RuleParams")
        self._params = params

    def evaluate(
        self,
        context: MultiTimeframeContext,
        assessment: JevAssessment,
        account: AccountView,
        safety: SafetyState,
    ) -> HardRuleResult:
        vetoes: list[Veto] = []
        if _both_operational_sides(context):
            _append_quality(vetoes, context, self._params)
            vetoes.append(_veto(VetoCode.AMBIGUOUS_SIGNAL, "buy and sell on the decision bar", "both", "one"))
        elif assessment.candidate_side is Side.NONE:
            _append_quality(vetoes, context, self._params)
            vetoes.append(_veto(VetoCode.NO_CANDIDATE, "no 15m candidate", "none", "one"))
        else:
            _append_unique(vetoes, context, assessment, account, safety, self._params)
        return HardRuleResult(passed=not vetoes, vetoes=tuple(vetoes))


def _both_operational_sides(context: MultiTimeframeContext) -> bool:
    """True when this 15m decision bar has both an operational buy and sell.

    evaluate does not receive FeatureVector. This does not choose third over
    second, and a confirmed signal at another time is not a candidate.
    """
    buy = False
    sell = False
    for signal in context.snapshots[Timeframe.M15].signals:
        if signal.time != context.decision_time or signal.timeframe is not Timeframe.M15:
            continue
        if signal.status is not SignalStatus.CONFIRMED:
            continue
        if signal.type in _BUY:
            buy = True
        elif signal.type in _SELL:
            sell = True
    return buy and sell


def _append_quality(vetoes: list[Veto], context: MultiTimeframeContext, params: RuleParams) -> None:
    _append_stale(vetoes, context)
    _append_gap(vetoes, context)
    _append_history(vetoes, context, params)


def _append_unique(
    vetoes: list[Veto],
    context: MultiTimeframeContext,
    assessment: JevAssessment,
    account: AccountView,
    safety: SafetyState,
    params: RuleParams,
) -> None:
    # Architecture §6 items 1–10. Item 4 (signal type) has no veto code.
    if _kill_applies(assessment, safety):
        vetoes.append(_veto(VetoCode.KILL_SWITCH, "kill switch", "true", "false"))
    _append_stale(vetoes, context)
    _append_gap(vetoes, context)
    _append_session(vetoes, assessment, params)
    _append_direction(vetoes, context, assessment)
    _append_vol(vetoes, assessment, params)
    if context.universe_rank is None:
        vetoes.append(_veto(VetoCode.OUTSIDE_UNIVERSE, "universe rank", "none", "1"))
    _append_history(vetoes, context, params)
    qty = _open_qty(account, context.symbol)
    if qty is not None:
        vetoes.append(_veto(VetoCode.POSITION_OPEN, "open qty", str(qty), "0"))


def _kill_applies(assessment: JevAssessment, safety: SafetyState) -> bool:
    if not safety.kill_switch:
        return False
    side = assessment.candidate_side
    action = assessment.proposed_action
    if side is Side.LONG:
        return action is ProposedAction.BUY
    if side is Side.SHORT:
        return action is ProposedAction.SELL
    return False


def _append_stale(vetoes: list[Veto], context: MultiTimeframeContext) -> None:
    if context.data_quality.stale:
        vetoes.append(_veto(VetoCode.STALE_DATA, "stale", "true", "false"))


def _append_gap(vetoes: list[Veto], context: MultiTimeframeContext) -> None:
    if VetoCode.GAP_DATA.value in context.data_quality.reasons:
        vetoes.append(_veto(VetoCode.GAP_DATA, "gap", "gap_data", "none"))


def _append_history(vetoes: list[Veto], context: MultiTimeframeContext, params: RuleParams) -> None:
    counts = {
        timeframe: sum(1 for bar in context.bars[timeframe] if bar.is_closed) for timeframe in Timeframe
    }
    windows = {
        Timeframe.M15: params.window_15m,
        Timeframe.H1: params.window_1h,
        Timeframe.H4: params.window_4h,
    }
    if any(counts[timeframe] < windows[timeframe] for timeframe in Timeframe):
        vetoes.append(
            _veto(VetoCode.INSUFFICIENT_HISTORY, "closed bars", _series(counts), _series(windows))
        )


def _append_session(vetoes: list[Veto], assessment: JevAssessment, params: RuleParams) -> None:
    bucket = _text(assessment.components["session"].raw, "session_bucket")
    listed = ",".join(params.hard_skip_buckets)
    if bucket is None:
        vetoes.append(_veto(VetoCode.SESSION_SKIP, "session bucket missing", "", listed))
    elif bucket in params.hard_skip_buckets:
        vetoes.append(_veto(VetoCode.SESSION_SKIP, "hard skip bucket", bucket, listed))


def _append_direction(
    vetoes: list[Veto], context: MultiTimeframeContext, assessment: JevAssessment
) -> None:
    if assessment.candidate_side is Side.LONG:
        allowed = _LONG_HTF
        blocked = _LONG_BLOCK_1H
    else:
        allowed = _SHORT_HTF
        blocked = _SHORT_BLOCK_1H
    bias_4h = context.snapshots[Timeframe.H4].structure_bias
    if bias_4h not in allowed:
        vetoes.append(_veto(VetoCode.HTF_DIRECTION, "4h bias", bias_4h.value, _names(allowed)))
    bias_1h = context.snapshots[Timeframe.H1].structure_bias
    if bias_1h in blocked:
        vetoes.append(_veto(VetoCode.MTF_1H_CONFLICT, "1h bias", bias_1h.value, "not " + _names(blocked)))


def _append_vol(vetoes: list[Veto], assessment: JevAssessment, params: RuleParams) -> None:
    pct = _number(assessment.components["volatility_volume"].raw, "atr_pct")
    band = f"{_fixed(params.atr_pct_min)},{_fixed(params.atr_pct_max)}"
    if pct is None:
        vetoes.append(_veto(VetoCode.VOL_BAND, "atr_pct missing", "", band))
    elif pct < params.atr_pct_min or pct > params.atr_pct_max:
        vetoes.append(_veto(VetoCode.VOL_BAND, "atr_pct", _fixed(pct), band))


def _open_qty(account: AccountView, symbol: str) -> object | None:
    for position in account.positions:
        if position.symbol == symbol and position.qty != 0:
            return position.qty
    return None


def _text(raw: dict[str, float | int | str | bool | None], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str) and value != "":
        return value
    return None


def _number(raw: dict[str, float | int | str | bool | None], key: str) -> float | None:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _series(values: dict[Timeframe, int]) -> str:
    return ",".join(f"{timeframe.value}={values[timeframe]}" for timeframe in Timeframe)


def _names(biases: tuple[StructureBias, ...]) -> str:
    return ",".join(bias.value for bias in biases)


def _fixed(value: float) -> str:
    return format(value, ".8f")


def _veto(code: VetoCode, message: str, measured: str, threshold: str) -> Veto:
    return Veto(code=code, message=message, measured=measured, threshold=threshold)
