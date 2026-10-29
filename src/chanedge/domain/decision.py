"""Decisions, features, orders, and chart frames. No scoring formula."""

from __future__ import annotations

from decimal import Decimal

from pydantic import model_validator

from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import Bi, ChanSignal, Zhongshu
from chanedge.domain.enums import (
    CHANNEL_NAMES,
    DecisionAction,
    OrderSide,
    ProposedAction,
    ReasonStage,
    RegimeLabel,
    SessionBucket,
    Side,
    SignalType,
    StructureBias,
    Timeframe,
    VetoCode,
)
from chanedge.domain.model import AwareDatetime, DomainModel
from chanedge.domain.risk import PartialTarget, PositionState, RiskPlan


class StructureFeatures(DomainModel):
    consecutive_bi_overlap_ratio: float
    bi_segment_direction_agree: float
    bi_contained_in_segment_ratio: float | None
    zs_clarity: float | None
    zs_bi_count: int
    zs_overlap_valid: bool
    breakout_leave_atr: float
    breakout_reentry_bars: int
    signal_type: SignalType | None
    signal_confirmed: bool
    subscore: float
    penalty: float
    skip: bool
    notes: tuple[str, ...] = ()


class LocationFeatures(DomainModel):
    price: float
    zs_zg: float | None
    zs_zd: float | None
    zs_gg: float | None
    zs_dd: float | None
    dist_zg_atr: float | None
    dist_zd_atr: float | None
    pos_in_zs: float | None
    dist_pullback_to_zg_atr: float | None
    dist_pullback_to_zd_atr: float | None
    prior_high: float | None
    prior_low: float | None
    dist_prior_high_atr: float | None
    dist_prior_low_atr: float | None
    dist_defending_atr: float | None
    htf_range_low: float | None
    htf_range_high: float | None
    pos_in_4h_range: float | None
    at_lower_edge: bool
    at_upper_edge: bool
    subscore: float
    penalty: float
    skip: bool


class ResonanceFeatures(DomainModel):
    bias_15m: StructureBias
    bias_1h: StructureBias
    bias_4h: StructureBias
    signed_15m: float
    signed_1h: float
    signed_4h: float
    signal_direction: Side
    resonance_count: int
    htf_gate_would_pass: bool
    subscore: float
    penalty: float
    skip: bool


class VolatilityFeatures(DomainModel):
    atr: float
    atr_pct: float
    atr_pct_min: float
    atr_pct_max: float
    in_band: bool
    rel_volume_20: float
    volume_20_median: float
    vol_p10: float | None
    vol_p50: float | None
    vol_p90: float | None
    vol_n: int
    regime_label: RegimeLabel
    subscore: float
    penalty: float
    skip: bool
    notes: tuple[str, ...] = ()


class SignalBarFeatures(DomainModel):
    open: float
    high: float
    low: float
    close: float
    range: float
    range_pct: float
    close_location: float
    body_ratio: float
    upper_wick_ratio: float
    lower_wick_ratio: float
    is_bull: bool
    is_bear: bool
    subscore: float
    penalty: float
    skip: bool


class SessionFeatures(DomainModel):
    hour_utc: int
    dow: int
    session_bucket: SessionBucket
    is_weekend: bool
    minutes_to_funding: int
    in_funding_window: bool
    session_multiplier: float
    hard_skip: bool
    subscore: float
    penalty: float
    skip: bool


class FeatureVector(DomainModel):
    feature_version: str
    symbol: str
    decision_time: AwareDatetime
    candidate_signal_id: str | None
    candidate_side: Side
    ambiguous_signal_ids: tuple[str, ...]
    structure: StructureFeatures
    location: LocationFeatures
    resonance: ResonanceFeatures
    volatility_volume: VolatilityFeatures
    signal_bar: SignalBarFeatures
    session: SessionFeatures


class ComponentScore(DomainModel):
    channel: str
    subscore: float
    penalty: float
    adjusted: float
    weight: float
    contribution: float
    skip: bool
    raw: dict[str, float | int | str | bool | None]


class JevAssessment(DomainModel):
    jev_version: str
    calibrated: bool
    candidate_side: Side
    score: float
    p_buy: float | None = None
    p_sell: float | None = None
    p_hold: float | None = None
    components: dict[str, ComponentScore]
    reasons: tuple[str, ...]
    threshold: float
    proposed_action: ProposedAction
    systemone_status: str | None = None
    systemone_model: str | None = None
    quality_choice: str | None = None
    quality_choice_confidence: float | None = None
    systemone_ms: float | None = None

    @model_validator(mode="after")
    def six_channels(self) -> JevAssessment:
        if set(self.components) != set(CHANNEL_NAMES):
            raise ValueError("components must be the six channels")
        allowed = {
            None,
            "carrier",
            "skipped_veto",
            "scored",
            "timeout",
            "http_error",
            "malformed",
            "missing_key",
            "cache_miss",
            "model_mismatch",
        }
        if self.systemone_status not in allowed:
            raise ValueError("systemone_status is not a known status")
        if self.quality_choice not in {None, "GO", "NO_GO"}:
            raise ValueError("quality_choice must be GO or NO_GO")
        return self


class Veto(DomainModel):
    code: VetoCode
    message: str
    measured: str
    threshold: str


class HardRuleResult(DomainModel):
    passed: bool
    vetoes: tuple[Veto, ...] = ()

    @model_validator(mode="after")
    def passed_matches_vetoes(self) -> HardRuleResult:
        if self.passed != (len(self.vetoes) == 0):
            raise ValueError("passed is true only when vetoes is empty")
        return self


class ReasonStep(DomainModel):
    stage: ReasonStage
    code: str
    detail: str


class SnapshotIds(DomainModel):
    m15: str | None = None
    h1: str | None = None
    h4: str | None = None


class Decision(DomainModel):
    decision_id: str
    symbol: str
    time: AwareDatetime
    action: DecisionAction
    snapshot_ids: SnapshotIds
    size: Decimal | None = None
    stop: float | None = None
    targets: tuple[PartialTarget, ...] = ()
    reason_chain: tuple[ReasonStep, ...] = ()
    feature_vector: FeatureVector | None = None
    assessment: JevAssessment | None = None
    hard_rule: HardRuleResult | None = None
    risk_plan: RiskPlan | None = None
    order_ids: tuple[str, ...] = ()


class OrderIntent(DomainModel):
    intent_id: str
    decision_id: str
    symbol: str
    side: OrderSide
    order_type: str
    qty: Decimal
    reduce_only: bool
    client_order_id: str
    limit_price: float | None = None


class OrderAck(DomainModel):
    client_order_id: str
    accepted: bool


class CancelAck(DomainModel):
    client_order_id: str
    accepted: bool


class ChartFrame(DomainModel):
    symbol: str
    timeframe: Timeframe
    as_of: AwareDatetime
    snapshot_id: str
    structure_bias: StructureBias
    bars: tuple[Bar, ...]
    bis: tuple[Bi, ...]
    zhongshus: tuple[Zhongshu, ...]
    signals: tuple[ChanSignal, ...]
    last_action: DecisionAction
    position: PositionState | None = None
    stop_price: float | None = None
    assessment: JevAssessment | None = None
    veto_codes: tuple[VetoCode, ...] = ()
    universe_rank: int | None = None

    @model_validator(mode="after")
    def rank_starts_at_one(self) -> ChartFrame:
        if self.universe_rank is not None and self.universe_rank < 1:
            raise ValueError("universe_rank starts at 1")
        return self
