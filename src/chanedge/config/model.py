"""Pydantic settings. Numeric defaults live in YAML, not here."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_WEIGHT_TOLERANCE = Decimal("1e-9")


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("expected a decimal number")
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("expected a decimal number")


Money = Annotated[Decimal, BeforeValidator(_to_decimal)]


def _require_sum_one(values: object, label: str) -> None:
    total = sum((_to_decimal(item) for item in values), Decimal(0))
    if abs(total - Decimal(1)) > _WEIGHT_TOLERANCE:
        raise ValueError(f"{label} must sum to 1")


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("must be a positive integer")
    return value


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    venue: str
    product: str
    decision_timeframe: str

    @field_validator("mode")
    @classmethod
    def paper_or_live(cls, value: str) -> str:
        if value not in ("paper", "live"):
            raise ValueError("runtime.mode must be paper or live")
        return value


class PinSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    venue_symbol: str


class UniverseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    size: int
    quote: str
    metric: str
    bar: str
    refresh: str
    refresh_minute: int
    exclude_bases: list[str]
    pin: list[PinSymbol] | None = None

    @field_validator("mode")
    @classmethod
    def known_mode(cls, value: str) -> str:
        if value not in ("top_quote_volume", "pin"):
            raise ValueError("universe.mode must be top_quote_volume or pin")
        return value

    @field_validator("size", mode="before")
    @classmethod
    def size_is_twenty(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value != 20:
            raise ValueError("universe.size must be 20")
        return value

    @field_validator("exclude_bases")
    @classmethod
    def clean_bases(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("exclude_bases must not contain duplicates")
        for item in value:
            if not isinstance(item, str) or item == "" or any(ch.isspace() for ch in item):
                raise ValueError("exclude_bases entries must be non-blank and contain no whitespace")
        return value

    @model_validator(mode="after")
    def pin_list(self) -> UniverseSettings:
        if self.mode != "pin":
            return self
        if not self.pin:
            raise ValueError("mode=pin requires a non-empty pin list")
        symbols = [item.symbol for item in self.pin]
        if len(symbols) != len(set(symbols)):
            raise ValueError("pin symbols must be unique")
        return self


class SafetySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kill_switch: bool


class MarketDataSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_start: str
    windows: dict[str, int]
    max_gap_bars: dict[str, int]
    stale_grace_seconds: int
    close_wait_seconds: int
    closed_bars_only: bool

    @field_validator("history_start", mode="before")
    @classmethod
    def history_start_text(cls, value: object) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if not isinstance(value, str) or value == "":
            raise ValueError("history_start must be a date string")
        return value


class ChanlunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_bi_bars: int
    zhongshu_min_bi: int
    segment_algo: str
    segment_enabled: bool
    bias_uses_segment: bool
    engine: str


class FeaturesSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atr_period: int
    volume_median_bars: int
    edge_band_atr: float


class VolatilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atr_pct_min: float
    atr_pct_max: float
    min_samples: int

    @field_validator("min_samples", mode="before")
    @classmethod
    def samples_positive(cls, value: object) -> int:
        return _positive_int(value)


class SessionMultipliers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asia: float
    europe: float
    overlap: float
    us: float
    late: float


class SessionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multipliers: SessionMultipliers
    weekend_multiplier: float
    funding_hours_utc: list[int]
    funding_penalty_minutes: int
    funding_penalty: float
    hard_skip_buckets: list[str]


class JevWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure: float
    location: float
    resonance: float
    volatility_volume: float
    signal_bar: float
    session: float


class StructureWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overlap: float
    agree: float
    contained: float
    clarity: float
    clean: float


class StructureChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: StructureWeights
    overlap_peak: float
    overlap_width: float
    overlap_penalty_above: float
    overlap_penalty: float
    clarity_full_at: float
    clean_leave_full_atr: float
    reentry_factor: list[float]

    @field_validator("reentry_factor")
    @classmethod
    def reentry_bounds(cls, value: list[float]) -> list[float]:
        if len(value) < 1:
            raise ValueError("reentry_factor must contain at least one item")
        for item in value:
            if not 0 <= item <= 1:
                raise ValueError("reentry_factor items must be between 0 and 1 inclusive")
        return value


class LocationWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loc: float
    htf_pos: float
    room: float


class LocationChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: LocationWeights
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


class ResonanceChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    breakout_abs: float
    signal_tf_floor: float


class VolatilityVolumeChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vol_weight: float
    volume_weight: float
    volume_floor: float
    volume_span: float


class SignalBarWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    close_location: float
    body: float
    wick: float


class SignalBarChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: SignalBarWeights
    against_bar_factor: float
    doji_range_pct: float
    doji_penalty: float


class JevChannels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure: StructureChannel
    location: LocationChannel
    resonance: ResonanceChannel
    volatility_volume: VolatilityVolumeChannel
    signal_bar: SignalBarChannel


class JevSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    weights: JevWeights
    enter_threshold: float
    hold_bias: float
    temperature: float
    channels: JevChannels

    @field_validator("hold_bias", "temperature")
    @classmethod
    def strictly_positive(cls, value: float, info: ValidationInfo) -> float:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be > 0")
        return value

    @field_validator("enter_threshold")
    @classmethod
    def unit_interval(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("enter_threshold must be between 0 and 1 inclusive")
        return value

    @model_validator(mode="after")
    def channel_weights(self) -> JevSettings:
        _require_sum_one(self.weights.model_dump().values(), "jev.weights")
        _require_sum_one(
            self.channels.structure.weights.model_dump().values(),
            "jev.channels.structure.weights",
        )
        _require_sum_one(
            self.channels.location.weights.model_dump().values(),
            "jev.channels.location.weights",
        )
        _require_sum_one(
            self.channels.signal_bar.weights.model_dump().values(),
            "jev.channels.signal_bar.weights",
        )
        volume = self.channels.volatility_volume
        _require_sum_one(
            (volume.vol_weight, volume.volume_weight),
            "jev.channels.volatility_volume weights",
        )
        return self


class PartialTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fraction: float
    mode: str
    r_fallback: float


class TrailSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    arm_r: float


class RiskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_equity_quote: Money
    risk_fraction: float
    max_notional_quote: Money
    max_open_positions: int
    max_same_direction: int
    max_gross_notional_quote: Money
    max_leverage: int
    max_cost_r: float
    stop_buffer_atr: float
    one_position_per_symbol: bool
    partials: list[PartialTarget]
    trail: TrailSettings

    @field_validator("max_open_positions", "max_same_direction", mode="before")
    @classmethod
    def positive_counts(cls, value: object) -> int:
        return _positive_int(value)

    @model_validator(mode="after")
    def caps(self) -> RiskSettings:
        if self.max_same_direction > self.max_open_positions:
            raise ValueError("max_same_direction must be <= max_open_positions")
        cost = _to_decimal(self.max_cost_r)
        if not Decimal(0) < cost <= Decimal(1):
            raise ValueError("max_cost_r must be in (0, 1]")
        return self


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_bps: Money
    slippage_bps: Money
    fill_model: str
    order_type: str
    position_mode: str
    margin_mode: str

    @field_validator("position_mode")
    @classmethod
    def one_way_only(cls, value: str) -> str:
        if value != "one_way":
            raise ValueError("position_mode must be one_way")
        return value


class JournalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sqlite_path: str
    parquet_root: str


class MonitorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    bar_tail: int


class SystemOneSettings(BaseModel):
    """Defaults keep config/default.yaml on the local scorer. enabled false omits the hash section."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model_pin: str = "jev-1.14.0"
    question_set: str = "entry-v1"
    timeout_seconds: float = 1.5
    cache_path: str = "data/jev/systemone.jsonl"
    base_url: str = "https://api.typesafe.ai"

    @field_validator("model_pin", "question_set", "cache_path")
    @classmethod
    def non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or value.strip() == "":
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("timeout_seconds must be > 0")
        return float(value)

    @field_validator("base_url")
    @classmethod
    def https_base(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("https://"):
            raise ValueError("base_url must be https")
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime: RuntimeSettings
    universe: UniverseSettings
    safety: SafetySettings
    marketdata: MarketDataSettings
    chanlun: ChanlunSettings
    features: FeaturesSettings
    volatility: VolatilitySettings
    session: SessionSettings
    jev: JevSettings
    systemone: SystemOneSettings = Field(default_factory=SystemOneSettings)
    risk: RiskSettings
    execution: ExecutionSettings
    journal: JournalSettings
    monitor: MonitorSettings
