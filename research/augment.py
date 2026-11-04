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


VISION = "https://data.binance.vision/data/futures/um"
DL_DIR = C.CACHE / "vision_dl"
FUND_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]
FETCH_FIRST, FETCH_LAST = "2025-07", "2026-10"


def month_key(ts: pd.Timestamp) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def months_between(a: str, b: str) -> list[str]:
    out, (y, m) = [], (int(a[:4]), int(a[5:7]))
    while (y, m) <= (int(b[:4]), int(b[5:7])):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def shift_month(mo: str, k: int) -> str:
    n = int(mo[:4]) * 12 + int(mo[5:7]) - 1 + k
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def month_start_us(mo: str) -> int:
    return int(pd.Timestamp(f"{mo}-01", tz="UTC").value // 1000)


def validate_funding_zip(zip_bytes: bytes, checksum_text: str, member: str, lo_us: int, hi_us: int) -> pd.DataFrame:
    """Validate an untrusted vision funding zip; return its rows or raise ValueError.

    Checks: sha256 equals the first field of the CHECKSUM file; exactly one member named `member` (no path);
    columns are exactly calc_time, funding_interval_hours, last_funding_rate; every calc_time lies in [lo_us, hi_us) (microseconds).
    """
    import hashlib
    import io
    import zipfile

    want = checksum_text.split()[0].strip().lower() if checksum_text.strip() else ""
    if hashlib.sha256(zip_bytes).hexdigest() != want:
        raise ValueError("sha256 mismatch")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"bad zip: {exc}") from exc
    names = zf.namelist()
    if len(names) != 1 or names[0] != member or "/" in names[0] or "\\" in names[0] or ".." in names[0]:
        raise ValueError(f"unexpected members {names!r}")
    df = pd.read_csv(io.BytesIO(zf.read(names[0])))
    if list(df.columns) != FUND_COLS:
        raise ValueError(f"unexpected columns {list(df.columns)!r}")
    if not len(df):
        raise ValueError("empty file")
    t_us = df["calc_time"].astype("int64") * 1000
    if (t_us < lo_us).any() or (t_us >= hi_us).any():
        raise ValueError("calc_time outside the expected period")
    return df


def _http_get(url: str) -> bytes | None:
    """Bytes of the URL, or None on 404 / network failure (after 2 retries)."""
    import urllib.error
    import urllib.request

    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ChanEdge-research"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except Exception as exc:  # network down, timeout, ...
            last = exc
    raise ConnectionError(repr(last))


def vision_url(kind: str, sym: str, period: str) -> str:
    """Download URL of one funding zip; the path segments are percent-encoded (non-ASCII symbols such as 币安人生USDT)."""
    from urllib.parse import quote

    return f"{VISION}/{kind}/fundingRate/{quote(sym, safe='')}/{quote(f'{sym}-fundingRate-{period}', safe='')}.zip"


def _fetch_one(kind: str, sym: str, period: str, lo_us: int, hi_us: int):
    """Download + validate one monthly/daily file into vision_dl. Returns (ok, reason); reason 'cached' = file already on disk."""
    name = f"{sym}-fundingRate-{period}"
    if (DL_DIR / kind / sym / f"{name}.csv").exists():
        return True, "cached"
    base = vision_url(kind, sym, period)
    try:
        z = _http_get(base)
        if z is None:
            return False, "404"
        ck = _http_get(base + ".CHECKSUM")
        if ck is None:
            return False, "no checksum"
        df = validate_funding_zip(z, ck.decode("utf-8", "replace"), name + ".csv", lo_us, hi_us)
    except ConnectionError as exc:
        return False, f"network {exc}"
    except ValueError as exc:
        return False, f"rejected: {exc}"
    d = DL_DIR / kind / sym
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / f"{name}.csv", index=False)
    return True, ""


def symbol_bar_range(symbol: str):
    """(first open_time, last open_time) of the symbol's 15m bars as Timestamps (UTC), or None."""
    import pyarrow.parquet as pq

    p = C.bars_path(symbol, "15m")
    if not p.exists():
        return None
    t = pq.read_table(p, columns=["open_time"]).to_pandas()["open_time"]
    if not len(t):
        return None
    return pd.Timestamp(t.min()).tz_convert("UTC") if pd.Timestamp(t.min()).tzinfo else pd.Timestamp(t.min(), tz="UTC"), (
        pd.Timestamp(t.max()).tz_convert("UTC") if pd.Timestamp(t.max()).tzinfo else pd.Timestamp(t.max(), tz="UTC")
    )


