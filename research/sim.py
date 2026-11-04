"""Signal simulator. Every signal is simulated independently on the 15m price path.

No account, no position cap. Matching order per 15m bar mirrors backtest/matcher.py + risk/review.py:
  (1) next-open exits fill at the open  (2) stop (open gap -> open, else touch -> stop)
  (3) TP1 / fixed R, only if the stop did not trigger  (4) close review -> queue next-open exit or move stop.
"""

from __future__ import annotations

import copy
import math
from bisect import bisect_left
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research import common as C

BIAS_DOWN = ("down", "breakout_down")
BIAS_UP = ("up", "breakout_up")
CHAN_TYPES = ("second_buy", "third_buy", "second_sell", "third_sell")
EXIT_MODULES = {
    "tp1": {"enabled": False, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5},
    "breakeven": {"enabled": False, "arm_r": 1.0},
    "ratchet": {"enabled": False},
    "fixed_r": {"enabled": False, "r": 2.0},
    "atr_trail": {"enabled": False, "mult": 3.0, "arm_r": 0.0},
    "opposite_signal": {"enabled": False, "tf": "15m"},
    "bias_1h": {"enabled": False},
    "level_fail": {"enabled": False},
    "time_stop": {"enabled": False, "bars": 96},
}
PRESETS = {
    "current": {
        "tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5},
        "breakeven": {"enabled": True, "arm_r": 1.0},
        "ratchet": {"enabled": True},
        "opposite_signal": {"enabled": True, "tf": "15m"},
        "bias_1h": {"enabled": True},
        "level_fail": {"enabled": True},
    },
    "ratchet_only": {
        "breakeven": {"enabled": True, "arm_r": 1.0},
        "ratchet": {"enabled": True},
    },
}
_FILTER_DEFAULTS = {
    "in_top20": True,
    "candidate_only": False,
    "gate_pass": False,
    "jev_min": None,
    "max_cost_r": None,
    "exclude_reemit": False,
}
# phase 1 optional keys: absent == default == old behaviour; resolved() never prints a default value (keeps phase 0 shas)
_FILTER_OPTIONAL = {
    "htf_4h": False,
    "vol_band": False,
    "exclude_tradfi": False,
    "min_stop_atr": None,
    "min_stop_pct": None,
}
DONCHIAN_NS = (16, 20, 24, 44, 55, 66)


class ConfigError(ValueError):
    pass


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check_keys(section: str, d: dict, allowed: set, required: set | None = None) -> None:
    if not isinstance(d, dict):
        raise ConfigError(f"{section} must be a mapping")
    extra = set(d) - allowed
    if extra:
        raise ConfigError(f"unknown key(s) in {section}: {sorted(extra)}")
    missing = (required if required is not None else allowed) - set(d)
    if missing:
        raise ConfigError(f"missing key(s) in {section}: {sorted(missing)}")


def _expect(section: str, key: str, value, kind) -> None:
    ok = {
        "bool": isinstance(value, bool),
        "num": _is_num(value),
        "int": isinstance(value, int) and not isinstance(value, bool),
        "str": isinstance(value, str),
        "num?": value is None or _is_num(value),
        "int?": value is None or (isinstance(value, int) and not isinstance(value, bool)),
    }[kind]
    if not ok:
        raise ConfigError(f"{section}.{key} has the wrong type: {value!r}")


