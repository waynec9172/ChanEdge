"""ChanEngine.compute. One left-to-right walk. Signals emit inside that walk."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Sequence

from chanedge.chanlun.bias import active_zhongshu_id, bias_at
from chanedge.chanlun.bi import WalkState
from chanedge.chanlun.fenxing import confirmed_fenxings, detect_fenxings
from chanedge.chanlun.include import include_merge
from chanedge.chanlun.segment import minimal_break
from chanedge.chanlun.version import ENGINE_VERSION
from chanedge.domain.bars import Bar
from chanedge.domain.canon import canonical_json, format_fixed8, format_time_z
from chanedge.domain.chanlun import ChanSnapshot, Segment
from chanedge.domain.enums import Timeframe


PENDING_ID = "cs_pending"


class ChanEngine:
    def __init__(
        self,
        *,
        config_hash: str,
        min_bi_bars: int = 5,
        segment_enabled: bool = False,
    ) -> None:
        if isinstance(min_bi_bars, bool) or not isinstance(min_bi_bars, int) or min_bi_bars < 1:
            raise ValueError("min_bi_bars must be a positive int")
        if not isinstance(segment_enabled, bool):
            raise ValueError("segment_enabled must be bool")
        if not isinstance(config_hash, str) or config_hash == "":
            raise ValueError("config_hash is required")
        self.config_hash = config_hash
        self.min_bi_bars = min_bi_bars
        self.segment_enabled = segment_enabled

    def compute(
        self,
        bars: Sequence[Bar],
        *,
        timeframe: Timeframe,
        as_of: datetime,
        identify: bool = True,
    ) -> ChanSnapshot:
        """identify=False leaves snapshot_id as PENDING_ID. Call identify() before writing it anywhere."""
        series = tuple(bars)
        _validate(series, timeframe, as_of)
        merged = include_merge(series)
        drafts = detect_fenxings(merged, series, timeframe)
        state = WalkState(self.min_bi_bars, series, timeframe)
        for draft in confirmed_fenxings(drafts):
            event = state.feed_fenxing(draft)
            if event is None:
                continue
            state.apply_zhongshu(event)
            state.apply_signals(event)
        segments: tuple[Segment, ...] = ()
        if self.segment_enabled:
            segments = minimal_break(state.bis, timeframe)
        pending = ChanSnapshot(
            snapshot_id=PENDING_ID,
            symbol=series[0].symbol,
            timeframe=timeframe,
            as_of=as_of,
            config_hash=self.config_hash,
            engine_version=ENGINE_VERSION,
            bar_window_hash=_window_hash(series),
            bars_start=series[0].open_time,
            bars_end=series[-1].open_time,
            bar_count=len(series),
            fenxings=tuple(draft.fenxing for draft in drafts),
            bis=state.bis,
            segments=segments,
            zhongshus=state.book.publish(state.held, series),
            signals=tuple(state.signals),
            structure_bias=bias_at(state.book, state.held, series),
            last_confirmed_bi_id=state.held[-1].bi.id if state.held else None,
            active_zhongshu_id=active_zhongshu_id(state.book, state.held, series),
        )
        if not identify:
            return pending
        return self.identify(pending)

    def identify(self, snapshot: ChanSnapshot) -> ChanSnapshot:
        if snapshot.snapshot_id != PENDING_ID:
            return snapshot
        return snapshot.model_copy(update={"snapshot_id": _snapshot_id(snapshot)})


def _validate(bars: tuple[Bar, ...], timeframe: Timeframe, as_of: datetime) -> None:
    if not bars:
        raise ValueError("bars must not be empty")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    symbol = bars[0].symbol
    for bar in bars:
        if bar.timeframe is not timeframe and bar.timeframe != timeframe:
            raise ValueError("bar timeframe does not match compute")
        if bar.symbol != symbol:
            raise ValueError("bars must share one symbol")


def _window_hash(bars: Sequence[Bar]) -> str:
    """Same line as marketdata bar_window_hash. chanlun does not import marketdata."""
    lines = [
        "|".join(
            (
                format_time_z(bar.open_time),
                format_fixed8(bar.open),
                format_fixed8(bar.high),
                format_fixed8(bar.low),
                format_fixed8(bar.close),
                format_fixed8(bar.volume),
            )
        )
        for bar in bars
        if bar.is_closed
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def window_hash(bars: Sequence[Bar]) -> str:
    """Hash of closed bars. Reuse compares this to the previous snapshot."""
    return _window_hash(bars)


def _snapshot_id(snapshot: ChanSnapshot) -> str:
    payload = snapshot.model_dump()
    payload.pop("snapshot_id")
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "cs_" + digest[:16]
