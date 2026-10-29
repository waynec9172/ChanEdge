"""Constructor parameters for pure modules. Callers map settings into these."""

from __future__ import annotations

import math
from decimal import Decimal

from pydantic import model_validator

from chanedge.domain.enums import SessionBucket
from chanedge.domain.model import DomainModel


class StructureScoreParams(DomainModel):
    overlap: float
    agree: float
    contained: float
    clarity: float
    clean: float
    overlap_peak: float
    overlap_width: float
    overlap_penalty_above: float
    overlap_penalty: float
    clarity_full_at: float
    clean_leave_full_atr: float
    reentry_factor: tuple[float, ...]


class LocationScoreParams(DomainModel):
    loc: float
    htf_pos: float
    room: float
    third_peak: float
    third_width: float
    second_peak: float
    second_width: float
    long_htf_peak: float
    short_htf_peak: float
    htf_width: float
    outside_range_score: float
    room_full_atr: float
    nearby_penalty_atr: float
    nearby_penalty: float


class ResonanceScoreParams(DomainModel):
    breakout_abs: float
    signal_tf_floor: float


class VolatilityScoreParams(DomainModel):
    vol_weight: float
    volume_weight: float
    volume_floor: float
    volume_span: float


class SignalBarScoreParams(DomainModel):
    close_location: float
    body: float
    wick: float
    against_bar_factor: float
    doji_range_pct: float
    doji_penalty: float


class SessionScoreParams(DomainModel):
    asia: float
    europe: float
    overlap: float
    us: float
    late: float
    weekend_multiplier: float
    funding_hours_utc: tuple[int, ...]
    funding_penalty_minutes: int
    funding_penalty: float
    hard_skip_buckets: tuple[str, ...]