@dataclass(frozen=True)
class SimConfig:
    name: str
    description: str
    signals: dict
    filters: dict
    entry: dict
    stop: dict
    exit: dict
    costs: dict

    @staticmethod
    def from_dict(d: dict) -> "SimConfig":
        _check_keys("experiment", d, {"name", "description", "signals", "filters", "entry", "stop", "exit", "costs"})
        _expect("experiment", "name", d["name"], "str")
        _expect("experiment", "description", d["description"], "str")
        sig = d["signals"]
        _check_keys("signals", sig, {"source", "tf", "types", "donchian_n"})
        if sig["source"] not in ("chan", "donchian"):
            raise ConfigError("signals.source must be chan or donchian")
        if sig["tf"] not in C.TFS:
            raise ConfigError("signals.tf must be 15m, 1h or 4h")
        if not isinstance(sig["types"], list) or not all(isinstance(x, str) for x in sig["types"]):
            raise ConfigError("signals.types must be a list of strings")
        if sig["source"] == "chan":
            bad = set(sig["types"]) - set(CHAN_TYPES)
            if bad or not sig["types"]:
                raise ConfigError(f"signals.types invalid for chan: {sorted(bad)}")
            if sig["donchian_n"] is not None:
                raise ConfigError("signals.donchian_n must be null for chan")
        else:
            if sig["tf"] == "15m":
                raise ConfigError("donchian signals exist for 1h and 4h only")
            if sig["donchian_n"] not in DONCHIAN_NS:
                raise ConfigError(f"signals.donchian_n must be one of {DONCHIAN_NS}")
            n = sig["donchian_n"]
            if set(sig["types"]) - {f"dc{n}_long", f"dc{n}_short"} or not sig["types"]:
                raise ConfigError(f"signals.types for donchian must be dc{n}_long / dc{n}_short")
        f = d["filters"]
        _check_keys("filters", f, set(_FILTER_DEFAULTS) | set(_FILTER_OPTIONAL), set(_FILTER_DEFAULTS))
        f = {**_FILTER_OPTIONAL, **f}
        for k in ("in_top20", "candidate_only", "gate_pass", "exclude_reemit", "htf_4h", "vol_band", "exclude_tradfi"):
            _expect("filters", k, f[k], "bool")
        for k in ("min_stop_atr", "min_stop_pct"):
            _expect("filters", k, f[k], "num?")
            if f[k] is not None and not f[k] > 0:
                raise ConfigError(f"filters.{k} must be > 0")
        if sig["source"] != "chan" and (f["htf_4h"] or f["vol_band"]):
            raise ConfigError("htf_4h / vol_band exist for chan signals only")
        _expect("filters", "jev_min", f["jev_min"], "num?")
        _expect("filters", "max_cost_r", f["max_cost_r"], "num?")
        if (sig["tf"] != "15m" or sig["source"] != "chan") and (f["candidate_only"] or f["gate_pass"] or f["jev_min"] is not None):
            raise ConfigError("candidate_only / gate_pass / jev_min exist for chan 15m signals only")
        e = d["entry"]
        _check_keys("entry", e, {"mode", "limit", "confirm"}, {"mode"})
        if e["mode"] not in ("market_next_open", "limit", "confirm"):
            raise ConfigError("entry.mode must be market_next_open, limit or confirm")
        entry = {"mode": e["mode"]}
        if e["mode"] == "limit":
            lim = e.get("limit")
            _check_keys("entry.limit", lim, {"price", "offset", "valid_bars"})
            if lim["price"] not in ("signal_close", "stop_frac", "defend_frac"):
                raise ConfigError("entry.limit.price must be signal_close, stop_frac or defend_frac")
            _expect("entry.limit", "offset", lim["offset"], "num")
            _expect("entry.limit", "valid_bars", lim["valid_bars"], "int")
            if lim["valid_bars"] < 1:
                raise ConfigError("entry.limit.valid_bars must be >= 1")
            entry["limit"] = dict(lim)
        if e["mode"] == "confirm":
            cf = e.get("confirm")
            _check_keys("entry.confirm", cf, {"bars", "require_close_beyond"})
            _expect("entry.confirm", "bars", cf["bars"], "int")
            _expect("entry.confirm", "require_close_beyond", cf["require_close_beyond"], "bool")
            if cf["bars"] < 1:
                raise ConfigError("entry.confirm.bars must be >= 1")
            entry["confirm"] = dict(cf)
        st = d["stop"]
        _check_keys("stop", st, {"buffer_atr", "round_to_tick"})
        _expect("stop", "buffer_atr", st["buffer_atr"], "num")
        _expect("stop", "round_to_tick", st["round_to_tick"], "bool")
        costs = d["costs"]
        _check_keys("costs", costs, {"taker_bps", "maker_bps", "slippage_bps"})
        for k in costs:
            _expect("costs", k, costs[k], "num")
        ex = resolve_exit(d["exit"])
        return SimConfig(
            name=d["name"],
            description=d["description"],
            signals=dict(sig),
            filters=dict(f),
            entry=entry,
            stop=dict(st),
            exit=ex,
            costs=dict(costs),
        )

    def resolved(self) -> dict:
        filters = {k: v for k, v in self.filters.items() if k not in _FILTER_OPTIONAL or v != _FILTER_OPTIONAL[k]}
        return {
            "name": self.name,
            "description": self.description,
            "signals": self.signals,
            "filters": filters,
            "entry": self.entry,
            "stop": self.stop,
            "exit": self.exit,
            "costs": self.costs,
        }


