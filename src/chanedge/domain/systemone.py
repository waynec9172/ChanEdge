"""System One values. No HTTP and no file I/O."""

from __future__ import annotations

from decimal import Decimal

from chanedge.domain.model import DomainModel

_STATUSES = frozenset(
    {
        "timeout",
        "http_error",
        "malformed",
        "missing_key",
        "cache_miss",
        "model_mismatch",
    }
)
_EPSILON = Decimal("0.000001")


class ScoreAnswer(DomainModel):
    score: float
    probabilities: dict[str, float]
    confidence: float


class ChoiceAnswer(DomainModel):
    choice: str
    probabilities: dict[str, float]
    confidence: float


class SystemOneResult(DomainModel):
    model: str
    scores: dict[str, ScoreAnswer]
    choices: dict[str, ChoiceAnswer]
    elapsed_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class SystemOneFailure(Exception):
    """Port failure. The message is the status only."""

    def __init__(
        self,
        status: str,
        elapsed_ms: float,
        error_class: str | None = None,
        model: str | None = None,
    ) -> None:
        if status not in _STATUSES:
            raise ValueError(status)
        self.status = status
        self.elapsed_ms = elapsed_ms
        self.error_class = error_class
        self.model = model
        super().__init__(status)


def score_in_range(score: float, level_count: int) -> bool:
    """True when score is within 1e-6 of the inclusive level range [0, level_count - 1]."""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or level_count < 2:
        return False
    value = Decimal(repr(float(score)))
    if not value.is_finite():
        return False
    top = Decimal(level_count - 1)
    return -_EPSILON <= value <= top + _EPSILON


def probabilities_cover(probabilities: dict[str, float], level_count: int) -> bool:
    expected = {str(index) for index in range(level_count)}
    return set(probabilities) == expected and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in probabilities.values()
    )


def choice_is_go_or_no_go(answer: ChoiceAnswer) -> bool:
    return answer.choice in {"GO", "NO_GO"} and set(answer.probabilities) == {"GO", "NO_GO"}
