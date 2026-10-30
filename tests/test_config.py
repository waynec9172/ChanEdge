from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from chanedge.config import Settings, canonical_json, config_hash, load_settings
from chanedge.config.model import PinSymbol

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config" / "default.yaml"
PAPER = ROOT / "config" / "paper.yaml"


def _load_mutated(tmp_path: Path, mutate) -> Settings:
    data = yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_settings(path)


def test_default_yaml_loads_locked_numbers() -> None:
    settings = load_settings(DEFAULT)
    assert settings.runtime.mode == "paper"
    assert settings.runtime.venue == "binanceusdm"
    assert settings.runtime.product == "usdt_perp"
    assert settings.runtime.decision_timeframe == "15m"
    assert settings.universe.mode == "top_quote_volume"
    assert settings.universe.size == 20
    assert settings.universe.quote == "USDT"
    assert settings.universe.metric == "quote_volume"
    assert settings.universe.bar == "1d"
    assert settings.universe.refresh_minute == 5
    assert settings.universe.exclude_bases == ["USDC", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "EUR"]
    assert settings.universe.pin is None
    assert settings.safety.kill_switch is True
    assert settings.marketdata.history_start == "2024-01-01"
    assert settings.marketdata.windows == {"15m": 1500, "1h": 1000, "4h": 500}
    assert settings.marketdata.max_gap_bars == {"15m": 1, "1h": 1, "4h": 1}
    assert settings.marketdata.stale_grace_seconds == 90
    assert settings.marketdata.close_wait_seconds == 3
    assert settings.marketdata.closed_bars_only is True
    assert settings.chanlun.min_bi_bars == 5
    assert settings.chanlun.zhongshu_min_bi == 3
    assert settings.chanlun.segment_enabled is False
    assert settings.chanlun.bias_uses_segment is False
    assert settings.features.atr_period == 14
    assert settings.volatility.atr_pct_min == pytest.approx(0.001)
    assert settings.volatility.atr_pct_max == pytest.approx(0.030)
    assert settings.volatility.min_samples == 200
    assert settings.jev.enter_threshold == pytest.approx(0.62)
    assert settings.jev.hold_bias == pytest.approx(0.35)
    assert settings.jev.temperature == pytest.approx(1.0)
    assert settings.jev.weights.structure == pytest.approx(0.24)
    assert settings.jev.weights.location == pytest.approx(0.18)
    assert settings.jev.weights.resonance == pytest.approx(0.18)
    assert settings.jev.weights.volatility_volume == pytest.approx(0.14)
    assert settings.jev.weights.signal_bar == pytest.approx(0.14)
    assert settings.jev.weights.session == pytest.approx(0.12)
    assert settings.jev.channels.structure.overlap_peak == pytest.approx(0.35)
    assert settings.jev.channels.structure.reentry_factor == pytest.approx([1.0, 0.4, 0.0])
    assert settings.risk.initial_equity_quote == Decimal("10000")
    assert settings.risk.risk_fraction == pytest.approx(0.005)
    assert settings.risk.max_notional_quote == Decimal("20000")
    assert settings.risk.max_gross_notional_quote == Decimal("20000")
    assert settings.risk.max_open_positions == 3
    assert settings.risk.max_same_direction == 2
    assert settings.risk.max_leverage == 2
    assert settings.risk.max_cost_r == pytest.approx(0.40)
    assert settings.risk.stop_buffer_atr == pytest.approx(0.15)
    assert settings.risk.trail.arm_r == pytest.approx(1.0)
    assert settings.risk.trail.kind == "structure_fenxing"
    assert settings.execution.fee_bps == Decimal("5.0")
    assert settings.execution.slippage_bps == Decimal("1.0")
    assert settings.execution.fill_model == "next_open"
    assert settings.execution.position_mode == "one_way"
    assert settings.journal.sqlite_path == "data/chanedge.sqlite"
    assert settings.monitor.host == "127.0.0.1"
    assert settings.monitor.port == 8765


def test_paper_overlay_keeps_venue_and_other_leaves() -> None:
    base = load_settings(DEFAULT)
    paper = load_settings(DEFAULT, PAPER)
    assert paper.runtime.mode == "paper"
    assert paper.safety.kill_switch is False
    assert paper.runtime.venue == "binanceusdm"
    assert paper.runtime.product == "usdt_perp"
    assert paper.runtime.decision_timeframe == "15m"
    expected = base.model_dump(mode="python")
    expected["runtime"]["mode"] = "paper"
    expected["safety"]["kill_switch"] = False
    assert paper.model_dump(mode="python") == expected


