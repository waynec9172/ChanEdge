"""Protocols from architecture §6. Implementations stay outside domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, Sequence

from chanedge.domain.records import (
    BarCommit,
    BookFlush,
    FundingMonth,
    JoinedFill,
    PendingOrder,
    StoredPosition,
    UniverseName,
)

from chanedge.domain.bars import Bar, Instrument, MultiTimeframeContext
from chanedge.domain.chanlun import ChanSnapshot
from chanedge.domain.decision import (
    CancelAck,
    FeatureVector,
    HardRuleResult,
    JevAssessment,
    OrderAck,
    OrderIntent,
)
from chanedge.domain.systemone import SystemOneResult
from chanedge.domain.enums import Timeframe
from chanedge.domain.risk import AccountView, PositionReview, PositionState, RiskPlan, SafetyState


class ChanEngine(Protocol):
    def compute(
        self, bars: Sequence[Bar], *, timeframe: Timeframe, as_of: datetime
    ) -> ChanSnapshot: ...


class FeatureBuilder(Protocol):
    def build(self, context: MultiTimeframeContext) -> FeatureVector: ...


class JevModel(Protocol):
    def assess(self, features: FeatureVector) -> JevAssessment: ...


class SystemOneReader(Protocol):
    """Read-only cache. No HTTP method."""

    def lookup(self, key: str) -> SystemOneResult | None: ...


class SystemOneCaller(Protocol):
    """What TypeSafeJev calls. A reader adapter and the HTTP client are different types."""

    def system_one(
        self,
        *,
        state: dict[str, object],
        questions: dict[str, object],
        model: str,
    ) -> SystemOneResult: ...


class RuleGate(Protocol):
    def evaluate(
        self,
        context: MultiTimeframeContext,
        assessment: JevAssessment,
        account: AccountView,
        safety: SafetyState,
    ) -> HardRuleResult: ...


class RiskManager(Protocol):
    def plan_entry(
        self,
        context: MultiTimeframeContext,
        features: FeatureVector,
        assessment: JevAssessment,
        rules: HardRuleResult,
        account: AccountView,
    ) -> RiskPlan: ...

    def review_open(
        self,
        context: MultiTimeframeContext,
        position: PositionState,
    ) -> PositionReview: ...


class Broker(Protocol):
    def submit(self, intent: OrderIntent) -> OrderAck: ...

    def cancel(self, client_order_id: str) -> CancelAck: ...

    def fetch_position(self, symbol: str) -> PositionState: ...


class MarketDataPort(Protocol):
    def fetch_closed_bars(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class BarSource(Protocol):
    """Already-written bars. This is not MarketDataPort.fetch_closed_bars."""

    def load(self, symbol: str, timeframe: Timeframe) -> tuple[Bar, ...]: ...


class UniverseSource(Protocol):
    def load(self, day: date) -> tuple[UniverseName, ...]: ...


class FundingSource(Protocol):
    def months(self, symbol: str, start: datetime, end: datetime) -> tuple[FundingMonth, ...]: ...


class Ledger(Protocol):
    def load_open_positions(self) -> tuple[StoredPosition, ...]: ...

    def load_pending_orders(self) -> tuple[PendingOrder, ...]: ...

    def load_joined_fills(self) -> tuple[JoinedFill, ...]: ...

    def get_cash(self) -> Decimal | None: ...

    def set_cash(self, cash_quote: Decimal) -> None: ...

    def commit(self, flush: BookFlush) -> None: ...


class ReportSink(Protocol):
    def begin_run(self, run_id: str) -> Path: ...

    def commit_bar(self, commit: BarCommit) -> None: ...

    def synchronous(self) -> int: ...

    def chart_frame_count(self) -> int: ...
