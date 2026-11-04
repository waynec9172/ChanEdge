"""Signal cache. Single left-to-right walk (replicated ChanEngine.compute loop) or rolling windows.

Commands:
  python -m research.signals compare                      # 3 coins x 3 months, single vs rolling
  python -m research.signals build [--symbols A,B] [--workers N] [--out-dir DIR]
  python -m research.signals estimate-retro               # append the full-build estimate to signals_build.log
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from multiprocessing import Pool

import numpy as np
import pandas as pd

from research import common as C

_UTC = timezone.utc
_NAN = float("nan")
TYPE_SIDE = {"second_buy": 1, "third_buy": 1, "second_sell": -1, "third_sell": -1}


# --------------------------------------------------------------------------- engine helpers
def _tf_enum(tf: str):
    from chanedge.domain.enums import Timeframe

    return Timeframe(tf)


def make_engine():
    from chanedge.chanlun.engine import ChanEngine

    s = C.settings()
    return ChanEngine(
        config_hash=C.config_digest(),
        min_bi_bars=s.chanlun.min_bi_bars,
        segment_enabled=s.chanlun.segment_enabled,
    )


def closed_bars(tf: str, symbol: str):
    return tuple(b for b in C.load_bar_objects(symbol, tf) if b.is_closed)


@dataclass
class WalkSignal:
    signal: object  # ChanSignal at emission
    zg: float
    zd: float


@dataclass
class WalkResult:
    signals: list  # list[WalkSignal]
    bi_events: pd.DataFrame  # confirm_time, event, direction, end_price, established_at


def walk(bars, tf: str) -> WalkResult:
    """Replica of ChanEngine.compute's loop that also records every emission and bi event."""
    from chanedge.chanlun.bi import WalkState
    from chanedge.chanlun.fenxing import confirmed_fenxings, detect_fenxings
    from chanedge.chanlun.include import include_merge

    series = tuple(bars)
    tfe = _tf_enum(tf)
    merged = include_merge(series)
    drafts = detect_fenxings(merged, series, tfe)
    eng = make_engine()
    state = WalkState(eng.min_bi_bars, series, tfe)
    emitted: list[WalkSignal] = []
    ev_time, ev_kind, ev_dir, ev_end, ev_est = [], [], [], [], []
    for draft in confirmed_fenxings(drafts):
        before = len(state.signals)
        event = state.feed_fenxing(draft)
        if event is None:
            continue
        state.apply_zhongshu(event)
        state.apply_signals(event)
        bi = state.held[-1].bi
        ev_time.append(series[draft.k_index_right].close_time)
        ev_kind.append(event)
        ev_dir.append(1 if str(bi.direction.value) == "up" else -1)
        ev_end.append(bi.end_price)
        ev_est.append(bi.established_at)
        new = state.signals[before:]
        if new:
            zs = {z.id: (z.zg, z.zd) for z in state.book.zhongshus}
            for sig in new:
                zg, zd = zs.get(sig.related_zhongshu_id, (_NAN, _NAN)) if sig.related_zhongshu_id else (_NAN, _NAN)
                emitted.append(WalkSignal(sig, zg, zd))
    events = pd.DataFrame(
        {
            "confirm_time": _ts(ev_time),
            "event": ev_kind,
            "direction": np.array(ev_dir, dtype="int8"),
            "end_price": np.array(ev_end, dtype="float64"),
            "established_at": _ts(ev_est),
        }
    )
    return WalkResult(emitted, events)


def _ts(values) -> pd.Series:
    return pd.Series(pd.to_datetime(list(values), utc=True)).astype("datetime64[us, UTC]")


def window_of(bars, closes, t: datetime, limit: int):
    end = bisect_right(closes, t)
    return bars[max(0, end - limit) : end]


def snapshot(engine, window, tf: str):
    return engine.compute(window, timeframe=_tf_enum(tf), as_of=window[-1].close_time, identify=False)