def test_weight_sum_099_is_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["jev"]["weights"]["structure"] = 0.23

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, mutate)


def test_channel_weight_sum_is_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["jev"]["channels"]["structure"]["weights"]["overlap"] = 0.14

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, mutate)


def test_volatility_channel_weights_are_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["jev"]["channels"]["volatility_volume"]["vol_weight"] = 0.5

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, mutate)


def test_universe_size_19_is_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["universe"]["size"] = 19

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, mutate)


def test_exclude_bases_rejects_duplicates_and_blanks(tmp_path: Path) -> None:
    def duplicate(data: dict) -> None:
        data["universe"]["exclude_bases"] = ["USDC", "USDC"]

    def blank(data: dict) -> None:
        data["universe"]["exclude_bases"] = ["USDC", " "]

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, duplicate)
    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, blank)


def test_pin_mode_requires_unique_symbols(tmp_path: Path) -> None:
    def empty(data: dict) -> None:
        data["universe"]["mode"] = "pin"

    def duplicated(data: dict) -> None:
        data["universe"]["mode"] = "pin"
        data["universe"]["pin"] = [
            {"symbol": "BTC/USDT", "venue_symbol": "BTC/USDT:USDT"},
            {"symbol": "BTC/USDT", "venue_symbol": "BTC/USDT:USDT"},
        ]

    def accepted(data: dict) -> None:
        data["universe"]["mode"] = "pin"
        data["universe"]["pin"] = [
            {"symbol": "BTC/USDT", "venue_symbol": "BTC/USDT:USDT"},
            {"symbol": "ETH/USDT", "venue_symbol": "ETH/USDT:USDT"},
        ]

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, empty)
    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, duplicated)
    loaded = _load_mutated(tmp_path, accepted)
    assert loaded.universe.mode == "pin"
    assert [item.symbol for item in loaded.universe.pin or []] == ["BTC/USDT", "ETH/USDT"]


def test_reentry_hold_bias_and_threshold_bounds(tmp_path: Path) -> None:
    def empty_reentry(data: dict) -> None:
        data["jev"]["channels"]["structure"]["reentry_factor"] = []

    def high_reentry(data: dict) -> None:
        data["jev"]["channels"]["structure"]["reentry_factor"] = [1.1]

    def zero_bias(data: dict) -> None:
        data["jev"]["hold_bias"] = 0

    def high_threshold(data: dict) -> None:
        data["jev"]["enter_threshold"] = 1.2

    def zero_temperature(data: dict) -> None:
        data["jev"]["temperature"] = 0

    for mutate in (empty_reentry, high_reentry, zero_bias, high_threshold, zero_temperature):
        with pytest.raises(ValidationError):
            _load_mutated(tmp_path, mutate)


def test_risk_and_position_mode_bounds(tmp_path: Path) -> None:
    def zero_cost(data: dict) -> None:
        data["risk"]["max_cost_r"] = 0

    def high_cost(data: dict) -> None:
        data["risk"]["max_cost_r"] = 1.01

    def too_many_same_direction(data: dict) -> None:
        data["risk"]["max_same_direction"] = 4

    def zero_same_direction(data: dict) -> None:
        data["risk"]["max_same_direction"] = 0

    def zero_samples(data: dict) -> None:
        data["volatility"]["min_samples"] = 0

    def hedge(data: dict) -> None:
        data["execution"]["position_mode"] = "hedge"

    for mutate in (zero_cost, high_cost, too_many_same_direction, zero_same_direction, zero_samples, hedge):
        with pytest.raises(ValidationError):
            _load_mutated(tmp_path, mutate)

    def cost_ceiling(data: dict) -> None:
        data["risk"]["max_cost_r"] = 1

    loaded = _load_mutated(tmp_path, cost_ceiling)
    assert loaded.risk.max_cost_r == pytest.approx(1)


def test_secret_fields_are_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["api_key"] = "secret"

    with pytest.raises(ValueError, match="api_key"):
        _load_mutated(tmp_path, mutate)

    def typesafe_key(data: dict) -> None:
        data["typesafe_api_key"] = "secret"

    with pytest.raises(ValueError, match="typesafe_api_key"):
        _load_mutated(tmp_path, typesafe_key)


