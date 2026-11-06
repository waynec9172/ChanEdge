"""Run one experiment YAML. Prints name, trade count and elapsed time only (never performance).

  python -m research.run <yaml> [--workers 6] [--registry PATH] [--neighbor] [--rerun "<reason>"] [--check]

--check recomputes in memory and compares with the stored results; it writes no registry row and no result file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research import common as C
from research.sim import ConfigError, SimConfig

MAX_EXPERIMENTS = 60
NB_MARK = "__nb_"


class RegistryError(Exception):
    exit_code = 3


def config_sha(resolved: dict) -> str:
    blob = json.dumps(resolved, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def core_sha(resolved: dict) -> str:
    """Same algorithm as config_sha, with name and description removed (identical settings -> identical core_sha)."""
    return config_sha({k: v for k, v in resolved.items() if k not in ("name", "description")})


def read_registry(path: Path) -> dict[str, set[str]]:
    """name -> set of config_sha seen."""
    seen: dict[str, set[str]] = {}
    if not Path(path).exists():
        return seen
    for line in Path(path).read_text().splitlines():
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 4 or cols[0] in ("time_utc", "---") or set(cols[0]) <= {"-", " "}:
            continue
        seen.setdefault(cols[1], set()).add(cols[2])
    return seen


def n_main(seen: dict) -> int:
    """Experiments counted against the limit: distinct registry names that are not neighbour tests."""
    return sum(1 for n in seen if NB_MARK not in n)


def check_registry(path: Path, name: str, sha: str, limit: int = MAX_EXPERIMENTS, rerun: str | None = None, require_rerun: bool = False) -> None:
    seen = read_registry(path)
    if name not in seen and NB_MARK not in name and n_main(seen) >= limit:
        raise RegistryError(f"experiment limit {limit} reached; refusing new name {name!r}")
    if name in seen and sha not in seen[name]:
        raise RegistryError(f"{name!r} already ran with a different config_sha; use a new name")
    if name in seen and require_rerun and not rerun:
        raise RegistryError(f"{name!r} is already in the registry; a legitimate re-run needs --rerun \"<reason>\"")


def append_registry(path: Path, name: str, sha: str, summary: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a") as fh:
        fh.write(f"| {stamp} | {name} | {sha} | {summary.replace('|', '/')} |\n")


def _exit_label(cfg: SimConfig, raw_exit: dict) -> str:
    ab = {"current": "cur", "ratchet_only": "rat"}
    if raw_exit.get("preset") and len(raw_exit) == 1:
        return raw_exit["preset"]
    if raw_exit.get("preset"):
        extra = cfg.exit["opposite_signal"]["tf"]
        return ab.get(raw_exit["preset"], raw_exit["preset"]) + (f"(opp{extra})" if extra != "15m" else "")
    parts = []
    for k, v in cfg.exit.items():
        if not v["enabled"]:
            continue
        if k == "fixed_r":
            parts.append(f"fx{v['r']}")
        elif k == "atr_trail":
            parts.append(f"atr{v['mult']}")
        elif k == "opposite_signal":
            parts.append("opp")
        elif k == "donchian_exit":
            parts.append(f"dcx{v['n']}")
        elif k == "time_barrier":
            parts.append(f"tb{v['bars']}")
        elif k == "row_target":
            parts.append("tp2")
        else:
            parts.append(k)
    return "+".join(parts) or "none"


def summarize(cfg: SimConfig, raw_exit: dict) -> str:
    f = cfg.filters
    filt = []
    if f["in_top20"]:
        filt.append("top20")
    if f["candidate_only"]:
        filt.append("cand")
    if f["gate_pass"]:
        filt.append("gate")
    if f["jev_min"] is not None:
        filt.append(f"jev>={f['jev_min']}")
    if f["max_cost_r"] is not None:
        filt.append(f"cost<={f['max_cost_r']:.2f}")
    if f["exclude_reemit"]:
        filt.append("noreemit")
    if f.get("htf_4h"):
        filt.append("htf4h")
    if f.get("vol_band"):
        filt.append("vol")
    if f.get("min_stop_atr") is not None:
        filt.append(f"ms>={f['min_stop_atr']}atr")
    if f.get("min_stop_pct") is not None:
        filt.append(f"ms>={f['min_stop_pct'] * 100:g}%")
    if f.get("exclude_tradfi"):
        filt.append("xtf")
    if f.get("dc_bias_4h"):
        filt.append("bias4h")
    if f.get("dc_not_in_zs4h"):
        filt.append("nozs4h")
    if f.get("delist_rule"):
        filt.append("delist")
    e = cfg.entry
    if e["mode"] == "market_next_open":
        mode = "market"
    elif e["mode"] == "limit":
        lim = e["limit"]
        kind = {"signal_close": "close", "defend_frac": f"mid{lim['offset']}", "stop_frac": f"stopfrac{lim['offset']}"}[lim["price"]]
        mode = f"limit:{kind},N{lim['valid_bars']}"
    else:
        mode = f"confirm:K{e['confirm']['bars']}"
    ex = _exit_label(cfg, raw_exit)
    sg = cfg.signals
    n = f" n={sg['donchian_n']}" if sg["donchian_n"] else ""
    if sg["source"] == "ict":
        from research.ict import params as ict_params

        n += f" ict={ict_params.table_key(sg['ict'])}"
    return (
        f"src={sg['source']} tf={sg['tf']}{n} types={len(sg['types'])} filt={','.join(filt) or 'none'} "
        f"entry={mode} stop={cfg.stop['buffer_atr']}atr exit={ex}"
    )


def compute(cfg: SimConfig, workers: int):
    from research import sim

    market = sim.load_market(bi_tf=cfg.signals["tf"] if cfg.signals["source"] == "chan" else "15m")
    signals = sim.select_signals(cfg, market)
    trades, attempts, counters = sim.simulate(cfg, market, signals, workers=workers, return_attempts=True)
    if cfg.filters["delist_rule"]:
        counters["delist_filtered"] = int(signals.attrs.get("delist_filtered", 0))
    return signals, trades, attempts, counters


def compare_frames(old: pd.DataFrame, new: pd.DataFrame) -> tuple[bool, float, str]:
    """(equal, max_abs_diff, note). Only columns both frames have are compared; numeric tolerance 1e-9.

    Every differing column is listed in the note (it no longer stops at the first one)."""
    if len(old) != len(new):
        return False, float("nan"), f"row count {len(old)} != {len(new)}"
    old = old.copy()
    new = new.copy()
    if "net_r_ex_funding" in new.columns and "net_r_ex_funding" not in old.columns and "net_r" in old.columns:
        old["net_r_ex_funding"] = old["net_r"]  # phase 0 files predate funding: their net_r has none deducted
        old = old.drop(columns=["net_r"])
        new = new.drop(columns=["net_r"])
    if "attempt_id" in old.columns and "attempt_id" in new.columns:
        keys = ["attempt_id"]
    else:
        keys = [k for k in ("signal_time", "symbol", "type") if k in old.columns and k in new.columns]
    old = old.sort_values(keys, kind="stable").reset_index(drop=True)
    new = new.sort_values(keys, kind="stable").reset_index(drop=True)
    worst = 0.0
    diffs: list[str] = []
    nan_seen = False
    for c in [c for c in old.columns if c in new.columns]:
        a, b = old[c], new[c]
        if pd.api.types.is_float_dtype(a) or pd.api.types.is_integer_dtype(a) and not pd.api.types.is_bool_dtype(a):
            av, bv = a.to_numpy(float), b.to_numpy(float)
            both_nan = np.isnan(av) & np.isnan(bv)
            d = np.where(both_nan, 0.0, np.abs(av - bv))
            if np.isnan(d).any():
                diffs.append(f"column {c}: NaN mismatch")
                nan_seen = True
                continue
            m = float(np.max(d)) if len(d) else 0.0
            if m > 1e-9:
                diffs.append(f"column {c}: max abs diff {m:.3e}")
            worst = max(worst, m)
        else:
            if not (a.astype(object).fillna("<na>").to_numpy() == b.astype(object).fillna("<na>").to_numpy()).all():
                diffs.append(f"column {c}: values differ")
    if nan_seen:
        worst = float("nan")
    if diffs:
        return False, worst, f"{len(diffs)} column(s) differ: " + "; ".join(diffs)
    return True, worst, ""


def do_check(cfg: SimConfig, workers: int) -> int:
    out = C.CACHE / "results"
    old_path = out / f"{cfg.name}.parquet"
    if not old_path.exists():
        print(f"CHECK FAIL {cfg.name}: no stored results", file=sys.stderr)
        return 4
    _signals, trades, attempts, _cnt = compute(cfg, workers)
    ok, worst, note = compare_frames(pd.read_parquet(old_path), trades)
    ap = out / f"{cfg.name}.attempts.parquet"
    if ok and ap.exists():
        ok, w2, note = compare_frames(pd.read_parquet(ap), attempts)
        worst = max(worst, w2) if w2 == w2 else w2
    line = f"CHECK {'OK' if ok else 'FAIL'} {cfg.name} trades={len(trades)} attempts={len(attempts)} max_abs_diff={worst:.3e}"
    logs = C.CACHE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "checks.log", "a") as fh:
        fh.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {line}{' ' + note if note else ''}\n")
    print(line)
    return 0 if ok else 4


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.run")
    p.add_argument("yaml")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--registry", default=str(C.OUT / "registry.md"))
    p.add_argument("--neighbor", action="store_true")
    p.add_argument("--rerun", default=None, metavar="REASON")
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)
    path = Path(a.yaml)
    try:
        raw = C.read_yaml(path)
        cfg = SimConfig.from_dict(raw)
        if cfg.name != path.stem:
            raise ConfigError(f"name {cfg.name!r} must equal the file name {path.stem!r}")
        is_nb_name = NB_MARK in cfg.name
        if is_nb_name != a.neighbor:
            raise ConfigError("neighbour tests need both the '__nb_' name and --neighbor" if is_nb_name else "--neighbor needs a '__nb_' name")
        if a.neighbor:
            if path.resolve().parent.name != "neighbors":
                raise ConfigError("neighbour YAMLs live in research/experiments/neighbors/")
            if not cfg.description.startswith("NEIGHBOR of "):
                raise ConfigError("neighbour description must start with 'NEIGHBOR of '")
    except (ConfigError, KeyError, TypeError, ValueError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    resolved = cfg.resolved()
    sha = config_sha(resolved)
    if a.check:
        return do_check(cfg, a.workers)
    registry = Path(a.registry)
    try:
        check_registry(registry, cfg.name, sha, rerun=a.rerun, require_rerun=True)
    except RegistryError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return RegistryError.exit_code
    t0 = time.time()
    signals, trades, attempts, counters = compute(cfg, a.workers)
    elapsed = time.time() - t0
    out = C.CACHE / "results"
    out.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(out / f"{cfg.name}.parquet")
    attempts.to_parquet(out / f"{cfg.name}.attempts.parquet")
    kind = "rerun" if a.rerun else ("neighbor" if a.neighbor else "new")
    meta = {
        "resolved": resolved,
        "config_sha": sha,
        "core_sha": core_sha(resolved),
        "kind": kind,
        "n_signals": int(len(signals)),
        "n_trades": int(len(trades)),
        "counters": counters,
        "status_counts": {k: int(v) for k, v in attempts["status"].value_counts().items()},
        "funding_missing": int(trades["funding_missing"].sum()) if len(trades) else 0,
        "elapsed_s": round(elapsed, 2),
    }
    (out / f"{cfg.name}.json").write_text(json.dumps(meta, indent=2, default=str))
    summary = summarize(cfg, raw.get("exit", {}))
    if a.neighbor:
        summary = cfg.description.split("\n")[0] + "; " + summary
    if a.rerun:
        summary = f"RERUN({a.rerun}): " + summary
    append_registry(registry, cfg.name, sha, summary)
    logs = C.CACHE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "runs.log", "a") as fh:
        fh.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {cfg.name} {sha} {kind}\n")
    print(f"{cfg.name}: trades={len(trades)} elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
