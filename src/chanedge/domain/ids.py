"""Pure structure ids and decision_id. No chanlun, features, or marketdata import."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from chanedge.domain.canon import canonical_json, format_fixed8, format_time_z
from chanedge.domain.enums import DecisionAction


def fx_id(
    timeframe: StrEnum | str,
    mark: StrEnum | str,
    open_time: datetime,
    price: float | Decimal | int,
) -> str:
    return f"fx:{_token(timeframe)}:{_token(mark)}:{format_time_z(open_time)}:{format_fixed8(price)}"


def bi_id(
    timeframe: StrEnum | str,
    direction: StrEnum | str,
    start_open_time: datetime,
    end_open_time: datetime,
    start_price: float | Decimal | int,
    end_price: float | Decimal | int,
) -> str:
    return (
        f"bi:{_token(timeframe)}:{_token(direction)}:"
        f"{format_time_z(start_open_time)}:{format_time_z(end_open_time)}:"
        f"{format_fixed8(start_price)}:{format_fixed8(end_price)}"
    )


def zs_id(
    timeframe: StrEnum | str,
    end_open_time: datetime,
    zg: float | Decimal | int,
    zd: float | Decimal | int,
) -> str:
    return (
        f"zs:{_token(timeframe)}:{format_time_z(end_open_time)}:"
        f"{format_fixed8(zg)}:{format_fixed8(zd)}"
    )


def sig_id(
    timeframe: StrEnum | str,
    signal_type: StrEnum | str,
    open_time: datetime,
    defending_price: float | Decimal | int,
) -> str:
    return (
        f"sig:{_token(timeframe)}:{_token(signal_type)}:"
        f"{format_time_z(open_time)}:{format_fixed8(defending_price)}"
    )


def seg_id(
    timeframe: StrEnum | str,
    direction: StrEnum | str,
    start_time: datetime,
    end_time: datetime,
    high: float | Decimal | int,
    low: float | Decimal | int,
) -> str:
    return (
        f"seg:{_token(timeframe)}:{_token(direction)}:"
        f"{format_time_z(start_time)}:{format_time_z(end_time)}:"
        f"{format_fixed8(high)}:{format_fixed8(low)}"
    )


def decision_id(
    symbol: str,
    decision_time: datetime,
    action: DecisionAction | str,
    config_hash: str,
    engine_version: str,
    feature_version: str,
    marketdata_version: str,
) -> str:
    """dec_ plus the first 16 hex chars of the seven-field canonical JSON array."""
    payload = [
        symbol,
        format_time_z(decision_time),
        _token(action),
        config_hash,
        engine_version,
        feature_version,
        marketdata_version,
    ]
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "dec_" + digest[:16]


def _token(value: StrEnum | str) -> str:
    if isinstance(value, StrEnum):
        return str(value)
    return value