def resolve_exit(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("exit must be a mapping")
    allowed = set(EXIT_MODULES) | {"preset"}
    extra = set(raw) - allowed
    if extra:
        raise ConfigError(f"unknown key(s) in exit: {sorted(extra)}")
    out = copy.deepcopy(EXIT_MODULES)
    preset = raw.get("preset")
    if preset is not None:
        if preset not in PRESETS:
            raise ConfigError(f"unknown exit preset {preset!r}")
        for k, v in PRESETS[preset].items():
            out[k].update(v)
    for k, v in raw.items():
        if k == "preset":
            continue
        _check_keys(f"exit.{k}", v, set(EXIT_MODULES[k]), {"enabled"})
        out[k].update(v)
    for k, v in out.items():
        for kk, vv in v.items():
            kind = {"enabled": "bool", "target": "str", "tf": "str", "bars": "int"}.get(kk, "num")
            _expect(f"exit.{k}", kk, vv, kind)
    if out["tp1"]["target"] not in ("prior_swing", "r"):
        raise ConfigError("exit.tp1.target must be prior_swing or r")
    if out["opposite_signal"]["tf"] not in C.TFS:
        raise ConfigError("exit.opposite_signal.tf invalid")
    if out["ratchet"]["enabled"] and not out["breakeven"]["enabled"]:
        raise ConfigError("exit.ratchet needs exit.breakeven")
    return out


# --------------------------------------------------------------------------- market data
def _us(series: pd.Series) -> np.ndarray:
    return series.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy().astype("int64")


@dataclass
class Market:
    bars: dict  # symbol -> dict of numpy arrays (ot, o, h, l, c)
    bias_down: dict  # symbol -> (close_time_us array, down flag array, up flag array) from bias_1h
    bi_new: dict  # symbol -> (confirm_us, up_end array, down_end array) event arrays for 'new'
    ticks: dict
    tables: dict = field(default_factory=dict)
    funding: dict | None = None  # symbol -> (funding_time_us array, rate array); None = funding not modelled
    funding_months: dict | None = None  # symbol -> set of "YYYY-MM" that have a funding CSV


def load_funding():
    """(funding, funding_months) from the augment cache, or (None, None) when it has not been built."""
    fp, mp = C.CACHE / "funding.parquet", C.CACHE / "funding_months.parquet"
    if not (fp.exists() and mp.exists()):
        return None, None
    f = pd.read_parquet(fp).sort_values(["symbol", "funding_time"], kind="stable")
    out = {}
    for sym, g in f.groupby("symbol", sort=False):
        out[sym] = (_us(g["funding_time"]), g["rate"].to_numpy(float))
    m = pd.read_parquet(mp)
    months = {sym: set(g["month"]) for sym, g in m.groupby("symbol", sort=False)}
    return out, months


def load_market(bi_tf: str = "15m") -> Market:
    cache = C.CACHE
    df = pd.read_parquet(cache / "bars_15m.parquet")
    df = df.sort_values(["symbol", "open_time"], kind="stable").reset_index(drop=True)
    ot = _us(df["open_time"])
    sym = df["symbol"].to_numpy()
    cuts = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1], True])
    arr = {c: df[c].to_numpy(float) for c in ("open", "high", "low", "close")}
    bars = {}
    for a, b in zip(cuts[:-1], cuts[1:]):
        bars[sym[a]] = {"ot": ot[a:b], "o": arr["open"][a:b], "h": arr["high"][a:b], "l": arr["low"][a:b], "c": arr["close"][a:b]}
    del df
    b1 = pd.read_parquet(cache / "bias_1h.parquet")
    bias = {}
    for s, g in b1.groupby("symbol", sort=False):
        g = g.sort_values("close_time")
        b = g["bias"].to_numpy()
        bias[s] = (_us(g["close_time"]), np.isin(b, BIAS_DOWN), np.isin(b, BIAS_UP))
    ev = pd.read_parquet(cache / f"bi_events_{bi_tf}.parquet")
    ev = ev[ev["event"] == "new"].sort_values(["symbol", "confirm_time"], kind="stable")
    bi = {}
    for s, g in ev.groupby("symbol", sort=False):
        t = _us(g["confirm_time"])
        d = g["direction"].to_numpy()
        e = g["end_price"].to_numpy(float)
        bi[s] = (t, np.where(d == 1, e, np.nan), np.where(d == -1, e, np.nan))
    inst = pd.read_parquet(cache / "instruments.parquet")
    ticks = {s: (None if pd.isna(t) else float(t)) for s, t in zip(inst["symbol"], inst["price_tick"])}
    fund, fmonths = load_funding()
    return Market(bars, bias, bi, ticks, funding=fund, funding_months=fmonths)


AUG_COLS = ("atr15_pct", "tp_up_end", "tp_down_end")


def load_signal_table(cfg: SimConfig, tf: str, source: str | None = None, aug: bool = False) -> pd.DataFrame:
    """Signal table; aug=True merges signals_{tf}_aug (atr15_pct, tp_up_end, tp_down_end) after asserting identical rows."""
    source = source or cfg.signals["source"]
    name = f"signals_{tf}.parquet" if source == "chan" else f"signals_donchian_{tf}.parquet"
    df = pd.read_parquet(C.CACHE / name)
    if aug and source == "chan":
        ap = C.CACHE / f"signals_{tf}_aug.parquet"
        needed = cfg.filters.get("vol_band") or (tf != "15m" and cfg.exit["tp1"]["enabled"])
        if not ap.exists():
            if needed:
                raise FileNotFoundError(f"{ap.name} is required by this configuration (run research.augment build)")
            return df
        a = pd.read_parquet(ap)
        if len(a) != len(df):
            raise ValueError(f"{ap.name}: {len(a)} rows, expected {len(df)}")
        for c in ("symbol", "type", "time"):
            if not (a[c].to_numpy() == df[c].to_numpy()).all():
                raise ValueError(f"{ap.name}: column {c} differs from {name}")
        for c in AUG_COLS:
            df[c] = a[c].to_numpy()
    return df


