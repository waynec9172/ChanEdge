"""JSONL cache, pin check, and the paper client. The SDK is not imported."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chanedge.domain.systemone import SystemOneFailure
from chanedge.jev.questions import MODEL_PIN, QUESTIONS
from chanedge.typesafe.cache import JsonlReader, LookupCaller, cache_digest, cache_key
from chanedge.typesafe.client import JsonlClient


def test_first_complete_line_wins_and_a_partial_tail_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "systemone.jsonl"
    client = _client(path, transport=_payload)
    state = {"symbol": "BTC/USDT", "features": {"structure": {"overlap": 0.1}}}
    first = client.system_one(state=state, questions=QUESTIONS, model=MODEL_PIN)
    path.write_bytes(path.read_bytes() + b'{"key": "torn"')
    reader = JsonlReader(path, MODEL_PIN)
    key = cache_key(MODEL_PIN, "entry-v1", QUESTIONS, state)
    assert reader.lookup(key).model == first.model
    assert "torn" not in {item[0] for item in reader.lookups}
    again = _client(path, transport=_explode).system_one(
        state=state, questions=QUESTIONS, model=MODEL_PIN
    )
    assert again.scores["structure"].score == first.scores["structure"].score
    assert not hasattr(JsonlReader(path, MODEL_PIN), "system_one")


def test_later_line_for_the_same_key_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "systemone.jsonl"
    state = {"symbol": "ETH/USDT"}
    _client(path, transport=_payload).system_one(state=state, questions=QUESTIONS, model=MODEL_PIN)
    key = cache_key(MODEL_PIN, "entry-v1", QUESTIONS, state)
    extra = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    extra["scores"]["structure"]["score"] = 4
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(extra) + "\n")
    found = JsonlReader(path, MODEL_PIN).lookup(key)
    assert found is not None
    assert found.scores["structure"].score == pytest.approx(0)


def test_alias_and_malformed_are_not_cached_and_timeout_retries(tmp_path: Path) -> None:
    path = tmp_path / "systemone.jsonl"
    state = {"symbol": "BTC/USDT"}

    def alias(**_kwargs):
        payload = _payload()
        payload["model"] = "jev-latest"
        return payload

    with pytest.raises(SystemOneFailure) as mismatch:
        _client(path, transport=alias).system_one(state=state, questions=QUESTIONS, model=MODEL_PIN)
    assert mismatch.value.status == "model_mismatch"
    assert mismatch.value.model == "jev-latest"
    assert path.read_text(encoding="utf-8") == ""

    calls = {"n": 0}

    def broken(**_kwargs):
        calls["n"] += 1
        return {"model": MODEL_PIN, "answers": {}}

    with pytest.raises(SystemOneFailure) as malformed:
        _client(path, transport=broken).system_one(state=state, questions=QUESTIONS, model=MODEL_PIN)
    assert malformed.value.status == "malformed"
    assert calls["n"] == 1
    assert path.read_text(encoding="utf-8") == ""

    slept: list[float] = []
    attempts = {"n": 0}

    def flaky(**_kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("slow secret")
        return _payload()

    client = _client(path, transport=flaky, attempts=3, sleep=slept.append)
    result = client.system_one(state=state, questions=QUESTIONS, model=MODEL_PIN)
    assert result.model == MODEL_PIN
    assert attempts["n"] == 3
    assert slept == [1.0, 2.0]
    assert client.failed_keys == []

    def boom(**_kwargs):
        raise RuntimeError("response body secret")

    with pytest.raises(SystemOneFailure) as http:
        _client(path, transport=boom, attempts=1).system_one(
            state={"symbol": "SOL/USDT"}, questions=QUESTIONS, model=MODEL_PIN
        )
    assert http.value.status == "http_error"
    assert http.value.error_class == "RuntimeError"
    assert "secret" not in str(http.value)


def test_missing_key_does_not_call_transport_and_reader_miss_is_cache_miss(tmp_path: Path) -> None:
    path = tmp_path / "systemone.jsonl"
    called = {"n": 0}

    def transport(**_kwargs):
        called["n"] += 1
        return _payload()

    with pytest.raises(SystemOneFailure) as missing:
        _client(path, transport=transport, api_key="").system_one(
            state={"symbol": "BTC/USDT"}, questions=QUESTIONS, model=MODEL_PIN
        )
    assert missing.value.status == "missing_key"
    assert called["n"] == 0
    reader = JsonlReader(path, MODEL_PIN)
    caller = LookupCaller(reader, question_set="entry-v1", model_pin=MODEL_PIN)
    with pytest.raises(SystemOneFailure) as miss:
        caller.system_one(state={"symbol": "BTC/USDT"}, questions=QUESTIONS, model=MODEL_PIN)
    assert miss.value.status == "cache_miss"
    assert reader.lookups == []
    with pytest.raises(ValueError, match="https"):
        _client(path, transport=transport, base_url="http://api.typesafe.ai")


def test_digest_sorts_successful_lookups(tmp_path: Path) -> None:
    path = tmp_path / "systemone.jsonl"
    client = _client(path, transport=_payload)
    client.system_one(state={"symbol": "BBB"}, questions=QUESTIONS, model=MODEL_PIN)
    client.system_one(state={"symbol": "AAA"}, questions=QUESTIONS, model=MODEL_PIN)
    reader = JsonlReader(path, MODEL_PIN)
    caller = LookupCaller(reader, question_set="entry-v1", model_pin=MODEL_PIN)
    caller.system_one(state={"symbol": "BBB"}, questions=QUESTIONS, model=MODEL_PIN)
    caller.system_one(state={"symbol": "AAA"}, questions=QUESTIONS, model=MODEL_PIN)
    assert cache_digest(reader.lookups) == cache_digest(list(reversed(reader.lookups)))
    changed = QUESTIONS["structure"]
    assert isinstance(changed, dict)
    other = dict(QUESTIONS)
    other["structure"] = {**changed, "instructions": changed["instructions"] + " extra"}
    assert cache_key(MODEL_PIN, "entry-v1", QUESTIONS, {"symbol": "AAA"}) != cache_key(
        MODEL_PIN, "entry-v1", other, {"symbol": "AAA"}
    )


def _client(path: Path, *, transport, attempts: int = 1, sleep=None, api_key: str = "k", base_url: str = "https://api.typesafe.ai"):
    return JsonlClient(
        path=path,
        model_pin=MODEL_PIN,
        question_set="entry-v1",
        timeout_seconds=1.5,
        base_url=base_url,
        api_key=api_key,
        attempts=attempts,
        sleep=sleep,
        transport=transport,
    )


def _payload(**_kwargs):
    answers = {}
    for name, spec in QUESTIONS.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") == "score":
            criteria = spec["criteria"]
            assert isinstance(criteria, list)
            answers[name] = {
                "score": 0,
                "probabilities": {str(index): (1.0 if index == 0 else 0.0) for index in range(len(criteria))},
                "confidence": 0.2,
            }
        else:
            answers[name] = {
                "choice": "NO_GO",
                "probabilities": {"GO": 0.0, "NO_GO": 1.0},
                "confidence": 0.2,
            }
    return {"model": MODEL_PIN, "answers": answers, "usage": {"input_tokens": 2, "output_tokens": 3}}


def _explode(**_kwargs):
    raise AssertionError("cache hit must not call the transport")