def rolling_signals(bars, tf: str, start: datetime, end: datetime):
    """Signals emitted exactly at close t, for each closed bar with close_time in [start, end]."""
    engine = make_engine()
    closes = [b.close_time for b in bars]
    limit = C.WINDOWS[tf]
    out = []
    lo = bisect_right(closes, start - timedelta(microseconds=1))
    hi = bisect_right(closes, end)
    for i in range(lo, hi):
        t = closes[i]
        window = bars[max(0, i + 1 - limit) : i + 1]
        snap = snapshot(engine, window, tf)
        out.extend(s for s in snap.signals if s.time == t)
    return out


# --------------------------------------------------------------------------- compare (2c)
_CMP_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
_CMP_START = datetime(2024, 3, 1, tzinfo=_UTC)
_CMP_END = datetime(2024, 6, 1, tzinfo=_UTC)


def _cmp_key(symbol, tf, s):
    return (symbol, tf, s.type.value, s.time, round(s.defending_price, 8))


def _compare_one(args):
    symbol, tf = args
    bars = closed_bars(tf, symbol)
    w = walk(bars, tf)
    single = {_cmp_key(symbol, tf, x.signal) for x in w.signals if _CMP_START <= x.signal.time <= _CMP_END}
    t0 = time.time()
    roll = {_cmp_key(symbol, tf, s) for s in rolling_signals(bars, tf, _CMP_START, _CMP_END)}
    return symbol, tf, single, roll, time.time() - t0


