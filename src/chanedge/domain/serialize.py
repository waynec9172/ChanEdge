"""JSON for journal columns. decision_id does not read these strings."""

from __future__ import annotations

import json

from pydantic import BaseModel


def dump_model(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def dump_model_omit_none(model: BaseModel) -> str:
    """Top-level None keys are dropped. Nested nulls stay. Used only for jev_json."""
    payload = {
        key: value for key, value in model.model_dump(mode="json").items() if value is not None
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dump_models(models: tuple[BaseModel, ...] | list[BaseModel]) -> str:
    payload = [model.model_dump(mode="json") for model in models]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
