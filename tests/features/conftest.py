"""Feature params fixture. Pytest injects it; tests do not import this module."""

from __future__ import annotations

from pathlib import Path

import pytest

from chanedge.config.load import load_settings
from chanedge.domain.params import (
    FeatureParams,
    LocationScoreParams,
    ResonanceScoreParams,
    SessionScoreParams,
    SignalBarScoreParams,
    StructureScoreParams,
    VolatilityScoreParams,
)

ROOT = Path(__file__).resolve().parents[2]


def params_from_settings(settings) -> FeatureParams:
    features = settings.features
    volatility = settings.volatility
    session = settings.session
    channels = settings.jev.channels
    structure = channels.structure
    location = channels.location
    volume = channels.volatility_volume
    bar = channels.signal_bar
    return FeatureParams(
        atr_period=features.atr_period,
        volume_median_bars=features.volume_median_bars,
        edge_band_atr=features.edge_band_atr,
        atr_pct_min=volatility.atr_pct_min,
        atr_pct_max=volatility.atr_pct_max,
        min_samples=volatility.min_samples,
        structure=StructureScoreParams(
            overlap=structure.weights.overlap,
            agree=structure.weights.agree,
            contained=structure.weights.contained,
            clarity=structure.weights.clarity,
            clean=structure.weights.clean,
            overlap_peak=structure.overlap_peak,
            overlap_width=structure.overlap_width,
            overlap_penalty_above=structure.overlap_penalty_above,
            overlap_penalty=structure.overlap_penalty,
            clarity_full_at=structure.clarity_full_at,
            clean_leave_full_atr=structure.clean_leave_full_atr,
            reentry_factor=tuple(structure.reentry_factor),
        ),
        location=LocationScoreParams(
            loc=location.weights.loc,
            htf_pos=location.weights.htf_pos,
            room=location.weights.room,
            third_peak=location.third_peak,
            third_width=location.third_width,
            second_peak=location.second_peak,
            second_width=location.second_width,
            long_htf_peak=location.long_htf_peak,
            short_htf_peak=location.short_htf_peak,
            htf_width=location.htf_width,
            outside_range_score=location.outside_range_score,
            room_full_atr=location.room_full_atr,
            nearby_penalty_atr=location.nearby_penalty_atr,
            nearby_penalty=location.nearby_penalty,
        ),
        resonance=ResonanceScoreParams(
            breakout_abs=channels.resonance.breakout_abs,
            signal_tf_floor=channels.resonance.signal_tf_floor,
        ),
        volatility_volume=VolatilityScoreParams(
            vol_weight=volume.vol_weight,
            volume_weight=volume.volume_weight,
            volume_floor=volume.volume_floor,
            volume_span=volume.volume_span,
        ),
        signal_bar=SignalBarScoreParams(
            close_location=bar.weights.close_location,
            body=bar.weights.body,
            wick=bar.weights.wick,
            against_bar_factor=bar.against_bar_factor,
            doji_range_pct=bar.doji_range_pct,
            doji_penalty=bar.doji_penalty,
        ),
        session=SessionScoreParams(
            asia=session.multipliers.asia,
            europe=session.multipliers.europe,
            overlap=session.multipliers.overlap,
            us=session.multipliers.us,
            late=session.multipliers.late,
            weekend_multiplier=session.weekend_multiplier,
            funding_hours_utc=tuple(session.funding_hours_utc),
            funding_penalty=session.funding_penalty,
            funding_penalty_minutes=session.funding_penalty_minutes,
            hard_skip_buckets=tuple(session.hard_skip_buckets),
        ),
    )


@pytest.fixture(scope="session")
def feature_params() -> FeatureParams:
    return params_from_settings(load_settings(ROOT / "config" / "default.yaml"))