def compare(workers: int = 6) -> None:
    C.CACHE.mkdir(parents=True, exist_ok=True)
    jobs = [(s, tf) for tf in C.TFS for s in _CMP_SYMBOLS]
    with Pool(workers, maxtasksperchild=1) as pool:
        results = pool.map(_compare_one, jobs)
    detail, mode, samples = {}, {}, []
    for tf in C.TFS:
        single, roll, elapsed = set(), set(), 0.0
        for symbol, tf2, s, r, el in results:
            if tf2 == tf:
                single |= s
                roll |= r
                elapsed += el
        diff = single ^ roll
        rate = len(diff) / len(roll) if roll else (0.0 if not single else 1.0)
        detail[tf] = {"n_single": len(single), "n_rolling": len(roll), "sym_diff": len(diff), "rate": rate}
        mode[tf] = "rolling" if rate > 0.02 else "single"
        for k in sorted(diff, key=lambda k: (k[0], k[3]))[:20]:
            samples.append((tf, "single_only" if k in single else "rolling_only", k))
    out = dict(mode)
    out["detail"] = detail
    (C.CACHE / "mode.json").write_text(json.dumps(out, indent=2, default=str))
    lines = [
        "# 訊號模式比對（單次走訪 vs 滾動視窗）",
        "",
        "幣：BTC/USDT, ETH/USDT, SOL/USDT；期間 2024-03-01 00:00 → 2024-06-01 00:00 UTC（close_time 閉區間）。",
        "鍵 = (symbol, tf, type, time, round(defending_price, 8))。差異率 = |單次 △ 滾動| / |滾動|，三幣合併。",
        "判定：差異率 > 0.02 的週期改用 rolling，否則 single（每個週期各自判定）。",
        "",
        "| tf | n_single | n_rolling | sym_diff | rate | 判定 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for tf in C.TFS:
        d = detail[tf]
        lines.append(f"| {tf} | {d['n_single']} | {d['n_rolling']} | {d['sym_diff']} | {d['rate']:.4%} | {mode[tf]} |")
    lines += ["", "## 不一致樣本（每週期前 20 筆）", "", "| tf | 來源 | symbol | type | time | defending |", "| --- | --- | --- | --- | --- | --- |"]
    for tf, where, k in samples:
        lines.append(f"| {tf} | {where} | {k[0]} | {k[2]} | {k[3].isoformat()} | {k[4]} |")
    (C.OUT / "signal_mode_check.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(out, indent=2, default=str))


# --------------------------------------------------------------------------- build (2d)
def _seg_time_range(symbol: str):
    segs = C.active_segments(symbol)
    if not segs:
        return None
    lo = datetime.combine(segs[0][0] - timedelta(days=1), datetime.min.time(), tzinfo=_UTC)
    hi = datetime.combine(segs[-1][1] + timedelta(days=2), datetime.min.time(), tzinfo=_UTC)
    return segs, lo, hi


def _in_segments(t: datetime, segs) -> bool:
    d = C.universe_date(t)
    if not (C.HISTORY_START <= d <= C.HISTORY_END):
        return False
    return any(a <= d <= b for a, b in segs)


def bias_series(engine, bars, tf: str, lo: datetime, hi: datetime) -> pd.DataFrame:
    closes = [b.close_time for b in bars]
    limit = C.WINDOWS[tf]
    times, vals = [], []
    start = bisect_right(closes, lo - timedelta(microseconds=1))
    stop = bisect_right(closes, hi)
    for i in range(start, stop):
        window = bars[max(0, i + 1 - limit) : i + 1]
        snap = snapshot(engine, window, tf)
        times.append(closes[i])
        vals.append(snap.structure_bias.value)
    return pd.DataFrame({"close_time": _ts(times), "bias": vals})


def _lookup_bias(df: pd.DataFrame, t: datetime) -> str | None:
    if df.empty:
        return None
    ts = pd.Timestamp(t)
    idx = df["close_time"].searchsorted(ts, side="right") - 1
    return None if idx < 0 else df["bias"].iloc[idx]


def _atr_at(bars, atr_values, closes_index, t):
    i = closes_index.get(t)
    if i is None:
        return _NAN
    v = atr_values[i]
    return _NAN if v is None else float(v)


def _last_ends(events: pd.DataFrame, t: datetime) -> tuple[float, float]:
    """Latest up / down bi endpoint with confirm_time <= t (replace events applied by taking the last row)."""
    ts = pd.Timestamp(t)
    res = []
    for d in (1, -1):
        sub = events[events["direction"] == d]
        idx = sub["confirm_time"].searchsorted(ts, side="right") - 1
        res.append(_NAN if idx < 0 else float(sub["end_price"].iloc[idx]))
    return res[0], res[1]


def build_symbol(symbol: str, modes: dict[str, str]) -> dict:
    from chanedge.app.bind import feature_params, jev_params, rule_params
    from chanedge.app.paper_loop import backtest_quality
    from chanedge.domain.bars import MultiTimeframeContext
    from chanedge.domain.enums import RuntimeMode, Timeframe
    from chanedge.domain.risk import AccountView, SafetyState
    from chanedge.features.atr import wilder_atr
    from chanedge.features.builder import FeatureBuilder
    from chanedge.features.select import select_candidate
    from chanedge.jev.model import JevModel
    from chanedge.risk.stops import _last_endpoint
    from chanedge.rules.gate import RuleGate

    t_start = time.time()
    s = C.settings()
    got = _seg_time_range(symbol)
    if got is None:
        return {"symbol": symbol, "elapsed": 0.0}
    segs, lo, hi = got
    engine = make_engine()
    bars = {tf: closed_bars(tf, symbol) for tf in C.TFS}
    closes = {tf: [b.close_time for b in bars[tf]] for tf in C.TFS}
    index = {tf: {c: i for i, c in enumerate(closes[tf])} for tf in C.TFS}
    uni = C.load_universe()
    rank_map = {
        d: r for d, r in zip(uni.loc[uni["symbol"] == symbol, "date"], uni.loc[uni["symbol"] == symbol, "rank"])
    }
    # --- bias series (only closed bars, window = last N bars with close_time <= t)
    bias = {tf: bias_series(engine, bars[tf], tf, lo, hi) for tf in ("1h", "4h")}
    # --- signals per tf
    walks = {}
    sigs: dict[str, list[WalkSignal]] = {}
    for tf in C.TFS:
        if modes[tf] == "single":
            w = walk(bars[tf], tf)
            walks[tf] = w
            sigs[tf] = [x for x in w.signals if _in_segments(x.signal.time, segs)]
        else:
            roll = rolling_signals_ranged(bars[tf], tf, segs, lo, hi)
            sigs[tf] = roll
    # --- 15m bi events
    if modes["15m"] == "single":
        events = walks["15m"].bi_events
    else:
        events = rolling_bi_events(engine, bars["15m"], lo, hi)
    events = events.copy()
    events.insert(0, "symbol", symbol)
    events["direction"] = events["direction"].astype("int8")

    inst = C.instrument(symbol)
    fb = FeatureBuilder(feature_params(s))
    jev = JevModel(jev_params(s))
    gate = RuleGate(rule_params(s))
    quality = backtest_quality(s)
    account = AccountView(equity_quote=Decimal(10000), open_position_count=0, gross_notional_quote=Decimal(0))
    safety = SafetyState(kill_switch=False, mode=RuntimeMode.PAPER)
    snap_cache: dict = {}

    def htf_snap(tf: str, t: datetime):
        end = bisect_right(closes[tf], t)
        if end == 0:
            return None, ()
        key = (tf, closes[tf][end - 1])
        window = bars[tf][max(0, end - C.WINDOWS[tf]) : end]
        if key not in snap_cache:
            if len(snap_cache) > 6:
                snap_cache.clear()
            snap_cache[key] = snapshot(engine, window, tf)
        return snap_cache[key], window

    rows15, rows1h4h = [], {"1h": [], "4h": []}
    seen_reemit: set = set()
    # reemit uses all emitted signals in chronological order, including those outside segments
    first_seen = {}
    for tf in C.TFS:
        if modes[tf] == "single":
            for x in walks[tf].signals:
                key = (tf, x.signal.type.value, x.signal.related_bi_id)
                first_seen.setdefault(key, x.signal.id)

    def reemit_flag(tf, sig):
        key = (tf, sig.type.value, sig.related_bi_id)
        first = first_seen.get(key)
        if first is None:
            first_seen[key] = sig.id
            return False
        return first != sig.id

    # --- 15m rows (group by time so features are computed once per bar)
    by_time: dict[datetime, list[WalkSignal]] = {}
    for x in sigs["15m"]:
        by_time.setdefault(x.signal.time, []).append(x)
    atr_fallback = wilder_atr(bars["15m"], 14)
    for t in sorted(by_time):
        i = index["15m"].get(t)
        win15 = bars["15m"][max(0, i + 1 - C.WINDOWS["15m"]) : i + 1]
        snap15 = snapshot(engine, win15, "15m")
        snap1h, win1h = htf_snap("1h", t)
        snap4h, win4h = htf_snap("4h", t)
        feats = None
        jscore = jaction = _NAN
        gate_pass = None
        veto = ""
        cand, amb_ids = select_candidate(snap15.signals, t)
        day = C.universe_date(t)
        rank = rank_map.get(day)
        if snap1h is not None and snap4h is not None:
            windows = {Timeframe.M15: win15, Timeframe.H1: win1h, Timeframe.H4: win4h}
            ctx = MultiTimeframeContext(
                context_id=f"{symbol}|{t.isoformat()}",
                symbol=symbol,
                decision_time=t,
                bars=windows,
                snapshots={Timeframe.M15: snap15, Timeframe.H1: snap1h, Timeframe.H4: snap4h},
                data_quality=quality(symbol, t, windows).model_copy(update={"stale": False}),
                instrument=inst,
                universe_date=day,
                universe_rank=rank,
            )
            feats = fb.build(ctx)
            assess = jev.assess(feats)
            rules = gate.evaluate(ctx, assess, account, safety)
            jscore = float(assess.score)
            jaction = assess.proposed_action.value
            gate_pass = bool(rules.passed)
            veto = ",".join(v.code.value for v in rules.vetoes)
        up_end = _last_endpoint(snap15, _dir("up"), t)
        dn_end = _last_endpoint(snap15, _dir("down"), t)
        by_id = {sg.id: sg for sg in snap15.signals if sg.time == t}
        zs_map = {z.id: (z.zg, z.zd) for z in snap15.zhongshus}
        for x in by_time[t]:
            sg = x.signal
            in_window = sg.id in by_id
            use = by_id.get(sg.id, sg)
            zg, zd = x.zg, x.zd
            if in_window and use.related_zhongshu_id in zs_map:
                zg, zd = zs_map[use.related_zhongshu_id]
            row = {
                "signal_id": sg.id,
                "symbol": symbol,
                "tf": "15m",
                "type": sg.type.value,
                "side": TYPE_SIDE[sg.type.value],
                "time": t,
                "close": float(use.price),
                "defending_price": float(use.defending_price),
                "prior_extreme": _NAN if use.prior_extreme is None else float(use.prior_extreme),
                "zs_zg": zg,
                "zs_zd": zd,
                "atr": float(feats.volatility_volume.atr) if feats is not None else _atr_at(bars["15m"], atr_fallback, index["15m"], t),
                "bias_4h": snap4h.structure_bias.value if snap4h is not None else None,
                "bias_1h": snap1h.structure_bias.value if snap1h is not None else None,
                "bias_15m": snap15.structure_bias.value,
                "universe_date": day,
                "rank": float(rank) if rank is not None else _NAN,
                "in_top20": rank is not None,
                "reemit": reemit_flag("15m", sg),
                "last_up_end": float(up_end) if up_end is not None else _NAN,
                "last_down_end": float(dn_end) if dn_end is not None else _NAN,
                "candidate": bool(cand is not None and cand.id == sg.id and not amb_ids),
                "ambiguous": bool(len(amb_ids) > 0 or (feats is not None and bool(feats.ambiguous_signal_ids))),
                "in_window": bool(in_window),
                "gate_pass": gate_pass,
                "veto_codes": veto,
                "jev_score": jscore,
                "jev_action": jaction,
                "atr_pct": float(feats.volatility_volume.atr_pct) if feats is not None else _NAN,
                "session_bucket": feats.session.session_bucket.value if feats is not None else None,
            }
            if feats is not None:
                for ch in ("structure", "location", "resonance", "volatility_volume", "signal_bar", "session"):
                    c = getattr(feats, ch)
                    row[f"ch_{ch}_subscore"] = float(c.subscore)
                    row[f"ch_{ch}_penalty"] = float(c.penalty)
            else:
                for ch in ("structure", "location", "resonance", "volatility_volume", "signal_bar", "session"):
                    row[f"ch_{ch}_subscore"] = _NAN
                    row[f"ch_{ch}_penalty"] = _NAN
            row["hist_ok"] = bool(
                len(win15) >= C.WINDOWS["15m"] and len(win1h) >= C.WINDOWS["1h"] and len(win4h) >= C.WINDOWS["4h"]
            )
            row["gap_veto"] = ("gap_data" in veto.split(",")) if feats is not None else None
            rows15.append(row)

    # --- 1h / 4h rows
    for tf in ("1h", "4h"):
        atr_vals = wilder_atr(bars[tf], 14)
        for x in sigs[tf]:
            sg = x.signal
            t = sg.time
            day = C.universe_date(t)
            rank = rank_map.get(day)
            up_end, dn_end = _last_ends(events, t)
            rows1h4h[tf].append(
                {
                    "signal_id": sg.id,
                    "symbol": symbol,
                    "tf": tf,
                    "type": sg.type.value,
                    "side": TYPE_SIDE[sg.type.value],
                    "time": t,
                    "close": float(sg.price),
                    "defending_price": float(sg.defending_price),
                    "prior_extreme": _NAN if sg.prior_extreme is None else float(sg.prior_extreme),
                    "zs_zg": x.zg,
                    "zs_zd": x.zd,
                    "atr": _atr_at(bars[tf], atr_vals, index[tf], t),
                    "bias_4h": _lookup_bias(bias["4h"], t),
                    "bias_1h": _lookup_bias(bias["1h"], t),
                    "universe_date": day,
                    "rank": float(rank) if rank is not None else _NAN,
                    "in_top20": rank is not None,
                    "reemit": reemit_flag(tf, sg),
                    "last_up_end": up_end,
                    "last_down_end": dn_end,
                }
            )
    for tf in ("1h", "4h"):
        bias[tf].insert(0, "symbol", symbol)
    b15 = C.load_bars_df(symbol, "15m")
    start_ts = pd.Timestamp(segs[0][0] - timedelta(days=1), tz="UTC")
    b15 = b15[b15["open_time"] >= start_ts][["symbol", "open_time", "open", "high", "low", "close"]]
    return {
        "symbol": symbol,
        "signals_15m": pd.DataFrame(rows15),
        "signals_1h": pd.DataFrame(rows1h4h["1h"]),
        "signals_4h": pd.DataFrame(rows1h4h["4h"]),
        "bias_1h": bias["1h"],
        "bias_4h": bias["4h"],
        "bi_events_15m": events,
        "bars_15m": b15,
        "instrument": (symbol, None if inst.price_tick is None else float(inst.price_tick)),
        "elapsed": time.time() - t_start,
    }


def _dir(name: str):
    from chanedge.domain.enums import Direction

    return Direction.UP if name == "up" else Direction.DOWN


def rolling_signals_ranged(bars, tf: str, segs, lo, hi):
    """Rolling signals only for closes whose universe date lies in the active segments."""
    engine = make_engine()
    closes = [b.close_time for b in bars]
    limit = C.WINDOWS[tf]
    out = []
    for i, t in enumerate(closes):
        if not _in_segments(t, segs):
            continue
        window = bars[max(0, i + 1 - limit) : i + 1]
        snap = snapshot(engine, window, tf)
        for s in snap.signals:
            if s.time == t:
                zs = {z.id: (z.zg, z.zd) for z in snap.zhongshus}
                zg, zd = zs.get(s.related_zhongshu_id, (_NAN, _NAN)) if s.related_zhongshu_id else (_NAN, _NAN)
                out.append(WalkSignal(s, zg, zd))
    return out


def rolling_bi_events(engine, bars, lo, hi) -> pd.DataFrame:
    closes = [b.close_time for b in bars]
    limit = C.WINDOWS["15m"]
    t_out, k_out, d_out, e_out, est_out = [], [], [], [], []
    start = bisect_right(closes, lo - timedelta(microseconds=1))
    stop = bisect_right(closes, hi)
    for i in range(start, stop):
        t = closes[i]
        snap = snapshot(engine, bars[max(0, i + 1 - limit) : i + 1], "15m")
        fx = {f.id: f for f in snap.fenxings}
        for bi in snap.bis:
            f = fx.get(bi.end_fx_id)
            if f is None or f.time != t:
                continue
            t_out.append(t)
            k_out.append("new" if bi.established_at == t else "replace")
            d_out.append(1 if bi.direction.value == "up" else -1)
            e_out.append(bi.end_price)
            est_out.append(bi.established_at)
    return pd.DataFrame(
        {
            "confirm_time": _ts(t_out),
            "event": k_out,
            "direction": np.array(d_out, dtype="int8"),
            "end_price": np.array(e_out, dtype="float64"),
            "established_at": _ts(est_out),
        }
    )


def _build_job(args):
    symbol, modes = args
    try:
        return build_symbol(symbol, modes)
    except Exception as exc:  # reported by the parent
        import traceback

        return {"symbol": symbol, "error": f"{exc!r}\n{traceback.format_exc()}"}


def _bar_weight(symbol: str) -> int:
    """Number of 15m bars inside the symbol's active range (the work a build job does scales with this)."""
    import pyarrow.parquet as pq

    got = _seg_time_range(symbol)
    if got is None:
        return 0
    _segs, lo, hi = got
    col = pq.read_table(C.bars_path(symbol, "15m"), columns=["open_time"]).to_pandas()["open_time"]
    return int(((col >= pd.Timestamp(lo)) & (col < pd.Timestamp(hi))).sum())


def estimate_total(done: list[tuple[str, float]], workers: int, symbols: list[str] | None = None) -> tuple[float, int]:
    """est = (sum elapsed / sum w over finished symbols) * sum w over all symbols / workers. Returns (seconds, n_symbols)."""
    allsyms = symbols or C.union_symbols()
    w_done = sum(_bar_weight(s) for s, _ in done)
    e_done = sum(e for _, e in done)
    w_all = sum(_bar_weight(s) for s in allsyms)
    return (e_done / w_done) * w_all / workers, len(allsyms)


def estimate_retro() -> int:
    """Append `# estimate-retro` to the existing full-build log, using the small-sample log (no rebuild)."""
    import re

    logs = C.CACHE / "logs"
    small = (logs / "signals_build_small.log").read_text().splitlines()
    done = []
    for ln in small:
        m = re.match(r"(\S+/USDT) sig15=\d+ sig1h=\d+ sig4h=\d+ elapsed=([\d.]+)s", ln)
        if m:
            done.append((m.group(1), float(m.group(2))))
    est, n = estimate_total(done, 6)
    line = f"# estimate-retro (from signals_build_small.log, {len(done)} symbols) full={n} symbols ~ {est:.0f} s at workers=6\n"
    path = logs / "signals_build.log"
    text = path.read_text()
    if "# estimate-retro" in text:
        print("already present")
        return 0
    with open(path, "a") as fh:
        fh.write(line)
    print(line.strip())
    return 0


def build(symbols: list[str] | None, workers: int, out_dir=None) -> int:
    mode_path = C.CACHE / "mode.json"
    if not mode_path.exists():
        print("mode.json is missing; run `python -m research.signals compare` first", file=sys.stderr)
        return 1
    modes = {tf: json.loads(mode_path.read_text())[tf] for tf in C.TFS}
    from pathlib import Path

    out_dir = Path(out_dir) if out_dir else C.CACHE
    out_dir.mkdir(parents=True, exist_ok=True)
    logs = out_dir / "logs" if out_dir != C.CACHE else C.CACHE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "signals_build.log"
    names = symbols or C.union_symbols()
    done_times: list[tuple[str, float]] = []
    parts: dict[str, list] = {k: [] for k in ("signals_15m", "signals_1h", "signals_4h", "bias_1h", "bias_4h", "bi_events_15m", "bars_15m")}
    instruments, failed = [], []
    t0 = time.time()
    with open(log_path, "a") as log:
        log.write(f"# build {datetime.now(_UTC).isoformat()} symbols={len(names)} modes={modes} workers={workers}\n")
        log.flush()
        with Pool(workers, maxtasksperchild=1) as pool:
            for res in pool.imap_unordered(_build_job, [(n, modes) for n in names]):
                if "error" in res:
                    failed.append(res["symbol"])
                    log.write(f"FAIL {res['symbol']} {res['error']}\n")
                    log.flush()
                    continue
                if "signals_15m" not in res:
                    log.write(f"{res['symbol']} skipped (no active segments)\n")
                    continue
                for k in parts:
                    parts[k].append(res[k])
                instruments.append(res["instrument"])
                done_times.append((res["symbol"], float(res["elapsed"])))
                log.write(
                    f"{res['symbol']} sig15={len(res['signals_15m'])} sig1h={len(res['signals_1h'])} "
                    f"sig4h={len(res['signals_4h'])} elapsed={res['elapsed']:.1f}s total={time.time() - t0:.0f}s\n"
                )
                log.flush()
        for k, frames in parts.items():
            frames = [f for f in frames if len(f)]
            if not frames:
                continue
            df = pd.concat(frames, ignore_index=True)
            if "time" in df.columns:
                df = df.sort_values(["time", "symbol"]).reset_index(drop=True)
            if k.startswith("signals_"):
                name = f"{k}.parquet"
            else:
                name = f"{k}.parquet"
            df.to_parquet(out_dir / name)
        pd.DataFrame(instruments, columns=["symbol", "price_tick"]).to_parquet(out_dir / "instruments.parquet")
        if symbols and done_times:
            est, n_all = estimate_total(done_times, workers)
            log.write(f"# estimate full={n_all} symbols ~ {est:.0f} s at workers={workers}\n")
        log.write(f"# done total={time.time() - t0:.0f}s failed={failed}\n")
    if failed:
        print("FAILED symbols:", ", ".join(failed), file=sys.stderr)
        return 1
    print(f"built {len(names)} symbols in {time.time() - t0:.0f}s")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.signals")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--workers", type=int, default=6)
    b = sub.add_parser("build")
    b.add_argument("--symbols", default=None)
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--out-dir", default=None)
    sub.add_parser("estimate-retro")
    a = p.parse_args(argv)
    if a.cmd == "compare":
        compare(a.workers)
        return 0
    if a.cmd == "estimate-retro":
        return estimate_retro()
    return build(a.symbols.split(",") if a.symbols else None, a.workers, a.out_dir)


if __name__ == "__main__":
    sys.exit(main())
