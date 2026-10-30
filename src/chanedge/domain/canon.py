"""Canonical JSON shared by config_hash and decision ids.

domain cannot import config. config.hash re-exports canonical_json from here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from json.encoder import encode_basestring
from typing import Mapping

# Same output as json.dumps(text, ensure_ascii=False) for a str, without the
# encoder setup per call. Snapshot ids dump hundreds of thousands of strings.
_string = encode_basestring


def canonical_json(value: object) -> str:
    """UTF-8 JSON: sorted keys, no extra whitespace, numbers to 8 decimal places."""
    return _dump(value)


def format_fixed8(value: float | Decimal | int) -> str:
    """format(x, '.8f'), then rewrite a negative zero string to 0.00000000."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError("expected a number")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("canonical JSON does not allow nan or infinity")
    return _fixed8(value)


@lru_cache(maxsize=1 << 18, typed=True)
def _fixed8(value: float | Decimal | int) -> str:
    """Cached by value and type. Prices and times repeat across every window."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not allow nan or infinity")
        number = Decimal(repr(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON does not allow nan or infinity")
        number = value
    else:
        number = Decimal(value)
    text = format(number, ".8f")
    if text == "-0.00000000":
        return "0.00000000"
    return text


def format_time_z(value: datetime) -> str:
    """YYYY-MM-DDTHH:MM:SS.mmmZ. Aware non-UTC values are converted first."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return _time_z(value)


@lru_cache(maxsize=1 << 18)
def _time_z(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    millis = utc.microsecond // 1000
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _dump(value: object) -> str:
    """Exact-type fast paths first; subclasses such as StrEnum take the general path."""
    kind = type(value)
    if kind is str:
        return _string(value)
    if kind is float:
        return _fixed8(value)  # raises for nan and infinity, like format_fixed8
    if kind is dict:
        keys = list(value)
        if all(type(key) is str for key in keys):
            keys.sort()
            return "{" + ",".join([_key(key) + _dump(value[key]) for key in keys]) + "}"
    if kind is list or kind is tuple:
        return "[" + ",".join([_dump(item) for item in value]) + "]"
    if kind is int:
        return str(value)
    return _dump_general(value)


@lru_cache(maxsize=4096)
def _key(key: str) -> str:
    return _string(key) + ":"


def _dump_general(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return format_fixed8(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, datetime):
        return _string(format_time_z(value))
    if isinstance(value, Mapping):
        items = ",".join(
            _string(str(key)) + ":" + _dump(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
        return "{" + items + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_dump(item) for item in value) + "]"
    raise TypeError(f"cannot canonicalize {type(value).__name__}")
