"""ICT P1 generator: Features, run_symbol, event/setup tables, blind-count funnel. Never simulates PnL."""

from __future__ import annotations

import argparse
import json
import sys
import time as _time
import types
import zlib
from datetime import date, datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from research import common as C
from research import donchian
from research.ict import fvg as FV
from research.ict import htf as HT
from research.ict import params as IP
from research.ict import state as ST
from research.ict.swings import swings

CACHE_DIR = C.CACHE / "ict"
M15 = 900_000_000
H1 = 3_600_000_000
H4 = 14_400_000_000
TF_US = {"15m": M15, "1h": H1}

# ----------------------------------------------------------------------------------------------- experiments (plan section 5 / 6)
_LADDER_ORDER = ("use_htf", "use_expansion", "use_fresh", "use_ltf", "use_sweep", "use_session", "use_funding")
LADDER = tuple(f"ict_L{i}" for i in range(8))
EXPERIMENTS: tuple = (
    ("ict_L0", "ladder", "純結構：所有濾網關閉，觸區即進場"),
    ("ict_L1", "ladder", "L0 + use_htf"),
    ("ict_L2", "ladder", "L1 + use_expansion"),
    ("ict_L3", "ladder", "L2 + use_fresh"),
    ("ict_L4", "ladder", "L3 + use_ltf"),
    ("ict_L5", "ladder", "L4 + use_sweep"),
    ("ict_L6", "ladder", "L5 + use_session"),
    ("ict_L7", "ladder", "L6 + use_funding = 完整模型 = 主假設 H-ICT"),
    ("ict_loo_htf", "loo", "L7，use_htf=false"),
    ("ict_loo_exp", "loo", "L7，use_expansion=false"),
    ("ict_loo_fresh", "loo", "L7，use_fresh=false"),
    ("ict_loo_ltf", "loo", "L7，use_ltf=false"),
    ("ict_loo_sweep", "loo", "L7，use_sweep=false"),
    ("ict_loo_session", "loo", "L7，use_session=false"),
    ("ict_x_trail", "exit", "L7 事件表；exit: tp1 + breakeven + ratchet，row_target 關閉，time_barrier 開啟"),
    ("ict_x_notb", "exit", "L7，time_barrier 關閉"),
    ("ict_rand", "random", "隨機基準（配對 ict_L7 的 symbol×side×季度事件數）"),
    ("ict_anchor_conf", "variant", "L7，anchor=confirmed"),
    ("ict_setup15m", "variant", "L7，setup_tf=15m"),
    ("ict_rsv1", "reserved", "預留"),
    ("ict_rsv2", "reserved", "預留"),
    ("ict_rsv3", "reserved", "預留"),
    ("ict_rsv4", "reserved", "預留"),
    ("ict_rsv5", "reserved", "預留"),
)
RANDOM_SEED = 20261105


NB_SPECS = {  # suffix after "__nb_" -> (kind, value, description text)
    "fvgk_0p4": ("fvg_k", 0.4, "signals.ict.fvg_k = 0.4"),
    "fvgk_0p6": ("fvg_k", 0.6, "signals.ict.fvg_k = 0.6"),
    "sl_0p2": ("buffer_atr", 0.2, "stop.buffer_atr = 0.2"),
    "sl_0p4": ("buffer_atr", 0.4, "stop.buffer_atr = 0.4"),
}
NB_MARK = "__nb_"


NEIGHBORS: tuple = tuple((f"ict_L7{NB_MARK}{k}", v[2]) for k, v in NB_SPECS.items())  # the 4 registered neighbours of ict_L7


def neighbor_names(base: str) -> list:
    return [f"{base}{NB_MARK}{k}" for k in NB_SPECS]


def _split_nb(name: str):
    if NB_MARK not in name:
        return name, None
    base, suf = name.split(NB_MARK, 1)
    if suf not in NB_SPECS:
        raise KeyError(name)
    return base, NB_SPECS[suf]


def ict_params(name: str) -> dict:
    base, nb = _split_nb(name)
    if nb is not None:
        d = dict(ict_params(base))
        if nb[0] == "fvg_k":
            d["fvg_k"] = nb[1]
        return IP.validate(d)
    d = dict(IP.DEFAULTS)

    def ladder(n):
        for i, k in enumerate(_LADDER_ORDER):
            d[k] = i < n

    if name in LADDER:
        ladder(int(name[-1]))
        return IP.validate(d)
    ladder(7)
    loo = {"ict_loo_htf": "use_htf", "ict_loo_exp": "use_expansion", "ict_loo_fresh": "use_fresh", "ict_loo_ltf": "use_ltf",
           "ict_loo_sweep": "use_sweep", "ict_loo_session": "use_session"}
    if name in loo:
        d[loo[name]] = False
    elif name in ("ict_x_trail", "ict_x_notb"):
        pass
    elif name == "ict_rand":
        d["random"] = {"seed": RANDOM_SEED, "match": "ict_L7"}
    elif name == "ict_anchor_conf":
        d["anchor"] = "confirmed"
    elif name == "ict_setup15m":
        d["setup_tf"] = "15m"
    else:
        raise KeyError(name)
    return IP.validate(d)


