"""Chanlun value objects. Construction only; the walk arrives in a later PR."""

from __future__ import annotations

from pydantic import model_validator

from chanedge.domain.enums import (
    Direction,
    Mark,
    SignalStatus,
    SignalType,
    StructureBias,
    Timeframe,
)
from chanedge.domain.model import AwareDatetime, DomainModel


class Fenxing(DomainModel):
    id: str
    timeframe: Timeframe
    mark: Mark
    index: int
    time: AwareDatetime
    price: float
    bar_open_time: AwareDatetime
    confirmed: bool
    k_index_left: int
    k_index_mid: int
    k_index_right: int


class Bi(DomainModel):
    id: str
    timeframe: Timeframe
    direction: Direction
    start_fx_id: str
    end_fx_id: str
    start_time: AwareDatetime
    end_time: AwareDatetime
    start_price: float
    end_price: float
    high: float
    low: float
    bar_count: int
    confirmed: bool


class Segment(DomainModel):
    id: str
    timeframe: Timeframe
    direction: Direction
    start_bi_id: str
    end_bi_id: str
    start_time: AwareDatetime
    end_time: AwareDatetime
    high: float
    low: float
    bi_ids: tuple[str, ...]
    confirmed: bool
    algo: str


class Zhongshu(DomainModel):
    id: str
    timeframe: Timeframe
    zg: float
    zd: float
    gg: float
    dd: float
    start_time: AwareDatetime
    end_time: AwareDatetime
    bi_ids: tuple[str, ...]
    direction_into: Direction
    level: int
    confirmed: bool


class ChanSignal(DomainModel):
    id: str
    timeframe: Timeframe
    type: SignalType
    status: SignalStatus
    time: AwareDatetime
    price: float
    direction: Direction
    defending_fx_id: str
    defending_price: float
    related_bi_id: str
    bar_open_time: AwareDatetime
    related_zhongshu_id: str | None = None
    prior_extreme: float | None = None
    notes: str = ""

    @model_validator(mode="after")
    def phase1_confirmed_only(self) -> ChanSignal:
        if self.status is not SignalStatus.CONFIRMED:
            raise ValueError("Phase 1 signals are confirmed")
        return self


class ChanSnapshot(DomainModel):
    snapshot_id: str
    symbol: str
    timeframe: Timeframe
    as_of: AwareDatetime
    config_hash: str
    engine_version: str
    bar_window_hash: str
    bars_start: AwareDatetime
    bars_end: AwareDatetime
    bar_count: int
    fenxings: tuple[Fenxing, ...]
    bis: tuple[Bi, ...]
    segments: tuple[Segment, ...]
    zhongshus: tuple[Zhongshu, ...]
    signals: tuple[ChanSignal, ...]
    structure_bias: StructureBias
    last_confirmed_bi_id: str | None = None
    active_zhongshu_id: str | None = None