class FeatureParams(DomainModel):
    atr_period: int
    volume_median_bars: int
    edge_band_atr: float
    atr_pct_min: float
    atr_pct_max: float
    min_samples: int
    structure: StructureScoreParams
    location: LocationScoreParams
    resonance: ResonanceScoreParams
    volatility_volume: VolatilityScoreParams
    signal_bar: SignalBarScoreParams
    session: SessionScoreParams

    @model_validator(mode="before")
    @classmethod
    def periods_are_positive(cls, data: object) -> object:
        if isinstance(data, dict):
            for name in ("atr_period", "volume_median_bars", "min_samples"):
                if name not in data:
                    continue
                value = data[name]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f"{name} must be a positive int")
            structure = data.get("structure")
            factor = structure.get("reentry_factor") if isinstance(structure, dict) else None
            if factor is not None and len(factor) < 1:
                raise ValueError("reentry_factor must contain at least one item")
        return data

    @model_validator(mode="after")
    def periods_stay_positive(self) -> FeatureParams:
        for name in ("atr_period", "volume_median_bars", "min_samples"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        if len(self.structure.reentry_factor) < 1:
            raise ValueError("reentry_factor must contain at least one item")
        return self


_JEV_WEIGHTS = (
    "structure",
    "location",
    "resonance",
    "volatility_volume",
    "signal_bar",
    "session",
)
_JEV_MASS = ("hold_bias", "temperature")


class JevParams(DomainModel):
    version: str
    structure: float
    location: float
    resonance: float
    volatility_volume: float
    signal_bar: float
    session: float
    enter_threshold: float
    hold_bias: float
    temperature: float

    @model_validator(mode="before")
    @classmethod
    def mass_is_positive(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "version" in data:
            version = data["version"]
            if not isinstance(version, str) or version == "":
                raise ValueError("version must be a non-empty string")
        for name in (*_JEV_WEIGHTS, "enter_threshold", *_JEV_MASS):
            if name not in data:
                continue
            value = data[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
        for name in _JEV_MASS:
            if name not in data:
                continue
            if data[name] <= 0:
                raise ValueError(f"{name} must be > 0")
        return data


_RULE_WINDOWS = ("window_15m", "window_1h", "window_4h")
_RULE_BAND = ("atr_pct_min", "atr_pct_max")
_SESSION_BUCKETS = {item.value for item in SessionBucket}


class RuleParams(DomainModel):
    """Windows, ATR band, and hard-skip buckets for RuleGate. No score threshold."""

    window_15m: int
    window_1h: int
    window_4h: int
    atr_pct_min: float
    atr_pct_max: float
    hard_skip_buckets: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def thresholds_are_real(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_rule_windows(data)
            _reject_rule_band(data)
            if "hard_skip_buckets" in data:
                _reject_buckets(data["hard_skip_buckets"])
        return data

    @model_validator(mode="after")
    def thresholds_stay_real(self) -> RuleParams:
        for name in _RULE_WINDOWS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in _RULE_BAND:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.atr_pct_min < 0 or self.atr_pct_max < self.atr_pct_min:
            raise ValueError("atr_pct band must satisfy 0 <= min <= max")
        _reject_buckets(self.hard_skip_buckets)
        return self


def _reject_rule_windows(data: dict[str, object]) -> None:
    for name in _RULE_WINDOWS:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive int")


def _reject_rule_band(data: dict[str, object]) -> None:
    seen: dict[str, float] = {}
    for name in _RULE_BAND:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        seen[name] = float(value)
    if len(seen) == 2 and (seen["atr_pct_min"] < 0 or seen["atr_pct_max"] < seen["atr_pct_min"]):
        raise ValueError("atr_pct band must satisfy 0 <= min <= max")


def _reject_buckets(buckets: object) -> None:
    if isinstance(buckets, (str, bytes)) or not isinstance(buckets, (list, tuple)):
        raise ValueError("hard_skip_buckets must be a list of session buckets")
    seen: set[str] = set()
    for item in buckets:
        if not isinstance(item, str) or item not in _SESSION_BUCKETS or item in seen:
            raise ValueError("hard_skip_buckets entries must be unique session buckets")
        seen.add(item)


_RISK_COUNTS = ("max_open_positions", "max_same_direction", "max_leverage")
_RISK_MONEY = (
    "risk_fraction",
    "max_notional_quote",
    "max_gross_notional_quote",
    "max_cost_r",
    "stop_buffer_atr",
    "partial_fraction",
    "r_fallback",
    "arm_r",
    "fee_bps",
    "slippage_bps",
)


class RiskParams(DomainModel):
    """Sizing, stop, and cost inputs for RiskManager. No numeric defaults."""

    risk_fraction: Decimal
    max_notional_quote: Decimal
    max_gross_notional_quote: Decimal
    max_open_positions: int
    max_same_direction: int
    max_leverage: int
    max_cost_r: Decimal
    stop_buffer_atr: Decimal
    partial_fraction: Decimal
    r_fallback: Decimal
    arm_r: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal

    @model_validator(mode="before")
    @classmethod
    def numbers_are_real(cls, data: object) -> object:
        if isinstance(data, dict):
            _reject_risk_counts(data)
            _reject_risk_money(data)
        return data

    @model_validator(mode="after")
    def numbers_stay_real(self) -> RiskParams:
        for name in _RISK_COUNTS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        if self.max_same_direction > self.max_open_positions:
            raise ValueError("max_same_direction must be <= max_open_positions")
        _require_positive(self.risk_fraction, "risk_fraction")
        _require_positive(self.max_notional_quote, "max_notional_quote")
        _require_positive(self.max_gross_notional_quote, "max_gross_notional_quote")
        _require_positive(self.r_fallback, "r_fallback")
        _require_positive(self.arm_r, "arm_r")
        _require_unit_interval(self.max_cost_r, "max_cost_r")
        _require_unit_interval(self.partial_fraction, "partial_fraction")
        _require_non_negative(self.stop_buffer_atr, "stop_buffer_atr")
        _require_non_negative(self.fee_bps, "fee_bps")
        _require_non_negative(self.slippage_bps, "slippage_bps")
        return self


def _reject_risk_counts(data: dict[str, object]) -> None:
    for name in _RISK_COUNTS:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive int")


def _reject_risk_money(data: dict[str, object]) -> None:
    for name in _RISK_MONEY:
        if name not in data:
            continue
        data[name] = _money(name, data[name])


def _money(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise ValueError(f"{name} must be a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if isinstance(value, Decimal):
        decimal = value
    else:
        try:
            decimal = Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"{name} must be a finite number") from exc
    if not decimal.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return decimal


def _require_positive(value: Decimal, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def _require_unit_interval(value: Decimal, name: str) -> None:
    if not Decimal(0) < value <= Decimal(1):
        raise ValueError(f"{name} must be in (0, 1]")
