from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from chanedge.domain.enums import InstrumentSource
from chanedge.marketdata.infer import decimal_places, infer_spec_from_csv
from chanedge.marketdata.version import MARKETDATA_VERSION
from chanedge.domain.ids import decision_id

UTC = timezone.utc


def _row(open_: str, high: str, low: str, close: str, volume: str) -> str:
    return f"1704067200000,{open_},{high},{low},{close},{volume},1704068099999,1,1,0,0,0"


def test_btc_style_text_yields_tick_and_step() -> None:
    spec = infer_spec_from_csv(_row("0.10", "0.10", "0.10", "0.10", "0.001"))
    assert spec.failed is False
    assert spec.price_tick == Decimal("0.1")
    assert spec.qty_step == Decimal("0.001")
    assert spec.min_qty == Decimal("0.001")
    assert spec.min_notional is None
    assert spec.instrument_source is InstrumentSource.INFERRED


def test_raw_token_keeps_places_that_float_would_spoil() -> None:
    assert decimal_places("0.00000010") == 7
    spec = infer_spec_from_csv(_row("0.00000010", "0.00000010", "0.00000010", "0.00000010", "1"))
    assert spec.failed is False
    assert spec.price_tick == Decimal("0.0000001")
    assert spec.qty_step == Decimal(1)
    assert spec.min_qty == Decimal(1)


def test_integer_prices_use_tick_one_and_max_places_win() -> None:
    text = "\n".join(
        (
            _row("1", "2", "1", "1", "1.0"),
            _row("0.01", "0.02", "0.01", "0.01", "10"),
        )
    )
    spec = infer_spec_from_csv(text)
    assert spec.price_tick == Decimal("0.01")
    assert spec.qty_step == Decimal(1)


def test_inference_failure_leaves_the_spec_empty() -> None:
    for text in (
        _row("0.10", "0.10", "0.10", "0.10", "abc"),
        _row("1e-7", "1e-7", "1e-7", "1e-7", "1"),
        "",
        "open_time,open,high,low,close,volume\n",
    ):
        spec = infer_spec_from_csv(text)
        assert spec.failed is True
        assert spec.price_tick is None
        assert spec.qty_step is None
        assert spec.min_qty is None
        assert spec.min_notional is None
        assert spec.instrument_source is None


def test_whitespace_is_stripped_before_counting() -> None:
    assert decimal_places("  0.10  ") == 1


def test_marketdata_version_names_the_rules_and_changes_decision_id() -> None:
    for phrase in (
        "vision-um-klines-monthly-else-daily",
        "symbol-endswith-USDT-no-underscore-exclude-bases",
        "skip-quote-volume-le-0",
        "csv-text-decimal-inference",
    ):
        assert phrase in MARKETDATA_VERSION
    moment = datetime(2024, 1, 1, 0, 15, tzinfo=UTC)
    config_hash = "a" * 64
    left = decision_id("BTC/USDT", moment, "HOLD", config_hash, "engine-v1", "feature-v1", MARKETDATA_VERSION)
    right = decision_id("BTC/USDT", moment, "HOLD", config_hash, "engine-v1", "feature-v1", "other")
    assert left != right
    assert left.startswith("dec_")