def experiment_dict(name: str) -> dict:
    base, nb = _split_nb(name)
    if nb is not None:
        d = experiment_dict(base)
        d["name"] = name
        d["description"] = f"NEIGHBOR of {base}: {nb[2]}"
        d["signals"] = {**d["signals"], "ict": ict_params(name)}
        if nb[0] == "buffer_atr":
            d["stop"] = {**d["stop"], "buffer_atr": nb[1]}
        return d
    ex = {
        "tp1": {"enabled": True, "fraction": 0.5, "target": "r", "r_fallback": 1.5},
        "breakeven": {"enabled": True, "arm_r": 1.5},
        "row_target": {"enabled": True},
        "time_barrier": {"enabled": True, "bars": 12, "min_r": 0.5},
    }
    desc = dict((n, t) for n, _, t in EXPERIMENTS)
    if name == "ict_x_trail":
        del ex["row_target"]
        ex["ratchet"] = {"enabled": True}
    elif name == "ict_x_notb":
        del ex["time_barrier"]
    return {
        "name": name,
        "description": desc[name],
        "signals": {"source": "ict", "tf": "15m", "types": ["ict_long", "ict_short"], "donchian_n": None, "ict": ict_params(name)},
        "filters": {
            "in_top20": True, "candidate_only": False, "gate_pass": False, "jev_min": None, "max_cost_r": 0.4,
            "exclude_reemit": False, "delist_rule": True, "exclude_tradfi": True,
        },
        "entry": {"mode": "market_next_open"},
        "stop": {"buffer_atr": 0.3, "round_to_tick": True},
        "exit": ex,
        "costs": {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1},
    }