def select_signals(cfg: SimConfig, market: Market | None = None) -> pd.DataFrame:
    sg = cfg.signals
    f = cfg.filters
    df = load_signal_table(cfg, sg["tf"], aug=True)
    m = df["type"].isin(sg["types"])
    if sg["source"] == "donchian":
        m &= df["n"] == sg["donchian_n"]
    if f["in_top20"]:
        m &= df["in_top20"].astype(bool)
    if f["candidate_only"]:
        m &= df["candidate"].astype(bool) & ~df["ambiguous"].astype(bool)
    if f["gate_pass"]:
        m &= df["gate_pass"].fillna(False).astype(bool)
    if f["jev_min"] is not None:
        m &= df["jev_score"] >= f["jev_min"]
    if f["exclude_reemit"]:
        m &= ~df["reemit"].astype(bool)
    if f["htf_4h"]:
        b4 = df["bias_4h"]
        m &= ((df["side"] == 1) & b4.isin(BIAS_UP)) | ((df["side"] == -1) & b4.isin(BIAS_DOWN))
    if f["vol_band"]:
        v = C.settings().volatility
        assert (v.atr_pct_min, v.atr_pct_max) == (0.001, 0.03), v
        a = df["atr15_pct"]
        m &= (a >= v.atr_pct_min) & (a <= v.atr_pct_max)  # NaN compares False -> rejected
    if f["exclude_tradfi"]:
        m &= ~df["symbol"].str.split("/").str[0].isin(C.TRADFI_BASES)
    day = C.universe_dates(df["time"])
    m &= (day >= C.HISTORY_START) & (day <= C.HISTORY_END)
    out = df[m].sort_values(["symbol", "time"], kind="stable").reset_index(drop=True)
    out["attempt_id"] = np.arange(len(out), dtype="int64")
    return out


def opposite_times(cfg: SimConfig) -> dict:
    """symbol -> {side: sorted array of signal times (us)} of unfiltered opposite signals."""
    ex = cfg.exit["opposite_signal"]
    if not ex["enabled"]:
        return {}
    if cfg.signals["source"] == "chan":
        df = load_signal_table(cfg, ex["tf"])
    else:
        df = load_signal_table(cfg, cfg.signals["tf"])
        df = df[df["n"] == cfg.signals["donchian_n"]]
    out: dict = {}
    for (s, side), g in df.groupby(["symbol", "side"], sort=False):
        out.setdefault(s, {})[int(side)] = np.sort(_us(g["time"]))
    return out


# --------------------------------------------------------------------------- simulation core
def _tick_round(price: float, tick: float | None, side: int, buffer_dec: Decimal | None, defending: float):
    """Structure stop with Decimal tick rounding, as risk/stops.py::structure_stop."""
    if tick is None or buffer_dec is None:
        return None
    t = Decimal(repr(tick))
    raw = Decimal(format(defending, ".8f")) - side * buffer_dec
    q = (raw / t).to_integral_value(rounding=ROUND_DOWN if side == 1 else ROUND_CEILING) * t
    return float(q)


def _floor_tick(price: float, tick: float, side: int) -> float:
    t = Decimal(repr(tick))
    q = (Decimal(format(price, ".8f")) / t).to_integral_value(rounding=ROUND_DOWN if side == 1 else ROUND_CEILING) * t
    return float(q)


def _month_range(a_us: int, b_us: int):
    a = pd.Timestamp(a_us, unit="us")
    b = pd.Timestamp(b_us, unit="us")
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def funding_for_trade(fund, fmonths, symbol, side, R, entry_us, exit_us, legs_ot, legs_w, ot, O, Cl):
    """Funding cost in R for one trade. Events F with entry_us < F <= exit_us; weight = share of legs exiting at or after F.

    mark = close of the 15m bar whose close_time == F, else open of the bar whose open_time == F, else the event is skipped.
    Returns (funding_r, n_events_counted, missing_flag).
    """
    if fund is None:
        return 0.0, 0, False
    missing = False
    months = fmonths.get(symbol, set()) if fmonths is not None else set()
    for mo in _month_range(entry_us, exit_us):
        if mo not in months:
            missing = True
            break
    ft, fr = fund.get(symbol, (np.empty(0, dtype="int64"), np.empty(0)))
    lo = int(np.searchsorted(ft, entry_us, side="right"))
    hi = int(np.searchsorted(ft, exit_us, side="right"))
    total = 0.0
    cnt = 0
    for k in range(lo, hi):
        F = int(ft[k])
        w = sum(wl for wl, tl in zip(legs_w, legs_ot) if tl >= F)
        idx = bisect_left(ot, F - 900_000_000)
        if idx < len(ot) and ot[idx] == F - 900_000_000:
            mark = Cl[idx]
        else:
            idx = bisect_left(ot, F)
            if idx < len(ot) and ot[idx] == F:
                mark = O[idx]
            else:
                missing = True
                continue
        total += w * side * float(fr[k]) * mark
        cnt += 1
    return total / R, cnt, missing


