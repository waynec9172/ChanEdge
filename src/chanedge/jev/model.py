"""JevModel.assess(features). Weights come from the constructor params."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from chanedge.domain.decision import ComponentScore, FeatureVector, JevAssessment
from chanedge.domain.enums import CHANNEL_NAMES, ProposedAction, Side
from chanedge.domain.params import JevParams

_DROPPED = {"subscore", "penalty", "skip"}


class JevModel:
    def __init__(self, params: JevParams) -> None:
        if not isinstance(params, JevParams):
            raise TypeError("params must be JevParams")
        self._params = params

    def assess(self, features: FeatureVector) -> JevAssessment:
        params = self._params
        components: dict[str, ComponentScore] = {}
        for name in CHANNEL_NAMES:
            channel = getattr(features, name)
            adjusted = _clamp(channel.subscore - channel.penalty)
            weight = getattr(params, name)
            components[name] = ComponentScore(
                channel=name,
                subscore=channel.subscore,
                penalty=channel.penalty,
                adjusted=adjusted,
                weight=weight,
                contribution=weight * adjusted,
                skip=channel.skip,
                raw=_raw(channel),
            )
        score = sum(item.contribution for item in components.values())
        # A missing side keeps both direction scores at 0. The composite stays the weighted sum.
        if features.candidate_side is Side.LONG:
            s_buy, s_sell = score, 0.0
        elif features.candidate_side is Side.SHORT:
            s_buy, s_sell = 0.0, score
        else:
            s_buy, s_sell = 0.0, 0.0
        z_buy = max(s_buy, 0.0) / params.temperature
        z_sell = max(s_sell, 0.0) / params.temperature
        z_hold = params.hold_bias
        total = z_buy + z_sell + z_hold
        if features.candidate_side is Side.LONG and score >= params.enter_threshold:
            action = ProposedAction.BUY
        elif features.candidate_side is Side.SHORT and score >= params.enter_threshold:
            action = ProposedAction.SELL
        else:
            action = ProposedAction.HOLD
        return JevAssessment(
            jev_version=params.version,
            calibrated=False,
            candidate_side=features.candidate_side,
            score=score,
            p_buy=z_buy / total,
            p_sell=z_sell / total,
            p_hold=z_hold / total,
            components=components,
            reasons=tuple(f"{name}={components[name].contribution:.8f}" for name in CHANNEL_NAMES),
            threshold=params.enter_threshold,
            proposed_action=action,
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _raw(model: BaseModel) -> dict[str, float | int | str | bool | None]:
    raw: dict[str, float | int | str | bool | None] = {}
    for key, value in model.model_dump().items():
        if key in _DROPPED:
            continue
        raw[key] = _plain(value)
    return raw


def hold_carrier(features: FeatureVector) -> JevAssessment:
    """HOLD assessment for the entry preflight. The gate still sees session and ATR raw."""
    components: dict[str, ComponentScore] = {}
    for name in CHANNEL_NAMES:
        channel = getattr(features, name)
        components[name] = ComponentScore(
            channel=name,
            subscore=0.0,
            penalty=0.0,
            adjusted=0.0,
            weight=0.0,
            contribution=0.0,
            skip=channel.skip,
            raw=_raw(channel),
        )
    return JevAssessment(
        jev_version="carrier",
        calibrated=False,
        candidate_side=features.candidate_side,
        score=0.0,
        components=components,
        reasons=(),
        threshold=0.0,
        proposed_action=ProposedAction.HOLD,
        systemone_status="carrier",
    )


def feature_raw(model: BaseModel) -> dict[str, float | int | str | bool | None]:
    return _raw(model)


def _plain(value: object) -> float | int | str | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, (list, tuple)):
        return ",".join("" if item is None else str(_plain(item)) for item in value)
    raise TypeError(f"unsupported raw value {type(value).__name__}")
