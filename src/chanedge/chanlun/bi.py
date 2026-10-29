"""Bi state machine. One pass over confirmed fenxings. Zhongshu is applied by the caller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from chanedge.chanlun.fenxing import DraftFenxing
from chanedge.chanlun.signals import SignalMemory
from chanedge.chanlun.zhongshu import ZhongshuBook
from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import Bi, ChanSignal
from chanedge.domain.enums import Direction, Mark, Timeframe
from chanedge.domain.ids import bi_id


@dataclass
class _HeldBi:
    bi: Bi
    end: DraftFenxing
    start_raw: int
    signal_slots: list[int] = field(default_factory=list)


class WalkState:
    """Left-to-right bi walk. PR-6 appends signals from the same events."""

    def __init__(self, min_bi_bars: int, bars: Sequence[Bar], timeframe: Timeframe) -> None:
        self.min_bi_bars = min_bi_bars
        self.bars = bars
        self.timeframe = timeframe
        self.held: list[_HeldBi] = []
        self.tentative: DraftFenxing | None = None
        self.book = ZhongshuBook(timeframe)
        self.signals: list[ChanSignal] = []
        self.memory = SignalMemory()

    @property
    def bis(self) -> tuple[Bi, ...]:
        return tuple(item.bi for item in self.held)

    def feed_fenxing(self, draft: DraftFenxing) -> str | None:
        """Return "new", "replace", or None. None does not touch zhongshu."""
        endpoint = self.held[-1].end if self.held else self.tentative
        if endpoint is None:
            self.tentative = draft
            return None
        if draft.mark == endpoint.mark:
            if _more_extreme(draft, endpoint):
                if self.held:
                    self._replace_last(draft)
                    return "replace"
                self.tentative = draft
            return None
        if _raw_between(endpoint, draft) >= self.min_bi_bars and _price_holds(endpoint, draft):
            self._append(endpoint, draft)
            self.tentative = None
            return "new"
        return None

    def apply_zhongshu(self, event: str) -> None:
        self.book.apply(event, self.held)

    def apply_signals(self, event: str) -> None:
        from chanedge.chanlun.signals import apply_signals

        apply_signals(self, event)

    def _append(self, start: DraftFenxing, end: DraftFenxing) -> None:
        self.held.append(
            _HeldBi(
                bi=self._build(start.raw_start, start.id, start.bar_open_time, start.price, start.mark, end),
                end=end,
                start_raw=start.raw_start,
            )
        )

    def _replace_last(self, end: DraftFenxing) -> None:
        last = self.held[-1]
        start_mark = Mark.BOTTOM if last.bi.direction is Direction.UP else Mark.TOP
        self.held[-1] = _HeldBi(
            bi=self._build(
                last.start_raw,
                last.bi.start_fx_id,
                last.bi.start_time,
                last.bi.start_price,
                start_mark,
                end,
            ),
            end=end,
            start_raw=last.start_raw,
            signal_slots=list(last.signal_slots),
        )

    def _build(
        self,
        start_raw: int,
        start_fx_id: str,
        start_time,
        start_price: float,
        start_mark: Mark,
        end: DraftFenxing,
    ) -> Bi:
        direction = Direction.UP if start_mark is Mark.BOTTOM else Direction.DOWN
        high, low = _span(self.bars, start_raw, end.k_index_mid, start_price, end.price)
        return Bi(
            id=bi_id(
                self.timeframe,
                direction,
                start_time,
                end.bar_open_time,
                start_price,
                end.price,
            ),
            timeframe=self.timeframe,
            direction=direction,
            start_fx_id=start_fx_id,
            end_fx_id=end.id,
            start_time=start_time,
            end_time=end.bar_open_time,
            start_price=start_price,
            end_price=end.price,
            high=high,
            low=low,
            bar_count=end.k_index_mid - start_raw + 1,
            confirmed=True,
        )


def _more_extreme(draft: DraftFenxing, endpoint: DraftFenxing) -> bool:
    if draft.mark is Mark.TOP:
        return draft.price > endpoint.price
    return draft.price < endpoint.price


def _price_holds(start: DraftFenxing, end: DraftFenxing) -> bool:
    if start.mark is Mark.BOTTOM and end.mark is Mark.TOP:
        return end.price > start.price
    if start.mark is Mark.TOP and end.mark is Mark.BOTTOM:
        return end.price < start.price
    return False


def _raw_between(start: DraftFenxing, end: DraftFenxing) -> int:
    return end.k_index_mid - start.k_index_mid - 1


def _span(
    bars: Sequence[Bar],
    start_raw: int,
    end_mid: int,
    start_price: float,
    end_price: float,
) -> tuple[float, float]:
    highs = [bars[index].high for index in range(start_raw, end_mid + 1)]
    lows = [bars[index].low for index in range(start_raw, end_mid + 1)]
    return max([*highs, start_price, end_price]), min([*lows, start_price, end_price])