def test_nested_token_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("token: abc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="token"):
        load_settings(path)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["runtime"]["nickname"] = "desk"

    with pytest.raises(ValidationError):
        _load_mutated(tmp_path, mutate)


def test_canonical_json_sorts_keys_and_formats_numbers() -> None:
    text = canonical_json({"b": 1, "a": 0.5, "nested": {"z": True, "y": None}, "items": ["x", 0.1]})
    assert text == '{"a":0.50000000,"b":1,"items":["x",0.10000000],"nested":{"y":null,"z":true}}'
    stamped = datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc)
    assert canonical_json({"t": stamped}) == '{"t":"2024-01-01T00:15:00.000Z"}'
    assert " " not in text


def test_config_hash_changes_with_weight_not_with_equity_or_switch() -> None:
    settings = load_settings(DEFAULT)
    original = config_hash(settings)
    assert len(original) == 64
    assert original == original.lower()
    assert original == config_hash(load_settings(DEFAULT))

    weights = settings.jev.weights.model_copy(update={"structure": settings.jev.weights.structure + 0.01})
    changed_weight = settings.model_copy(update={"jev": settings.jev.model_copy(update={"weights": weights})})
    assert config_hash(changed_weight) != original

    changed_equity = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"initial_equity_quote": Decimal("1")})}
    )
    assert config_hash(changed_equity) == original

    changed_switch = settings.model_copy(
        update={"safety": settings.safety.model_copy(update={"kill_switch": False})}
    )
    assert config_hash(changed_switch) == original

    changed_mode = settings.model_copy(update={"runtime": settings.runtime.model_copy(update={"mode": "live"})})
    assert config_hash(changed_mode) == original

    changed_wait = settings.model_copy(
        update={"marketdata": settings.marketdata.model_copy(update={"close_wait_seconds": 99})}
    )
    assert config_hash(changed_wait) == original

    changed_timeframe = settings.model_copy(
        update={"runtime": settings.runtime.model_copy(update={"decision_timeframe": "1h"})}
    )
    assert config_hash(changed_timeframe) == original

    changed_history = settings.model_copy(
        update={"marketdata": settings.marketdata.model_copy(update={"history_start": "2020-01-01"})}
    )
    assert config_hash(changed_history) == original

    pinned = settings.model_copy(
        update={
            "universe": settings.universe.model_copy(
                update={"pin": [PinSymbol(symbol="BTC/USDT", venue_symbol="BTC/USDT:USDT")]}
            )
        }
    )
    assert config_hash(pinned) == original

    changed_journal = settings.model_copy(
        update={"journal": settings.journal.model_copy(update={"sqlite_path": "other.sqlite"})}
    )
    assert config_hash(changed_journal) == original
    assert config_hash(load_settings(DEFAULT, PAPER)) == original

    changed_venue = settings.model_copy(
        update={"runtime": settings.runtime.model_copy(update={"venue": "other"})}
    )
    assert config_hash(changed_venue) != original

    enabled = settings.model_copy(
        update={"systemone": settings.systemone.model_copy(update={"enabled": True})}
    )
    enabled_hash = config_hash(enabled)
    assert enabled_hash != original
    assert config_hash(
        enabled.model_copy(
            update={"systemone": enabled.systemone.model_copy(update={"model_pin": "jev-9"})}
        )
    ) != enabled_hash
    assert config_hash(
        enabled.model_copy(
            update={"systemone": enabled.systemone.model_copy(update={"question_set": "entry-v2"})}
        )
    ) != enabled_hash
    assert config_hash(
        enabled.model_copy(
            update={"systemone": enabled.systemone.model_copy(update={"timeout_seconds": 9})}
        )
    ) == enabled_hash
    assert config_hash(
        enabled.model_copy(
            update={"systemone": enabled.systemone.model_copy(update={"cache_path": "other.jsonl"})}
        )
    ) == enabled_hash
    assert config_hash(
        enabled.model_copy(
            update={
                "systemone": enabled.systemone.model_copy(update={"base_url": "https://example.test"})
            }
        )
    ) == enabled_hash


