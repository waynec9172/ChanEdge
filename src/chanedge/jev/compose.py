"""Map a System One result onto the fixed weights. This module does not open HTTP."""

from __future__ import annotations

from decimal import Decimal

from chanedge.domain.canon import canonical_json, format_fixed8, format_time_z
from chanedge.domain.decision import ComponentScore, FeatureVector, JevAssessment
from chanedge.domain.enums import CHANNEL_NAMES, ProposedAction, Side
from chanedge.domain.params import JevParams
from chanedge.domain.ports import SystemOneCaller
from chanedge.domain.systemone import (
    ChoiceAnswer,
    ScoreAnswer,
    SystemOneFailure,
    SystemOneResult,
    choice_is_go_or_no_go,
    probabilities_cover,
    score_in_range,
)
from chanedge.jev.model import feature_raw
from chanedge.jev.questions import QUESTIONS

_VERSION = "typesafe-v1"


class TypeSafeJev:
    def __init__(self, params: JevParams, port: SystemOneCaller, *, model_pin: str) -> None:
        if not isinstance(params, JevParams):
            raise TypeError("params must be JevParams")
        self._params = params
        self._port = port
        self._pin = model_pin

    def assess(self, features: FeatureVector) -> JevAssessment:
        state = _state(features)
        try:
            result = self._port.system_one(state=state, questions=QUESTIONS, model=self._pin)
        except SystemOneFailure as failure:
            return _failed(features, self._params, failure)
        problem = _problem(result)
        if problem is not None:
            return _failed(
                features,
                self._params,
                SystemOneFailure("malformed", result.elapsed_ms, model=result.model),
            )
        return _scored(features, self._params, result)


def _state(features: FeatureVector) -> dict[str, object]:
    return {
        "symbol": features.symbol,
        "timeframe": "15m",
        "decision_time": format_time_z(features.decision_time),
        "candidate_signal_id": features.candidate_signal_id,
        "candidate_side": features.candidate_side.value,
        "features": {name: feature_raw(getattr(features, name)) for name in CHANNEL_NAMES},
    }


def _problem(result: SystemOneResult) -> str | None:
    for name, spec in QUESTIONS.items():
        if not isinstance(spec, dict):
            return name
        kind = spec.get("type")
        if kind == "score":
            criteria = spec.get("criteria")
            answer = result.scores.get(name)
            if not isinstance(criteria, list) or not isinstance(answer, ScoreAnswer):
                return name
            if not score_in_range(answer.score, len(criteria)):
                return name
            if not probabilities_cover(answer.probabilities, len(criteria)):
                return name
        elif kind == "choice":
            answer_choice = result.choices.get(name)
            if not isinstance(answer_choice, ChoiceAnswer) or not choice_is_go_or_no_go(answer_choice):
                return name
        else:
            return name
    return None


def _scored(features: FeatureVector, params: JevParams, result: SystemOneResult) -> JevAssessment:
    choice = result.choices["final_decision"]
    components: dict[str, ComponentScore] = {}
    reasons: list[str] = []
    total = Decimal(0)
    for name in CHANNEL_NAMES:
        spec = QUESTIONS[name]
        assert isinstance(spec, dict)
        criteria = spec["criteria"]
        assert isinstance(criteria, list)
        answer = result.scores[name]
        subscore = _subscore(answer.score, len(criteria))
        weight = Decimal(repr(float(getattr(params, name))))
        contribution = weight * subscore
        total += contribution
        raw = feature_raw(getattr(features, name))
        raw["systemone_score"] = answer.score
        raw["systemone_confidence"] = answer.confidence
        raw["probabilities_json"] = canonical_json(answer.probabilities)
        components[name] = ComponentScore(
            channel=name,
            subscore=float(subscore),
            penalty=0.0,
            adjusted=float(subscore),
            weight=float(weight),
            contribution=float(contribution),
            skip=getattr(features, name).skip,
            raw=raw,
        )
        reasons.append(f"{name}={format_fixed8(contribution)}")
    quantized = Decimal(format_fixed8(total))
    threshold = Decimal(format_fixed8(params.enter_threshold))
    if features.candidate_side is Side.LONG and quantized >= threshold:
        action = ProposedAction.BUY
    elif features.candidate_side is Side.SHORT and quantized >= threshold:
        action = ProposedAction.SELL
    else:
        action = ProposedAction.HOLD
    entered = action in (ProposedAction.BUY, ProposedAction.SELL)
    if (choice.choice == "GO") != entered:
        reasons.append("choice_disagrees")
    return JevAssessment(
        jev_version=_VERSION,
        calibrated=False,
        candidate_side=features.candidate_side,
        score=float(quantized),
        components=components,
        reasons=tuple(reasons),
        threshold=params.enter_threshold,
        proposed_action=action,
        systemone_status="scored",
        systemone_model=result.model,
        quality_choice=choice.choice,
        quality_choice_confidence=choice.confidence,
        systemone_ms=result.elapsed_ms,
    )


def _failed(features: FeatureVector, params: JevParams, failure: SystemOneFailure) -> JevAssessment:
    components: dict[str, ComponentScore] = {}
    reasons: list[str] = []
    if failure.error_class:
        reasons.append(f"error_class={failure.error_class}")
    for name in CHANNEL_NAMES:
        channel = getattr(features, name)
        weight = float(getattr(params, name))
        components[name] = ComponentScore(
            channel=name,
            subscore=0.0,
            penalty=0.0,
            adjusted=0.0,
            weight=weight,
            contribution=0.0,
            skip=channel.skip,
            raw=feature_raw(channel),
        )
        reasons.append(f"{name}={format_fixed8(0)}")
    return JevAssessment(
        jev_version=_VERSION,
        calibrated=False,
        candidate_side=features.candidate_side,
        score=0.0,
        components=components,
        reasons=tuple(reasons),
        threshold=params.enter_threshold,
        proposed_action=ProposedAction.HOLD,
        systemone_status=failure.status,
        systemone_model=failure.model,
        systemone_ms=failure.elapsed_ms,
    )


def _subscore(score: float, level_count: int) -> Decimal:
    top = Decimal(level_count - 1)
    value = Decimal(repr(float(score)))
    if value < 0:
        value = Decimal(0)
    if value > top:
        value = top
    return value / top
