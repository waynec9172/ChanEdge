"""Read-only report on a results parquet. Default: in-sample only. --oos needs a log entry and works once per name."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research import common as C

OOS_LOG = C.OUT / "oos_log.md"


class OosRefused(Exception):
    exit_code = 3


def oos_names(log: Path) -> set[str]:
    names: set[str] = set()
    if Path(log).exists():
        for line in Path(log).read_text().splitlines():
            if line.startswith("|"):
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cols) >= 3:
                    names.add(cols[1])
    return names


def log_oos(name: str, command: str, log: Path = OOS_LOG) -> None:
    """Refuse a second OOS look at the same experiment, then append before anything is shown."""
    if name in oos_names(log):
        raise OosRefused(f"{name} already has an OOS entry in {log}; each experiment is looked at once")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(log, "a") as fh:
        fh.write(f"| {stamp} | {name} | {command.replace('|', '/')} |\n")


def metrics(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0}
    pos = df.loc[df["net_r"] > 0, "net_r"].sum()
    neg = -df.loc[df["net_r"] < 0, "net_r"].sum()
    q = lambda s: [float(x) for x in np.percentile(s, [25, 50, 75])]
    return {
        "n": n,
        "mean_net_r": float(df["net_r"].mean()),
        "mean_gross_r": float(df["gross_r"].mean()),
        "mean_fee_r": float(df["fee_r"].mean()),
        "win_rate": float((df["net_r"] > 0).mean()),
        "pf": float(pos / neg) if neg > 0 else float("inf"),
        "sum_net_r": float(df["net_r"].sum()),
        "median_bars_held": float(df["bars_held"].median()),
        "mfe_q": q(df["mfe_r"]),
        "mae_q": q(df["mae_r"]),
    }


def fmt(m: dict) -> str:
    if m["n"] == 0:
        return "n=0"
    return (
        f"n={m['n']} net={m['mean_net_r']:+.4f} gross={m['mean_gross_r']:+.4f} fee={m['mean_fee_r']:.4f} "
        f"win={m['win_rate']:.3f} pf={m['pf']:.3f} sum={m['sum_net_r']:+.1f} med_bars={m['median_bars_held']:.0f} "
        f"mfe25/50/75={m['mfe_q'][0]:.2f}/{m['mfe_q'][1]:.2f}/{m['mfe_q'][2]:.2f} "
        f"mae25/50/75={m['mae_q'][0]:.2f}/{m['mae_q'][1]:.2f}/{m['mae_q'][2]:.2f}"
    )


def select_sample(df: pd.DataFrame, oos: bool) -> pd.DataFrame:
    return df[df["sample"] == ("OOS" if oos else "IS")]


def render(name: str, df: pd.DataFrame, by: str | None, oos: bool) -> list[str]:
    label = (
        f"sample=OOS {C.OOS_START}→{C.OOS_END}" if oos else f"sample=IS {C.IS_START.isoformat()}→{C.IS_END.isoformat()}"
    ).replace("2025-07-01→", "2025-07-01→")
    lines = [label, f"== {name}", fmt(metrics(df))]
    if len(df):
        dist = df["exit_reason"].value_counts()
        lines.append("exit_reason: " + ", ".join(f"{k}={v}" for k, v in dist.items()))
    if by and len(df):
        key = {
            "type": df["type"],
            "exit_reason": df["exit_reason"],
            "tf": df["tf"],
            "month": df["signal_time"].dt.strftime("%Y-%m"),
        }[by]
        for k, g in df.groupby(key, sort=True):
            lines.append(f"  {by}={k}: {fmt(metrics(g))}")
    return lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.report")
    p.add_argument("names", nargs="+")
    p.add_argument("--by", choices=["type", "exit_reason", "tf", "month"])
    p.add_argument("--oos", action="store_true")
    a = p.parse_args(argv)
    out: list[str] = []
    for name in a.names:
        path = C.CACHE / "results" / f"{name}.parquet"
        if not path.exists():
            print(f"no results for {name}", file=sys.stderr)
            return 2
        if a.oos:
            try:
                log_oos(name, "python -m research.report " + " ".join(sys.argv[1:] if argv is None else argv))
            except OosRefused as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return OosRefused.exit_code
        out.extend(render(name, select_sample(pd.read_parquet(path), a.oos), a.by, a.oos))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
