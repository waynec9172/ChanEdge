"""Second and third buy/sell, emitted from the same left-to-right walk."""

from __future__ import annotations

from dataclasses import dataclass

from chanedge.chanlun.bias import live_departure, select_active_through
from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.enums import Direction, SignalStatus, SignalType
from chanedge.domain.ids import sig_id


@dataclass
class _DepartureRecord:
    seen_pullback: bool = False
    third_emitted: bool = False
    pullback_slot: int | None = None


class SignalMemory:
    """Departure identities already used for a third buy or third sell."""

    def __init__(self) -> None:
        self.departures: dict[tuple[str, object], _DepartureRecord] = {}

    def record(self, zs_id: str, first_open_time: object) -> _DepartureRecord:
        key = (zs_id, first_open_time)
        found = self.departures.get(key)
        if found is None:
            found = _DepartureRecord()
            self.departures[key] = found
        return found


def apply_signals(state, event: str) -> None:
    """`new` may emit. `replace` rewrites related_bi_id or re-emits a second buy/sell."""
    if event not in ("new", "replace"):
        raise ValueError(f"unknown bi event {event}")
    bi = state.held[-1].bi
    if bi.direction == Direction.DOWN or bi.direction is Direction.DOWN:
        _on_down(state, event)
        return
    _on_up(state, event)


def _on_down(state, event: str) -> None:
    active, departure = _context(state)
    level = state.held[-1].bi.end_price
    prior = _previous_end(state, Direction.DOWN)
    above_zg = active is not None and level > active.zg
    if event == "replace" and _has(state, SignalType.THIRD_BUY):
        _rewrite(state, SignalType.THIRD_BUY)
        return
    if _try_third(state, active, departure, "up", SignalType.THIRD_BUY, Direction.UP):
        return
    if above_zg:
        return
    if prior is None or not level > prior:
        return
    if active is not None and level > active.zg:
        return
    if event == "replace":
        _rewrite(state, SignalType.SECOND_BUY)
    _emit(
        state,
        kind=SignalType.SECOND_BUY,
        direction=Direction.UP,
        defending=level,
        prior=prior,
        related=None,
    )


def _on_up(state, event: str) -> None:
    active, departure = _context(state)
    level = state.held[-1].bi.end_price
    prior = _previous_end(state, Direction.UP)
    below_zd = active is not None and level < active.zd
    if event == "replace" and _has(state, SignalType.THIRD_SELL):
        _rewrite(state, SignalType.THIRD_SELL)
        return
    if _try_third(state, active, departure, "down", SignalType.THIRD_SELL, Direction.DOWN):
        return
    if below_zd:
        return
    if prior is None or not level < prior:
        return
    if active is not None and level < active.zd:
        return
    if event == "replace":
        _rewrite(state, SignalType.SECOND_SELL)
    _emit(
        state,
        kind=SignalType.SECOND_SELL,
        direction=Direction.DOWN,
        defending=level,
        prior=prior,
        related=None,
    )


def _try_third(state, active, departure, side: str, kind: SignalType, direction: Direction) -> bool:
    """Emit at most one third-class signal for this departure. True when this call emits."""
    if active is None or departure is None or departure[0] != side:
        return False
    _depart_side, start = departure
    item = state.held[-1]
    if item.end.k_index_mid <= start:
        return False
    record = state.memory.record(active.id, state.bars[start].open_time)
    slot = len(state.held) - 1
    if record.seen_pullback and record.pullback_slot != slot:
        return False
    if not record.seen_pullback:
        record.seen_pullback = True
        record.pullback_slot = slot
    if record.third_emitted:
        return False
    cleared = item.bi.low > active.zg if side == "up" else item.bi.high < active.zd
    if not cleared:
        return False
    record.third_emitted = True
    _emit(
        state,
        kind=kind,
        direction=direction,
        defending=item.bi.end_price,
        prior=None,
        related=active.id,
    )
    return True


def _context(state):
    confirm = state.held[-1].end.k_index_right
    active = select_active_through(state.book, state.held, state.bars, confirm)
    if active is None:
        return None, None
    return active, live_departure(active, state.bars, confirm)


def _previous_end(state, direction: Direction) -> float | None:
    for item in reversed(state.held[:-1]):
        if item.bi.direction == direction:
            return item.bi.end_price
    return None


def _has(state, kind: SignalType) -> bool:
    for slot in state.held[-1].signal_slots:
        if state.signals[slot].type == kind:
            return True
    return False


def _rewrite(state, kind: SignalType) -> None:
    bi_id = state.held[-1].bi.id
    for slot in state.held[-1].signal_slots:
        signal = state.signals[slot]
        if signal.type == kind:
            state.signals[slot] = signal.model_copy(update={"related_bi_id": bi_id})


def _emit(
    state,
    *,
    kind: SignalType,
    direction: Direction,
    defending: float,
    prior: float | None,
    related: str | None,
) -> None:
    item = state.held[-1]
    bar = state.bars[item.end.k_index_right]
    state.signals.append(
        ChanSignal(
            id=sig_id(state.timeframe, kind, bar.open_time, defending),
            timeframe=state.timeframe,
            type=kind,
            status=SignalStatus.CONFIRMED,
            time=bar.close_time,
            price=bar.close,
            direction=direction,
            defending_fx_id=item.end.id,
            defending_price=defending,
            related_bi_id=item.bi.id,
            bar_open_time=bar.open_time,
            related_zhongshu_id=related,
            prior_extreme=prior,
            notes="",
        )
    )
    item.signal_slots.append(len(state.signals) - 1)
