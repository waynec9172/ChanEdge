"""Bi zhongshu built during the walk. A replace does not re-judge membership."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chanedge.domain.chanlun import Zhongshu
from chanedge.domain.enums import Direction, Timeframe
from chanedge.domain.ids import zs_id

# The domain field is an int. Phase 1 only builds a bi zhongshu.
_BI_LEVEL = 1


@dataclass
class _Zhongshu:
    id: str
    zg: float
    zd: float
    start_time: datetime
    direction_into: Direction
    member_indexes: list[int]
    confirm_index: int
    ended: bool = False


@dataclass
class ZhongshuBook:
    timeframe: Timeframe
    zhongshus: list[_Zhongshu] = field(default_factory=list)
    buffer: list[int] = field(default_factory=list)

    def apply(self, event: str, held: list) -> None:
        """`replace` keeps the judgment made when that bi was new."""
        if event == "replace":
            return
        if event != "new":
            raise ValueError(f"unknown bi event {event}")
        index = len(held) - 1
        current = self._open()
        if current is not None:
            bi = held[index].bi
            if bi.low > current.zg or bi.high < current.zd:
                current.ended = True
                self.buffer = [index]
            else:
                current.member_indexes.append(index)
            return
        self.buffer.append(index)
        if len(self.buffer) < 3:
            return
        trio = self.buffer[:3]
        zg = min(held[item].bi.high for item in trio)
        zd = max(held[item].bi.low for item in trio)
        if zg <= zd:
            self.buffer.pop(0)
            return
        first = held[trio[0]].bi
        third = held[trio[2]]
        self.zhongshus.append(
            _Zhongshu(
                id=zs_id(self.timeframe, first.end_time, zg, zd),
                zg=zg,
                zd=zd,
                start_time=first.start_time,
                direction_into=first.direction,
                member_indexes=list(trio),
                confirm_index=third.end.k_index_right,
                ended=False,
            )
        )
        self.buffer = self.buffer[3:]

    def publish(self, held: list) -> tuple[Zhongshu, ...]:
        published: list[Zhongshu] = []
        for zs in self.zhongshus:
            members = [held[index].bi for index in zs.member_indexes]
            published.append(
                Zhongshu(
                    id=zs.id,
                    timeframe=self.timeframe,
                    zg=zs.zg,
                    zd=zs.zd,
                    gg=max(bi.high for bi in members),
                    dd=min(bi.low for bi in members),
                    start_time=zs.start_time,
                    end_time=members[-1].end_time,
                    bi_ids=tuple(bi.id for bi in members),
                    direction_into=zs.direction_into,
                    level=_BI_LEVEL,
                    confirmed=True,
                )
            )
        return tuple(published)

    def _open(self) -> _Zhongshu | None:
        if self.zhongshus and not self.zhongshus[-1].ended:
            return self.zhongshus[-1]
        return None
