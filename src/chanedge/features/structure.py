"""Structure channel. Clarity is 0.5 when the 15m snapshot has no active zhongshu."""

from __future__ import annotations

from collections.abc import Sequence

from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import Bi, ChanSignal, ChanSnapshot, Segment, Zhongshu
from chanedge.domain.decision import StructureFeatures
from chanedge.domain.enums import SignalType
from chanedge.domain.params import FeatureParams
from chanedge.features.mathutil import clamp, ratio, tent

_SEGMENT_ABSENT = "segment_absent"
_ZHONGSHU_ABSENT = "zhongshu_absent"


def structure_channel(
    snapshot: ChanSnapshot,
    bars: Sequence[Bar],
    signal_index: int,
    signal: ChanSignal | None,
    atr: float,
    params: FeatureParams,
) -> StructureFeatures:
    bis = _ordered_bis(snapshot)
    overlap = _overlap_ratio(bis)
    segment = _last_segment(snapshot)
    notes: list[str] = []
    if segment is None:
        agree = 0.5
        contained: float | None = None
        notes.append(_SEGMENT_ABSENT)
    else:
        agree = _agree(bis, segment)
        contained = _contained(snapshot, segment)
    active = _find(snapshot, snapshot.active_zhongshu_id)
    if active is None:
        clarity: float | None = None
        zs_count = 0
        overlap_valid = False
        notes.append(_ZHONGSHU_ABSENT)
    else:
        clarity = 0.0 if active.gg <= active.dd else (active.zg - active.zd) / (active.gg - active.dd)
        zs_count = len(active.bi_ids)
        overlap_valid = active.zg > active.zd
    leave, reentry = _breakout(snapshot, bars, signal_index, signal, atr)
    score = params.structure
    clarity_term = 0.5 if active is None else clamp(ratio(clarity or 0.0, score.clarity_full_at), 0.0, 1.0)
    contained_term = 0.5 if contained is None else contained
    clean = clamp(ratio(leave, score.clean_leave_full_atr), 0.0, 1.0) * _reentry_factor(score.reentry_factor, reentry)
    subscore = 0.0
    if signal is not None:
        subscore = (
            score.overlap * tent(overlap, score.overlap_peak, score.overlap_width)
            + score.agree * agree
            + score.contained * contained_term
            + score.clarity * clarity_term
            + score.clean * clean
        )
    penalty = score.overlap_penalty if overlap > score.overlap_penalty_above else 0.0
    return StructureFeatures(
        consecutive_bi_overlap_ratio=overlap,
        bi_segment_direction_agree=agree,
        bi_contained_in_segment_ratio=contained,
        zs_clarity=clarity,
        zs_bi_count=zs_count,
        zs_overlap_valid=overlap_valid,
        breakout_leave_atr=leave,
        breakout_reentry_bars=reentry,
        signal_type=None if signal is None else signal.type,
        signal_confirmed=signal is not None,
        subscore=subscore,
        penalty=penalty,
        skip=False,
        notes=tuple(notes),
    )


def _ordered_bis(snapshot: ChanSnapshot) -> list[Bi]:
    confirmed = [bi for bi in snapshot.bis if bi.confirmed]

    def key(bi: Bi) -> tuple[int, object]:
        index = _fx_index(snapshot, bi.end_fx_id)
        return (10**9 if index is None else index, bi.end_time)

    return sorted(confirmed, key=key)


def _overlap_ratio(bis: list[Bi]) -> float:
    if len(bis) < 3:
        return 0.0
    ratios: list[float] = []
    for start in range(len(bis) - 3, -1, -1):
        ratios.append(_pair_ratio(bis[start], bis[start + 2]))
        if len(ratios) == 3:
            break
    if not ratios:
        return 0.0
    return sum(ratios) / len(ratios)


def _pair_ratio(left: Bi, right: Bi) -> float:
    shorter = min(left.high - left.low, right.high - right.low)
    if shorter <= 0:
        return 0.0
    intersection = min(left.high, right.high) - max(left.low, right.low)
    if intersection < 0:
        intersection = 0.0
    return intersection / shorter


def _last_segment(snapshot: ChanSnapshot) -> Segment | None:
    chosen: Segment | None = None
    for segment in snapshot.segments:
        if not segment.confirmed:
            continue
        if chosen is None or segment.end_time >= chosen.end_time:
            chosen = segment
    return chosen


def _agree(bis: list[Bi], segment: Segment) -> float:
    if not bis:
        return 0.0
    if bis[-1].direction is segment.direction:
        return 1.0
    return 0.0


