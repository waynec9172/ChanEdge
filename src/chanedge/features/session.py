"""Session channel. Funding proximity is a penalty. It does not veto."""

from __future__ import annotations

from datetime import datetime, timezone

from chanedge.domain.chanlun import ChanSignal
from chanedge.domain.decision import SessionFeatures
from chanedge.domain.enums import SessionBucket
from chanedge.domain.params import FeatureParams, SessionScoreParams
from chanedge.features.mathutil import clamp

_UTC = timezone.utc
_DAY_MINUTES = 24 * 60


def session_channel(
    decision_time: datetime,
    signal: ChanSignal | None,
    params: FeatureParams,
) -> SessionFeatures:
    utc = decision_time.astimezone(_UTC)
    bucket = _bucket(utc.hour)
    score = params.session
    multiplier = _multiplier(bucket, score)
    weekend = utc.weekday() >= 5
    weekend_factor = score.weekend_multiplier if weekend else 1.0
    subscore = 0.0 if signal is None else clamp(multiplier * weekend_factor, 0.0, 1.0)
    minutes = _minutes_to_funding(utc, score.funding_hours_utc)
    in_window = bool(score.funding_hours_utc) and minutes <= score.funding_penalty_minutes
    return SessionFeatures(
        hour_utc=utc.hour,
        dow=utc.weekday(),
        session_bucket=bucket,
        is_weekend=weekend,
        minutes_to_funding=minutes,
        in_funding_window=in_window,
        session_multiplier=multiplier,
        hard_skip=bucket.value in score.hard_skip_buckets,
        subscore=subscore,
        penalty=score.funding_penalty if in_window else 0.0,
        skip=False,
    )


def _bucket(hour: int) -> SessionBucket:
    if hour < 7:
        return SessionBucket.ASIA
    if hour < 12:
        return SessionBucket.EUROPE
    if hour < 16:
        return SessionBucket.OVERLAP
    if hour < 21:
        return SessionBucket.US
    return SessionBucket.LATE


def _multiplier(bucket: SessionBucket, score: SessionScoreParams) -> float:
    return {
        SessionBucket.ASIA: score.asia,
        SessionBucket.EUROPE: score.europe,
        SessionBucket.OVERLAP: score.overlap,
        SessionBucket.US: score.us,
        SessionBucket.LATE: score.late,
    }[bucket]


def _minutes_to_funding(utc: datetime, hours: tuple[int, ...]) -> int:
    if not hours:
        return 0
    minute = utc.hour * 60 + utc.minute
    best = _DAY_MINUTES
    for mark in hours:
        raw = abs(minute - mark * 60)
        best = min(best, raw, _DAY_MINUTES - raw)
    return best