# ----------------------------------------------------------------------------------------------- features
class Features:
    """Read-only bundle of numpy arrays (see research/plans/ict_phase1_spec.md section 6.1)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _us(series: pd.Series) -> np.ndarray:
    return series.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy().astype("int64")


def _conf(piv: np.ndarray, n: int) -> np.ndarray:
    return piv + n


def build_features(symbol: str, b15: pd.DataFrame, b1h: pd.DataFrame, b4h: pd.DataFrame, funding, P: dict) -> Features:
    n = P["swing_n"]
    m_ot = _us(b15["open_time"])
    m_ct = m_ot + M15
    m = {c: b15[c].to_numpy(float) for c in ("open", "high", "low", "close")}
    if P["setup_tf"] == "15m":
        sb, tf_us = b15, M15
    else:
        sb, tf_us = b1h, H1
    S_ot = _us(sb["open_time"])
    S_ct = S_ot + tf_us
    S_o, S_h, S_l, S_c, S_v = (sb[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))
    N = len(S_ot)
    S_atr = donchian.wilder_atr_np(S_h, S_l, S_c, P["atr_n"])
    sh_p, sh_pr, sl_p, sl_pr = swings(S_h, S_l, n)
    msh_p, msh_pr, msl_p, msl_pr = swings(m["high"], m["low"], n)
    # setup-bar mapping
    pos = np.searchsorted(S_ct, m_ct, side="left")
    ok = pos < N
    s_of_ct = np.full(len(m_ct), -1, dtype=np.int64)
    s_of_ct[ok] = np.where(S_ct[pos[ok]] == m_ct[ok], pos[ok], -1)
    s_last_of_m = np.searchsorted(S_ct, m_ct, side="right") - 1
    # fvg
    g = FV.fvgs(S_h, S_l, S_atr, P["fvg_k"])
    fvg_ct = S_ct[g["idx"]] if len(g["idx"]) else np.empty(0, dtype=np.int64)
    touch = FV.first_touch(g["side"], g["lo"], g["hi"], fvg_ct, m_ot, m["high"], m["low"])
    kill = FV.kill_time(g["side"], g["lo"], g["hi"], g["idx"], S_c, S_ct)
    # expansion
    tr = np.full(N, np.nan)
    if N > 1:
        tr[1:] = np.maximum.reduce([S_h[1:] - S_l[1:], np.abs(S_h[1:] - S_c[:-1]), np.abs(S_l[1:] - S_c[:-1])])
    atr_prev = np.r_[np.nan, S_atr[:-1]] if N else S_atr
    med = pd.Series(S_v).shift(1).rolling(P["exp_vol_n"]).median().to_numpy()
    with np.errstate(invalid="ignore"):
        bigbar = (tr >= P["exp_tr_atr"] * atr_prev) | (S_v >= P["exp_vol_mult"] * med)
    # sweeps against the last swing confirmed before the bar opened (conf <= i-1)
    idx = np.arange(N)
    cnt_h = np.searchsorted(sh_p + n, idx, side="left")
    cnt_l = np.searchsorted(sl_p + n, idx, side="left")
    last_sh = np.where(cnt_h > 0, sh_pr[np.maximum(cnt_h - 1, 0)] if len(sh_pr) else np.nan, np.nan)
    last_sl = np.where(cnt_l > 0, sl_pr[np.maximum(cnt_l - 1, 0)] if len(sl_pr) else np.nan, np.nan)
    last_sh_pivot = np.where(cnt_h > 0, sh_p[np.maximum(cnt_h - 1, 0)] if len(sh_p) else -1, -1)
    last_sl_pivot = np.where(cnt_l > 0, sl_p[np.maximum(cnt_l - 1, 0)] if len(sl_p) else -1, -1)
    with np.errstate(invalid="ignore"):
        sweep_dn = (S_h > last_sh) & (S_c <= last_sh)
        sweep_up = (S_l < last_sl) & (S_c >= last_sl)

    def cs(a):
        return np.r_[0, np.cumsum(a.astype(np.int64))]

    # 4h
    ct4, bear, bull = HT.htf_flags(b4h, n, P["htf_ema"])
    h4_idx_of_m15 = HT.align(ct4, m_ct)
    h4_idx_of_s = HT.align(ct4, S_ct)
    if funding is None:
        fund_t, fund_r = np.empty(0, dtype=np.int64), np.empty(0)
    else:
        fund_t, fund_r = np.asarray(funding[0], dtype=np.int64), np.asarray(funding[1], dtype=float)
    return Features(
        symbol=symbol,
        m_ot=m_ot, m_ct=m_ct, m_o=m["open"], m_h=m["high"], m_l=m["low"], m_c=m["close"],
        S_ot=S_ot, S_ct=S_ct, S_o=S_o, S_h=S_h, S_l=S_l, S_c=S_c, S_v=S_v, S_atr=S_atr,
        s_of_ct=s_of_ct, s_last_of_m=s_last_of_m,
        sh_pivot=sh_p, sh_price=sh_pr, sh_conf=sh_p + n, sl_pivot=sl_p, sl_price=sl_pr, sl_conf=sl_p + n,
        m_sh_pivot=msh_p, m_sh_price=msh_pr, m_sh_conf=msh_p + n, m_sl_pivot=msl_p, m_sl_price=msl_pr, m_sl_conf=msl_p + n,
        fvg_idx=g["idx"], fvg_side=g["side"], fvg_lo=g["lo"], fvg_hi=g["hi"], fvg_ct=fvg_ct, fvg_touch=touch, fvg_kill=kill,
        bigbar=bigbar, bigbar_cs=cs(bigbar),
        sweep_dn=sweep_dn, sweep_up=sweep_up, sweep_dn_cs=cs(sweep_dn), sweep_up_cs=cs(sweep_up),
        last_sh_price=last_sh, last_sl_price=last_sl, last_sh_pivot=last_sh_pivot, last_sl_pivot=last_sl_pivot,
        h4_ct=ct4, h4_idx_of_m15=h4_idx_of_m15, h4_idx_of_s=h4_idx_of_s, h4_bear=bear, h4_bull=bull,
        fund_t=fund_t, fund_r=fund_r,
    )


# ----------------------------------------------------------------------------------------------- run
def run_symbol(symbol: str, F: Features, P: dict, stop_at_us: int | None = None, state=None, start_after_us: int | None = None):
    """Walk the 15m closes. Returns (events, transitions, info). info["state"] = (short, long) machines after the last processed bar.

    stop_at_us: process closes with close_time <= stop_at_us. start_after_us: skip closes <= it (used to resume from `state`).
    end_of_data transitions are emitted only when stop_at_us is None.
    """
    ss = state if state is not None else ST.initial_state()
    ss = list(ss)
    n = len(F.m_ct)
    k0 = 0 if start_after_us is None else int(np.searchsorted(F.m_ct, start_after_us, side="right"))
    k1 = n if stop_at_us is None else int(np.searchsorted(F.m_ct, stop_at_us, side="right"))
    s_closes = np.flatnonzero(F.s_of_ct >= 0)
    events: list = []
    trans: list = []
    k = k0
    last_k = k0 - 1
    while k < k1:
        if ss[0].phase not in ST.ACTIVE and ss[1].phase not in ST.ACTIVE:
            j = int(np.searchsorted(s_closes, k, side="left"))
            if j >= len(s_closes):
                break
            k = int(s_closes[j])
            if k >= k1:
                break
        for q in (0, 1):
            ss[q], tr, ev = ST.step15(ss[q], k, F, P)
            trans.extend(tr)
            if ev is not None:
                events.append(ev)
        s = int(F.s_of_ct[k])
        if s >= 0:
            for q in (0, 1):
                ss[q], tr = ST.stepS(ss[q], s, F, P)
                trans.extend(tr)
        last_k = k
        k += 1
    if stop_at_us is None:
        t_end = int(F.m_ct[-1]) if n else 0
        for q in (0, 1):
            if ss[q].phase in ST.ACTIVE:
                trans.append(ST._tr(t_end, ss[q].setup, ss[q].phase, ST.Phase.INVALID, "end_of_data"))
    return events, trans, {"state": tuple(ss), "last_k": last_k}


# ----------------------------------------------------------------------------------------------- tables
EVENT_DTYPES: dict = {
    "signal_id": "str", "symbol": "str", "tf": "str", "type": "str", "side": "int64", "time": "ts",
    "close": "float64", "atr": "float64", "defending_price": "float64", "tp2": "float64", "a0": "float64",
    "zone_lo": "float64", "zone_hi": "float64", "fvg_lo": "float64", "fvg_hi": "float64", "setup_id": "str",
    "bos_time": "ts", "zone_time": "ts", "touch_time": "ts", "fvg_time": "ts", "trigger_kind": "str",
    "f_htf": "bool", "f_expansion": "bool", "f_sweep": "bool", "f_fresh": "bool", "f_session": "bool", "f_funding": "bool",
    "f_ltf": "bool", "funding_rate": "float64", "universe_date": "date", "rank": "float64", "in_top20": "bool", "sample": "obj",
}
SETUP_DTYPES: dict = {
    "setup_id": "str", "symbol": "str", "side": "int64", "bos_time": "ts", "max_phase": "str", "reason": "str",
    "end_time": "ts", "n_reanchor": "int64", "signal_id": "str", "in_top20_at_bos": "bool", "sample": "obj",
}
_PHASE_RANK = {"BOS": 0, "BOS_CONFIRMED": 1, "ZONE_ARMED": 2, "IN_ZONE": 3, "TRIGGERED": 4}


def _ts(us) -> pd.Series:
    a = np.asarray(us, dtype="float64")
    mask = np.isnan(a)
    v = pd.to_datetime(pd.Series(np.where(mask, 0, a).astype("int64")), unit="us", utc=True).astype("datetime64[us, UTC]")
    return v.mask(pd.Series(mask))


def _frame(cols: dict, dtypes: dict) -> pd.DataFrame:
    out = {}
    for c, kind in dtypes.items():
        v = cols[c]
        if kind == "ts":
            if len(v):
                out[c] = _ts([np.nan if x is None else x for x in v])
            else:
                out[c] = pd.Series([], dtype="datetime64[us, UTC]")
        elif kind == "str":
            out[c] = pd.Series(v, dtype="object").astype("str") if len(v) else pd.Series([], dtype="str")
        elif kind == "bool":
            out[c] = pd.Series(v, dtype="bool")
        elif kind in ("int64", "float64"):
            out[c] = pd.Series(v, dtype=kind)
        else:  # date / obj
            out[c] = pd.Series(v, dtype="object")
    return pd.DataFrame(out)


def _rank_of(rank_by_date, ts_series: pd.Series):
    days = C.universe_dates(ts_series)
    rk = np.array([rank_by_date.get(d, np.nan) for d in days], dtype="float64")
    return days, rk


def _iso(us: int) -> str:
    return pd.Timestamp(us, unit="us", tz="UTC").isoformat()


def events_frame(symbol: str, key: str, P: dict, F: Features, events: list, rank_by_date: dict):
    """Returns (events DataFrame, set of setup_ids dropped by warmup/range)."""
    warm_us = int(pd.Timestamp(P["warmup_until"], tz="UTC").value // 1000)
    cols: dict = {c: [] for c in EVENT_DTYPES}
    dropped: dict = {}
    for ev in events:
        sp = ev.setup
        if ev.time < warm_us:
            dropped[sp.setup_id] = "warmup_dropped"
            continue
        d = pd.Timestamp(ev.time - 5 * 60_000_000, unit="us", tz="UTC").date()
        if not (C.HISTORY_START <= d <= C.HISTORY_END):
            dropped[sp.setup_id] = "range_dropped"
            continue
        side = "short" if ev.side == -1 else "long"
        r = rank_by_date.get(d, np.nan)
        fq = sp.fvg_id
        row = {
            "signal_id": f"ict|{key}|{symbol}|{side}|{_iso(ev.time)}", "symbol": symbol, "tf": "15m", "type": f"ict_{side}",
            "side": ev.side, "time": ev.time, "close": ev.close, "atr": ev.atr, "defending_price": ev.defending, "tp2": ev.tp2,
            "a0": sp.a0, "zone_lo": sp.zone_lo, "zone_hi": sp.zone_hi, "fvg_lo": float(F.fvg_lo[fq]), "fvg_hi": float(F.fvg_hi[fq]),
            "setup_id": sp.setup_id, "bos_time": sp.bos_time, "zone_time": sp.zone_time, "touch_time": sp.touch_time,
            "fvg_time": int(F.fvg_ct[fq]), "trigger_kind": ev.trigger_kind,
            "f_htf": bool(ST._flag(sp, "htf")), "f_expansion": bool(ST._flag(sp, "exp")), "f_sweep": bool(ST._flag(sp, "sweep")),
            "f_fresh": bool(ST._flag(sp, "fresh")), "f_session": ev.f_session, "f_funding": ev.f_funding,
            "f_ltf": ev.trigger_kind in ("mss", "wick"), "funding_rate": ev.funding_rate, "universe_date": d, "rank": r,
            "in_top20": bool(r == r), "sample": None,
        }
        for c in cols:
            cols[c].append(row[c])
    df = _frame(cols, EVENT_DTYPES)
    if len(df):
        df["sample"] = C.sample_of_series(df["time"])
    return df, dropped


def setups_frame(symbol: str, trans: list, ev_ids: dict, dropped: dict, rank_by_date: dict) -> pd.DataFrame:
    info: dict = {}
    for t in trans:
        d = info.setdefault(t.setup_id, {"side": t.side, "max": "BOS", "reason": None, "end": t.time, "re": 0})
        if t.frm == t.to:
            if t.reason == "reanchor":
                d["re"] += 1
            continue
        d["end"] = t.time
        if t.to == "INVALID":
            d["reason"] = t.reason
        elif t.to in _PHASE_RANK and _PHASE_RANK[t.to] > _PHASE_RANK[d["max"]]:
            d["max"] = t.to
    cols: dict = {c: [] for c in SETUP_DTYPES}
    for sid, d in info.items():
        bos = int(sid.rsplit("|", 1)[1])
        reason = d["reason"]
        if d["max"] == "TRIGGERED":
            reason = dropped.get(sid)
        day = pd.Timestamp(bos - 5 * 60_000_000, unit="us", tz="UTC").date()
        r = rank_by_date.get(day, np.nan)
        row = {
            "setup_id": sid, "symbol": symbol, "side": d["side"], "bos_time": bos, "max_phase": d["max"], "reason": reason,
            "end_time": d["end"], "n_reanchor": d["re"], "signal_id": ev_ids.get(sid), "in_top20_at_bos": bool(r == r), "sample": None,
        }
        for c in cols:
            cols[c].append(row[c])
    df = _frame(cols, SETUP_DTYPES)
    if len(df):
        df["sample"] = C.sample_of_series(df["bos_time"])
        df["reason"] = df["reason"].astype(object).where(df["reason"].notna(), None)
        df["signal_id"] = df["signal_id"].astype(object).where(df["signal_id"].notna(), None)
    return df


def _quarter_label(t_us: int) -> str:
    ts = pd.Timestamp(t_us, unit="us", tz="UTC")
    return f"{ts.year}Q{ts.quarter}"


def random_events(symbol: str, key: str, P: dict, F: Features, counts: dict, rank_by_date: dict) -> pd.DataFrame:
    """Plan 5.1: draw n decision bars per (symbol, side, quarter) cell without replacement among eligible 15m closes."""
    warm_us = int(pd.Timestamp(P["warmup_until"], tz="UTC").value // 1000)
    cols: dict = {c: [] for c in EVENT_DTYPES}
    ct = F.m_ct
    if len(ct) == 0:
        return _frame(cols, EVENT_DTYPES)
    sec = ct // 1_000_000
    hour = (sec // 3600) % 24
    wd = (sec // 86400 + 3) % 7
    sess = (hour >= P["session_start_h"]) & (hour < P["session_end_h"]) & ((wd <= 4) | (not P["weekdays_only"]))
    ts = pd.Series(pd.to_datetime(ct - 5 * 60_000_000, unit="us", utc=True))
    days = ts.dt.date.to_numpy()
    top = np.array([d in rank_by_date for d in days])
    in_range = np.array([C.HISTORY_START <= d <= C.HISTORY_END for d in days])
    si = F.s_last_of_m
    atr_ok = (si >= 0) & ~np.isnan(F.S_atr[np.maximum(si, 0)])
    hidx = F.h4_idx_of_m15
    q_of = (pd.Series(pd.to_datetime(ct, unit="us", utc=True)).dt.tz_convert("UTC"))
    qlab = (q_of.dt.year.astype(str) + "Q" + q_of.dt.quarter.astype(str)).to_numpy()
    for side in (-1, 1):
        rng = np.random.default_rng([P["random"]["seed"], zlib.crc32(symbol.encode()), 0 if side == -1 else 1])
        hf = F.h4_bear if side == -1 else F.h4_bull
        htf_ok = (hidx >= 0) & hf[np.maximum(hidx, 0)]
        elig = htf_ok & top & sess & atr_ok & in_range & (ct >= warm_us) & (si >= P["sweep_bars"] - 1)
        cells = sorted((q, n) for (sd_, q), n in counts.items() if sd_ == side)
        for q, n in cells:
            pool = np.flatnonzero(elig & (qlab == q))
            if not len(pool) or n <= 0:
                continue
            got = 0
            for kk in rng.permutation(pool):
                kk = int(kk)
                s_ = int(si[kk])
                c = float(F.m_c[kk])
                if side == -1:
                    cnt = int(np.searchsorted(F.sh_conf, s_, side="right"))
                    a1 = None
                    for j in range(cnt - 1, -1, -1):
                        if F.sh_price[j] > c:
                            a1 = float(F.sh_price[j])
                            break
                    a0 = float(F.S_l[s_ - P["sweep_bars"] + 1:s_ + 1].min())
                else:
                    cnt = int(np.searchsorted(F.sl_conf, s_, side="right"))
                    a1 = None
                    for j in range(cnt - 1, -1, -1):
                        if F.sl_price[j] < c:
                            a1 = float(F.sl_price[j])
                            break
                    a0 = float(F.S_h[s_ - P["sweep_bars"] + 1:s_ + 1].max())
                if a1 is None:
                    continue
                T = int(ct[kk])
                d = days[kk]
                r = rank_by_date.get(d, np.nan)
                rate = ST._funding_at(F, T)
                nm = "short" if side == -1 else "long"
                row = {
                    "signal_id": f"ict|{key}|{symbol}|{nm}|{_iso(T)}", "symbol": symbol, "tf": "15m", "type": f"ict_{nm}", "side": side,
                    "time": T, "close": c, "atr": float(F.S_atr[s_]), "defending_price": a1, "tp2": a0 - P["tp2_ext"] * (a1 - a0),
                    "a0": a0, "zone_lo": np.nan, "zone_hi": np.nan, "fvg_lo": np.nan, "fvg_hi": np.nan, "setup_id": f"rand|{symbol}|{side}|{T}",
                    "bos_time": None, "zone_time": None, "touch_time": None, "fvg_time": None, "trigger_kind": "random",
                    "f_htf": True, "f_expansion": False, "f_sweep": False, "f_fresh": False, "f_session": True, "f_funding": True,
                    "f_ltf": False, "funding_rate": rate, "universe_date": d, "rank": r, "in_top20": bool(r == r), "sample": None,
                }
                for c_ in cols:
                    cols[c_].append(row[c_])
                got += 1
                if got >= n:
                    break
    df = _frame(cols, EVENT_DTYPES)
    if len(df):
        df = df.sort_values(["time", "side"], kind="stable").reset_index(drop=True)
        df["sample"] = C.sample_of_series(df["time"])
    return df


def _feat_key(P: dict) -> tuple:
    return tuple(P[k] for k in ("setup_tf", "swing_n", "atr_n", "fvg_k", "htf_ema", "exp_tr_atr", "exp_vol_mult", "exp_vol_n"))


def empty_events() -> pd.DataFrame:
    return _frame({c: [] for c in EVENT_DTYPES}, EVENT_DTYPES)


def empty_setups() -> pd.DataFrame:
    return _frame({c: [] for c in SETUP_DTYPES}, SETUP_DTYPES)


def symbol_job(args) -> dict:
    """args = (symbol, [(key, P)], rank_by_date, (fund_t, fund_r) [, match_counts])."""
    symbol, variants, rank_by_date, fund = args[:4]
    match = args[4] if len(args) > 4 else {}
    try:
        b15 = C.load_bars_df(symbol, "15m")
        b1h = C.load_bars_df(symbol, "1h")
        b4h = C.load_bars_df(symbol, "4h")
    except FileNotFoundError:
        return {"symbol": symbol, "variants": {k: (empty_events(), empty_setups()) for k, _ in variants}}
    out = {}
    cache: dict = {}
    for key, P in variants:
        fk = _feat_key(P)
        if fk not in cache:
            cache.clear()
            cache[fk] = build_features(symbol, b15, b1h, b4h, fund, P)
        F = cache[fk]
        if P["random"] is not None:
            out[key] = (random_events(symbol, key, P, F, match.get(key, {}), rank_by_date), empty_setups())
            continue
        events, trans, _ = run_symbol(symbol, F, P)
        edf, dropped = events_frame(symbol, key, P, F, events, rank_by_date)
        ev_ids = dict(zip(edf["setup_id"], edf["signal_id"])) if len(edf) else {}
        out[key] = (edf, setups_frame(symbol, trans, ev_ids, dropped, rank_by_date))
    return {"symbol": symbol, "variants": out}


# ----------------------------------------------------------------------------------------------- build
def _paths(key: str) -> tuple:
    return CACHE_DIR / f"events_{key}.parquet", CACHE_DIR / f"setups_{key}.parquet", CACHE_DIR / f"events_{key}.json"


def _load_inputs():
    uni = C.load_universe()
    ranks: dict = {}
    for d, s, r in zip(uni["date"], uni["symbol"], uni["rank"]):
        ranks.setdefault(s, {})[d] = float(r)
    f = pd.read_parquet(C.CACHE / "funding.parquet")
    f = f[~f["imputed"]].sort_values(["symbol", "funding_time"], kind="stable")
    fund = {s: (_us(g["funding_time"]), g["rate"].to_numpy(float)) for s, g in f.groupby("symbol", sort=False)}
    return ranks, fund


def _nrows(symbol: str) -> int:
    try:
        return pq.ParquetFile(C.bars_path(symbol, "15m")).metadata.num_rows
    except Exception:
        return 0


def _match_counts(match_key: str) -> dict:
    ev = pd.read_parquet(_paths(match_key)[0])
    ev = ev[ev["in_top20"]]
    out: dict = {}
    if not len(ev):
        return out
    q = C.quarter_of_series(ev["time"])
    for (s, side, qq), n in ev.assign(q=q).groupby(["symbol", "side", "q"]).size().items():
        out.setdefault(s, {})[(int(side), qq)] = int(n)
    return out


def build(keys_params: list, workers: int, force: bool) -> dict:
    """keys_params = [(key, P)]. Builds events/setups/sidecar under research/cache/ict. Random variants need their match table first."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    result = {}
    for key, P in keys_params:
        ep, sp, mp = _paths(key)
        result[key] = ep
        if not force and ep.exists() and sp.exists() and mp.exists() and json.loads(mp.read_text())["params"] == IP.validate(P):
            continue
        todo.append((key, IP.validate(P)))
    plain = [(k, P) for k, P in todo if P["random"] is None]
    rand = [(k, P) for k, P in todo if P["random"] is not None]
    if plain:
        _build_group(plain, workers, None)
    for k, P in rand:
        mk = IP.table_key(ict_params(P["random"]["match"]))
        if not _paths(mk)[0].exists():
            _build_group([(mk, ict_params(P["random"]["match"]))], workers, None)
        _build_group([(k, P)], workers, {k: _match_counts(mk)})
    return result


