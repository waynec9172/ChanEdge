"""ICT P1 parameters. Any change to generation logic must bump ICT_VERSION (it is part of table_key / config_sha)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date

ICT_VERSION = "ict-p1.0"
DEFAULTS: dict = {
    "version": ICT_VERSION, "setup_tf": "1h", "swing_n": 2, "atr_n": 14, "fvg_k": 0.5,
    "ote_lo": 0.618, "ote_hi": 0.786, "anchor": "causal", "tp2_ext": 0.618, "zone_valid_bars": 24,
    "use_htf": True, "htf_ema": 50,
    "use_expansion": True, "exp_tr_atr": 1.5, "exp_vol_mult": 1.5, "exp_vol_n": 20,
    "use_fresh": True,
    "use_ltf": True, "ltf_bars": 16, "wick_frac": 0.5,
    "use_sweep": True, "sweep_bars": 24,
    "use_session": True, "session_start_h": 7, "session_end_h": 21, "weekdays_only": True,
    "use_funding": True, "funding_block": 0.0005,
    "warmup_until": "2024-01-15",
    "random": None,
}

_INT = ("swing_n", "atr_n", "zone_valid_bars", "htf_ema", "exp_vol_n", "ltf_bars", "sweep_bars", "session_start_h", "session_end_h")
_NUM = ("fvg_k", "ote_lo", "ote_hi", "tp2_ext", "exp_tr_atr", "exp_vol_mult", "wick_frac", "funding_block")
_BOOL = ("use_htf", "use_expansion", "use_fresh", "use_ltf", "use_sweep", "use_session", "weekdays_only", "use_funding")


def validate(d: dict) -> dict:
    from research.sim import ConfigError

    if not isinstance(d, dict):
        raise ConfigError("signals.ict must be a mapping")
    if set(d) != set(DEFAULTS):
        raise ConfigError(f"signals.ict keys differ: missing {sorted(set(DEFAULTS) - set(d))}, extra {sorted(set(d) - set(DEFAULTS))}")
    for k in _INT:
        if not isinstance(d[k], int) or isinstance(d[k], bool):
            raise ConfigError(f"signals.ict.{k} must be an int")
    for k in _NUM:
        if isinstance(d[k], bool) or not isinstance(d[k], (int, float)) or not math.isfinite(d[k]):
            raise ConfigError(f"signals.ict.{k} must be a finite number")
    for k in _BOOL:
        if not isinstance(d[k], bool):
            raise ConfigError(f"signals.ict.{k} must be a bool")
    if d["version"] != ICT_VERSION:
        raise ConfigError(f"signals.ict.version must be {ICT_VERSION}")
    if d["setup_tf"] not in ("1h", "15m"):
        raise ConfigError("signals.ict.setup_tf must be 1h or 15m")
    if d["swing_n"] < 1 or d["atr_n"] < 2 or not d["fvg_k"] > 0:
        raise ConfigError("signals.ict: swing_n >= 1, atr_n >= 2, fvg_k > 0")
    if not 0 < d["ote_lo"] < d["ote_hi"] < 1:
        raise ConfigError("signals.ict: 0 < ote_lo < ote_hi < 1")
    if d["anchor"] not in ("causal", "confirmed"):
        raise ConfigError("signals.ict.anchor must be causal or confirmed")
    for k in ("zone_valid_bars", "ltf_bars", "sweep_bars", "exp_vol_n"):
        if d[k] < 1:
            raise ConfigError(f"signals.ict.{k} must be >= 1")
    if not 0 <= d["session_start_h"] < d["session_end_h"] <= 24:
        raise ConfigError("signals.ict: 0 <= session_start_h < session_end_h <= 24")
    if not d["funding_block"] > 0:
        raise ConfigError("signals.ict.funding_block must be > 0")
    try:
        if not isinstance(d["warmup_until"], str):
            raise ValueError
        date.fromisoformat(d["warmup_until"])
    except ValueError:
        raise ConfigError("signals.ict.warmup_until must be an ISO date string") from None
    r = d["random"]
    if r is not None:
        if not isinstance(r, dict) or set(r) != {"seed", "match"} or not isinstance(r["seed"], int) or isinstance(r["seed"], bool) or not isinstance(r["match"], str):
            raise ConfigError("signals.ict.random must be null or {seed:int, match:str}")
    return dict(d)


def table_key(d: dict) -> str:
    blob = json.dumps(validate(d), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]
