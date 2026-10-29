"""String enums from architecture §6. Values are the canonical tokens."""

from __future__ import annotations

from enum import StrEnum


class Timeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


class Mark(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"


class StructureBias(StrEnum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    BREAKOUT_UP = "breakout_up"
    BREAKOUT_DOWN = "breakout_down"


class SignalType(StrEnum):
    SECOND_BUY = "second_buy"
    THIRD_BUY = "third_buy"
    SECOND_SELL = "second_sell"
    THIRD_SELL = "third_sell"
    FIRST_BUY = "first_buy"
    FIRST_SELL = "first_sell"


class SignalStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class ProductType(StrEnum):
    USDT_PERP = "usdt_perp"
    SPOT = "spot"


class DecisionAction(StrEnum):
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"
    REDUCE = "REDUCE"
    HOLD = "HOLD"


class ProposedAction(StrEnum):
    """JEV action. This is not DecisionAction."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class VetoCode(StrEnum):
    NO_CANDIDATE = "no_candidate"
    AMBIGUOUS_SIGNAL = "ambiguous_signal"
    HTF_DIRECTION = "htf_direction"
    MTF_1H_CONFLICT = "mtf_1h_conflict"
    STALE_DATA = "stale_data"
    PIPELINE_TIMEOUT = "pipeline_timeout"
    GAP_DATA = "gap_data"
    VOL_BAND = "vol_band"
    SESSION_SKIP = "session_skip"
    POSITION_OPEN = "position_already_open"
    KILL_SWITCH = "kill_switch"
    RISK_CAP = "risk_cap"
    MAX_NOTIONAL = "max_notional"
    MIN_QTY = "min_qty"
    MAX_OPEN_POSITIONS = "max_open_positions"
    MAX_SAME_DIRECTION = "max_same_direction"
    MAX_GROSS_NOTIONAL = "max_gross_notional"
    COST_R = "cost_r"
    INSTRUMENT_SPEC = "instrument_spec"
    OUTSIDE_UNIVERSE = "outside_universe"
    INSUFFICIENT_HISTORY = "insufficient_history"


class InstrumentSource(StrEnum):
    EXCHANGE = "exchange"
    INFERRED = "inferred"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class FillModel(StrEnum):
    NEXT_OPEN = "next_open"
    INTRABAR = "intrabar"


class ExitKind(StrEnum):
    EXIT = "EXIT"
    REDUCE = "REDUCE"


class ExitReason(StrEnum):
    OPPOSITE_SIGNAL = "opposite_signal"
    BIAS_1H = "bias_1h"
    STRUCTURE_STOP = "structure_stop"
    BREAKEVEN_STOP = "breakeven_stop"
    BREAKEVEN_ADVERSE = "breakeven_adverse"
    RATCHET_STOP = "ratchet_stop"
    ZHONGSHU_FAIL = "zhongshu_fail"
    SWING_FAIL = "swing_fail"


class AmendReason(StrEnum):
    BREAKEVEN = "breakeven"
    RATCHET = "ratchet"


class PartialReason(StrEnum):
    PRIOR_SWING = "prior_swing"
    R_MULTIPLE = "r_multiple"


class TrailKind(StrEnum):
    STRUCTURE_FENXING = "structure_fenxing"


class ReasonStage(StrEnum):
    DATA = "data"
    CHANLUN = "chanlun"
    JEV = "jev"
    RULES = "rules"
    RISK = "risk"
    EXECUTION = "execution"


class RuntimeMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class SessionBucket(StrEnum):
    ASIA = "asia"
    EUROPE = "europe"
    OVERLAP = "overlap"
    US = "us"
    LATE = "late"


class RegimeLabel(StrEnum):
    LOW_EXTREME = "low_extreme"
    LOW_NORMAL = "low_normal"
    HIGH_NORMAL = "high_normal"
    HIGH_EXTREME = "high_extreme"
    UNKNOWN = "unknown"


CHANNEL_NAMES: tuple[str, ...] = (
    "structure",
    "location",
    "resonance",
    "volatility_volume",
    "signal_bar",
    "session",
)
