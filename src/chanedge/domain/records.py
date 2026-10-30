"""Run records that are not the locked section-6 models.

The backtest loop, the paper broker, and the report adapter share these
shapes. Adding a field here does not change Bar, Decision, or RiskPlan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Mapping

from pydantic import model_validator

from chanedge.domain.bars import Bar, DataQuality, Instrument, MultiTimeframeContext
from chanedge.domain.chanlun import ChanSignal, ChanSnapshot
from chanedge.domain.decision import (
    FeatureVector,
    HardRuleResult,
    JevAssessment,
    ReasonStep,
)
from chanedge.domain.enums import DecisionAction, ExitReason, OrderSide, Timeframe
from chanedge.domain.model import AwareDatetime, DomainModel
from chanedge.domain.risk import (
    AccountView,
    AmendStop,
    PositionReview,
    PositionState,
    RiskPlan,
    SafetyState,
)


class UniverseUnavailable(RuntimeError):
    """A walked universe file is missing or unreadable."""


class UniverseName(DomainModel):
    symbol: str
    rank: int

    @model_validator(mode="after")
    def rank_starts_at_one(self) -> UniverseName:
        if isinstance(self.rank, bool) or self.rank < 1:
            raise ValueError("universe rank starts at 1")
        return self


class PendingOrder(DomainModel):
    client_order_id: str
    decision_id: str
    symbol: str
    side: OrderSide
    qty: Decimal
    reduce_only: bool
    group_order: int
    exit_reason: ExitReason | None
    plan: RiskPlan | None
    entry_decision_time: AwareDatetime | None
    submitted_at: AwareDatetime


class MatchFill(DomainModel):
    fill_id: str
    client_order_id: str
    decision_id: str
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal
    fee_quote: Decimal
    slippage_quote: Decimal
    fill_time: AwareDatetime
    bar_seq: int
    reduce_only: bool
    exit_reason: ExitReason | None = None
    partial_reason: str | None = None


class JoinedFill(DomainModel):
    fill_id: str
    client_order_id: str
    price: Decimal
    qty: Decimal
    fee_quote: Decimal
    slippage_quote: Decimal
    fill_time: AwareDatetime
    bar_seq: int
    symbol: str
    side: str
    reduce_only: bool


class OrderRecord(DomainModel):
    client_order_id: str
    decision_id: str
    symbol: str
    side: str
    qty: Decimal
    reduce_only: bool
    status: str
    submitted_at: AwareDatetime
    update_only: bool = False


class FillRecord(DomainModel):
    fill_id: str
    client_order_id: str
    decision_id: str
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    fee_quote: Decimal
    slippage_quote: Decimal
    fill_time: AwareDatetime
    bar_seq: int
    reduce_only: bool
    exit_reason: str | None = None
    partial_reason: str | None = None


class StoredPosition(DomainModel):
    state: PositionState
    arm_close: float | None
    updated_at: AwareDatetime


class DecisionRecord(DomainModel):
    symbol: str
    decision_time: AwareDatetime
    action: str
    config_hash: str
    engine_version: str
    feature_version: str
    marketdata_version: str
    universe_date: date
    created_at: AwareDatetime
    decision_id: str
    rank: int | None = None
    proposed_jev_action: str | None = None
    size_qty: Decimal | None = None
    stop_price: Decimal | None = None
    snapshot_id_m15: str | None = None
    snapshot_id_h1: str | None = None
    snapshot_id_h4: str | None = None
    feature_json: str | None = None
    jev_json: str | None = None
    hard_rule_json: str | None = None
    risk_plan_json: str | None = None
    reason_chain_json: str | None = None
    order_ids_json: str | None = None
    calibrated: bool = False


class BookFlush(DomainModel):
    orders: tuple[OrderRecord, ...]
    fills: tuple[FillRecord, ...]
    positions: tuple[StoredPosition, ...]
    cash: Decimal


class BarCommit(DomainModel):
    decisions: tuple[DecisionRecord, ...]
    orders: tuple[OrderRecord, ...]
    fills: tuple[FillRecord, ...]
    positions: tuple[StoredPosition, ...]
    cash: Decimal


class FundingPoint(DomainModel):
    calc_time: AwareDatetime
    rate: Decimal


class FundingMonth(DomainModel):
    """present is false when that month's file is missing."""

    year: int
    month: int
    present: bool
    points: tuple[FundingPoint, ...] = ()


class PipelineRequest(DomainModel):
    symbol: str
    decision_time: AwareDatetime
    universe_date: date
    universe_rank: int | None
    group: str
    full_log: bool
    flattened: bool
    bars: Mapping[Timeframe, tuple[Bar, ...]]
    data_quality: DataQuality
    instrument: Instrument
    account: AccountView
    safety: SafetyState
    position: PositionState | None
    previous: Mapping[Timeframe, ChanSnapshot]
    config_hash: str
    engine_version: str
    feature_version: str
    marketdata_version: str
    order_type: str
    group_order: int
    record: bool = True
    # Every open shadow on this symbol. Each gets its own review_open.
    shadow_positions: tuple[PositionState, ...] = ()


class PipelineResult(DomainModel):
    decision: DecisionRecord
    action: DecisionAction
    submitted: bool
    record: bool
    group: str
    candidate: ChanSignal | None
    ambiguous: bool
    features: FeatureVector | None
    assessment: JevAssessment | None
    rules: HardRuleResult | None
    plan: RiskPlan | None
    context: MultiTimeframeContext | None
    amend: AmendStop | None
    bar_close: float | None
    order: PendingOrder | None
    snapshots: Mapping[Timeframe, ChanSnapshot]
    shadow_reviews: tuple[PositionReview, ...]
    reason_steps: tuple[ReasonStep, ...]