# Every leaf of the loaded default settings. A new key fails this list until it is
# classified against architecture §7. Order is not significant.
LEAF_PATHS = (
    "runtime.mode",
    "runtime.venue",
    "runtime.product",
    "runtime.decision_timeframe",
    "universe.mode",
    "universe.size",
    "universe.quote",
    "universe.metric",
    "universe.bar",
    "universe.refresh",
    "universe.refresh_minute",
    "universe.exclude_bases.0",
    "universe.exclude_bases.1",
    "universe.exclude_bases.2",
    "universe.exclude_bases.3",
    "universe.exclude_bases.4",
    "universe.exclude_bases.5",
    "universe.exclude_bases.6",
    "universe.pin",
    "safety.kill_switch",
    "marketdata.history_start",
    "marketdata.windows.15m",
    "marketdata.windows.1h",
    "marketdata.windows.4h",
    "marketdata.max_gap_bars.15m",
    "marketdata.max_gap_bars.1h",
    "marketdata.max_gap_bars.4h",
    "marketdata.stale_grace_seconds",
    "marketdata.close_wait_seconds",
    "marketdata.closed_bars_only",
    "chanlun.min_bi_bars",
    "chanlun.zhongshu_min_bi",
    "chanlun.segment_algo",
    "chanlun.segment_enabled",
    "chanlun.bias_uses_segment",
    "chanlun.engine",
    "features.atr_period",
    "features.volume_median_bars",
    "features.edge_band_atr",
    "volatility.atr_pct_min",
    "volatility.atr_pct_max",
    "volatility.min_samples",
    "session.multipliers.asia",
    "session.multipliers.europe",
    "session.multipliers.overlap",
    "session.multipliers.us",
    "session.multipliers.late",
    "session.weekend_multiplier",
    "session.funding_hours_utc.0",
    "session.funding_hours_utc.1",
    "session.funding_hours_utc.2",
    "session.funding_penalty_minutes",
    "session.funding_penalty",
    "session.hard_skip_buckets",
    "jev.version",
    "jev.weights.structure",
    "jev.weights.location",
    "jev.weights.resonance",
    "jev.weights.volatility_volume",
    "jev.weights.signal_bar",
    "jev.weights.session",
    "jev.enter_threshold",
    "jev.hold_bias",
    "jev.temperature",
    "jev.channels.structure.weights.overlap",
    "jev.channels.structure.weights.agree",
    "jev.channels.structure.weights.contained",
    "jev.channels.structure.weights.clarity",
    "jev.channels.structure.weights.clean",
    "jev.channels.structure.overlap_peak",
    "jev.channels.structure.overlap_width",
    "jev.channels.structure.overlap_penalty_above",
    "jev.channels.structure.overlap_penalty",
    "jev.channels.structure.clarity_full_at",
    "jev.channels.structure.clean_leave_full_atr",
    "jev.channels.structure.reentry_factor.0",
    "jev.channels.structure.reentry_factor.1",
    "jev.channels.structure.reentry_factor.2",
    "jev.channels.location.weights.loc",
    "jev.channels.location.weights.htf_pos",
    "jev.channels.location.weights.room",
    "jev.channels.location.third_peak",
    "jev.channels.location.third_width",
    "jev.channels.location.second_peak",
    "jev.channels.location.second_width",
    "jev.channels.location.long_htf_peak",
    "jev.channels.location.short_htf_peak",
    "jev.channels.location.htf_width",
    "jev.channels.location.outside_range_score",
    "jev.channels.location.room_full_atr",
    "jev.channels.location.nearby_penalty_atr",
    "jev.channels.location.nearby_penalty",
    "jev.channels.resonance.breakout_abs",
    "jev.channels.resonance.signal_tf_floor",
    "jev.channels.volatility_volume.vol_weight",
    "jev.channels.volatility_volume.volume_weight",
    "jev.channels.volatility_volume.volume_floor",
    "jev.channels.volatility_volume.volume_span",
    "jev.channels.signal_bar.weights.close_location",
    "jev.channels.signal_bar.weights.body",
    "jev.channels.signal_bar.weights.wick",
    "jev.channels.signal_bar.against_bar_factor",
    "jev.channels.signal_bar.doji_range_pct",
    "jev.channels.signal_bar.doji_penalty",
    "risk.initial_equity_quote",
    "risk.risk_fraction",
    "risk.max_notional_quote",
    "risk.max_open_positions",
    "risk.max_same_direction",
    "risk.max_gross_notional_quote",
    "risk.max_leverage",
    "risk.max_cost_r",
    "risk.stop_buffer_atr",
    "risk.one_position_per_symbol",
    "risk.partials.0.fraction",
    "risk.partials.0.mode",
    "risk.partials.0.r_fallback",
    "risk.trail.kind",
    "risk.trail.arm_r",
    "execution.fee_bps",
    "execution.slippage_bps",
    "execution.fill_model",
    "execution.order_type",
    "execution.position_mode",
    "execution.margin_mode",
    "journal.sqlite_path",
    "journal.parquet_root",
    "monitor.host",
    "monitor.port",
    "monitor.bar_tail",
    "systemone.enabled",
    "systemone.model_pin",
    "systemone.question_set",
    "systemone.timeout_seconds",
    "systemone.cache_path",
    "systemone.base_url",
)


