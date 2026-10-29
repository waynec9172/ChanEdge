"""Load default YAML and recursively merge an optional overlay."""

from __future__ import annotations

from pathlib import Path

import yaml

from chanedge.config.model import Settings

_SECRET_KEYS = frozenset({"api_key", "api_secret", "token", "typesafe_api_key"})


def load_settings(default_path: Path | str, overlay_path: Path | str | None = None) -> Settings:
    merged = _read_mapping(default_path)
    if overlay_path is not None:
        merged = _deep_merge(merged, _read_mapping(overlay_path))
    _reject_secret_keys(merged)
    return Settings.model_validate(merged)


def _read_mapping(path: Path | str) -> dict[str, object]:
    text = Path(path).read_text(encoding="utf-8")
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return loaded


def _deep_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _reject_secret_keys(value: object, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SECRET_KEYS:
                raise ValueError(f"secret field {key} is not allowed at {here}")
            _reject_secret_keys(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_keys(item, f"{path}[{index}]")
