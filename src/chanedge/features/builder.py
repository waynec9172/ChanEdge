"""FeatureBuilder.build(context). Numbers come from the constructor params."""

from __future__ import annotations

from datetime import datetime

from chanedge.domain.bars import Bar, MultiTimeframeContext
from chanedge.domain.decision import FeatureVector
from chanedge.domain.enums import Timeframe
from chanedge.domain.params import FeatureParams
from chanedge.features.atr import wilder_atr
from chanedge.features.location import location_channel
from chanedge.features.resonance import resonance_channel
from chanedge.features.select import candidate_side, select_candidate
from chanedge.features.session import session_channel
from chanedge.features.signal_bar import signal_bar_channel
from chanedge.features.structure import structure_channel
from chanedge.features.version import FEATURE_VERSION
from chanedge.features.volatility import volatility_channel


class FeatureBuilder:
    def __init__(self, params: FeatureParams) -> None:
        if not isinstance(params, FeatureParams):
            raise TypeError("params must be FeatureParams")
        self._params = params

    def build(self, context: MultiTimeframeContext) -> FeatureVector:
        params = self._params
        bars = context.bars[Timeframe.M15]
        snapshot = context.snapshots[Timeframe.M15]
        index = _decision_index(bars, context.decision_time)
        bar = bars[index]
        if bar.symbol != context.symbol:
            raise ValueError("decision bar symbol does not match the context")
        atr_values = wilder_atr(bars, params.atr_period)
        atr = atr_values[index] if atr_values[index] is not None else 0.0
        signal, ambiguous = select_candidate(snapshot.signals, context.decision_time)
        side = candidate_side(signal)
        return FeatureVector(
            feature_version=FEATURE_VERSION,
            symbol=context.symbol,
            decision_time=context.decision_time,
            candidate_signal_id=None if signal is None else signal.id,
            candidate_side=side,
            ambiguous_signal_ids=ambiguous,
            structure=structure_channel(snapshot, bars, index, signal, atr, params),
            location=location_channel(
                snapshot,
                context.snapshots[Timeframe.H4],
                bar,
                signal,
                side,
                atr,
                params,
            ),
            resonance=resonance_channel(
                snapshot,
                context.snapshots[Timeframe.H1],
                context.snapshots[Timeframe.H4],
                side,
                params,
            ),
            volatility_volume=volatility_channel(bars, index, signal, atr_values, atr, params),
            signal_bar=signal_bar_channel(bar, signal, side, params),
            session=session_channel(context.decision_time, signal, params),
        )


def _decision_index(bars: tuple[Bar, ...], decision_time: datetime) -> int:
    found: int | None = None
    for index, bar in enumerate(bars):
        if bar.close_time == decision_time:
            found = index
    if found is None:
        raise ValueError("decision bar is not in the 15m window")
    return found