def test_every_settings_leaf_is_hashed_only_when_section7_includes_it() -> None:
    """model_copy does not re-validate, so weight sums, universe.size, and position_mode are nudged too."""
    settings = load_settings(DEFAULT)
    found = {_dotted(path) for path in _iter_leaves(settings)}
    expected = set(LEAF_PATHS)
    assert found == expected, (sorted(found - expected), sorted(expected - found))
    original = config_hash(settings)
    mismatches: list[str] = []
    for dotted in sorted(found):
        path = _parse_path(dotted)
        new_value: object
        if dotted == "universe.pin":
            new_value = [PinSymbol(symbol="BTC/USDT", venue_symbol="BTC/USDT:USDT")]
        else:
            new_value = _nudge(_leaf_value(settings, path))
        nudged = _replace(settings, path, new_value)
        changed = config_hash(nudged) != original
        want = _section7_includes(path)
        if changed != want:
            mismatches.append(f"{dotted} changed={changed} included={want}")
    assert mismatches == []


def test_canonical_json_normalizes_signed_zero_and_rejects_nonfinite() -> None:
    assert canonical_json(-0.0) == "0.00000000"
    assert canonical_json(0.0) == "0.00000000"
    assert canonical_json(Decimal("-0.0")) == "0.00000000"
    assert canonical_json({"z": -0.0}) == '{"z":0.00000000}'
    for value in (float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ValueError):
            canonical_json(value)


def test_canonical_json_collapses_tiny_negative_zero_and_converts_to_utc() -> None:
    assert canonical_json(0.3 - (0.1 + 0.2)) == "0.00000000"
    assert canonical_json(Decimal("2E+4")) == "20000.00000000"
    assert canonical_json(Decimal("20000")) == "20000.00000000"
    assert canonical_json(Decimal("20000.0")) == "20000.00000000"
    plus8 = timezone(timedelta(hours=8))
    stamped = datetime(2024, 1, 1, 8, 15, tzinfo=plus8)
    assert canonical_json({"t": stamped}) == '{"t":"2024-01-01T00:15:00.000Z"}'
    with pytest.raises(ValueError):
        canonical_json(datetime(2024, 1, 1, 0, 15))


def test_yaml_decimal_spelling_does_not_change_config_hash(tmp_path: Path) -> None:
    raw = DEFAULT.read_text(encoding="utf-8")
    needle = "max_notional_quote: 20000"
    assert needle in raw

    def load_spelling(spelling: str):
        path = tmp_path / f"notional-{spelling}.yaml"
        path.write_text(raw.replace(needle, f"max_notional_quote: {spelling}", 1), encoding="utf-8")
        return load_settings(path)

    integer = load_spelling("20000")
    dotted = load_spelling("20000.0")
    assert integer.risk.max_notional_quote == Decimal("20000")
    assert dotted.risk.max_notional_quote == Decimal("20000")
    assert config_hash(integer) == config_hash(dotted)

    settings = load_settings(DEFAULT)
    spelled = {}
    for spelling in ("20000", "20000.0", "2E+4"):
        risk = settings.risk.model_copy(update={"max_notional_quote": Decimal(spelling)})
        spelled[spelling] = config_hash(settings.model_copy(update={"risk": risk}))
    assert len(set(spelled.values())) == 1


def test_money_float_does_not_keep_binary_tail(tmp_path: Path) -> None:
    def mutate(data: dict) -> None:
        data["execution"]["fee_bps"] = 0.1

    loaded = _load_mutated(tmp_path, mutate)
    assert loaded.execution.fee_bps == Decimal("0.1")


