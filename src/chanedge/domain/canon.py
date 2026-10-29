"""Canonical JSON shared by config_hash and decision ids.

domain cannot import config. config.hash re-exports canonical_json from here.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping


def canonical_json(value: object) -> str:
    """UTF-8 JSON: sorted keys, no extra whitespace, numbers to 8 decimal places."""
    return _dump(value)


def format_fixed8(value: float | Decimal | int) -> str:
    """format(x, '.8f'), then rewrite a negative zero string to 0.00000000."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError("expected a number")
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
    utc = value.astimezone(timezone.utc)
    millis = utc.microsecond // 1000
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _dump(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return format_fixed8(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return json.dumps(format_time_z(value), ensure_ascii=False)
    if isinstance(value, Mapping):
        items = ",".join(
            json.dumps(str(key), ensure_ascii=False) + ":" + _dump(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
        return "{" + items + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_dump(item) for item in value) + "]"
    raise TypeError(f"cannot canonicalize {type(value).__name__}")
