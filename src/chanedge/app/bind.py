"""Copy Settings into the domain params objects. The pipeline does not load YAML."""

from __future__ import annotations

from chanedge.domain.params import (
    FeatureParams,
    JevParams,
    LocationScoreParams,
    ResonanceScoreParams,
    RiskParams,
    RuleParams,
    SessionScoreParams,
    SignalBarScoreParams,
    StructureScoreParams,
    VolatilityScoreParams,
)


def feature_params(settings) -> FeatureParams:
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


def jev_params(settings) -> JevParams:
    weights = settings.jev.weights
    jev = settings.jev
    return JevParams(
        version=jev.version,
        structure=weights.structure,
        location=weights.location,
        resonance=weights.resonance,
        volatility_volume=weights.volatility_volume,
        signal_bar=weights.signal_bar,
        session=weights.session,
        enter_threshold=jev.enter_threshold,
        hold_bias=jev.hold_bias,
        temperature=jev.temperature,
    )


def rule_params(settings) -> RuleParams:
    windows = settings.marketdata.windows
    volatility = settings.volatility
    return RuleParams(
        window_15m=windows["15m"],
        window_1h=windows["1h"],
        window_4h=windows["4h"],
        atr_pct_min=volatility.atr_pct_min,
        atr_pct_max=volatility.atr_pct_max,
        hard_skip_buckets=tuple(settings.session.hard_skip_buckets),
    )


def risk_params(settings) -> RiskParams:
    risk = settings.risk
    partial = risk.partials[0]
    execution = settings.execution
    return RiskParams(
        risk_fraction=risk.risk_fraction,
        max_notional_quote=risk.max_notional_quote,
        max_gross_notional_quote=risk.max_gross_notional_quote,
        max_open_positions=risk.max_open_positions,
        max_same_direction=risk.max_same_direction,
        max_leverage=risk.max_leverage,
        max_cost_r=risk.max_cost_r,
        stop_buffer_atr=risk.stop_buffer_atr,
        partial_fraction=partial.fraction,
        r_fallback=partial.r_fallback,
        arm_r=risk.trail.arm_r,
        fee_bps=execution.fee_bps,
        slippage_bps=execution.slippage_bps,
    )
