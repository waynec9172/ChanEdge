"""Paper and warm HTTP client. typesafe_sdk is imported only when a real call is built."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from chanedge.domain.systemone import (
    ChoiceAnswer,
    ScoreAnswer,
    SystemOneFailure,
    SystemOneResult,
)
from chanedge.typesafe.cache import JsonlCache, cache_key, validate_for_cache

Transport = Callable[..., object]


class JsonlClient:
    def __init__(
        self,
        *,
        path: Path,
        model_pin: str,
        question_set: str,
        timeout_seconds: float,
        base_url: str,
        api_key: str,
        attempts: int = 1,
        sleep: Callable[[float], None] | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not str(base_url).startswith("https://"):
            raise ValueError("base_url must be https")
        if attempts < 1:
            raise ValueError("attempts must be >= 1")
        self._cache = JsonlCache(path, model_pin)
        self._pin = model_pin
        self._question_set = question_set
        self._timeout = timeout_seconds
        self._base_url = base_url
        self._api_key = api_key
        self._attempts = attempts
        self._sleep = time.sleep if sleep is None else sleep
        self._transport = transport
        self._sdk = None
        self.failed_keys: list[str] = []

    def system_one(
        self,
        *,
        state: dict[str, object],
        questions: dict[str, object],
        model: str,
    ) -> SystemOneResult:
        started = time.perf_counter()
        if model != self._pin:
            raise SystemOneFailure("model_mismatch", _elapsed(started), model=model)
        key = cache_key(self._pin, self._question_set, questions, state)
        found = self._cache.lookup(key)
        if found is not None:
            return found
        if not self._api_key:
            raise SystemOneFailure("missing_key", _elapsed(started))
        last: SystemOneFailure | None = None
        for attempt in range(self._attempts):
            try:
                result = self._call(state, questions, model, started)
                validate_for_cache(questions, result)
            except SystemOneFailure as exc:
                last = exc
                if exc.status not in {"timeout", "http_error"} or attempt + 1 >= self._attempts:
                    if exc.status in {"timeout", "http_error"}:
                        self.failed_keys.append(key)
                    raise
                self._sleep(float(attempt + 1))
                continue
            if result.model != self._pin:
                raise SystemOneFailure(
                    "model_mismatch",
                    result.elapsed_ms,
                    model=result.model,
                )
            self._cache.append(key, result)
            return result
        assert last is not None
        raise last

    def _call(
        self,
        state: dict[str, object],
        questions: dict[str, object],
        model: str,
        started: float,
    ) -> SystemOneResult:
        try:
            if self._transport is not None:
                payload = self._transport(state=state, questions=questions, model=model)
            else:
                payload = self._sdk_call(state, questions, model)
        except SystemOneFailure:
            raise
        except Exception as exc:
            raise SystemOneFailure(
                _classify(exc),
                _elapsed(started),
                error_class=type(exc).__name__,
            ) from None
        try:
            result = _parse(payload, _elapsed(started))
        except (TypeError, ValueError):
            raise SystemOneFailure("malformed", _elapsed(started)) from None
        return result

    def _sdk_call(self, state: dict[str, object], questions: dict[str, object], model: str) -> object:
        client = self._sdk_client()
        response = client.system_one(state=state, questions=questions, model=model)
        answers = getattr(response, "answers", None)
        usage = getattr(response, "usage", None)
        return {
            "model": getattr(response, "model", None),
            "answers": answers if isinstance(answers, dict) else _answers_from(response),
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            },
        }

    def _sdk_client(self):
        if self._sdk is not None:
            return self._sdk
        from typesafe_sdk import TypeSafeClient

        kwargs: dict[str, object] = {
            "timeout": self._timeout,
            "base_url": self._base_url,
            "api_key": self._api_key,
        }
        try:
            from typesafe_sdk import RetryPolicy

            kwargs["retry"] = RetryPolicy(max_retries=0)
        except ImportError:
            pass
        self._sdk = TypeSafeClient(**kwargs)
        return self._sdk


def _answers_from(response: object) -> dict[str, object]:
    scores = getattr(response, "scores", {}) or {}
    choices = getattr(response, "choices", {}) or {}
    merged: dict[str, object] = {}
    merged.update(dict(scores))
    merged.update(dict(choices))
    return merged


def _parse(payload: object, elapsed_ms: float) -> SystemOneResult:
    if not isinstance(payload, dict):
        raise ValueError("payload")
    model = payload.get("model")
    answers = payload.get("answers")
    if not isinstance(model, str) or not isinstance(answers, dict):
        raise ValueError("payload")
    scores: dict[str, ScoreAnswer] = {}
    choices: dict[str, ChoiceAnswer] = {}
    for name, answer in answers.items():
        if not isinstance(answer, dict):
            raise ValueError(name)
        if "choice" in answer:
            probabilities = _string_keys(answer.get("probabilities"))
            choices[name] = ChoiceAnswer(
                choice=str(answer["choice"]),
                probabilities=probabilities,
                confidence=float(answer["confidence"]),
            )
        elif "score" in answer:
            scores[name] = ScoreAnswer(
                score=float(answer["score"]),
                probabilities=_string_keys(answer.get("probabilities")),
                confidence=float(answer["confidence"]),
            )
        else:
            raise ValueError(name)
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return SystemOneResult(
        model=model,
        scores=scores,
        choices=choices,
        elapsed_ms=elapsed_ms,
        input_tokens=_optional_int(usage.get("input_tokens")),
        output_tokens=_optional_int(usage.get("output_tokens")),
    )


def _string_keys(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("probabilities")
    return {str(key): float(item) for key, item in value.items()}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("tokens")
    return value


def _classify(exc: Exception) -> str:
    name = type(exc).__name__
    if isinstance(exc, (TimeoutError, ConnectionError)) or "Timeout" in name or "Connection" in name:
        return "timeout"
    return "http_error"


def _elapsed(started: float) -> float:
    return (time.perf_counter() - started) * 1000
