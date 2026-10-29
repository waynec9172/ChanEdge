"""Shared tent and clamps. Undefined division returns 0."""

from __future__ import annotations


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def tent(value: float, peak: float, width: float) -> float:
    if width <= 0:
        return 0.0
    return clamp(1.0 - abs(value - peak) / width, 0.0, 1.0)
