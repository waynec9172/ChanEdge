"""PR-8 weighted score. Params arrive at construction. No hard-rule veto."""

from __future__ import annotations

import ast
import inspect
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chanedge.config.load import load_settings
from chanedge.domain.decision import (
    FeatureVector,
    LocationFeatures,
    ResonanceFeatures,
    SessionFeatures,
    SignalBarFeatures,
    StructureFeatures,
    VolatilityFeatures,
)
from chanedge.domain.enums import (
    CHANNEL_NAMES,
    ProposedAction,
    RegimeLabel,
    SessionBucket,
    Side,
    StructureBias,
)
from chanedge.domain.params import JevParams
from chanedge.jev.model import JevModel

ROOT = Path(__file__).resolve().parents[2]
JEV = ROOT / "src" / "chanedge" / "jev"
WHEN = datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc)


def test_jev_imports_only_domain() -> None:
    forbidden = (
        "chanedge.risk",
        "chanedge.execution",
        "chanedge.config",
        "chanedge.features",
        "chanedge.chanlun",
        "chanedge.rules",
        "chanedge.typesafe",
        "typesafe_sdk",
    )
    for path in JEV.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            for name in forbidden:
                assert not module.startswith(name), path


def test_assess_takes_only_the_feature_vector() -> None:
    assert list(inspect.signature(JevModel.assess).parameters) == ["self", "features"]
    with pytest.raises(TypeError):
        JevModel(object())
    with pytest.raises(ValueError):
        _params(hold_bias=True)
    with pytest.raises(ValueError):
        _params(temperature=0)
    with pytest.raises(ValueError):
        _params(hold_bias=0)
    with pytest.raises(ValueError):
        _params(version="")


def test_exact_threshold_buys_and_the_other_side_stays_zero() -> None:
    model = JevModel(_params(structure=1, enter_threshold=0.62))
    bought = model.assess(_vector(Side.LONG, structure={"subscore": 0.62}))
    assert bought.calibrated is False
    assert bought.score == pytest.approx(0.62)
    assert bought.threshold == pytest.approx(0.62)
    assert bought.proposed_action is ProposedAction.BUY
    assert bought.p_sell == 0
    assert bought.p_buy == pytest.approx(0.62 / (0.62 + 0.35))
    assert bought.p_hold == pytest.approx(0.35 / (0.62 + 0.35))
    assert bought.p_buy + bought.p_sell + bought.p_hold == pytest.approx(1)
    soft = math.exp(0.62) / (math.exp(0.62) + math.exp(0) + math.exp(0.35))
    assert bought.p_buy != pytest.approx(soft)
    assert bought.reasons[0] == "structure=0.62000000"
    assert len(bought.reasons) == 6
    held = model.assess(_vector(Side.LONG, structure={"subscore": 0.61}))
    assert held.proposed_action is ProposedAction.HOLD
    sold = model.assess(_vector(Side.SHORT, structure={"subscore": 0.62}))
    assert sold.proposed_action is ProposedAction.SELL
    assert sold.p_buy == 0
    assert sold.p_sell == pytest.approx(0.62 / (0.62 + 0.35))


def test_penalty_is_applied_before_the_weight_and_skip_stays_in_the_sum() -> None:
    model = JevModel(_params(structure=0.62))
    penalised = model.assess(_vector(Side.LONG, structure={"subscore": 1.0, "penalty": 0.5}))
    assert penalised.components["structure"].adjusted == pytest.approx(0.5)
    assert penalised.components["structure"].contribution == pytest.approx(0.31)
    assert penalised.proposed_action is ProposedAction.HOLD
    clamped = model.assess(_vector(Side.LONG, structure={"subscore": 0.1, "penalty": 0.5}))
    assert clamped.components["structure"].adjusted == 0
    kept = JevModel(_params(structure=1)).assess(
        _vector(Side.LONG, structure={"subscore": 0.62, "skip": True})
    )
    assert kept.components["structure"].skip is True
    assert kept.score == pytest.approx(0.62)
    assert kept.proposed_action is ProposedAction.BUY


def test_resonance_gate_is_raw_only_and_weights_are_not_renormalised() -> None:
    model = JevModel(_params(resonance=1))
    gated = model.assess(_vector(Side.LONG, resonance={"subscore": 0.0, "htf_gate_would_pass": True}))
    assert gated.components["resonance"].raw["htf_gate_would_pass"] is True
    assert gated.components["resonance"].contribution == 0
    assert gated.proposed_action is ProposedAction.HOLD
    mixed = JevModel(_params(structure=0.4, location=0.6))
    scored = mixed.assess(
        _vector(Side.LONG, structure={"subscore": 1.0}, location={"subscore": 0.5})
    )
    assert scored.score == pytest.approx(0.7)
    assert scored.proposed_action is ProposedAction.BUY