def simulate_symbol(cfg: SimConfig, symbol: str, sig: pd.DataFrame, mk: dict, bias, bi, opp: dict, tick, funding=None, attempts_out=None):
    ex = cfg.exit
    costs = cfg.costs
    taker = costs["taker_bps"] / 1e4
    maker = costs["maker_bps"] / 1e4
    slip = costs["slippage_bps"] / 1e4
    buf_atr = cfg.stop["buffer_atr"]
    round_tick = cfg.stop["round_to_tick"]
    max_cost = cfg.filters["max_cost_r"]
    ms_atr = cfg.filters.get("min_stop_atr")
    ms_pct = cfg.filters.get("min_stop_pct")
    mode = cfg.entry["mode"]
    fund, fmonths = funding if funding is not None else (None, None)
    n_bars = len(mk["ot"])
    ot = mk["ot"].tolist()
    O = mk["o"].tolist()
    H = mk["h"].tolist()
    L = mk["l"].tolist()
    Cl = mk["c"].tolist()
    ct = [x + 900_000_000 for x in ot]
    # aligned 1h bias flags for each bar (value of the last 1h close <= bar close)
    if ex["bias_1h"]["enabled"] and len(bias[0]):
        bt, bdown, bup = bias
        pos = np.searchsorted(bt, np.array(ct), side="right") - 1
        valid = pos >= 0
        pos = np.where(valid, pos, 0)
        b_down = (bdown[pos] & valid).tolist()
        b_up = (bup[pos] & valid).tolist()
    else:
        b_down = b_up = [False] * n_bars
    # aligned new bi endpoints (of the signal timeframe; the event is usable from the 15m bar closing at confirm_time)
    if ex["ratchet"]["enabled"] and bi is not None:
        et, eup, edn = bi
        idx = np.searchsorted(np.array(ct), et)  # bar whose close_time == event time
        nup = [math.nan] * n_bars
        ndn = [math.nan] * n_bars
        ctarr = np.array(ct)
        for k in range(len(et)):
            j = int(idx[k])
            if j < n_bars and ctarr[j] == et[k]:
                if not math.isnan(eup[k]):
                    nup[j] = float(eup[k])
                if not math.isnan(edn[k]):
                    ndn[j] = float(edn[k])
    else:
        nup = ndn = None
    rows = []
    cnt = {
        "signals": 0, "no_entry_bar": 0, "invalid_stop": 0, "tick_missing": 0, "cost_rejected": 0,
        "unfilled": 0, "confirm_abandoned": 0, "minstop_rejected": 0,
    }
    tp1C, beC, ratC, fixC, trC = ex["tp1"], ex["breakeven"], ex["ratchet"], ex["fixed_r"], ex["atr_trail"]
    oppC, biasC, lvlC, timeC = ex["opposite_signal"], ex["bias_1h"], ex["level_fail"], ex["time_stop"]
    has_tp_cols = "tp_up_end" in sig.columns
    for r in sig.itertuples(index=False):
        cnt["signals"] += 1
        side = int(r.side)
        T_us = int(r.time.value // 1000) if hasattr(r.time, "value") else None
        tf_us = C.TF_US[r.tf]
        aid = int(getattr(r, "attempt_id", -1))

        def att(status, end_us, _r=r, _side=side, _T=T_us, _aid=aid):
            if attempts_out is not None:
                attempts_out.append((_aid, _r.signal_id, symbol, _r.tf, _r.type, _side, _T, status, int(end_us)))

        j0 = bisect_left(ot, T_us)
        if j0 >= n_bars:
            cnt["no_entry_bar"] += 1
            att("no_entry_bar", T_us)
            continue
        atr = float(r.atr)
        if not (atr == atr):
            cnt["invalid_stop"] += 1
            att("invalid_stop", T_us)
            continue
        defending = float(r.defending_price)
        # ---- stop
        buffer = buf_atr * atr
        stop = None
        if round_tick:
            if tick is None:
                cnt["tick_missing"] += 1
            else:
                bd = Decimal(repr(buf_atr)) * Decimal(format(atr, ".8f"))
                stop = _tick_round(0, tick, side, bd, defending)
        if stop is None:
            stop = defending - side * buffer
        sig_close = float(r.close)

        def minstop_fail(ref, _stop=stop, _side=side, _atr=atr):
            dist = _side * (ref - _stop)
            if ms_atr is not None and not dist / _atr >= ms_atr:
                return True
            if ms_pct is not None and not dist / ref >= ms_pct:
                return True
            return False

        # ---- entry
        jf = None
        maker_entry = False
        if mode == "market_next_open":
            jf = j0
            entry_ref = sig_close
            p_entry = O[jf] * (1 + side * slip)
            if not side * (entry_ref - stop) > 0:
                cnt["invalid_stop"] += 1
                att("invalid_stop", T_us)
                continue
            if minstop_fail(entry_ref):
                cnt["minstop_rejected"] += 1
                att("minstop_rejected", T_us)
                continue
        elif mode == "limit":
            lim = cfg.entry["limit"]
            if lim["price"] == "signal_close":
                lvl = sig_close - side * lim["offset"] * atr
            elif lim["price"] == "defend_frac":
                lvl = sig_close - lim["offset"] * (sig_close - defending)
            else:
                lvl = sig_close - side * lim["offset"] * side * (sig_close - stop)
            if not side * (lvl - stop) > 0:
                cnt["invalid_stop"] += 1
                att("invalid_stop", T_us)
                continue
            if minstop_fail(lvl):
                cnt["minstop_rejected"] += 1
                att("minstop_rejected", T_us)
                continue
            t_end = T_us + lim["valid_bars"] * tf_us  # valid while open_time < T + N signal-timeframe bars
            last_valid = None
            j = j0
            while j < n_bars and ot[j] < t_end:
                last_valid = j
                if (side == 1 and L[j] < lvl) or (side == -1 and H[j] > lvl):  # strictly through the limit
                    jf = j
                    break
                j += 1
            if jf is None:
                cnt["unfilled"] += 1
                att("unfilled", ot[last_valid] if last_valid is not None else T_us)
                continue
            entry_ref = lvl
            p_entry = lvl
            maker_entry = True
        else:  # confirm: wait K signal-timeframe bars, then enter at the next 15m open
            cf = cfg.entry["confirm"]
            t_end = T_us + cf["bars"] * tf_us
            jl = None
            dead_at = None
            j = j0
            while j < n_bars and ot[j] < t_end:
                if (side == 1 and L[j] <= stop) or (side == -1 and H[j] >= stop):
                    dead_at = j
                    break
                jl = j
                j += 1
            if dead_at is not None:
                cnt["confirm_abandoned"] += 1
                att("abandoned", ot[dead_at])
                continue
            if jl is None or ct[jl] != t_end:  # missing data inside the window
                cnt["confirm_abandoned"] += 1
                att("abandoned", ot[jl] if jl is not None else T_us)
                continue
            last_close = Cl[jl]
            if cf["require_close_beyond"] and ((side == 1 and last_close < sig_close) or (side == -1 and last_close > sig_close)):
                cnt["confirm_abandoned"] += 1
                att("abandoned", ot[jl])
                continue
            if jl + 1 >= n_bars:
                cnt["no_entry_bar"] += 1
                att("no_entry_bar", T_us)
                continue
            if not side * (last_close - stop) > 0:
                cnt["invalid_stop"] += 1
                att("invalid_stop", T_us)
                continue
            if minstop_fail(last_close):
                cnt["confirm_abandoned"] += 1
                att("abandoned", ot[jl])
                continue
            jf = jl + 1
            entry_ref = last_close
            p_entry = O[jf] * (1 + side * slip)
        R = side * (entry_ref - stop)
        if max_cost is not None and (2 * (taker + slip)) / (R / entry_ref) > max_cost:
            cnt["cost_rejected"] += 1
            att("cost_rejected", T_us)
            continue
        fee_entry = maker if maker_entry else taker
        # ---- exit plan
        tp_price = None
        tp_frac = 0.0
        if tp1C["enabled"]:
            tp_frac = tp1C["fraction"]
            if tp1C["target"] == "prior_swing":
                if has_tp_cols:
                    end = float(r.tp_up_end if side == 1 else r.tp_down_end)
                else:
                    end = float(r.last_up_end if side == 1 else r.last_down_end)
                if end == end and ((side == 1 and end > entry_ref) or (side == -1 and end < entry_ref)):
                    tp_price = end
            if tp_price is None:
                tp_price = entry_ref + side * tp1C["r_fallback"] * R
        fix_price = entry_ref + side * fixC["r"] * R if fixC["enabled"] else None
        jopp = n_bars + 1
        if oppC["enabled"]:
            arr = opp.get(symbol, {}).get(-side)
            if arr is not None and len(arr):
                kk = int(np.searchsorted(arr, ot[jf], side="right"))  # strictly after the entry bar opened
                if kk < len(arr):
                    jopp = bisect_left(ct, int(arr[kk]))
        level = None
        if lvlC["enabled"]:
            typ = r.type
            if typ == "third_buy":
                level = float(r.zs_zg)
            elif typ == "third_sell":
                level = float(r.zs_zd)
            elif typ in ("second_buy", "second_sell"):
                level = float(r.prior_extreme)
            if level is not None and level != level:
                level = None
        entry_buffer = buffer
        # ---- walk bars
        cur_stop = stop
        kind = "initial"
        arm_close_adverse = False
        pending = None
        tp_done = False
        legs = []  # (weight, price, fee_rate, leg open_time)
        rem = 1.0
        best = H[jf] if side == 1 else L[jf]
        worst = L[jf] if side == 1 else H[jf]
        hi_close = -1e300 if side == 1 else 1e300
        trail_armed = trC["enabled"] and trC["arm_r"] <= 0
        exit_bar = None
        exit_reason = None
        j = jf
        while j < n_bars:
            o_, h_, l_, c_ = O[j], H[j], L[j], Cl[j]
            if pending is not None and j > jf:
                p = o_ * (1 - side * slip)
                legs.append((rem, p, taker, ot[j]))
                exit_bar, exit_reason, rem = j, pending, 0.0
                break
            # extremes (bars the position was alive through, including this bar's range)
            if side == 1:
                if h_ > best:
                    best = h_
                if l_ < worst:
                    worst = l_
            else:
                if l_ < best:
                    best = l_
                if h_ > worst:
                    worst = h_
            # (2) stop: always taker + slippage
            raw = None
            if side == 1:
                if o_ <= cur_stop:
                    raw = o_
                elif l_ <= cur_stop:
                    raw = cur_stop
            else:
                if o_ >= cur_stop:
                    raw = o_
                elif h_ >= cur_stop:
                    raw = cur_stop
            if raw is not None:
                p = raw * (1 - side * slip)
                legs.append((rem, p, taker, ot[j]))
                exit_bar, rem = j, 0.0
                if kind == "initial":
                    exit_reason = "structure_stop"
                elif kind == "breakeven":
                    exit_reason = "breakeven_adverse" if arm_close_adverse else "breakeven_stop"
                elif kind == "ratchet":
                    exit_reason = "ratchet_stop"
                else:
                    exit_reason = "trail_stop"
                break
            # (3) targets
            if not (maker_entry and j == jf):
                hit = False
                if tp_price is not None and not tp_done:
                    raw = None
                    if side == 1:
                        raw = o_ if o_ >= tp_price else (tp_price if h_ >= tp_price else None)
                    else:
                        raw = o_ if o_ <= tp_price else (tp_price if l_ <= tp_price else None)
                    if raw is not None:
                        p = raw * (1 - side * slip)
                        legs.append((tp_frac, p, taker, ot[j]))
                        rem -= tp_frac
                        tp_done = True
                        hit = True
                if not hit and fix_price is not None:
                    # a resting maker order at the target: filled only when price trades strictly through it, at the target price
                    if (side == 1 and h_ > fix_price) or (side == -1 and l_ < fix_price):
                        legs.append((rem, fix_price, maker, ot[j]))
                        exit_bar, exit_reason, rem = j, "fixed_r", 0.0
                        break
            # (4) close review
            if j >= jopp:
                pending = "opposite_signal"
            elif biasC["enabled"] and (b_down[j] if side == 1 else b_up[j]):
                pending = "bias_1h"
            elif level is not None and ((side == 1 and c_ < level) or (side == -1 and c_ > level)):
                pending = "zhongshu_fail" if r.type in ("third_buy", "third_sell") else "swing_fail"
            elif timeC["enabled"] and (j - jf + 1) >= timeC["bars"]:
                pending = "time_stop"
            else:
                moved = False
                if beC["enabled"]:
                    armed = (cur_stop >= entry_ref) if side == 1 else (cur_stop <= entry_ref)
                    if not armed:
                        reach = entry_ref + side * beC["arm_r"] * R
                        if (side == 1 and h_ >= reach) or (side == -1 and l_ <= reach):
                            cur_stop = entry_ref
                            kind = "breakeven"
                            arm_close_adverse = (c_ < entry_ref) if side == 1 else (c_ > entry_ref)
                            moved = True
                    elif ratC["enabled"] and tick is not None:
                        ep = ndn[j] if side == 1 else nup[j]
                        if ep == ep and ((side == 1 and ep > cur_stop) or (side == -1 and ep < cur_stop)):
                            cand = _floor_tick(ep - side * entry_buffer, tick, side)
                            if (side == 1 and cand > cur_stop) or (side == -1 and cand < cur_stop):
                                cur_stop = cand
                                kind = "ratchet"
                                moved = True
                if trC["enabled"]:
                    if not trail_armed:
                        reach = entry_ref + side * trC["arm_r"] * R
                        if (side == 1 and h_ >= reach) or (side == -1 and l_ <= reach):
                            trail_armed = True
                    if side == 1:
                        hi_close = max(hi_close, c_)
                    else:
                        hi_close = min(hi_close, c_)
                    if trail_armed:
                        cand = hi_close - side * trC["mult"] * atr
                        if (side == 1 and cand > cur_stop) or (side == -1 and cand < cur_stop):
                            cur_stop = cand
                            kind = "trail"
            j += 1
        if exit_bar is None:  # data ended while holding
            p = Cl[n_bars - 1] * (1 - side * slip)
            legs.append((rem, p, taker, ot[n_bars - 1]))
            exit_bar, exit_reason, rem = n_bars - 1, "end_of_data", 0.0
        gross = 0.0
        fee = p_entry * fee_entry
        wsum = 0.0
        psum = 0.0
        for w, p, fr, _lt in legs:
            gross += w * side * (p - p_entry)
            fee += w * p * fr
            wsum += w
            psum += w * p
        gross_r = gross / R
        fee_r = fee / R
        fund_r, n_fund, fund_missing = funding_for_trade(
            fund, fmonths, symbol, side, R, ot[jf], ot[exit_bar], [x[3] for x in legs], [x[0] for x in legs], ot, O, Cl
        )
        att("filled", ot[exit_bar])
        rows.append(
            (
                r.signal_id,
                symbol,
                r.tf,
                r.type,
                side,
                r.time,
                ot[jf],
                p_entry,
                entry_ref,
                stop,
                R,
                ot[exit_bar],
                psum / wsum if wsum else float("nan"),
                gross_r,
                gross_r - fee_r - fund_r,
                fee_r,
                side * (best - p_entry) / R,
                side * (worst - p_entry) / R,
                exit_bar - jf,
                exit_reason,
                tp_done,
                aid,
                fund_r,
                gross_r - fee_r,
                n_fund,
                fund_missing,
            )
        )
    return rows, cnt


_COLS = [
    "signal_id", "symbol", "tf", "type", "side", "signal_time", "entry_time", "entry_price", "entry_reference",
    "stop_initial", "r_dist", "exit_time", "exit_price", "gross_r", "net_r", "fee_r", "mfe_r", "mae_r",
    "bars_held", "exit_reason", "tp1_hit",
    "attempt_id", "funding_r", "net_r_ex_funding", "n_funding", "funding_missing",
]
_ATT_COLS = ["attempt_id", "signal_id", "symbol", "tf", "type", "side", "signal_time", "status", "end_time"]
_G: dict = {}


def _work(symbol: str):
    cfg, market, sig_by, opp = _G["cfg"], _G["market"], _G["sig_by"], _G["opp"]
    mk = market.bars.get(symbol)
    sig = sig_by[symbol]
    att: list = []
    if mk is None:
        return [], {"signals": len(sig), "no_bars": len(sig)}, [
            (int(getattr(r, "attempt_id", -1)), r.signal_id, symbol, r.tf, r.type, int(r.side), int(r.time.value // 1000), "no_bars", int(r.time.value // 1000))
            for r in sig.itertuples(index=False)
        ]
    funding = (market.funding, market.funding_months) if market.funding is not None else None
    rows, cnt = simulate_symbol(
        cfg, symbol, sig, mk, market.bias_down.get(symbol, ((), (), ())), market.bi_new.get(symbol), opp, market.ticks.get(symbol),
        funding=funding, attempts_out=att,
    )
    return rows, cnt, att


def _us_to_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype("int64"), unit="us", utc=True).astype("datetime64[us, UTC]")


def simulate(cfg: SimConfig, market: Market, signals: pd.DataFrame, workers: int = 1, opp: dict | None = None, return_attempts: bool = False):
    """Return (trades DataFrame, counters), or (trades, attempts, counters) when return_attempts. Signals are simulated independently."""
    if opp is None:
        opp = opposite_times(cfg)
    sig_by = {s: g for s, g in signals.groupby("symbol", sort=False)}
    _G.update(cfg=cfg, market=market, sig_by=sig_by, opp=opp)
    names = sorted(sig_by, key=lambda s: -len(sig_by[s]))
    rows: list = []
    atts: list = []
    total: dict = {}

    def merge(res):
        rr, cc, aa = res
        rows.extend(rr)
        atts.extend(aa)
        for k, v in cc.items():
            total[k] = total.get(k, 0) + v

    if workers > 1:
        with Pool(workers) as pool:
            for res in pool.imap_unordered(_work, names, chunksize=1):
                merge(res)
    else:
        for n in names:
            merge(_work(n))
    df = pd.DataFrame(rows, columns=_COLS)
    if len(df):
        for c in ("signal_time",):
            df[c] = pd.to_datetime(df[c], utc=True).astype("datetime64[us, UTC]")
        for c in ("entry_time", "exit_time"):
            df[c] = _us_to_ts(df[c])
        df["sample"] = C.sample_of_series(df["signal_time"])
        df = df.sort_values(["signal_time", "symbol"], kind="stable").reset_index(drop=True)
    else:
        df["sample"] = []
    if not return_attempts:
        return df, total
    ad = pd.DataFrame(atts, columns=_ATT_COLS)
    if len(ad):
        ad["signal_time"] = _us_to_ts(ad["signal_time"])
        ad["end_time"] = _us_to_ts(ad["end_time"])
        ad["sample"] = C.sample_of_series(ad["signal_time"])
        ad = ad.sort_values(["attempt_id"], kind="stable").reset_index(drop=True) if (ad["attempt_id"] >= 0).all() else ad.sort_values(["signal_time", "symbol"], kind="stable").reset_index(drop=True)
    else:
        ad["sample"] = []
    return df, ad, total
