"""Location channel. Second-class loc measures distance to the defending price."""

from __future__ import annotations

from chanedge.domain.bars import Bar
from chanedge.domain.chanlun import Bi, ChanSignal, ChanSnapshot, Zhongshu
from chanedge.domain.decision import LocationFeatures
from chanedge.domain.enums import Direction, Side, SignalType
from chanedge.domain.params import FeatureParams
from chanedge.features.mathutil import clamp, ratio, tent

# Architecture formula: a second buy or sell is at the edge only inside (0, 1] ATR.
_SECOND_EDGE_ATR = 1.0


def location_channel(
    snapshot: ChanSnapshot,
    snapshot_4h: ChanSnapshot,
    bar: Bar,
    signal: ChanSignal | None,
    side: Side,
    atr: float,
    params: FeatureParams,
) -> LocationFeatures:
    price = bar.close
    zone = _active(snapshot)
    prior_high, prior_low = _priors(snapshot, signal)
    dist_high = None if prior_high is None else ratio(prior_high - price, atr)
    dist_low = None if prior_low is None else ratio(price - prior_low, atr)
    zg = zd = gg = dd = None
    dist_zg = dist_zd = pos_in_zs = None
    if zone is not None:
        zg, zd, gg, dd = zone.zg, zone.zd, zone.gg, zone.dd
        dist_zg = ratio(price - zg, atr)
        dist_zd = ratio(price - zd, atr)
        pos_in_zs = 0.5 if zg == zd else (price - zd) / (zg - zd)
    pull_zg, pull_zd, dist_defending = _signal_distances(signal, price, zg, zd, atr)
    htf_low, htf_high = _htf_range(snapshot_4h)
    if htf_low is None or htf_high is None:
        pos_4h = None
    elif htf_high == htf_low:
        pos_4h = 0.5
    else:
        pos_4h = (price - htf_low) / (htf_high - htf_low)
    subscore, penalty = _score(
        signal,
        side,
        params,
        pull_zg=pull_zg,
        pull_zd=pull_zd,
        dist_defending=dist_defending,
        pos_4h=pos_4h,
        dist_high=dist_high,
        dist_low=dist_low,
    )
    return LocationFeatures(
        price=price,
        zs_zg=zg,
        zs_zd=zd,
        zs_gg=gg,
        zs_dd=dd,
        dist_zg_atr=dist_zg,
        dist_zd_atr=dist_zd,
        pos_in_zs=pos_in_zs,
        dist_pullback_to_zg_atr=pull_zg,
        dist_pullback_to_zd_atr=pull_zd,
        prior_high=prior_high,
        prior_low=prior_low,
        dist_prior_high_atr=dist_high,
        dist_prior_low_atr=dist_low,
        dist_defending_atr=dist_defending,
        htf_range_low=htf_low,
        htf_range_high=htf_high,
        pos_in_4h_range=pos_4h,
        at_lower_edge=_lower_edge(signal, pull_zg, dist_defending, params.edge_band_atr),
        at_upper_edge=_upper_edge(signal, pull_zd, dist_defending, params.edge_band_atr),
        subscore=subscore,
        penalty=penalty,
        skip=False,
    )


def _score(
    signal: ChanSignal | None,
    side: Side,
    params: FeatureParams,
    *,
    pull_zg: float | None,
    pull_zd: float | None,
    dist_defending: float | None,
    pos_4h: float | None,
    dist_high: float | None,
    dist_low: float | None,
) -> tuple[float, float]:
    if signal is None:
        return 0.0, 0.0
    weights = params.location
    if side is Side.LONG:
        loc = _long_loc(signal, weights, pull_zg, dist_defending)
        htf = _htf_term(pos_4h, weights.long_htf_peak, weights.htf_width, weights.outside_range_score, above=True)
        room, penalty = _room(dist_high, weights)
    else:
        loc = _short_loc(signal, weights, pull_zd, dist_defending)
        htf = _htf_term(pos_4h, weights.short_htf_peak, weights.htf_width, weights.outside_range_score, above=False)
        room, penalty = _room(dist_low, weights)
    subscore = weights.loc * loc + weights.htf_pos * htf + weights.room * room
    return subscore, penalty


def _long_loc(signal: ChanSignal, weights, pull_zg: float | None, dist_defending: float | None) -> float:
    if signal.type is SignalType.THIRD_BUY:
        if pull_zg is None:
            return 0.0
        return tent(pull_zg, weights.third_peak, weights.third_width)
    if dist_defending is None or dist_defending <= 0:
        return 0.0
    return tent(dist_defending, weights.second_peak, weights.second_width)


