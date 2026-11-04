"""Run one experiment YAML. Prints name, trade count and elapsed time only (never performance)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from research import common as C
from research.sim import ConfigError, SimConfig

MAX_EXPERIMENTS = 60


class RegistryError(Exception):
    exit_code = 3


def config_sha(resolved: dict) -> str:
    blob = json.dumps(resolved, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


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


def check_registry(path: Path, name: str, sha: str, limit: int = MAX_EXPERIMENTS) -> None:
    seen = read_registry(path)
    if name not in seen and len(seen) >= limit:
        raise RegistryError(f"experiment limit {limit} reached; refusing new name {name!r}")
    if name in seen and sha not in seen[name]:
        raise RegistryError(f"{name!r} already ran with a different config_sha; use a new name")


def append_registry(path: Path, name: str, sha: str, summary: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a") as fh:
        fh.write(f"| {stamp} | {name} | {sha} | {summary.replace('|', '/')} |\n")


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
    mode = {"market_next_open": "market", "limit": "limit", "confirm": "confirm"}[cfg.entry["mode"]]
    if raw_exit.get("preset") and len(raw_exit) == 1:
        ex = raw_exit["preset"]
    else:
        ex = "+".join(k for k, v in cfg.exit.items() if v["enabled"]) or "none"
    sg = cfg.signals
    n = f" n={sg['donchian_n']}" if sg["donchian_n"] else ""
    return (
        f"src={sg['source']} tf={sg['tf']}{n} types={len(sg['types'])} filt={','.join(filt) or 'none'} "
        f"entry={mode} stop={cfg.stop['buffer_atr']}atr exit={ex}"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.run")
    p.add_argument("yaml")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--registry", default=str(C.OUT / "registry.md"))
    a = p.parse_args(argv)
    path = Path(a.yaml)
    try:
        raw = C.read_yaml(path)
        cfg = SimConfig.from_dict(raw)
        if cfg.name != path.stem:
            raise ConfigError(f"name {cfg.name!r} must equal the file name {path.stem!r}")
    except (ConfigError, KeyError, TypeError, ValueError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    resolved = cfg.resolved()
    sha = config_sha(resolved)
    registry = Path(a.registry)
    try:
        check_registry(registry, cfg.name, sha)
    except RegistryError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return RegistryError.exit_code
    from research import sim

    t0 = time.time()
    market = sim.load_market()
    signals = sim.select_signals(cfg, market)
    trades, counters = sim.simulate(cfg, market, signals, workers=a.workers)
    elapsed = time.time() - t0
    out = C.CACHE / "results"
    out.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(out / f"{cfg.name}.parquet")
    meta = {
        "resolved": resolved,
        "config_sha": sha,
        "n_signals": int(len(signals)),
        "n_trades": int(len(trades)),
        "counters": counters,
        "elapsed_s": round(elapsed, 2),
    }
    (out / f"{cfg.name}.json").write_text(json.dumps(meta, indent=2, default=str))
    append_registry(registry, cfg.name, sha, summarize(cfg, raw.get("exit", {})))
    print(f"{cfg.name}: trades={len(trades)} elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
