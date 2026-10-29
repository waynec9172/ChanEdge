"""structure_bias from the active departure, then the last two opposite end prices."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from chanedge.chanlun.zhongshu import ZhongshuBook, _Zhongshu
from chanedge.domain.bars import Bar
from chanedge.domain.enums import Direction, StructureBias


def bias_at(book: ZhongshuBook, held: list, bars: Sequence[Bar]) -> StructureBias:
    active = select_active(book, held, bars)
    if active is not None:
        side = _departure(active, bars)
        if side == "up":
            return StructureBias.BREAKOUT_UP
        if side == "down":
            return StructureBias.BREAKOUT_DOWN
    bis = [item.bi for item in held]
    downs = [bi for bi in bis if bi.direction is Direction.DOWN]
    if len(downs) >= 2 and downs[-1].end_price > downs[-2].end_price:
        return StructureBias.UP
    ups = [bi for bi in bis if bi.direction is Direction.UP]
    if len(ups) >= 2 and ups[-1].end_price < ups[-2].end_price:
        return StructureBias.DOWN
    return StructureBias.NEUTRAL


def active_zhongshu_id(book: ZhongshuBook, held: list, bars: Sequence[Bar]) -> str | None:
    active = select_active(book, held, bars)
    if active is None:
        return None
    return active.id


def select_active(book: ZhongshuBook, held: list, bars: Sequence[Bar]) -> _Zhongshu | None:
    """Latest end_time among confirmed zhongshu whose current departure is still alive."""
    if not bars:
        return None
    return select_active_through(book, held, bars, len(bars) - 1)


def select_active_through(
    book: ZhongshuBook,
    held: list,
    bars: Sequence[Bar],
    last_index: int,
) -> _Zhongshu | None:
    """Same selection as select_active, using closes through last_index only."""
    chosen: _Zhongshu | None = None
    chosen_end: datetime | None = None
    for zs in book.zhongshus:
        if live_departure(zs, bars, last_index) is None:
            continue
        end = held[zs.member_indexes[-1]].bi.end_time
        if chosen is None or chosen_end is None or end >= chosen_end:
            chosen = zs
            chosen_end = end
    return chosen


def live_departure(zs: _Zhongshu, bars: Sequence[Bar], last_index: int) -> tuple[str, int] | None:
    """Live departure as of last_index. Returns (side, first outside bar)."""
    if last_index < zs.confirm_index:
        return None
    side = "inside"
    alive = False
    start = zs.confirm_index
    end = min(last_index, len(bars) - 1)
    for index in range(zs.confirm_index, end + 1):
        close = bars[index].close
        if zs.zd <= close <= zs.zg:
            side = "inside"
            alive = False
            continue
        if close > zs.zg:
            if side != "up":
                side = "up"
                start = index
                alive = True
            continue
        if side != "down":
            side = "down"
            start = index
            alive = True
    if not alive:
        return None
    return side, start


def _departure(zs: _Zhongshu, bars: Sequence[Bar]) -> str | None:
    """Up or down when the departure that contains as_of has not returned inside."""
    if not bars:
        return None
    found = live_departure(zs, bars, len(bars) - 1)
    if found is None:
        return None
    return found[0]