def _build_group(group: list, workers: int, match) -> None:
    t0 = _time.time()
    ranks, fund = _load_inputs()
    symbols = sorted(C.union_symbols(), key=lambda s: -_nrows(s))
    empty = (np.empty(0, dtype=np.int64), np.empty(0))

    def jobs():
        for s in symbols:
            m = {k: match[k].get(s, {}) for k, _ in group} if match else {}
            yield (s, group, ranks.get(s, {}), fund.get(s, empty), m)

    ev_parts = {k: [] for k, _ in group}
    st_parts = {k: [] for k, _ in group}
    if workers > 1:
        with Pool(workers, maxtasksperchild=1) as pool:
            it = pool.imap_unordered(symbol_job, jobs(), chunksize=1)
            for res in it:
                for k, (e, s) in res["variants"].items():
                    ev_parts[k].append(e)
                    st_parts[k].append(s)
    else:
        for a in jobs():
            res = symbol_job(a)
            for k, (e, s) in res["variants"].items():
                ev_parts[k].append(e)
                st_parts[k].append(s)
    elapsed = _time.time() - t0
    for key, P in group:
        e = pd.concat([x for x in ev_parts[key] if len(x)] or [empty_events()], ignore_index=True)
        s = pd.concat([x for x in st_parts[key] if len(x)] or [empty_setups()], ignore_index=True)
        if len(e):
            e = e.sort_values(["time", "symbol", "side"], kind="stable").reset_index(drop=True)
        if len(s):
            s = s.sort_values(["bos_time", "symbol", "side"], kind="stable").reset_index(drop=True)
        ep, sp, mp = _paths(key)
        e.to_parquet(ep)
        s.to_parquet(sp)
        mp.write_text(json.dumps({
            "key": key, "params": P, "ict_version": IP.ICT_VERSION, "n_symbols": len(symbols), "rows": int(len(e)),
            "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "elapsed_s": round(elapsed, 1),
        }, indent=1, sort_keys=True))


