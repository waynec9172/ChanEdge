"""This bar's candidate. Third class beats second class. Buy plus sell clears it."""

from __future__ import annotations

from datetime import datetime

from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.enums import Side, SignalStatus, SignalType

_BUY = {SignalType.SECOND_BUY, SignalType.THIRD_BUY}
_SELL = {SignalType.SECOND_SELL, SignalType.THIRD_SELL}
_OPERATIONAL = _BUY | _SELL


def select_candidate(
    signals: tuple[ChanSignal, ...] | list[ChanSignal],
    decision_time: datetime,
) -> tuple[ChanSignal | None, tuple[str, ...]]:
    """Signals are already the 15m list. Match time, not the latest confirmed."""
    on_bar = [
        signal
        for signal in signals
        if signal.time == decision_time
        and signal.status is SignalStatus.CONFIRMED
        and signal.type in _OPERATIONAL
    ]
    buy = _prefer(on_bar, SignalType.THIRD_BUY, SignalType.SECOND_BUY)
    sell = _prefer(on_bar, SignalType.THIRD_SELL, SignalType.SECOND_SELL)
    if buy is not None and sell is not None:
        chosen = {buy.id, sell.id}
        ordered: list[str] = []
        for signal in on_bar:
            if signal.id in chosen and signal.id not in ordered:
                ordered.append(signal.id)
        return None, tuple(ordered)
    return buy or sell, ()


def candidate_side(signal: ChanSignal | None) -> Side:
    if signal is None:
        return Side.NONE
    if signal.type in _BUY:
        return Side.LONG
    if signal.type in _SELL:
        return Side.SHORT
    return Side.NONE


def _prefer(
    signals: list[ChanSignal],
    third: SignalType,
    second: SignalType,
) -> ChanSignal | None:
    thirds = [signal for signal in signals if signal.type is third]
    if thirds:
        return thirds[-1]
    seconds = [signal for signal in signals if signal.type is second]
    if seconds:
        return seconds[-1]
    return None