def fetch_funding() -> int:
    """Plan 8.7 A: try to download missing (symbol, month) funding files (2025-07..2026-10) from Binance vision."""
    from concurrent.futures import ThreadPoolExecutor

    logs = C.CACHE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    DL_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"local": 0, "dl_monthly": 0, "dl_daily": 0, "missing": 0, "cached": 0}
    targets = []
    with open(logs / "funding_fetch.log", "a") as log:
        log.write("# fetch-funding start\n")
        for s in C.union_symbols():
            rng = symbol_bar_range(s)
            fs = funding_symbol(s)
            if rng is None:
                continue
            for mo in months_between(FETCH_FIRST, FETCH_LAST):
                if month_key(rng[1]) < mo or month_key(rng[0]) > mo:
                    continue
                if (FUNDING_DIR / fs / f"{fs}-fundingRate-{mo}.csv").exists():
                    counts["local"] += 1
                    continue
                targets.append((s, fs, mo, rng[1]))
        log.write(f"# targets={len(targets)} local={counts['local']}\n")
        # daily availability probe (one file, plan 8.7 A.3)
        daily_ok = False
        try:
            daily_ok = _http_get(f"{VISION}/daily/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-10-01.zip") is not None
        except ConnectionError as exc:
            log.write(f"# daily probe network failure {exc}\n")
        if not daily_ok:
            log.write("# daily not available\n")

        def work(t):
            s, fs, mo, last_open = t
            lo, hi = month_start_us(mo), month_start_us(shift_month(mo, 1))
            ok, why = _fetch_one("monthly", fs, mo, lo, hi)
            if ok:
                return t, "dl_monthly", why
            if not daily_ok:
                return t, "missing", f"monthly {why}"
            last_day = min(last_open.day, 31)
            got = 0
            n_cached = 0
            for dday in range(1, last_day + 1):
                day = f"{mo}-{dday:02d}"
                dlo = int(pd.Timestamp(day, tz="UTC").value // 1000)
                ok, why2 = _fetch_one("daily", fs, day, dlo, dlo + 86_400_000_000)
                if not ok:
                    return t, "missing", f"monthly {why}; daily {day} {why2}; got {got}/{last_day} days"
                got += 1
                n_cached += why2 == "cached"
            return t, "dl_daily", f"{got} days" + (" cached" if n_cached == got else "")

        with ThreadPoolExecutor(max_workers=4) as ex:
            for t, src, why in ex.map(work, targets):
                counts[src] += 1
                counts["cached"] += why.endswith("cached")
                log.write(f"{t[1]} {t[2]} {src} {why}\n")
                log.flush()
        log.write(f"# done dl_monthly={counts['dl_monthly']} dl_daily={counts['dl_daily']} missing={counts['missing']} cached={counts['cached']}\n")
    print(f"fetch-funding: {counts}")
    return 0


def _read_vision_month(sym: str, mo: str):
    """(DataFrame, source) from vision_dl for a (symbol, month): monthly file first, then a complete set of daily files."""
    m = DL_DIR / "monthly" / sym / f"{sym}-fundingRate-{mo}.csv"
    if m.exists():
        return pd.read_csv(m), "dl_monthly"
    d = DL_DIR / "daily" / sym
    if d.is_dir():
        files = sorted(d.glob(f"{sym}-fundingRate-{mo}-*.csv"))
        if files:
            return pd.concat([pd.read_csv(f) for f in files], ignore_index=True), "dl_daily"
    return None, None


def impute_month_events(mo: str, hist_abs: np.ndarray, market_abs: np.ndarray, interval_h: int | None, last_close_us: int):
    """Imputed funding events for one missing month (plan 8.7 B.2).

    hist_abs = |rate| of the symbol's REAL events in the 3 calendar months before `mo`; market_abs = same for all symbols.
    Returns (event_times_us list, rate, interval_h, basis) or None when no rate can be found.
    """
    if len(hist_abs):
        rate, basis = float(np.median(hist_abs)), "own"
    elif len(market_abs):
        rate, basis = float(np.median(market_abs)), "market"
    else:
        return None
    h = int(interval_h) if interval_h else 8
    start, end = month_start_us(mo), month_start_us(shift_month(mo, 1))
    step = h * 3_600_000_000
    ev = []
    t = start
    while t < end and t <= last_close_us:
        ev.append(t)
        t += step
    return ev, rate, h, basis


def build_funding(log) -> list[str]:
    frames, months, failed = [], [], []
    ranges = {}
    for s in C.union_symbols():
        fs = funding_symbol(s)
        d = FUNDING_DIR / fs
        parts = []
        have: dict[str, str] = {}
        if d.is_dir():
            for f in sorted(d.glob(f"{fs}-fundingRate-*.csv")):
                mo = f.stem.rsplit("-fundingRate-", 1)[1]
                have[mo] = "local"
                parts.append(pd.read_csv(f))
        for mo in months_between(FETCH_FIRST, FETCH_LAST):
            if mo in have:
                continue
            df_dl, src = _read_vision_month(fs, mo)
            if df_dl is not None:
                have[mo] = src
                parts.append(df_dl)
        rng = symbol_bar_range(s)
        ranges[s] = rng
        if not parts and rng is None:
            failed.append(s)
            log.write(f"FAIL {s} no funding data and no bars\n")
            continue
        for mo, src in have.items():
            months.append((s, mo, src, ""))
        if parts:
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
        log.write(f"funding {s} rows={sum(len(x) for x in parts)} files={len(parts)}\n")
    real = pd.concat(frames, ignore_index=True).sort_values(["symbol", "funding_time"], kind="stable").reset_index(drop=True)
    real = real.drop_duplicates(["symbol", "funding_time"], keep="last").reset_index(drop=True)
    real["imputed"] = False
    real["basis"] = ""
    # ---- imputation of months without any source (plan 8.7 B.2)
    real["_mo"] = real["funding_time"].dt.strftime("%Y-%m")
    real["_abs"] = real["rate"].abs()
    by_sym = {s: g for s, g in real.groupby("symbol", sort=False)}
    have_months = {}
    for s, mo, src, _b in months:
        have_months.setdefault(s, set()).add(mo)
    imputed_frames = []
    n_imp_months = {"own": 0, "market": 0}
    for s in C.union_symbols():
        rng = ranges.get(s)
        if rng is None:
            continue
        first_mo, last_mo = month_key(rng[0]), month_key(rng[1])
        last_close_us = int((rng[1] + pd.Timedelta(minutes=15)).value // 1000)
        g = by_sym.get(s)
        for mo in months_between(first_mo, last_mo):
            if mo in have_months.get(s, set()):
                continue
            window = {shift_month(mo, -k) for k in (1, 2, 3)}
            hist = g[g["_mo"].isin(window)]["_abs"].to_numpy() if g is not None else np.empty(0)
            mk = None
            if not len(hist):
                mk = real[real["_mo"].isin(window)]["_abs"].to_numpy()
            prev = g[g["_mo"] < mo] if g is not None else None
            ih = int(prev["interval_h"].iloc[-1]) if prev is not None and len(prev) else None
            res = impute_month_events(mo, hist, mk if mk is not None else np.empty(0), ih, last_close_us)
            if res is None:
                months.append((s, mo, "imputed", "none"))
                log.write(f"IMPUTE-NONE {s} {mo} no rate available\n")
                continue
            ev, rate, h, basis = res
            months.append((s, mo, "imputed", basis))
            n_imp_months[basis] += 1
            if ev:
                imputed_frames.append(
                    pd.DataFrame(
                        {
                            "symbol": s,
                            "funding_time": pd.to_datetime(np.array(ev, dtype="int64"), unit="us", utc=True).astype("datetime64[us, UTC]"),
                            "rate": rate,
                            "interval_h": np.int8(h),
                            "imputed": True,
                            "basis": basis,
                        }
                    )
                )
    real = real.drop(columns=["_mo", "_abs"])
    out = pd.concat([real] + imputed_frames, ignore_index=True) if imputed_frames else real
    out = out.sort_values(["symbol", "funding_time"], kind="stable").reset_index(drop=True)
    out.to_parquet(C.CACHE / "funding.parquet")
    fm = pd.DataFrame(months, columns=["symbol", "month", "source", "basis"])
    fm.to_parquet(C.CACHE / "funding_months.parquet")
    src_counts = fm["source"].value_counts().to_dict()
    log.write(f"funding rows={len(out)} symbols={out['symbol'].nunique()} imputed_events={int(out['imputed'].sum())}\n")
    log.write(f"# sources (symbol,month) {src_counts} imputed_basis={n_imp_months}\n")
    return failed


DELIST_MIN_BARS = 96
DELIST_COLS = ["symbol", "run_start", "run_end", "n_bars", "delist_bar", "delist_close", "to_end", "has_gap"]


def flat_runs(df: pd.DataFrame, min_bars: int = DELIST_MIN_BARS) -> list[dict]:
    """Flat-line runs of one symbol's closed 15m bars (sorted by open_time): high == low == close and volume == 0, >= min_bars
    consecutive rows (row order; time gaps inside a run do not split it). delist_bar = open_time of the row before the run."""
    if df.empty:
        return []
    h, lo, c, v = (df[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    flat = (h == lo) & (lo == c) & (v == 0)
    ot = df["open_time"].reset_index(drop=True)
    n = len(df)
    edges = np.flatnonzero(np.diff(np.r_[0, flat.astype(np.int8), 0]))
    out = []
    for a, b in zip(edges[0::2], edges[1::2]):  # run = rows a .. b-1
        if b - a < min_bars:
            continue
        gaps = ot.iloc[a:b].diff().dropna()
        out.append(
            {
                "run_start": ot.iloc[a],
                "run_end": ot.iloc[b - 1],
                "n_bars": int(b - a),
                "delist_bar": ot.iloc[a - 1] if a > 0 else pd.NaT,
                "delist_close": float(c[a - 1]) if a > 0 else float("nan"),
                "to_end": bool(b == n),
                "has_gap": bool((gaps != pd.Timedelta(minutes=15)).any()),
            }
        )
    return out


def build_delist(log) -> list[str]:
    rows = []
    for s in C.union_symbols():
        df = C.load_bars_df(s, "15m")
        for r in flat_runs(df):
            rows.append({"symbol": s, **r})
    d = pd.DataFrame(rows, columns=DELIST_COLS)
    for c in ("run_start", "run_end", "delist_bar"):
        d[c] = pd.to_datetime(d[c], utc=True).astype("datetime64[us, UTC]")
    d = d.sort_values(["symbol", "run_start"], kind="stable").reset_index(drop=True)
    d.to_parquet(C.CACHE / "delist.parquet")
    cut = pd.Timestamp("2025-07-01", tz="UTC")
    log.write(
        f"# delist runs={len(d)} symbols={d['symbol'].nunique()} to_end={int(d['to_end'].sum())} relist={int((~d['to_end']).sum())} "
        f"to_end_start_before_2025-07-01={int((d['to_end'] & (d['run_start'] < cut)).sum())} no_delist_bar={int(d['delist_bar'].isna().sum())} "
        f"with_gap={int(d['has_gap'].sum())}\n"
    )
    return []


DCAUG_COLS = ["symbol", "type", "time", "bias4_snap", "zs4_zg", "zs4_zd", "zs4_count"]


def _dcaug_job(args):
    symbol, t_us = args
    try:
        from bisect import bisect_right

        from research import signals

        t0 = time.time()
        eng = signals.make_engine()
        bars = signals.closed_bars("4h", symbol)
        closes_us = np.array([int(pd.Timestamp(b.close_time).value // 1000) for b in bars], dtype="int64")
        limit = C.WINDOWS["4h"]
        ends = np.searchsorted(closes_us, t_us, side="right")  # bars with close_time <= T
        cache: dict = {}
        bias = np.full(len(t_us), None, dtype=object)
        zg = np.full(len(t_us), np.nan)
        zd = np.full(len(t_us), np.nan)
        cnt = np.full(len(t_us), np.nan)
        for k, end in enumerate(ends.tolist()):
            if end == 0:
                continue
            if end not in cache:
                snap = signals.snapshot(eng, bars[max(0, end - limit) : end], "4h")
                zs = snap.zhongshus
                cache[end] = (snap.structure_bias.value, (zs[-1].zg, zs[-1].zd) if zs else (np.nan, np.nan), len(zs))
            b, (g, d), n = cache[end]
            bias[k], zg[k], zd[k], cnt[k] = b, g, d, n
        return {"symbol": symbol, "bias": bias, "zg": zg, "zd": zd, "cnt": cnt, "elapsed": time.time() - t0, "snaps": len(cache)}
    except Exception as exc:
        import traceback

        return {"symbol": symbol, "error": f"{exc!r}\n{traceback.format_exc()}"}


def build_dcaug(workers: int, log) -> list[str]:
    """Plan 4.5: per Donchian row (top-20 rows only) the 4h structure_bias and latest zhongshu of the last closed 4h snapshot at T."""
    from research import signals

    failed: list[str] = []
    t_all = time.time()
    tot = {"rows": 0, "mm": 0, "nb": 0, "nz": 0}
    for tf in ("1h", "4h"):
        df = pd.read_parquet(C.CACHE / f"signals_donchian_{tf}.parquet", columns=["symbol", "type", "time", "in_top20"])
        top = df["in_top20"].to_numpy(bool)
        t_us = time_ns(df["time"]).astype("int64") // 1000
        bias = np.full(len(df), None, dtype=object)
        zg = np.full(len(df), np.nan)
        zd = np.full(len(df), np.nan)
        cnt = np.full(len(df), np.nan)
        syms = df["symbol"].to_numpy()
        idx_by = {}
        for i in np.flatnonzero(top).tolist():
            idx_by.setdefault(syms[i], []).append(i)
        jobs = [(s, t_us[np.array(ix)]) for s, ix in idx_by.items()]
        order = {s: np.array(ix) for s, ix in idx_by.items()}
        with Pool(workers, maxtasksperchild=1) as pool:
            for res in pool.imap_unordered(_dcaug_job, jobs):
                s = res["symbol"]
                if "error" in res:
                    failed.append(s)
                    log.write(f"FAIL dcaug {tf} {s} {res['error']}\n")
                    log.flush()
                    continue
                ix = order[s]
                bias[ix], zg[ix], zd[ix], cnt[ix] = res["bias"], res["zg"], res["zd"], res["cnt"]
                log.write(f"dcaug {tf} {s} rows={len(ix)} snaps={res['snaps']} elapsed={res['elapsed']:.1f}s total={time.time() - t_all:.0f}s\n")
                log.flush()
        if failed:
            return failed
        out = df[["symbol", "type", "time"]].copy()
        out["bias4_snap"] = bias
        out["zs4_zg"] = zg
        out["zs4_zd"] = zd
        out["zs4_count"] = cnt
        # self check against bias_4h.parquet (same algorithm, built in phase 1)
        b4 = pd.read_parquet(C.CACHE / "bias_4h.parquet")
        by = {s: g.sort_values("close_time").reset_index(drop=True) for s, g in b4.groupby("symbol", sort=False)}
        mismatch = no_bias = 0
        for s, ix in order.items():
            g = by.get(s)
            ts = df["time"].iloc[ix]
            for i, t in zip(ix.tolist(), ts):
                ref = signals._lookup_bias(g, t.to_pydatetime()) if g is not None else None
                if ref is None and bias[i] is None:
                    no_bias += 1
                elif ref != bias[i]:
                    mismatch += 1
        out.to_parquet(C.CACHE / f"signals_donchian_{tf}_aug.parquet")
        no_zs = int((top & (cnt == 0)).sum())
        log.write(f"# dcaug-tf {tf} rows={int(top.sum())} bias_mismatch={mismatch} no_bias={no_bias} no_zs={no_zs}\n")
        tot["rows"] += int(top.sum())
        tot["mm"] += mismatch
        tot["nb"] += no_bias
        tot["nz"] += no_zs
        log.flush()
    log.write(f"# dcaug rows={tot['rows']} bias_mismatch={tot['mm']} no_bias={tot['nb']} no_zs={tot['nz']}\n")
    return failed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.augment")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--only", default="bi,sig,funding")
    sub.add_parser("fetch-funding")
    a = p.parse_args(argv)
    if a.cmd == "fetch-funding":
        return fetch_funding()
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
        if "delist" in only:
            failed += build_delist(log)
        if "dcaug" in only:
            failed += build_dcaug(a.workers, log)
        log.write(f"# done total={time.time() - t0:.0f}s failed={failed}\n")
    if failed:
        print("FAILED:", failed, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