def test_hold_bias_and_temperature_do_not_choose_the_action() -> None:
    model = JevModel(_params(structure=1, hold_bias=2, temperature=2, enter_threshold=0.62))
    bought = model.assess(_vector(Side.LONG, structure={"subscore": 0.62}))
    assert bought.proposed_action is ProposedAction.BUY
    assert bought.p_sell == 0
    assert bought.p_buy == pytest.approx(0.31 / (0.31 + 2))
    assert bought.p_hold == pytest.approx(2 / (0.31 + 2))


def test_no_candidate_holds_and_keeps_measurements() -> None:
    vector = _vector(
        Side.NONE,
        structure={"subscore": 1.0, "penalty": 0.15, "notes": ("zhongshu_absent",)},
        ambiguous=("sig-sell", "sig-buy"),
    )
    assessment = JevModel(_params(structure=1)).assess(vector)
    assert assessment.candidate_side is Side.NONE
    assert assessment.proposed_action is ProposedAction.HOLD
    assert assessment.p_buy == 0
    assert assessment.p_sell == 0
    assert assessment.p_hold == pytest.approx(1)
    raw = assessment.components["structure"].raw
    assert raw["notes"] == "zhongshu_absent"
    assert raw["consecutive_bi_overlap_ratio"] == 0
    assert "subscore" not in raw
    assert set(assessment.components) == set(CHANNEL_NAMES)


def test_default_settings_drive_the_score() -> None:
    settings = load_settings(ROOT / "config" / "default.yaml")
    params = JevParams(
        version=settings.jev.version,
        structure=settings.jev.weights.structure,
        location=settings.jev.weights.location,
        resonance=settings.jev.weights.resonance,
        volatility_volume=settings.jev.weights.volatility_volume,
        signal_bar=settings.jev.weights.signal_bar,
        session=settings.jev.weights.session,
        enter_threshold=settings.jev.enter_threshold,
        hold_bias=settings.jev.hold_bias,
        temperature=settings.jev.temperature,
    )
    assert params.enter_threshold == pytest.approx(0.62)
    assert params.hold_bias == pytest.approx(0.35)
    assessment = JevModel(params).assess(
        _vector(
            Side.LONG,
            structure={"subscore": 1},
            location={"subscore": 1},
            resonance={"subscore": 1},
            volatility_volume={"subscore": 1},
            signal_bar={"subscore": 1},
            session={"subscore": 1},
        )
    )
    assert assessment.jev_version == "weighted-v1"
    assert assessment.score == pytest.approx(1)
    assert assessment.proposed_action is ProposedAction.BUY


def test_typesafe_maps_every_channel_from_zero_and_quantizes_the_threshold() -> None:
    from chanedge.domain.systemone import ChoiceAnswer, SystemOneFailure
    from chanedge.jev.compose import TypeSafeJev
    from chanedge.jev.questions import MODEL_PIN, QUESTIONS

    settings = load_settings(ROOT / "config" / "default.yaml")
    params = JevParams(
        version=settings.jev.version,
        structure=settings.jev.weights.structure,
        location=settings.jev.weights.location,
        resonance=settings.jev.weights.resonance,
        volatility_volume=settings.jev.weights.volatility_volume,
        signal_bar=settings.jev.weights.signal_bar,
        session=settings.jev.weights.session,
        enter_threshold=settings.jev.enter_threshold,
        hold_bias=settings.jev.hold_bias,
        temperature=settings.jev.temperature,
    )
    port = _Port(_result(1.0, "GO"))
    model = TypeSafeJev(params, port, model_pin=MODEL_PIN)
    bought = model.assess(_vector(Side.LONG))
    assert port.calls[0]["model"] == MODEL_PIN
    assert port.calls[0]["questions"] is QUESTIONS
    assert "subscore" not in port.calls[0]["state"]["features"]["structure"]
    assert bought.proposed_action is ProposedAction.BUY
    assert bought.systemone_status == "scored"
    assert bought.p_buy is None
    assert bought.quality_choice == "GO"
    assert "choice_disagrees" not in bought.reasons
    assert bought.systemone_ms == 12.0
    assert list(inspect.signature(TypeSafeJev.assess).parameters) == ["self", "features"]

    held = TypeSafeJev(params, _Port(_result(0.0, "GO")), model_pin=MODEL_PIN).assess(
        _vector(Side.LONG)
    )
    assert held.proposed_action is ProposedAction.HOLD
    assert "choice_disagrees" in held.reasons

    exact = TypeSafeJev(
        params, _Port(_result(params.enter_threshold, "NO_GO")), model_pin=MODEL_PIN
    ).assess(_vector(Side.LONG))
    assert exact.score == pytest.approx(params.enter_threshold)
    assert exact.proposed_action is ProposedAction.BUY
    assert "choice_disagrees" in exact.reasons

    agreed = TypeSafeJev(params, _Port(_result(0.0, "NO_GO")), model_pin=MODEL_PIN).assess(
        _vector(Side.LONG)
    )
    assert agreed.proposed_action is ProposedAction.HOLD
    assert "choice_disagrees" not in agreed.reasons

    with pytest.raises(RuntimeError):
        TypeSafeJev(params, _Port(error=RuntimeError("no")), model_pin=MODEL_PIN).assess(
            _vector(Side.LONG)
        )
    failed = TypeSafeJev(
        params,
        _Port(error=SystemOneFailure("timeout", 4.0, error_class="TimeoutError")),
        model_pin=MODEL_PIN,
    ).assess(_vector(Side.SHORT))
    assert failed.proposed_action is ProposedAction.HOLD
    assert failed.systemone_status == "timeout"
    assert failed.systemone_ms == 4.0
    assert failed.candidate_side is Side.SHORT
    assert "error_class=TimeoutError" in failed.reasons
    assert "choice_disagrees" not in failed.reasons

    broken = _result(1.0, "GO")
    broken = broken.model_copy(
        update={
            "choices": {
                "final_decision": ChoiceAnswer(
                    choice="MAYBE",
                    probabilities={"GO": 1.0, "NO_GO": 0.0},
                    confidence=0.2,
                )
            }
        }
    )
    malformed = TypeSafeJev(params, _Port(broken), model_pin=MODEL_PIN).assess(_vector(Side.LONG))
    assert malformed.systemone_status == "malformed"
    assert malformed.proposed_action is ProposedAction.HOLD


