"""JSONL cache. One exclusive writer. The first complete line for a key wins.

Windows msvcrt.LK_LOCK is exclusive, not shared. The critical section covers
the read and the append, which is the practical equivalent of a shared read:
a reader cannot observe a torn line while the writer holds the lock.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from chanedge.domain.canon import canonical_json
from chanedge.domain.systemone import (
    ChoiceAnswer,
    ScoreAnswer,
    SystemOneFailure,
    SystemOneResult,
    choice_is_go_or_no_go,
    probabilities_cover,
    score_in_range,
)


def cache_key(
    model_pin: str,
    question_set: str,
    questions: dict[str, object],
    state: dict[str, object],
) -> str:
    payload = canonical_json([model_pin, question_set, questions, state])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def answer_hash(result: SystemOneResult) -> str:
    payload = {
        "model": result.model,
        "scores": {
            name: {
                "score": answer.score,
                "probabilities": dict(answer.probabilities),
                "confidence": answer.confidence,
            }
            for name, answer in sorted(result.scores.items())
        },
        "choices": {
            name: {
                "choice": answer.choice,
                "probabilities": dict(answer.probabilities),
                "confidence": answer.confidence,
            }
            for name, answer in sorted(result.choices.items())
        },
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def cache_digest(lookups: list[tuple[str, str]]) -> str:
    ordered = [{"key": key, "answer_hash": digest} for key, digest in sorted(lookups)]
    return hashlib.sha256(canonical_json(ordered).encode("utf-8")).hexdigest()


def validate_for_cache(questions: dict[str, object], result: SystemOneResult) -> None:
    """Raise malformed before a line is appended. jev repeats this on a fake port."""
    for name, spec in questions.items():
        if not isinstance(spec, dict):
            raise SystemOneFailure("malformed", result.elapsed_ms, model=result.model)
        kind = spec.get("type")
        if kind == "score":
            criteria = spec.get("criteria")
            answer = result.scores.get(name)
            if not isinstance(criteria, list) or not isinstance(answer, ScoreAnswer):
                raise SystemOneFailure("malformed", result.elapsed_ms, model=result.model)
            if not score_in_range(answer.score, len(criteria)) or not probabilities_cover(
                answer.probabilities, len(criteria)
            ):
                raise SystemOneFailure("malformed", result.elapsed_ms, model=result.model)
        elif kind == "choice":
            answer_choice = result.choices.get(name)
            if not isinstance(answer_choice, ChoiceAnswer) or not choice_is_go_or_no_go(answer_choice):
                raise SystemOneFailure("malformed", result.elapsed_ms, model=result.model)
        else:
            raise SystemOneFailure("malformed", result.elapsed_ms, model=result.model)


class JsonlCache:
    def __init__(self, path: Path, model_pin: str) -> None:
        self.path = Path(path)
        self.model_pin = model_pin

    def read(self) -> dict[str, SystemOneResult]:
        with _exclusive(self.path) as handle:
            return _rows(handle, self.model_pin)

    def lookup(self, key: str) -> SystemOneResult | None:
        return self.read().get(key)

    def append(self, key: str, result: SystemOneResult) -> None:
        if result.model != self.model_pin:
            return
        with _exclusive(self.path) as handle:
            found = _rows(handle, self.model_pin)
            if key in found:
                return
            line = canonical_json(_plain(key, result)) + "\n"
            handle.seek(0, os.SEEK_END)
            handle.write(line.encode("utf-8"))
            handle.flush()


class JsonlReader:
    """lookup only. system_one lives on LookupCaller so this type has no HTTP method."""

    def __init__(self, path: Path, model_pin: str) -> None:
        self._cache = JsonlCache(path, model_pin)
        self.model_pin = model_pin
        self.lookups: list[tuple[str, str]] = []

    def lookup(self, key: str) -> SystemOneResult | None:
        found = self._cache.lookup(key)
        if found is not None:
            self.lookups.append((key, answer_hash(found)))
        return found


class LookupCaller:
    """Backtest port. Reads the cache and raises cache_miss. It does not call HTTP."""

    def __init__(self, reader: JsonlReader, *, question_set: str, model_pin: str) -> None:
        self._reader = reader
        self._question_set = question_set
        self._model_pin = model_pin

    def system_one(
        self,
        *,
        state: dict[str, object],
        questions: dict[str, object],
        model: str,
    ) -> SystemOneResult:
        if model != self._model_pin:
            raise SystemOneFailure("model_mismatch", 0.0, model=model)
        key = cache_key(model, self._question_set, questions, state)
        found = self._reader.lookup(key)
        if found is None:
            raise SystemOneFailure("cache_miss", 0.0)
        return found


def _plain(key: str, result: SystemOneResult) -> dict[str, object]:
    return {
        "key": key,
        "model": result.model,
        "scores": {
            name: {
                "score": answer.score,
                "probabilities": dict(answer.probabilities),
                "confidence": answer.confidence,
            }
            for name, answer in result.scores.items()
        },
        "choices": {
            name: {
                "choice": answer.choice,
                "probabilities": dict(answer.probabilities),
                "confidence": answer.confidence,
            }
            for name, answer in result.choices.items()
        },
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "elapsed_ms": result.elapsed_ms,
    }


def _rows(handle, model_pin: str) -> dict[str, SystemOneResult]:
    handle.seek(0)
    raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    if text and not text.endswith("\n"):
        cut = text.rfind("\n")
        text = "" if cut < 0 else text[: cut + 1]
    found: dict[str, SystemOneResult] = {}
    for line in text.splitlines():
        if not line:
            continue
        try:
            payload = json.loads(line)
            result = _result(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        key = payload.get("key") if isinstance(payload, dict) else None
        if not isinstance(key, str) or key in found or result.model != model_pin:
            continue
        found[key] = result
    return found


def _result(payload: object) -> SystemOneResult:
    if not isinstance(payload, dict):
        raise ValueError("row")
    scores = {
        name: ScoreAnswer.model_validate(answer)
        for name, answer in dict(payload.get("scores") or {}).items()
    }
    choices = {
        name: ChoiceAnswer.model_validate(answer)
        for name, answer in dict(payload.get("choices") or {}).items()
    }
    return SystemOneResult(
        model=str(payload["model"]),
        scores=scores,
        choices=choices,
        elapsed_ms=float(payload["elapsed_ms"]),
        input_tokens=payload.get("input_tokens"),
        output_tokens=payload.get("output_tokens"),
    )


@contextmanager
def _exclusive(path: Path) -> Iterator[object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        _acquire(handle)
        try:
            yield handle
        finally:
            _release(handle)
    finally:
        handle.close()


def _acquire(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
