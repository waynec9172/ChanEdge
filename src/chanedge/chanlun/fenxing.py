"""Fenxing on merged bars. k_index_mid is the middle bar's raw_end.

k_index_right and time come from the first raw bar of the right merged bar,
so a later inside bar merged into it does not move the confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from chanedge.chanlun.include import MergedBar
from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import Fenxing
from chanedge.domain.enums import Mark, Timeframe
from chanedge.domain.ids import fx_id


@dataclass(frozen=True)
class DraftFenxing:
    fenxing: Fenxing
    raw_start: int

    @property
    def mark(self) -> Mark:
        return self.fenxing.mark

    @property
    def price(self) -> float:
        return self.fenxing.price

    @property
    def k_index_mid(self) -> int:
        return self.fenxing.k_index_mid

    @property
    def k_index_right(self) -> int:
        return self.fenxing.k_index_right

    @property
    def bar_open_time(self):
        return self.fenxing.bar_open_time

    @property
    def id(self) -> str:
        return self.fenxing.id


def detect_fenxings(
    merged: Sequence[MergedBar],
    bars: Sequence[Bar],
    timeframe: Timeframe,
) -> tuple[DraftFenxing, ...]:
    """Every strict top or bottom. A bar that is both is not a fenxing."""
    found: list[DraftFenxing] = []
    for index in range(1, len(merged) - 1):
        left, mid, right = merged[index - 1], merged[index], merged[index + 1]
        is_top = mid.high > left.high and mid.high > right.high
        is_bottom = mid.low < left.low and mid.low < right.low
        if is_top == is_bottom:
            continue
        mark = Mark.TOP if is_top else Mark.BOTTOM
        price = mid.high if is_top else mid.low
        mid_bar = bars[mid.raw_end]
        # The fenxing exists once the right merged bar's first raw bar closes.
        # Inside bars merged into it later must not move the confirmation bar.
        confirm_bar = bars[right.raw_start]
        last_right_bar = bars[right.raw_end]
        found.append(
            DraftFenxing(
                fenxing=Fenxing(
                    id=fx_id(timeframe, mark, mid_bar.open_time, price),
                    timeframe=timeframe,
                    mark=mark,
                    index=index,
                    time=confirm_bar.close_time,
                    price=price,
                    bar_open_time=mid_bar.open_time,
                    confirmed=last_right_bar.is_closed,
                    k_index_left=left.raw_end,
                    k_index_mid=mid.raw_end,
                    k_index_right=right.raw_start,
                ),
                raw_start=mid.raw_start,
            )
        )
    return tuple(found)


def confirmed_fenxings(drafts: Sequence[DraftFenxing]) -> tuple[DraftFenxing, ...]:
    """Confirmed fenxings in k_index_mid order. Unconfirmed ones stay out of the walk."""
    ordered = tuple(draft for draft in drafts if draft.fenxing.confirmed)
    return tuple(sorted(ordered, key=lambda draft: draft.k_index_mid))