class _Port:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def system_one(self, *, state, questions, model):
        self.calls.append({"state": state, "questions": questions, "model": model})
        if self.error is not None:
            raise self.error
        return self.result


def _result(subscore: float, choice: str):
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
                choice=choice,
                probabilities={"GO": 0.5, "NO_GO": 0.5},
                confidence=0.4,
            )
        },
        elapsed_ms=12.0,
    )


def _params(**overrides) -> JevParams:
    values = {
        "version": "weighted-v1",
        "structure": 0.0,
        "location": 0.0,
        "resonance": 0.0,
        "volatility_volume": 0.0,
        "signal_bar": 0.0,
        "session": 0.0,
        "enter_threshold": 0.62,
        "hold_bias": 0.35,
        "temperature": 1.0,
    }
    values.update(overrides)
    return JevParams(**values)


def _vector(side: Side, ambiguous: tuple[str, ...] = (), **channels) -> FeatureVector:
    vector = FeatureVector(
        feature_version="feature-v1",
        symbol="BTC/USDT",
        decision_time=WHEN,
        candidate_signal_id=None if side is Side.NONE else "sig",
        candidate_side=side,
        ambiguous_signal_ids=ambiguous,
        structure=StructureFeatures(
            consecutive_bi_overlap_ratio=0.0,
            bi_segment_direction_agree=0.5,
            bi_contained_in_segment_ratio=None,
            zs_clarity=None,
            zs_bi_count=0,
            zs_overlap_valid=False,
            breakout_leave_atr=0.0,
            breakout_reentry_bars=0,
            signal_type=None,
            signal_confirmed=False,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
        location=LocationFeatures(
            price=100.0,
            zs_zg=None,
            zs_zd=None,
            zs_gg=None,
            zs_dd=None,
            dist_zg_atr=None,
            dist_zd_atr=None,
            pos_in_zs=None,
            dist_pullback_to_zg_atr=None,
            dist_pullback_to_zd_atr=None,
            prior_high=None,
            prior_low=None,
            dist_prior_high_atr=None,
            dist_prior_low_atr=None,
            dist_defending_atr=None,
            htf_range_low=None,
            htf_range_high=None,
            pos_in_4h_range=None,
            at_lower_edge=False,
            at_upper_edge=False,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
        resonance=ResonanceFeatures(
            bias_15m=StructureBias.NEUTRAL,
            bias_1h=StructureBias.NEUTRAL,
            bias_4h=StructureBias.NEUTRAL,
            signed_15m=0.0,
            signed_1h=0.0,
            signed_4h=0.0,
            signal_direction=side,
            resonance_count=0,
            htf_gate_would_pass=False,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
        volatility_volume=VolatilityFeatures(
            atr=0.0,
            atr_pct=0.0,
            atr_pct_min=0.001,
            atr_pct_max=0.030,
            in_band=False,
            rel_volume_20=0.0,
            volume_20_median=0.0,
            vol_p10=None,
            vol_p50=None,
            vol_p90=None,
            vol_n=0,
            regime_label=RegimeLabel.UNKNOWN,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
        signal_bar=SignalBarFeatures(
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            range=2.0,
            range_pct=0.02,
            close_location=0.5,
            body_ratio=0.0,
            upper_wick_ratio=0.5,
            lower_wick_ratio=0.5,
            is_bull=False,
            is_bear=False,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
        session=SessionFeatures(
            hour_utc=0,
            dow=0,
            session_bucket=SessionBucket.ASIA,
            is_weekend=False,
            minutes_to_funding=60,
            in_funding_window=False,
            session_multiplier=0.85,
            hard_skip=False,
            subscore=0.0,
            penalty=0.0,
            skip=False,
        ),
    )
    for name, fields in channels.items():
        current = getattr(vector, name)
        vector = vector.model_copy(update={name: current.model_copy(update=fields)})
    return vector
