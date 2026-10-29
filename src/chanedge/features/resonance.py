"""Resonance channel. Long and short each use the map written for that side."""

from __future__ import annotations

from chanedge.domain.chanlun import ChanSnapshot
from chanedge.domain.decision import ResonanceFeatures
from chanedge.domain.enums import Side, StructureBias
from chanedge.domain.params import FeatureParams
from chanedge.features.mathutil import clamp


def resonance_channel(
    snapshot_15m: ChanSnapshot,
    snapshot_1h: ChanSnapshot,
    snapshot_4h: ChanSnapshot,
    side: Side,
    params: FeatureParams,
) -> ResonanceFeatures:
    strength = params.resonance.breakout_abs
    signed_15m = _signed(snapshot_15m.structure_bias, strength)
    signed_1h = _signed(snapshot_1h.structure_bias, strength)
    signed_4h = _signed(snapshot_4h.structure_bias, strength)
    signed = (signed_15m, signed_1h, signed_4h)
    neutral = _long_map(0.0)
    if side is Side.LONG:
        raw = [_long_map(value) for value in signed]
        floored = list(raw)
        floored[0] = max(floored[0], params.resonance.signal_tf_floor)
        gate = snapshot_4h.structure_bias in {StructureBias.UP, StructureBias.BREAKOUT_UP} and snapshot_1h.structure_bias not in {
            StructureBias.DOWN,
            StructureBias.BREAKOUT_DOWN,
        }
        subscore = sum(floored) / 3
        count = sum(value > neutral for value in raw)
        direction = Side.LONG
    elif side is Side.SHORT:
        raw = [_short_map(value) for value in signed]
        floored = list(raw)
        floored[0] = max(floored[0], params.resonance.signal_tf_floor)
        gate = snapshot_4h.structure_bias in {StructureBias.DOWN, StructureBias.BREAKOUT_DOWN} and snapshot_1h.structure_bias not in {
            StructureBias.UP,
            StructureBias.BREAKOUT_UP,
        }
        subscore = sum(floored) / 3
        count = sum(value > neutral for value in raw)
        direction = Side.SHORT
    else:
        gate = False
        subscore = 0.0
        count = 0
        direction = Side.NONE
    return ResonanceFeatures(
        bias_15m=snapshot_15m.structure_bias,
        bias_1h=snapshot_1h.structure_bias,
        bias_4h=snapshot_4h.structure_bias,
        signed_15m=signed_15m,
        signed_1h=signed_1h,
        signed_4h=signed_4h,
        signal_direction=direction,
        resonance_count=count,
        htf_gate_would_pass=gate,
        subscore=subscore,
        penalty=0.0,
        skip=False,
    )


def _signed(bias: StructureBias, breakout_abs: float) -> float:
    if bias is StructureBias.UP:
        return 1.0
    if bias is StructureBias.DOWN:
        return -1.0
    if bias is StructureBias.NEUTRAL:
        return 0.0
    if bias is StructureBias.BREAKOUT_UP:
        return breakout_abs
    return -breakout_abs


def _long_map(signed: float) -> float:
    return clamp((signed + 1.0) / 2.0, 0.0, 1.0)


def _short_map(signed: float) -> float:
    return clamp((1.0 - signed) / 2.0, 0.0, 1.0)