# ----------------------------------------------------------------------------------------------- funnel (counts only)
REASONS = ("no_anchor1", "htf_reject", "no_expansion", "no_sweep", "replaced", "htf_lost", "close_above_anchor1", "zone_empty",
           "stale_fvg", "close_above_zone", "zone_expired", "no_trigger", "session", "funding", "warmup_dropped", "end_of_data")
QUARTERS = ("2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2")


def _split(df: pd.DataFrame, col_side="side") -> str:
    s = int((df[col_side] == -1).sum())
    return f"{len(df)} ({s}/{len(df) - s})"


def funnel_markdown(per_variant: dict, meta: dict | None = None) -> str:
    """per_variant: name -> dict(key, setups, events_raw, events_sel); counts only, IS rows only (everything else dropped on entry)."""
    meta = meta or {}
    pv = {}
    for name, d in per_variant.items():
        pv[name] = {
            "key": d.get("key", ""),
            "setups": d["setups"][d["setups"]["sample"] == "IS"],
            "raw": d["events_raw"][d["events_raw"]["sample"] == "IS"],
            "sel": d["events_sel"][d["events_sel"]["sample"] == "IS"],
        }
    names = list(pv)
    L = ["# ICT P1 盲測漏斗（只計數、只 IS、無損益）", ""]
    L.append(
        f"- 產生：`.venv/bin/python -m research.ict.generate count --workers 6`，{meta.get('utc', '-')}，ICT_VERSION={IP.ICT_VERSION}，"
        f"耗時 {meta.get('elapsed', '-')} 秒，幣數 {meta.get('n_symbols', '-')}"
    )
    L.append("- 範圍：IS 2024-01-15 → 2025-06-30（2024-01-01 → 01-14 暖機丟棄）")
    L.append("- 事件計數口徑：sim.select_signals 之後（in_top20、exclude_tradfi、delist_rule、日期範圍），未模擬")
    L += ["", "## 1. 各階計數（多空合計；括號內為 short/long）",
          "| 階 | 實驗 | key | BOS 候選 | setup 成立 | zone 建立 | 觸區 | 事件（原始） | 事件（篩選後） | ≥150 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name in names:
        d = pv[name]
        st = d["setups"]
        rank = st["max_phase"].map(lambda x: _PHASE_RANK.get(x, 0)) if len(st) else pd.Series([], dtype=int)
        cells = [_split(st[rank >= r]) for r in (0, 1, 2, 3)] if len(st) else ["0 (0/0)"] * 4
        tag = "L7" if name == "ict_L7" else (name.replace("ict_", "") if name != "ict_setup15m" else "15m")
        thr = ("是" if len(d["sel"]) >= 150 else "否") if name in ("ict_L7", "ict_setup15m") else "—"
        L.append(f"| {tag} | {name} | {d['key']} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {len(d['raw'])} | {_split(d['sel'])} | {thr} |")
    L += ["", "## 2. 季度分佈（篩選後事件，short/long）", "| 實驗 | " + " | ".join(QUARTERS) + " |", "|---|" + "---|" * len(QUARTERS)]
    for name in names:
        sel = pv[name]["sel"]
        q = C.quarter_of_series(sel["time"]) if len(sel) else pd.Series([], dtype=str)
        row = []
        for qq in QUARTERS:
            m = (q == qq).to_numpy() if len(sel) else np.zeros(0, dtype=bool)
            s = int((sel["side"].to_numpy()[m] == -1).sum()) if len(sel) else 0
            row.append(f"{int(m.sum())} ({s}/{int(m.sum()) - s})")
        L.append(f"| {name} | " + " | ".join(row) + " |")
    L.append("")
    L.append("（2024Q1 只含 01-15 之後）")
    L += ["", "## 3. 失效原因（依 bos_time 屬 IS 的 setups）；`close_above_*` 在做多時表示 close_below"]
    extra = sorted({r for d in pv.values() for r in d["setups"]["reason"].dropna().unique()} - set(REASONS))
    L.append("| reason | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for r in list(REASONS) + extra:
        L.append(f"| {r} | " + " | ".join(str(int((pv[n]["setups"]["reason"] == r).sum())) for n in names) + " |")
    L += ["", "## 4. 每幣分佈（L7 篩選後事件）"]
    if "ict_L7" in pv:
        sel = pv["ict_L7"]["sel"]
        vc = sel["symbol"].value_counts() if len(sel) else pd.Series([], dtype=int)
        n_sym = int(meta.get("n_symbols", len(vc)) or len(vc))
        L.append(f"- 最多：{int(vc.max()) if len(vc) else 0}（{vc.idxmax() if len(vc) else '-'}）")
        counts = np.r_[vc.to_numpy(), np.zeros(max(n_sym - len(vc), 0), dtype=int)]
        L.append(f"- 中位數：{float(np.median(counts)) if len(counts) else 0}")
        L.append(f"- 0 事件的幣數：{int((counts == 0).sum())}")
    n = len(pv["ict_L7"]["sel"]) if "ict_L7" in pv else 0
    L += ["", "## 5. 判定", f"ict_L7 IS 事件數 = {n}。"]
    if n >= 150:
        L.append("N ≥ 150 → 盲測門檻通過，可進 P2。")
    else:
        L.append("N < 150 → 停止：依 ict_phase1.md 第 8 節回報，只能改走 ict_setup15m 或另開 top-50 計畫。")
    return "\n".join(L) + "\n"


def count(workers: int, out: Path, names=LADDER + ("ict_setup15m",), rebuild: bool = False) -> int:
    from research import sim

    t0 = _time.time()
    kp = [(IP.table_key(ict_params(n)), ict_params(n)) for n in names]
    build(kp, workers, rebuild)
    market = types.SimpleNamespace(delist=sim.load_delist())
    per = {}
    for n, (key, P) in zip(names, kp):
        cfg = sim.SimConfig.from_dict(experiment_dict(n))
        sel = sim.select_signals(cfg, market)
        raw = pd.read_parquet(_paths(key)[0])
        per[n] = {"key": key, "setups": pd.read_parquet(_paths(key)[1]), "events_raw": raw, "events_sel": sel}
    md = funnel_markdown(per, {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "elapsed": int(_time.time() - t0),
                               "n_symbols": len(C.union_symbols())})
    Path(out).write_text(md)
    n7 = int(((per["ict_L7"]["events_sel"]["sample"] == "IS")).sum()) if "ict_L7" in per else 0
    print(f"ICT COUNT L7_IS={n7} verdict={'PASS' if n7 >= 150 else 'STOP'}")
    return 0


# ----------------------------------------------------------------------------------------------- P2 S0: YAML + manifest
ICT_EXP_DIR = C.EXPERIMENTS / "ict"
ICT_NB_DIR = ICT_EXP_DIR / "neighbors"
ICT_MANIFEST = ICT_EXP_DIR / "ict_manifest.json"


def _dump(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def registered_names() -> list:
    """The 19 registered main experiments in plan section 5 order (ict_rsv1-5 are never generated)."""
    return [n for n, kind, _ in EXPERIMENTS if kind != "reserved"]


def manifest_dict() -> dict:
    from research import run as R
    from research.sim import SimConfig

    def row(n):
        d = experiment_dict(n)
        return {"name": n, "kind": next((k for m, k, _ in EXPERIMENTS if m == n), "neighbor"), "table_key": IP.table_key(d["signals"]["ict"]),
                "config_sha": R.config_sha(SimConfig.from_dict(d).resolved())}

    mains = registered_names()
    nbs = neighbor_names("ict_L7")
    return {
        "plan": "research/plans/ict_phase1.md",
        "ict_version": IP.ICT_VERSION,
        "run": [row(n) for n in mains],
        "neighbors": {"ict_L7": [row(n) for n in nbs]},
        "reserved": [n for n, kind, _ in EXPERIMENTS if kind == "reserved"],
        "order": {"S1": ["ict_L7"] + nbs, "S2": [n for n in mains if n != "ict_L7"]},
    }


def planned_files(extra_neighbors_of: tuple = ()) -> dict:
    """path -> text of every file `gen` owns."""
    files = {ICT_EXP_DIR / f"{n}.yaml": _dump(experiment_dict(n)) for n in registered_names()}
    for base in ("ict_L7",) + tuple(extra_neighbors_of):
        if base == "ict_rand" or base not in registered_names():
            raise SystemExit(f"neighbours are not defined for {base!r}")
        for n in neighbor_names(base):
            files[ICT_NB_DIR / f"{n}.yaml"] = _dump(experiment_dict(n))
    files[ICT_MANIFEST] = _dump(manifest_dict())
    return files


def gen(check: bool = False, extra_neighbors_of: tuple = ()) -> int:
    files = planned_files(extra_neighbors_of)
    bad = [p for p, t in files.items() if not p.exists() or p.read_text() != t]
    if check:
        for p in bad:
            print("GEN MISMATCH", p)
        print(f"GEN CHECK {'OK' if not bad else 'FAIL'}: {len(files)} files")
        return 0 if not bad else 1
    for p in bad:
        if p.exists():
            print("refusing to overwrite a different existing file:", p, file=sys.stderr)
            return 2
    for p in bad:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[p])
    print(f"GEN wrote {len(bad)} new files, {len(files) - len(bad)} already identical")
    return 0


def _all_params() -> list:
    out = {}
    for n, kind, _ in EXPERIMENTS:
        if kind != "reserved":
            out[n] = ict_params(n)
    for n, _ in NEIGHBORS:
        out[n] = ict_params(n)
    seen, kp = set(), []
    for n, P in out.items():
        k = IP.table_key(P)
        if k not in seen:
            seen.add(k)
            kp.append((k, P))
    return kp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="research.ict.generate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--exp")
    g.add_argument("--all", action="store_true")
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--force", action="store_true")
    c = sub.add_parser("count")
    c.add_argument("--workers", type=int, default=6)
    c.add_argument("--out", default=str(C.OUT / "ict_funnel.md"))
    c.add_argument("--rebuild", action="store_true")
    gp = sub.add_parser("gen", help="write the 19 registered YAMLs + 4 ict_L7 neighbours + manifest (never overwrites)")
    gp.add_argument("--check", action="store_true", help="only verify the files on disk equal what gen would write")
    gp.add_argument("--neighbors-of", action="append", default=[], metavar="NAME", help="also write the 4 neighbours of another registered experiment (A1.3 step 3)")
    k = sub.add_parser("key")
    k.add_argument("--exp", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "key":
        print(IP.table_key(ict_params(a.exp)))
        return 0
    if a.cmd == "gen":
        return gen(a.check, tuple(a.neighbors_of))
    if a.cmd == "count":
        return count(a.workers, Path(a.out), rebuild=a.rebuild)
    if a.all:
        kp = _all_params()
    else:
        kp = []
        for n in a.exp.split(","):
            P = ict_params(n)
            kp.append((IP.table_key(P), P))
    res = build(kp, a.workers, a.force)
    for k_, p in res.items():
        print(k_, p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
