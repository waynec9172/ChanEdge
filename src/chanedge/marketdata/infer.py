"""Decimal inference from vision CSV text. Never float() the token first."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal

from chanedge.domain.enums import InstrumentSource

_NUMBER = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)")
_OPEN_TIME = 0
_OPEN = 1
_HIGH = 2
_LOW = 3
_CLOSE = 4
_VOLUME = 5


@dataclass(frozen=True)
class InferredSpec:
    """Empty fields plus failed=True when a token is not a plain number.

    On success the three sizes are positive Decimals, min_notional stays empty,
    and instrument_source is inferred. INSTRUMENT_SPEC is not raised here.
    """

    price_tick: Decimal | None
    qty_step: Decimal | None
    min_qty: Decimal | None
    min_notional: Decimal | None
    instrument_source: InstrumentSource | None
    failed: bool


def decimal_places(token: str) -> int:
    """Places left after the point, once trailing zeros are stripped.

    No decimal point means 0. A token that is not a plain decimal number raises
    ValueError. Scientific notation is not a plain number.
    """
    text = token.strip()
    if _NUMBER.fullmatch(text) is None:
        raise ValueError(f"not a plain number: {token!r}")
    if "." not in text:
        return 0
    fractional = text.split(".", 1)[1]
    return len(fractional.rstrip("0"))


def is_plain_number(token: str) -> bool:
    return _NUMBER.fullmatch(token.strip()) is not None


def tick_from_places(places: int) -> Decimal:
    if places < 0:
        raise ValueError("places must be >= 0")
    if places == 0:
        return Decimal(1)
    return Decimal(10) ** -places


def infer_spec_from_csv(text: str) -> InferredSpec:
    """Max price places across open/high/low/close, volume places for qty_step.

    Header rows and blank rows are ignored. Any data row whose price or volume
    token is not a plain number fails the whole inference.
    """
    price_places = 0
    volume_places = 0
    saw_row = False
    for row in _data_rows(text):
        if len(row) <= _VOLUME:
            return _failed()
        saw_row = True
        try:
            places = [decimal_places(row[index]) for index in (_OPEN, _HIGH, _LOW, _CLOSE)]
            volume_places = max(volume_places, decimal_places(row[_VOLUME]))
        except ValueError:
            return _failed()
        price_places = max(price_places, *places)
    if not saw_row:
        return _failed()
    price_tick = tick_from_places(price_places)
    qty_step = tick_from_places(volume_places)
    if price_tick <= 0 or qty_step <= 0:
        return _failed()
    return InferredSpec(
        price_tick=price_tick,
        qty_step=qty_step,
        min_qty=qty_step,
        min_notional=None,
        instrument_source=InstrumentSource.INFERRED,
        failed=False,
    )


def _failed() -> InferredSpec:
    return InferredSpec(
        price_tick=None,
        qty_step=None,
        min_qty=None,
        min_notional=None,
        instrument_source=None,
        failed=True,
    )


def _data_rows(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    rows: list[list[str]] = []
    for raw in reader:
        cells = [cell.strip() for cell in raw]
        if not cells or all(cell == "" for cell in cells):
            continue
        open_time = cells[_OPEN_TIME] if cells else ""
        if not open_time.isdigit():
            continue
        rows.append(cells)
    return rows
