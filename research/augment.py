"""Cache additions for phase 1 (not experiments): HTF bi events, signals_{tf}_aug, funding.

  python -m research.augment build [--workers 6] [--only bi,sig,funding]

Outputs under research/cache/: bi_events_{1h,4h}.parquet, signals_{15m,1h,4h}_aug.parquet (same rows/order as the
signal tables; columns symbol,type,time,atr15_pct,tp_up_end,tp_down_end), funding.parquet, funding_months.parquet.
Log: research/cache/logs/augment.log (one line per symbol, last line `# done ...`).
"""

from __future__ import annotations

import argparse
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research import common as C
from research import donchian

FUNDING_DIR = C.ROOT / "data" / "futures" / "um" / "monthly" / "fundingRate"


def time_ns(series: pd.Series) -> np.ndarray:
    """tz-aware datetime Series -> int64 nanoseconds since epoch (UTC)."""
    return series.dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[ns]").to_numpy().astype("int64")


def atr15_pct_at(close_time_ns: np.ndarray, high, low, close, t_ns: np.ndarray) -> np.ndarray:
    """Wilder ATR(14) / close of the 15m bar whose close_time == t (NaN when there is no such bar)."""
    pct = donchian.wilder_atr_np(high, low, close, 14) / close
    idx = np.searchsorted(close_time_ns, t_ns)
    idx_c = np.minimum(idx, len(close_time_ns) - 1)
    ok = (idx < len(close_time_ns)) & (close_time_ns[idx_c] == t_ns)
    return np.where(ok, pct[idx_c], np.nan)


def last_bi_ends(ev_times_ns: np.ndarray, ev_dir: np.ndarray, ev_end: np.ndarray, t_ns: np.ndarray):
    """For each t: (end of the latest up bi, end of the latest down bi) with confirm_time <= t (replace events applied)."""
    res = []
    for d in (1, -1):
        m = ev_dir == d
        times, ends = ev_times_ns[m], ev_end[m]
        idx = np.searchsorted(times, t_ns, side="right") - 1
        res.append(np.where(idx >= 0, ends[np.maximum(idx, 0)] if len(ends) else np.nan, np.nan))
    return res[0], res[1]


def _job(args):
    symbol, times, do_bi = args
    t0 = time.time()
    try:
        from research import signals

        out = {"symbol": symbol}
        b15 = C.load_bars_df(symbol, "15m")
        ct = time_ns(b15["close_time"])
        h, lo, c = (b15[x].to_numpy(float) for x in ("high", "low", "close"))
        out["atr15"] = {tf: atr15_pct_at(ct, h, lo, c, t) for tf, t in times.items()}
        if do_bi:
            ev = {}
            for tf in ("1h", "4h"):
                ev[tf] = signals.walk(signals.closed_bars(tf, symbol), tf).bi_events
            out["events"] = ev
        out["elapsed"] = time.time() - t0
        return out
    except Exception as exc:
        import traceback

        return {"symbol": symbol, "error": f"{exc!r}\n{traceback.format_exc()}"}