def _contained(snapshot: ChanSnapshot, segment: Segment) -> float:
    members = [bi for bi in snapshot.bis if bi.id in segment.bi_ids]
    if not members:
        return 0.0
    inside = 0
    for bi in members:
        if bi.low >= segment.low and bi.high <= segment.high:
            inside += 1
    return inside / len(members)


def _breakout(
    snapshot: ChanSnapshot,
    bars: Sequence[Bar],
    signal_index: int,
    signal: ChanSignal | None,
    atr: float,
) -> tuple[float, int]:
    if signal is None or not bars:
        return 0.0, 0
    kind = signal.type
    if kind is SignalType.SECOND_BUY:
        return _second_leave(signal.defending_price, signal.prior_extreme, atr), _second_reentry(
            snapshot, bars, signal_index
        )
    if kind is SignalType.SECOND_SELL:
        return _second_leave(signal.prior_extreme, signal.defending_price, atr), _second_reentry(
            snapshot, bars, signal_index
        )
    if kind is SignalType.THIRD_BUY:
        return _third_leave(snapshot, bars, signal_index, signal, atr, side="up")
    if kind is SignalType.THIRD_SELL:
        return _third_leave(snapshot, bars, signal_index, signal, atr, side="down")
    return 0.0, 0


def _second_leave(left: float | None, right: float | None, atr: float) -> float:
    if left is None or right is None:
        return 0.0
    return ratio(left - right, atr)


def _second_reentry(snapshot: ChanSnapshot, bars: Sequence[Bar], signal_index: int) -> int:
    active = _find(snapshot, snapshot.active_zhongshu_id)
    if active is None:
        return 0
    found = _departure(snapshot, active, bars, signal_index)
    if found is None:
        return 0
    return _reentry_count(active, bars, found[1], signal_index)


def _third_leave(
    snapshot: ChanSnapshot,
    bars: Sequence[Bar],
    signal_index: int,
    signal: ChanSignal,
    atr: float,
    *,
    side: str,
) -> tuple[float, int]:
    zone = _find(snapshot, signal.related_zhongshu_id)
    if zone is None:
        return 0.0, 0
    found = _departure(snapshot, zone, bars, signal_index)
    if found is None or found[0] != side:
        return 0.0, 0
    start, end = found[1], signal_index
    window = bars[start : end + 1]
    if side == "up":
        leave = ratio(max(bar.high for bar in window) - zone.zg, atr)
    else:
        leave = ratio(zone.zd - min(bar.low for bar in window), atr)
    return leave, _reentry_count(zone, bars, start, end)


def _departure(
    snapshot: ChanSnapshot,
    zone: Zhongshu,
    bars: Sequence[Bar],
    last_index: int,
) -> tuple[str, int] | None:
    """Live departure through last_index. Scan starts at the creating third bi's end bar."""
    confirm = _confirm_index(snapshot, zone, len(bars))
    if last_index < confirm:
        return None
    side = "inside"
    alive = False
    start = confirm
    end = min(last_index, len(bars) - 1)
    for index in range(confirm, end + 1):
        close = bars[index].close
        if zone.zd <= close <= zone.zg:
            side = "inside"
            alive = False
            continue
        if close > zone.zg:
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


def _confirm_index(snapshot: ChanSnapshot, zone: Zhongshu, bar_count: int) -> int:
    if len(zone.bi_ids) < 3 or bar_count < 1:
        return 0
    bi = next((item for item in snapshot.bis if item.id == zone.bi_ids[2]), None)
    if bi is None:
        return 0
    fx = next((item for item in snapshot.fenxings if item.id == bi.end_fx_id), None)
    if fx is None:
        return 0
    return min(max(fx.k_index_right, 0), bar_count - 1)


def _reentry_count(zone: Zhongshu, bars: Sequence[Bar], start: int, end: int) -> int:
    count = 0
    for index in range(start, end + 1):
        close = bars[index].close
        if zone.zd <= close <= zone.zg:
            count += 1
    return count


def _reentry_factor(factors: tuple[float, ...], bars: int) -> float:
    index = bars if bars < len(factors) else len(factors) - 1
    return factors[index]


def _find(snapshot: ChanSnapshot, zs_id: str | None) -> Zhongshu | None:
    if zs_id is None:
        return None
    for zone in snapshot.zhongshus:
        if zone.id == zs_id:
            return zone
    return None


def _fx_index(snapshot: ChanSnapshot, fx_id: str) -> int | None:
    for fenxing in snapshot.fenxings:
        if fenxing.id == fx_id:
            return fenxing.k_index_mid
    return None
