"""One symbol, one closed 15m bar. The loop owns order, exposure, and commits.

full_log and flattened arrive on the request. This function does not read
Settings, does not scan the universe, and does not size shadow positions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from chanedge.chanlun.engine import window_hash
from chanedge.domain.accounting import quantize
from chanedge.domain.bars import MultiTimeframeContext
from chanedge.domain.canon import format_time_z
from chanedge.domain.decision import HardRuleResult, OrderIntent, ReasonStep, Veto
from chanedge.domain.enums import (
    DecisionAction,
    OrderSide,
    ProposedAction,
    ReasonStage,
    Side,
    Timeframe,
    VetoCode,
)
from chanedge.domain.ids import decision_id
from chanedge.domain.params import RuleParams
from chanedge.domain.ports import Broker, ChanEngine, FeatureBuilder, JevModel, RiskManager, RuleGate
from chanedge.domain.records import DecisionRecord, PendingOrder, PipelineRequest, PipelineResult
from chanedge.domain.serialize import dump_model, dump_model_omit_none, dump_models
from chanedge.features.select import select_candidate
from chanedge.jev.model import hold_carrier

_ENTRY = "entry"
_EXIT = "exit"


@dataclass
class PipelineServices:
    engine: ChanEngine
    features: FeatureBuilder
    jev: JevModel
    rules: RuleGate
    risk: RiskManager
    broker: Broker
    rule_params: RuleParams
    log_jev: JevModel | None = None
    score_after_preflight: bool = False
    warm: bool = False


def run_pipeline(request: PipelineRequest, services: PipelineServices) -> PipelineResult:
    if request.group not in (_ENTRY, _EXIT):
        raise ValueError("group is entry or exit")
    if request.flattened:
        return _flattened(request)
    bars_15 = tuple(request.bars.get(Timeframe.M15, ()))
    if not bars_15:
        if request.group != _ENTRY or request.full_log:
            raise ValueError("15m window is empty")
        return _slim(request, services, None)
    snap_15 = _reuse_or_compute(services, bars_15, Timeframe.M15, request.previous)
    candidate, ambiguous_ids = select_candidate(snap_15.signals, request.decision_time)
    slim = (
        request.group == _ENTRY
        and not request.full_log
        and candidate is None
        and len(ambiguous_ids) == 0
    )
    if slim:
        return _slim(request, services, snap_15)
    bars_1h = tuple(request.bars.get(Timeframe.H1, ()))
    bars_4h = tuple(request.bars.get(Timeframe.H4, ()))
    if not bars_1h or not bars_4h:
        return _short_history(request, services, snap_15)
    snapshots = {
        Timeframe.M15: snap_15,
        Timeframe.H1: _reuse_or_compute(services, bars_1h, Timeframe.H1, request.previous),
        Timeframe.H4: _reuse_or_compute(services, bars_4h, Timeframe.H4, request.previous),
    }
    context = _context(request, snapshots)
    if request.group == _EXIT:
        result = _exit(request, services, context, snapshots, candidate, ambiguous_ids)
    else:
        result = _entry(request, services, context, snapshots, candidate, ambiguous_ids)
    if request.shadow_position is not None and result.context is not None:
        review = services.risk.review_open(result.context, request.shadow_position)
        return _replace(result, shadow_review=review)
    return result


def _flattened(request: PipelineRequest) -> PipelineResult:
    steps = (
        ReasonStep(stage=ReasonStage.EXECUTION, code="FLATTENED_THIS_BAR", detail="flat this bar"),
    )
    return _finish(
        request,
        action=DecisionAction.HOLD,
        steps=steps,
        submitted=False,
        candidate=None,
        ambiguous=False,
        features=None,
        assessment=None,
        rules=None,
        plan=None,
        context=None,
        amend=None,
        bar_close=None,
        order=None,
        snapshots={},
        shadow_review=None,
        include_ids=False,
    )


def _slim(request: PipelineRequest, services: PipelineServices, snap_15) -> PipelineResult:
    rules = _slim_rules(request, services.rule_params)
    steps = tuple(
        ReasonStep(
            stage=ReasonStage.CHANLUN if veto.code is VetoCode.NO_CANDIDATE else ReasonStage.DATA,
            code=veto.code.value,
            detail=veto.message,
        )
        for veto in rules.vetoes
    )
    snapshots = {} if snap_15 is None else {Timeframe.M15: snap_15}
    return _finish(
        request,
        action=DecisionAction.HOLD,
        steps=steps,
        submitted=False,
        candidate=None,
        ambiguous=False,
        features=None,
        assessment=None,
        rules=rules,
        plan=None,
        context=None,
        amend=None,
        bar_close=None,
        order=None,
        snapshots=snapshots,
        shadow_review=None,
        include_ids=False,
    )


def _short_history(request: PipelineRequest, services: PipelineServices, snap_15) -> PipelineResult:
    """A 1H or 4H window is empty, so no context can be built. HOLD on the data vetoes.

    A new listing or an unfilled history lands here instead of raising out of the
    paper loop. The frozen stop and TP1 still match; only this bar's review waits.
    """
    rules = HardRuleResult(passed=False, vetoes=tuple(_data_vetoes(request, services.rule_params)))
    steps = tuple(
        ReasonStep(stage=ReasonStage.DATA, code=veto.code.value, detail=veto.message)
        for veto in rules.vetoes
    )
    return _finish(
        request,
        action=DecisionAction.HOLD,
        steps=steps,
        submitted=False,
        candidate=None,
        ambiguous=False,
        features=None,
        assessment=None,
        rules=rules,
        plan=None,
        context=None,
        amend=None,
        bar_close=None,
        order=None,
        snapshots={Timeframe.M15: snap_15},
        shadow_review=None,
        include_ids=False,
        stop_price=None if request.position is None else quantize(request.position.stop_price),
    )


def _exit(request, services, context, snapshots, candidate, ambiguous_ids):
    if request.position is None or request.position.qty == 0:
        raise ValueError("exit group needs an open position")
    features = services.features.build(context)
    scorer = services.log_jev or services.jev
    assessment = scorer.assess(features)
    review = services.risk.review_open(context, request.position)
    bar_close = _bar_close(context, request)
    ambiguous = len(ambiguous_ids) > 0
    if review.exit is not None:
        action = DecisionAction.EXIT
        side = OrderSide.SELL if request.position.qty > 0 else OrderSide.BUY
        ident = _ident(request, action)
        intent = OrderIntent(
            intent_id=ident,
            decision_id=ident,
            symbol=request.symbol,
            side=side,
            order_type=request.order_type,
            qty=review.exit.qty,
            reduce_only=True,
            client_order_id=ident,
        )
        submitted, order = _queue(
            services,
            request,
            intent,
            exit_reason=review.exit.reason,
            plan=None,
            entry_decision_time=None,
        )
        if not submitted and request.record:
            action = DecisionAction.HOLD
            order = None
            steps = (
                ReasonStep(stage=ReasonStage.EXECUTION, code="rejected", detail="submit"),
            )
        else:
            steps = (
                ReasonStep(
                    stage=ReasonStage.RISK,
                    code=review.exit.reason.value,
                    detail="next_open",
                ),
            )
        return _finish(
            request,
            action=action,
            steps=steps,
            submitted=submitted and request.record,
            candidate=candidate,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=None,
            plan=None,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=order,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
            size_qty=abs(request.position.qty),
            stop_price=quantize(request.position.stop_price),
        )
    if review.amend_stop is not None:
        amend = review.amend_stop
        steps = (
            ReasonStep(
                stage=ReasonStage.RISK,
                code=amend.reason.value,
                detail=format(amend.new_stop_price, ".8f"),
            ),
        )
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=steps,
            submitted=False,
            candidate=candidate,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=None,
            plan=None,
            context=context,
            amend=amend,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
            stop_price=quantize(amend.new_stop_price),
        )
    steps = (ReasonStep(stage=ReasonStage.RISK, code="HOLD", detail="review"),)
    return _finish(
        request,
        action=DecisionAction.HOLD,
        steps=steps,
        submitted=False,
        candidate=candidate,
        ambiguous=ambiguous,
        features=features,
        assessment=assessment,
        rules=None,
        plan=None,
        context=context,
        amend=None,
        bar_close=bar_close,
        order=None,
        snapshots=snapshots,
        shadow_review=None,
        include_ids=True,
        stop_price=quantize(request.position.stop_price),
    )


_JEV_CODE = {
    "timeout": "JEV_TIMEOUT",
    "http_error": "JEV_HTTP_ERROR",
    "malformed": "JEV_MALFORMED",
    "model_mismatch": "JEV_MODEL_MISMATCH",
    "cache_miss": "JEV_CACHE_MISS",
    "missing_key": "JEV_NO_KEY",
}


def _entry(request, services, context, snapshots, candidate, ambiguous_ids):
    features = services.features.build(context)
    ambiguous = len(ambiguous_ids) > 0 or bool(features.ambiguous_signal_ids)
    chosen = None if ambiguous else candidate
    bar_close = _bar_close(context, request)
    if services.score_after_preflight:
        return _entry_after_preflight(
            request,
            services,
            context,
            snapshots,
            features,
            chosen,
            ambiguous,
            bar_close,
        )
    assessment = services.jev.assess(features)
    rules = services.rules.evaluate(context, assessment, request.account, request.safety)
    return _entry_from_rules(
        request,
        services,
        context,
        snapshots,
        features,
        assessment,
        rules,
        chosen,
        ambiguous,
        bar_close,
    )


def _entry_after_preflight(
    request, services, context, snapshots, features, chosen, ambiguous, bar_close
):
    carrier = hold_carrier(features)
    rules = services.rules.evaluate(context, carrier, request.account, request.safety)
    if request.safety.kill_switch:
        rules = _with_entry_kill(rules)
    if not rules.passed:
        skipped = carrier.model_copy(update={"systemone_status": "skipped_veto"})
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=_rule_steps(rules),
            submitted=False,
            candidate=chosen,
            ambiguous=ambiguous,
            features=features,
            assessment=skipped,
            rules=rules,
            plan=None,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
        )
    assessment = services.jev.assess(features)
    status = assessment.systemone_status
    if status not in (None, "scored"):
        detail = status or "jev"
        for reason in assessment.reasons:
            if reason.startswith("error_class="):
                detail = reason.split("=", 1)[1]
                break
        steps = (
            ReasonStep(
                stage=ReasonStage.JEV,
                code=_JEV_CODE.get(status or "", status or "JEV"),
                detail=detail,
            ),
        )
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=steps,
            submitted=False,
            candidate=chosen,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=None,
            plan=None,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
        )
    if services.warm:
        steps = (
            ReasonStep(stage=ReasonStage.JEV, code="scored", detail=assessment.proposed_action.value),
        )
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=steps,
            submitted=False,
            candidate=chosen,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=None,
            plan=None,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
        )
    rules = services.rules.evaluate(context, assessment, request.account, request.safety)
    return _entry_from_rules(
        request,
        services,
        context,
        snapshots,
        features,
        assessment,
        rules,
        chosen,
        ambiguous,
        bar_close,
    )


def _entry_from_rules(
    request, services, context, snapshots, features, assessment, rules, chosen, ambiguous, bar_close
):
    if not rules.passed or assessment.proposed_action is ProposedAction.HOLD:
        steps = _rule_steps(rules)
        if rules.passed:
            steps = steps + (
                ReasonStep(stage=ReasonStage.JEV, code=assessment.proposed_action.value, detail="hold"),
            )
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=steps,
            submitted=False,
            candidate=chosen,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=rules,
            plan=None,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
        )
    plan = services.risk.plan_entry(context, features, assessment, rules, request.account)
    if plan.rejected or plan.qty <= 0:
        code = "rejected" if plan.reject_reason is None else plan.reject_reason.value
        steps = (ReasonStep(stage=ReasonStage.RISK, code=code, detail="plan"),)
        return _finish(
            request,
            action=DecisionAction.HOLD,
            steps=steps,
            submitted=False,
            candidate=chosen,
            ambiguous=ambiguous,
            features=features,
            assessment=assessment,
            rules=rules,
            plan=plan,
            context=context,
            amend=None,
            bar_close=bar_close,
            order=None,
            snapshots=snapshots,
            shadow_review=None,
            include_ids=True,
        )
    if assessment.candidate_side is Side.LONG:
        action = DecisionAction.ENTER_LONG
        side = OrderSide.BUY
    elif assessment.candidate_side is Side.SHORT:
        action = DecisionAction.ENTER_SHORT
        side = OrderSide.SELL
    else:
        raise ValueError("accepted entry has no side")
    ident = _ident(request, action)
    intent = OrderIntent(
        intent_id=ident,
        decision_id=ident,
        symbol=request.symbol,
        side=side,
        order_type=request.order_type,
        qty=plan.qty,
        reduce_only=False,
        client_order_id=ident,
    )
    submitted, order = _queue(
        services,
        request,
        intent,
        exit_reason=None,
        plan=plan,
        entry_decision_time=request.decision_time,
    )
    if not submitted and request.record:
        action = DecisionAction.HOLD
        order = None
        steps = (ReasonStep(stage=ReasonStage.EXECUTION, code="rejected", detail="submit"),)
    else:
        steps = (
            ReasonStep(stage=ReasonStage.EXECUTION, code=action.value, detail=ident),
        )
    return _finish(
        request,
        action=action,
        steps=steps,
        submitted=submitted and request.record,
        candidate=chosen,
        ambiguous=ambiguous,
        features=features,
        assessment=assessment,
        rules=rules,
        plan=plan,
        context=context,
        amend=None,
        bar_close=bar_close,
        order=order,
        snapshots=snapshots,
        shadow_review=None,
        include_ids=True,
    )


def _queue(services, request, intent, *, exit_reason, plan, entry_decision_time):
    pending = PendingOrder(
        client_order_id=intent.client_order_id,
        decision_id=intent.decision_id,
        symbol=intent.symbol,
        side=intent.side,
        qty=quantize(intent.qty),
        reduce_only=intent.reduce_only,
        group_order=request.group_order,
        exit_reason=exit_reason,
        plan=plan,
        entry_decision_time=entry_decision_time,
        submitted_at=request.decision_time,
    )
    if not request.record:
        return False, pending
    broker = services.broker
    queue = getattr(broker, "queue_order", None)
    if queue is None:
        ack = broker.submit(intent)
    else:
        ack = queue(
            intent,
            group_order=request.group_order,
            exit_reason=exit_reason,
            plan=plan,
            entry_decision_time=entry_decision_time,
            submitted_at=request.decision_time,
        )
    if not ack.accepted:
        return False, None
    return True, pending


def _finish(
    request: PipelineRequest,
    *,
    action: DecisionAction,
    steps,
    submitted: bool,
    candidate,
    ambiguous: bool,
    features,
    assessment,
    rules,
    plan,
    context,
    amend,
    bar_close,
    order,
    snapshots,
    shadow_review,
    include_ids: bool,
    size_qty: Decimal | None = None,
    stop_price: Decimal | None = None,
) -> PipelineResult:
    ident = _ident(request, action)
    if size_qty is None and plan is not None:
        size_qty = plan.qty
    if stop_price is None and plan is not None and plan.structure_stop_price is not None:
        stop_price = quantize(plan.structure_stop_price)
    m15 = h1 = h4 = None
    if include_ids:
        m15 = snapshots[Timeframe.M15].snapshot_id
        h1 = snapshots[Timeframe.H1].snapshot_id
        h4 = snapshots[Timeframe.H4].snapshot_id
    order_ids = None
    if submitted and order is not None:
        order_ids = json.dumps([order.client_order_id], ensure_ascii=False)
    decision = DecisionRecord(
        symbol=request.symbol,
        decision_time=request.decision_time,
        action=action.value,
        config_hash=request.config_hash,
        engine_version=request.engine_version,
        feature_version=request.feature_version,
        marketdata_version=request.marketdata_version,
        universe_date=request.universe_date,
        created_at=request.decision_time,
        decision_id=ident,
        rank=request.universe_rank,
        proposed_jev_action=None if assessment is None else assessment.proposed_action.value,
        size_qty=size_qty,
        stop_price=stop_price,
        snapshot_id_m15=m15,
        snapshot_id_h1=h1,
        snapshot_id_h4=h4,
        feature_json=None if features is None else dump_model(features),
        jev_json=None if assessment is None else dump_model_omit_none(assessment),
        hard_rule_json=None if rules is None else dump_model(rules),
        risk_plan_json=None if plan is None else dump_model(plan),
        reason_chain_json=None if not steps else dump_models(steps),
        order_ids_json=order_ids,
        calibrated=False if assessment is None else assessment.calibrated,
    )
    return PipelineResult(
        decision=decision,
        action=action,
        submitted=submitted,
        record=request.record,
        group=request.group,
        candidate=None if ambiguous else candidate,
        ambiguous=ambiguous,
        features=features,
        assessment=assessment,
        rules=rules,
        plan=plan,
        context=context,
        amend=amend,
        bar_close=bar_close,
        order=order if submitted or not request.record else None,
        snapshots=snapshots,
        shadow_review=shadow_review,
        reason_steps=tuple(steps),
    )


def _replace(result: PipelineResult, *, shadow_review) -> PipelineResult:
    return PipelineResult(
        decision=result.decision,
        action=result.action,
        submitted=result.submitted,
        record=result.record,
        group=result.group,
        candidate=result.candidate,
        ambiguous=result.ambiguous,
        features=result.features,
        assessment=result.assessment,
        rules=result.rules,
        plan=result.plan,
        context=result.context,
        amend=result.amend,
        bar_close=result.bar_close,
        order=result.order,
        snapshots=result.snapshots,
        shadow_review=shadow_review,
        reason_steps=result.reason_steps,
    )


def _slim_rules(request: PipelineRequest, params: RuleParams) -> HardRuleResult:
    vetoes = _data_vetoes(request, params)
    vetoes.append(Veto(code=VetoCode.NO_CANDIDATE, message="no 15m candidate", measured="none", threshold="one"))
    return HardRuleResult(passed=False, vetoes=tuple(vetoes))


def _data_vetoes(request: PipelineRequest, params: RuleParams) -> list[Veto]:
    """STALE_DATA, GAP_DATA, and INSUFFICIENT_HISTORY, in that order."""
    vetoes: list[Veto] = []
    quality = request.data_quality
    if quality.stale:
        vetoes.append(Veto(code=VetoCode.STALE_DATA, message="stale", measured="true", threshold="false"))
    if VetoCode.GAP_DATA.value in quality.reasons:
        vetoes.append(Veto(code=VetoCode.GAP_DATA, message="gap", measured="gap_data", threshold="none"))
    counts = {
        Timeframe.M15: _closed(request.bars.get(Timeframe.M15, ())),
        Timeframe.H1: _closed(request.bars.get(Timeframe.H1, ())),
        Timeframe.H4: _closed(request.bars.get(Timeframe.H4, ())),
    }
    windows = {
        Timeframe.M15: params.window_15m,
        Timeframe.H1: params.window_1h,
        Timeframe.H4: params.window_4h,
    }
    if any(counts[timeframe] < windows[timeframe] for timeframe in Timeframe):
        measured = ",".join(f"{timeframe.value}={counts[timeframe]}" for timeframe in Timeframe)
        threshold = ",".join(f"{timeframe.value}={windows[timeframe]}" for timeframe in Timeframe)
        vetoes.append(
            Veto(
                code=VetoCode.INSUFFICIENT_HISTORY,
                message="closed bars",
                measured=measured,
                threshold=threshold,
            )
        )
    return vetoes


def _with_entry_kill(rules: HardRuleResult) -> HardRuleResult:
    if any(item.code is VetoCode.KILL_SWITCH for item in rules.vetoes):
        return rules
    veto = Veto(code=VetoCode.KILL_SWITCH, message="kill switch", measured="true", threshold="false")
    vetoes = rules.vetoes + (veto,)
    return HardRuleResult(passed=False, vetoes=vetoes)


def _rule_steps(rules: HardRuleResult) -> tuple[ReasonStep, ...]:
    return tuple(
        ReasonStep(stage=ReasonStage.RULES, code=veto.code.value, detail=veto.message)
        for veto in rules.vetoes
    )


def _reuse_or_compute(services: PipelineServices, bars, timeframe: Timeframe, previous):
    as_of = bars[-1].close_time
    digest = window_hash(bars)
    prior = previous.get(timeframe)
    if prior is not None and prior.as_of == as_of and prior.bar_window_hash == digest:
        return prior
    return services.engine.compute(bars, timeframe=timeframe, as_of=as_of)


def _context(request: PipelineRequest, snapshots) -> MultiTimeframeContext:
    return MultiTimeframeContext(
        context_id=f"{request.symbol}|{format_time_z(request.decision_time)}",
        symbol=request.symbol,
        decision_time=request.decision_time,
        bars={timeframe: tuple(request.bars.get(timeframe, ())) for timeframe in Timeframe},
        snapshots=dict(snapshots),
        data_quality=request.data_quality,
        instrument=request.instrument,
        universe_date=request.universe_date,
        universe_rank=request.universe_rank,
    )


def _bar_close(context: MultiTimeframeContext, request: PipelineRequest) -> float:
    for bar in context.bars[Timeframe.M15]:
        if bar.close_time == request.decision_time:
            return bar.close
    raise ValueError("decision bar is not in the 15m window")


def _closed(bars) -> int:
    return sum(1 for bar in bars if bar.is_closed)


def _ident(request: PipelineRequest, action: DecisionAction) -> str:
    return decision_id(
        request.symbol,
        request.decision_time,
        action,
        request.config_hash,
        request.engine_version,
        request.feature_version,
        request.marketdata_version,
    )