def build_bi_sig(workers: int, log) -> list[str]:
    tables = {tf: pd.read_parquet(C.CACHE / f"signals_{tf}.parquet", columns=["symbol", "type", "time"]) for tf in C.TFS}
    rows = {tf: tables[tf].groupby("symbol", sort=False).indices for tf in C.TFS}
    t_ns = {tf: time_ns(tables[tf]["time"]) for tf in C.TFS}
    aug = {
        tf: {
            "atr15_pct": np.full(len(tables[tf]), np.nan),
            "tp_up_end": np.full(len(tables[tf]), np.nan),
            "tp_down_end": np.full(len(tables[tf]), np.nan),
        }
        for tf in C.TFS
    }
    syms = sorted(set(C.union_symbols()))
    jobs = []
    for s in syms:
        times = {tf: t_ns[tf][rows[tf][s]] for tf in C.TFS if s in rows[tf]}
        jobs.append((s, times, True))
    events = {"1h": [], "4h": []}
    failed = []
    t0 = time.time()
    with Pool(workers, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(_job, jobs):
            s = res["symbol"]
            if "error" in res:
                failed.append(s)
                log.write(f"FAIL {s} {res['error']}\n")
                log.flush()
                continue
            for tf, v in res["atr15"].items():
                aug[tf]["atr15_pct"][rows[tf][s]] = v
            for tf in ("1h", "4h"):
                ev = res["events"][tf]
                ev.insert(0, "symbol", s)
                events[tf].append(ev)
                if s in rows[tf] and len(ev):
                    up, dn = last_bi_ends(time_ns(ev["confirm_time"]), ev["direction"].to_numpy(), ev["end_price"].to_numpy(float), t_ns[tf][rows[tf][s]])
                    aug[tf]["tp_up_end"][rows[tf][s]] = up
                    aug[tf]["tp_down_end"][rows[tf][s]] = dn
            log.write(f"{s} elapsed={res['elapsed']:.1f}s total={time.time() - t0:.0f}s\n")
            log.flush()
    if failed:
        return failed
    for tf in ("1h", "4h"):
        df = pd.concat([e for e in events[tf] if len(e)], ignore_index=True)
        df.to_parquet(C.CACHE / f"bi_events_{tf}.parquet")
        log.write(f"bi_events_{tf} rows={len(df)}\n")
    full15 = pd.read_parquet(C.CACHE / "signals_15m.parquet", columns=["last_up_end", "last_down_end"])
    aug["15m"]["tp_up_end"] = full15["last_up_end"].to_numpy(float)
    aug["15m"]["tp_down_end"] = full15["last_down_end"].to_numpy(float)
    for tf in C.TFS:
        d = tables[tf][["symbol", "type", "time"]].copy()
        for k, v in aug[tf].items():
            d[k] = v
        d.to_parquet(C.CACHE / f"signals_{tf}_aug.parquet")
        log.write(f"signals_{tf}_aug rows={len(d)} atr15_pct_nan={int(np.isnan(aug[tf]['atr15_pct']).sum())}\n")
    return failed


def funding_symbol(symbol: str) -> str:
    return symbol.replace("/", "")  # BTC/USDT -> BTCUSDT


def round_calc_time_us(calc_time_ms: pd.Series) -> pd.Series:
    """calc_time (ms, sometimes +1 ms) rounded to the nearest minute, as int64 microseconds."""
    ms = calc_time_ms.astype("int64").to_numpy()
    return pd.Series(np.round(ms / 60000.0).astype("int64") * 60_000_000, index=calc_time_ms.index)


def build_funding(log) -> list[str]:
    frames, months, failed = [], [], []
    for s in C.union_symbols():
        d = FUNDING_DIR / funding_symbol(s)
        if not d.is_dir():
            failed.append(s)
            log.write(f"FAIL {s} no funding folder\n")
            continue
        parts = []
        for f in sorted(d.glob(f"{d.name}-fundingRate-*.csv")):
            mo = f.stem.rsplit("-fundingRate-", 1)[1]
            months.append((s, mo))
            parts.append(pd.read_csv(f))
        df = pd.concat(parts, ignore_index=True)
        t = round_calc_time_us(df["calc_time"])
        frames.append(
            pd.DataFrame(
                {
                    "symbol": s,
                    "funding_time": pd.to_datetime(t, unit="us", utc=True).astype("datetime64[us, UTC]"),
                    "rate": df["last_funding_rate"].astype(float),
                    "interval_h": df["funding_interval_hours"].astype("int8"),
                }
            )
        )
        log.write(f"funding {s} rows={len(df)} files={len(parts)}\n")
    out = pd.concat(frames, ignore_index=True).sort_values(["symbol", "funding_time"], kind="stable").reset_index(drop=True)
    out = out.drop_duplicates(["symbol", "funding_time"], keep="last").reset_index(drop=True)
    out.to_parquet(C.CACHE / "funding.parquet")
    pd.DataFrame(months, columns=["symbol", "month"]).to_parquet(C.CACHE / "funding_months.parquet")
    log.write(f"funding rows={len(out)} symbols={out['symbol'].nunique()}\n")
    return failed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.augment")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--only", default="bi,sig,funding")
    a = p.parse_args(argv)
    only = set(a.only.split(","))
    logs = C.CACHE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    failed: list[str] = []
    with open(logs / "augment.log", "a") as log:
        log.write(f"# build only={sorted(only)} workers={a.workers}\n")
        if only & {"bi", "sig"}:
            failed += build_bi_sig(a.workers, log)
        if "funding" in only:
            failed += build_funding(log)
        log.write(f"# done total={time.time() - t0:.0f}s failed={failed}\n")
    if failed:
        print("FAILED:", failed, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
