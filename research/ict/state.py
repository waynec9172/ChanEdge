"""ICT state machines (pure functions). One machine per side: -1 = short, +1 = long (exact mirror).

Per 15m close k: step15 for each machine, then (if the 15m close is also a setup-bar close) stepS.
All Features fields are used only up to the current close time; the prefix tests verify this.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

import numpy as np

M15_US = 900_000_000
TF_US = {"15m": 900_000_000, "1h": 3_600_000_000}


class Phase(str, Enum):
    IDLE = "IDLE"
    BOS_CONFIRMED = "BOS_CONFIRMED"
    ZONE_ARMED = "ZONE_ARMED"
    IN_ZONE = "IN_ZONE"
    TRIGGERED = "TRIGGERED"
    INVALID = "INVALID"


ACTIVE = (Phase.BOS_CONFIRMED, Phase.ZONE_ARMED, Phase.IN_ZONE)


@dataclass(frozen=True)
class Setup:
    setup_id: str
    side: int
    bos_s: int
    bos_time: int
    a1: float
    a1_pivot: int
    a0: float | None
    a0_s: int | None
    fvg_id: int | None
    zone_lo: float | None
    zone_hi: float | None
    zone_time: int | None
    zone_eff: int | None
    touch_time: int | None
    touch_k: int | None
    flags: tuple


@dataclass(frozen=True)
class SideState:
    side: int
    setup: Setup | None
    phase: Phase
    last_bos_swing: int


@dataclass(frozen=True)
class Transition:
    time: int
    setup_id: str
    side: int
    frm: str
    to: str
    reason: str


@dataclass(frozen=True)
class Event:
    time: int
    side: int
    close: float
    atr: float
    defending: float
    tp2: float
    setup: Setup
    trigger_kind: str
    funding_rate: float
    f_session: bool
    f_funding: bool


def idle(side: int) -> SideState:
    return SideState(side, None, Phase.IDLE, -1)


def initial_state() -> tuple:
    return (idle(-1), idle(1))


def _flag(setup: Setup, name: str):
    for k, v in setup.flags:
        if k == name:
            return v
    return None


def _set_flag(flags: tuple, name: str, value) -> tuple:
    return tuple((k, value if k == name else v) for k, v in flags)


def _tr(t, setup, frm, to, reason) -> Transition:
    return Transition(int(t), setup.setup_id, setup.side, getattr(frm, "value", frm), getattr(to, "value", to), reason)


# ----------------------------------------------------------------------------------------------- zone construction
def _ote(sd: int, a0: float, a1: float, P: dict) -> tuple:
    if sd == -1:
        return a0 + P["ote_lo"] * (a1 - a0), a0 + P["ote_hi"] * (a1 - a0)
    return a0 - P["ote_hi"] * (a0 - a1), a0 - P["ote_lo"] * (a0 - a1)


def _build_zone(setup: Setup, a0: float, s: int, t: int, F, P: dict):
    """Returns ("ok", zone_lo, zone_hi, fvg_index, fresh) or ("fail", reason)."""
    sd = setup.side
    lo_p, hi_p = _ote(sd, a0, setup.a1, P)
    i0 = int(np.searchsorted(F.fvg_idx, setup.a1_pivot, side="left"))
    i1 = int(np.searchsorted(F.fvg_idx, s, side="right"))
    sl = slice(i0, i1)
    base = (F.fvg_side[sl] == sd) & (F.fvg_kill[sl] > t) & (F.fvg_ct[sl] <= t)
    fresh = F.fvg_touch[sl] > t
    lo = np.maximum(lo_p, F.fvg_lo[sl])
    hi = np.minimum(hi_p, F.fvg_hi[sl])
    ok_geom = lo < hi

    def pick(mask):
        cand = np.flatnonzero(mask)
        if not len(cand):
            return None
        length = (hi - lo)[cand]
        best = length.max()
        tied = cand[length == best]
        q = tied[np.argmax(F.fvg_ct[sl][tied])]  # newer wins
        return int(q)

    mask = base & ok_geom & (fresh if P["use_fresh"] else True)
    q = pick(mask)
    if q is None:
        if P["use_fresh"] and pick(base & ok_geom) is not None:
            return ("fail", "stale_fvg")
        return ("fail", "zone_empty")
    return ("ok", float(lo[q]), float(hi[q]), i0 + q, bool(fresh[q]))


# ----------------------------------------------------------------------------------------------- stepS
def stepS(ss: SideState, s: int, F, P: dict):
    sd = ss.side
    t = int(F.S_ct[s])
    trans: list = []
    setup, phase, last_bos = ss.setup, ss.phase, ss.last_bos_swing
    c = float(F.S_c[s])
    created = False
    # (a) BOS: short breaks the last confirmed swing low, long the last confirmed swing high (close, strict)
    if sd == -1:
        piv, prc, conf = F.sl_pivot, F.sl_price, F.sl_conf
    else:
        piv, prc, conf = F.sh_pivot, F.sh_price, F.sh_conf
    cnt = int(np.searchsorted(conf, s, side="right"))
    if cnt > 0 and int(piv[cnt - 1]) > last_bos:
        bos = c < prc[cnt - 1] if sd == -1 else c > prc[cnt - 1]
        if bos:
            last_bos = int(piv[cnt - 1])
            if phase == Phase.IN_ZONE:
                trans.append(_tr(t, setup, Phase.IN_ZONE, Phase.IN_ZONE, "bos_ignored_in_zone"))
            else:
                if phase in (Phase.BOS_CONFIRMED, Phase.ZONE_ARMED):
                    trans.append(_tr(t, setup, phase, Phase.INVALID, "replaced"))
                    setup, phase = None, Phase.IDLE
                setup2, phase2, tr2 = _candidate(sd, s, t, c, F, P)
                trans.extend(tr2)
                if setup2 is not None:
                    setup, phase, created = setup2, phase2, True
    # (c) anchor 0 / (d) zone
    if setup is not None and not created and phase in (Phase.BOS_CONFIRMED, Phase.ZONE_ARMED):
        cand = cand_s = None
        if P["anchor"] == "causal":
            if sd == -1:
                seg = F.S_l[setup.bos_s:s + 1]
                m = setup.bos_s + int(np.argmin(seg))
                if m < s:
                    cand, cand_s = float(F.S_l[m]), m
            else:
                seg = F.S_h[setup.bos_s:s + 1]
                m = setup.bos_s + int(np.argmax(seg))
                if m < s:
                    cand, cand_s = float(F.S_h[m]), m
        else:
            if sd == -1:
                spiv, sprc, sconf = F.sl_pivot, F.sl_price, F.sl_conf
            else:
                spiv, sprc, sconf = F.sh_pivot, F.sh_price, F.sh_conf
            lo_i = int(np.searchsorted(spiv, setup.bos_s, side="left"))
            hi_i = int(np.searchsorted(sconf, s, side="right"))
            if hi_i > lo_i:
                pr = sprc[lo_i:hi_i]
                q = int(np.argmin(pr)) if sd == -1 else int(np.argmax(pr))
                cand, cand_s = float(pr[q]), int(spiv[lo_i + q])
        better = cand is not None and (setup.a0 is None or (cand < setup.a0 if sd == -1 else cand > setup.a0))
        if better:
            res = _build_zone(setup, cand, s, t, F, P)
            if res[0] == "fail":
                trans.append(_tr(t, setup, phase, Phase.INVALID, res[1]))
                setup, phase = None, Phase.IDLE
            else:
                _, zlo, zhi, fq, fresh = res
                first = phase == Phase.BOS_CONFIRMED
                setup = dataclasses.replace(
                    setup, a0=cand, a0_s=cand_s, fvg_id=fq, zone_lo=zlo, zone_hi=zhi,
                    zone_time=t if first else setup.zone_time, zone_eff=t, flags=_set_flag(setup.flags, "fresh", fresh),
                )
                trans.append(_tr(t, setup, phase, Phase.ZONE_ARMED, "zone_built" if first else "reanchor"))
                phase = Phase.ZONE_ARMED
    return SideState(sd, setup, phase, last_bos), trans


def _candidate(sd: int, s: int, t: int, c: float, F, P: dict):
    sid = f"{F.symbol}|{sd}|{t}"
    stub = Setup(sid, sd, s, t, 0.0, -1, None, None, None, None, None, None, None, None, None, ())

    def reject(reason):
        return None, Phase.IDLE, [_tr(t, stub, Phase.IDLE, Phase.INVALID, reason)]

    if sd == -1:
        cnta = int(np.searchsorted(F.sh_conf, s, side="right"))
        if cnta == 0:
            return reject("no_anchor1")
        ph = int(F.sh_pivot[cnta - 1])
        seg = F.S_h[ph:s + 1]
        off = int(np.argmax(seg))
        a1 = float(seg[off])
        if a1 <= c:
            return reject("no_anchor1")
    else:
        cnta = int(np.searchsorted(F.sl_conf, s, side="right"))
        if cnta == 0:
            return reject("no_anchor1")
        ph = int(F.sl_pivot[cnta - 1])
        seg = F.S_l[ph:s + 1]
        off = int(np.argmin(seg))
        a1 = float(seg[off])
        if a1 >= c:
            return reject("no_anchor1")
    a1p = ph + off
    hidx = int(F.h4_idx_of_s[s])
    hb = F.h4_bear if sd == -1 else F.h4_bull
    f_htf = bool(hidx >= 0 and hb[hidx])
    f_exp = bool(F.bigbar_cs[s + 1] - F.bigbar_cs[a1p] > 0)
    scs = F.sweep_dn_cs if sd == -1 else F.sweep_up_cs
    w0 = max(0, s - P["sweep_bars"] + 1)
    f_sw = bool(scs[s + 1] - scs[w0] > 0)
    if P["use_htf"] and not f_htf:
        return reject("htf_reject")
    if P["use_expansion"] and not f_exp:
        return reject("no_expansion")
    if P["use_sweep"] and not f_sw:
        return reject("no_sweep")
    flags = (("htf", f_htf), ("exp", f_exp), ("sweep", f_sw), ("fresh", None))
    setup = Setup(sid, sd, s, t, a1, a1p, None, None, None, None, None, None, None, None, None, flags)
    return setup, Phase.BOS_CONFIRMED, [_tr(t, setup, Phase.IDLE, Phase.BOS_CONFIRMED, "bos")]


# ----------------------------------------------------------------------------------------------- step15
def _funding_at(F, T: int) -> float:
    ft = F.fund_t
    if len(ft) == 0:
        return float("nan")
    i = int(np.searchsorted(ft, T, side="right")) - 1
    if i >= 0 and T - int(ft[i]) <= 86_400_000_000:
        return float(F.fund_r[i])
    return float("nan")


def step15(ss: SideState, k: int, F, P: dict):
    """Returns (SideState, [Transition], Event | None)."""
    setup, phase = ss.setup, ss.phase
    if phase not in ACTIVE:
        return ss, [], None
    sd = ss.side
    T = int(F.m_ct[k])
    o, h, l, c = float(F.m_o[k]), float(F.m_h[k]), float(F.m_l[k]), float(F.m_c[k])
    trans: list = []

    def dead(reason):
        trans.append(_tr(T, setup, phase, Phase.INVALID, reason))
        return SideState(sd, None, Phase.IDLE, ss.last_bos_swing), trans, None

    hidx = int(F.h4_idx_of_m15[k])
    hb = F.h4_bear if sd == -1 else F.h4_bull
    if P["use_htf"] and not (hidx >= 0 and hb[hidx]):
        return dead("htf_lost")
    if (c > setup.a1) if sd == -1 else (c < setup.a1):
        return dead("close_above_anchor1")
    if phase in (Phase.ZONE_ARMED, Phase.IN_ZONE) and ((c > setup.zone_hi) if sd == -1 else (c < setup.zone_lo)):
        return dead("close_above_zone")
    kind = "touch"
    if phase == Phase.ZONE_ARMED:
        touched = int(F.m_ot[k]) >= setup.zone_eff and ((h >= setup.zone_lo) if sd == -1 else (l <= setup.zone_hi))
        if touched:
            setup = dataclasses.replace(setup, touch_time=T, touch_k=k)
            trans.append(_tr(T, setup, Phase.ZONE_ARMED, Phase.IN_ZONE, "touch"))
            phase = Phase.IN_ZONE
        elif T >= setup.zone_time + P["zone_valid_bars"] * TF_US[P["setup_tf"]]:
            return dead("zone_expired")
    if phase == Phase.IN_ZONE and P["use_ltf"]:
        R = h - l
        if sd == -1:
            wick = R > 0 and (h - max(o, c)) >= P["wick_frac"] * R and c <= l + R / 3
            piv, prc, conf = F.m_sl_pivot, F.m_sl_price, F.m_sl_conf
        else:
            wick = R > 0 and (min(o, c) - l) >= P["wick_frac"] * R and c >= h - R / 3
            piv, prc, conf = F.m_sh_pivot, F.m_sh_price, F.m_sh_conf
        mss = False
        q = int(np.searchsorted(conf, k, side="left")) - 1  # last swing confirmed strictly before k
        if q >= 0 and int(piv[q]) >= setup.touch_k:
            mss = (c < prc[q]) if sd == -1 else (c > prc[q])
        if mss:
            kind = "mss"
        elif wick:
            kind = "wick"
        else:
            if T >= setup.touch_time + (P["ltf_bars"] - 1) * M15_US:
                return dead("no_trigger")
            return SideState(sd, setup, phase, ss.last_bos_swing), trans, None
    if phase != Phase.IN_ZONE:
        return SideState(sd, setup, phase, ss.last_bos_swing), trans, None
    # ---- decision
    sec = T // 1_000_000
    hour = (sec // 3600) % 24
    wd = (sec // 86400 + 3) % 7
    f_session = P["session_start_h"] <= hour < P["session_end_h"] and (not P["weekdays_only"] or wd <= 4)
    if P["use_session"] and not f_session:
        return dead("session")
    rate = _funding_at(F, T)
    if rate != rate:
        f_funding = True
    elif sd == -1:
        f_funding = not (rate <= -P["funding_block"])
    else:
        f_funding = not (rate >= P["funding_block"])
    if P["use_funding"] and not f_funding:
        return dead("funding")
    si = int(F.s_last_of_m[k])
    atr = float(F.S_atr[si]) if si >= 0 else float("nan")
    a0, a1 = setup.a0, setup.a1
    ev = Event(T, sd, c, atr, a1, a0 - P["tp2_ext"] * (a1 - a0), setup, kind, rate, bool(f_session), bool(f_funding))
    trans.append(_tr(T, setup, Phase.IN_ZONE, Phase.TRIGGERED, kind))
    return SideState(sd, None, Phase.IDLE, ss.last_bos_swing), trans, ev