def _iter_leaves(value: object, path: tuple = ()) -> list[tuple]:
    if isinstance(value, BaseModel):
        found = []
        for key in type(value).model_fields:
            found.extend(_iter_leaves(getattr(value, key), path + (key,)))
        return found
    if isinstance(value, dict):
        found = []
        for key in value:
            found.extend(_iter_leaves(value[key], path + (str(key),)))
        return found
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return [path]
        found = []
        for index, item in enumerate(value):
            found.extend(_iter_leaves(item, path + (index,)))
        return found
    return [path]


def _dotted(path: tuple) -> str:
    return ".".join(str(part) for part in path)


def _parse_path(dotted: str) -> tuple:
    return tuple(int(piece) if piece.isdigit() else piece for piece in dotted.split("."))


def _section7_includes(path: tuple) -> bool:
    head = path[0]
    if head in {"chanlun", "features", "volatility", "session", "jev"}:
        return True
    name = path[1]
    included, excluded = _SECTION_FIELDS[head]
    if name in included:
        return True
    if name in excluded:
        return False
    raise AssertionError(f"unclassified settings leaf {path}")


_SECTION_FIELDS = {
    "runtime": ({"venue", "product"}, {"mode", "decision_timeframe"}),
    "universe": (
        {"mode", "size", "quote", "metric", "bar", "refresh", "refresh_minute", "exclude_bases"},
        {"pin"},
    ),
    "safety": (set(), {"kill_switch"}),
    "marketdata": (
        {"windows", "max_gap_bars", "stale_grace_seconds", "closed_bars_only"},
        {"history_start", "close_wait_seconds"},
    ),
    "risk": (
        {
            "risk_fraction",
            "max_notional_quote",
            "max_open_positions",
            "max_same_direction",
            "max_gross_notional_quote",
            "max_leverage",
            "max_cost_r",
            "stop_buffer_atr",
            "one_position_per_symbol",
            "partials",
            "trail",
        },
        {"initial_equity_quote"},
    ),
    "execution": (
        {"fee_bps", "slippage_bps", "fill_model", "order_type", "position_mode", "margin_mode"},
        set(),
    ),
    "journal": (set(), {"sqlite_path", "parquet_root"}),
    "monitor": (set(), {"host", "port", "bar_tail"}),
    "systemone": (
        {"enabled"},
        {"model_pin", "question_set", "timeout_seconds", "cache_path", "base_url"},
    ),
}


def _leaf_value(root: object, path: tuple) -> object:
    current = root
    for part in path:
        current = current[part] if isinstance(current, (list, dict)) else getattr(current, part)
    return current


def _nudge(value: object) -> object:
    if isinstance(value, bool):
        return not value
    if isinstance(value, Decimal):
        return value + 1
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        return value + "_x"
    if isinstance(value, list):
        return ["x"]
    if value is None:
        return "x"
    raise TypeError(type(value))


def _replace(root: object, path: tuple, new: object) -> object:
    key, *rest = path
    if isinstance(root, BaseModel):
        current = getattr(root, key)
        updated = _replace(current, tuple(rest), new) if rest else new
        return root.model_copy(update={key: updated})
    if isinstance(root, dict):
        copied = dict(root)
        copied[key] = _replace(copied[key], tuple(rest), new) if rest else new
        return copied
    if isinstance(root, list):
        copied = list(root)
        copied[key] = _replace(copied[key], tuple(rest), new) if rest else new
        return copied
    raise TypeError(type(root))




def test_negative_weight_is_rejected_even_when_the_sum_is_one(tmp_path: Path) -> None:
    overlay = tmp_path / "negative.yaml"
    overlay.write_text("jev:\n  weights:\n    structure: 0.60\n    location: -0.18\n", encoding="utf-8")
    with pytest.raises(ValueError, match=">= 0"):
        load_settings(DEFAULT, overlay)


def test_systemone_values_live_in_the_default_yaml() -> None:
    import yaml

    loaded = yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))
    assert loaded["systemone"]["enabled"] is False
    assert loaded["systemone"]["model_pin"] == "jev-1.14.0"
    from chanedge.config.model import SystemOneSettings

    assert all(field.is_required() for field in SystemOneSettings.model_fields.values())