def _short_loc(signal: ChanSignal, weights, pull_zd: float | None, dist_defending: float | None) -> float:
    if signal.type is SignalType.THIRD_SELL:
        if pull_zd is None:
            return 0.0
        return tent(pull_zd, weights.third_peak, weights.third_width)
    if dist_defending is None or dist_defending <= 0:
        return 0.0
    return tent(dist_defending, weights.second_peak, weights.second_width)


def _htf_term(pos: float | None, peak: float, width: float, outside: float, *, above: bool) -> float:
    if pos is None:
        return 0.0
    if above and pos > 1:
        return outside
    if not above and pos < 0:
        return outside
    return tent(pos, peak, width)


def _room(distance: float | None, weights) -> tuple[float, float]:
    if distance is None:
        return 0.0, 0.0
    room = clamp(ratio(distance, weights.room_full_atr), 0.0, 1.0)
    penalty = weights.nearby_penalty if distance < weights.nearby_penalty_atr else 0.0
    return room, penalty


def _lower_edge(
    signal: ChanSignal | None,
    pull_zg: float | None,
    dist_defending: float | None,
    edge_band: float,
) -> bool:
    if signal is None:
        return False
    if signal.type is SignalType.THIRD_BUY and pull_zg is not None:
        return 0 <= pull_zg <= edge_band
    if signal.type is SignalType.SECOND_BUY and dist_defending is not None:
        return 0 < dist_defending <= _SECOND_EDGE_ATR
    return False


def _upper_edge(
    signal: ChanSignal | None,
    pull_zd: float | None,
    dist_defending: float | None,
    edge_band: float,
) -> bool:
    if signal is None:
        return False
    if signal.type is SignalType.THIRD_SELL and pull_zd is not None:
        return 0 <= pull_zd <= edge_band
    if signal.type is SignalType.SECOND_SELL and dist_defending is not None:
        return 0 < dist_defending <= _SECOND_EDGE_ATR
    return False


def _signal_distances(
    signal: ChanSignal | None,
    price: float,
    zg: float | None,
    zd: float | None,
    atr: float,
) -> tuple[float | None, float | None, float | None]:
    if signal is None:
        return None, None, None
    pull_zg = None
    pull_zd = None
    defending = None
    if signal.type is SignalType.THIRD_BUY and zg is not None:
        pull_zg = ratio(signal.defending_price - zg, atr)
    if signal.type is SignalType.THIRD_SELL and zd is not None:
        pull_zd = ratio(zd - signal.defending_price, atr)
    if signal.type is SignalType.SECOND_BUY:
        defending = ratio(price - signal.defending_price, atr)
    if signal.type is SignalType.SECOND_SELL:
        defending = ratio(signal.defending_price - price, atr)
    return pull_zg, pull_zd, defending


def _priors(snapshot: ChanSnapshot, signal: ChanSignal | None) -> tuple[float | None, float | None]:
    if signal is None:
        return None, None
    signal_index = _fx_index(snapshot, signal.defending_fx_id)
    if signal_index is None:
        return None, None
    return (
        _previous_end(snapshot, Direction.UP, signal_index),
        _previous_end(snapshot, Direction.DOWN, signal_index),
    )


def _previous_end(snapshot: ChanSnapshot, direction: Direction, signal_index: int) -> float | None:
    chosen: Bi | None = None
    chosen_index = -1
    for bi in snapshot.bis:
        if not bi.confirmed or bi.direction is not direction:
            continue
        end_index = _fx_index(snapshot, bi.end_fx_id)
        if end_index is None or end_index >= signal_index:
            continue
        if chosen is None or end_index >= chosen_index:
            chosen = bi
            chosen_index = end_index
    if chosen is None:
        return None
    return chosen.end_price


def _htf_range(snapshot: ChanSnapshot) -> tuple[float | None, float | None]:
    zone = _active(snapshot)
    if zone is not None:
        return zone.zd, zone.zg
    chosen: Bi | None = None
    for bi in snapshot.bis:
        if not bi.confirmed:
            continue
        if chosen is None or bi.end_time >= chosen.end_time:
            chosen = bi
    if chosen is None:
        return None, None
    return chosen.low, chosen.high


def _active(snapshot: ChanSnapshot) -> Zhongshu | None:
    if snapshot.active_zhongshu_id is None:
        return None
    for zone in snapshot.zhongshus:
        if zone.id == snapshot.active_zhongshu_id:
            return zone
    return None


def _fx_index(snapshot: ChanSnapshot, fx_id: str) -> int | None:
    for fenxing in snapshot.fenxings:
        if fenxing.id == fx_id:
            return fenxing.k_index_mid
    return None
