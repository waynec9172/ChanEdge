"""Risk plan and position state. No sizing formula in this module."""

from __future__ import annotations

from decimal import Decimal

from pydantic import model_validator

from chanedge.domain.enums import (
    AmendReason,
    ExitKind,
    ExitReason,
    FillModel,
    PartialReason,
    RuntimeMode,
    Side,
    SignalType,
    StructureBias,
    Timeframe,
    TrailKind,
    VetoCode,
)
from chanedge.domain.model import AwareDatetime, DomainModel


class InvalidationSpec(DomainModel):
    opposite_signal_types: tuple[SignalType, ...]
    htf_timeframe: Timeframe
    htf_bias_exit: tuple[StructureBias, ...]
    stop_price: float
    defending_fx_id: str
    effective_after: AwareDatetime
    zhongshu_id: str | None = None
    zhongshu_fail_price: float | None = None
    swing_fail_price: float | None = None

    @model_validator(mode="after")
    def htf_is_1h(self) -> InvalidationSpec:
        if self.htf_timeframe is not Timeframe.H1:
            raise ValueError("htf_timeframe is H1")
        return self


class ExitInstruction(DomainModel):
    kind: ExitKind
    reason: ExitReason
    qty: Decimal
    trigger_price: float
    fill_model: FillModel


class AmendStop(DomainModel):
    new_stop_price: float
    reason: AmendReason


class PositionReview(DomainModel):
    exit: ExitInstruction | None = None
    amend_stop: AmendStop | None = None

    @model_validator(mode="after")
    def exit_excludes_amend(self) -> PositionReview:
        if self.exit is not None and self.amend_stop is not None:
            raise ValueError("exit and amend_stop cannot both be set")
        return self


class PartialTarget(DomainModel):
    fraction: float
    price: float
    reason: PartialReason


class TrailRule(DomainModel):
    kind: TrailKind
    arm_r: float
    breakeven_price: float
    buffer: float
    ratchet: float | None = None


class RiskPlan(DomainModel):
    symbol: str
    side: Side
    risk_fraction: Decimal
    target_risk_fraction: Decimal
    equity_quote: Decimal
    qty: Decimal
    notional: Decimal
    max_notional: Decimal
    rejected: bool
    entry_reference: float | None = None
    atr: float | None = None
    structure_stop_price: float | None = None
    stop_buffer: float | None = None
    defending_fx_id: str | None = None
    invalidation: InvalidationSpec | None = None
    realized_risk_fraction: Decimal | None = None
    cost_r: Decimal | None = None
    binding_constraint: str | None = None
    partial_targets: tuple[PartialTarget, ...] = ()
    trail: TrailRule | None = None
    reject_reason: VetoCode | None = None

    @model_validator(mode="after")
    def rejection_shape(self) -> RiskPlan:
        if self.rejected != (self.reject_reason is not None):
            raise ValueError("rejected is true only when reject_reason is set")
        if self.rejected:
            if self.realized_risk_fraction is not None:
                raise ValueError("realized_risk_fraction is empty when rejected")
            return self
        missing = [name for name in _ACCEPTED if getattr(self, name) is None]
        if missing:
            raise ValueError("accepted plan is missing " + ", ".join(missing))
        return self


class PositionState(DomainModel):
    symbol: str
    qty: Decimal
    avg_price: float
    stop_price: float
    plan: RiskPlan
    entry_decision_id: str
    entry_decision_time: AwareDatetime
    entry_bar_open_time: AwareDatetime


class AccountView(DomainModel):
    equity_quote: Decimal
    positions: tuple[PositionState, ...] = ()
    open_order_ids: tuple[str, ...] = ()
    open_position_count: int
    gross_notional_quote: Decimal


class SafetyState(DomainModel):
    kill_switch: bool
    mode: RuntimeMode


_ACCEPTED = (
    "entry_reference",
    "atr",
    "structure_stop_price",
    "stop_buffer",
    "defending_fx_id",
    "invalidation",
    "realized_risk_fraction",
    "cost_r",
    "binding_constraint",
    "trail",
)
