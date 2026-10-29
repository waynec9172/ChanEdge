from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from chanedge.domain.canon import canonical_json, format_fixed8
from chanedge.domain.enums import DecisionAction, Direction, Mark, SignalType, Timeframe
from chanedge.domain.ids import bi_id, decision_id, fx_id, seg_id, sig_id, zs_id

UTC = timezone.utc
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
T1 = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
HASH = "a" * 64


def test_structure_ids_match_the_locked_strings() -> None:
    assert fx_id(Timeframe.M15, Mark.BOTTOM, T1, 100.5) == (
        "fx:15m:bottom:2024-01-01T00:15:00.000Z:100.50000000"
    )
    assert bi_id(Timeframe.M15, Direction.DOWN, T0, T1, 100, 90) == (
        "bi:15m:down:2024-01-01T00:00:00.000Z:2024-01-01T00:15:00.000Z:100.00000000:90.00000000"
    )
    assert zs_id(Timeframe.M15, T1, 50, 40) == (
        "zs:15m:2024-01-01T00:15:00.000Z:50.00000000:40.00000000"
    )
    assert sig_id(Timeframe.M15, SignalType.SECOND_BUY, T1, 100.5) == (
        "sig:15m:second_buy:2024-01-01T00:15:00.000Z:100.50000000"
    )
    assert bi_id(Timeframe.M15, Direction.DOWN, T0, T1, 100, 90) == bi_id(
        "15m", "down", T0, T1, 100.0, 90.0
    )


def test_decision_id_matches_the_locked_sample_and_changes_with_one_version() -> None:
    sample = decision_id(
        "BTC/USDT",
        T1,
        DecisionAction.HOLD,
        HASH,
        "engine-v1",
        "feature-v1",
        "marketdata-v1",
    )
    assert sample == "dec_ad70ba8d71d416fd"
    assert sample == decision_id(
        "BTC/USDT", T1, "HOLD", HASH, "engine-v1", "feature-v1", "marketdata-v1"
    )
    changed = decision_id(
        "BTC/USDT", T1, DecisionAction.HOLD, HASH, "engine-v2", "feature-v1", "marketdata-v1"
    )
    assert changed != sample


def test_decision_id_is_the_canonical_json_array() -> None:
    payload = [
        "BTC/USDT",
        "2024-01-01T00:15:00.000Z",
        "HOLD",
        HASH,
        "engine-v1",
        "feature-v1",
        "marketdata-v1",
    ]
    text = canonical_json(payload)
    assert " " not in text
    assert "\\/" not in text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert "dec_" + digest[:16] == "dec_ad70ba8d71d416fd"


def test_ids_convert_non_utc_and_collapse_negative_zero() -> None:
    plus8 = timezone(timedelta(hours=8))
    local = datetime(2024, 1, 1, 8, 15, tzinfo=plus8)
    assert fx_id(Timeframe.M15, Mark.BOTTOM, local, 100.5) == (
        "fx:15m:bottom:2024-01-01T00:15:00.000Z:100.50000000"
    )
    tiny = 0.3 - (0.1 + 0.2)
    assert format_fixed8(tiny) == "0.00000000"
    assert fx_id(Timeframe.M15, Mark.BOTTOM, T1, tiny).endswith(":0.00000000")
    with pytest.raises(ValueError):
        fx_id(Timeframe.M15, Mark.BOTTOM, datetime(2024, 1, 1, 0, 15), 1)


def test_segment_id_uses_the_same_price_and_time_format() -> None:
    assert seg_id(Timeframe.M15, Direction.UP, T0, T1, 30, 25) == (
        "seg:15m:up:2024-01-01T00:00:00.000Z:2024-01-01T00:15:00.000Z:30.00000000:25.00000000"
    )
