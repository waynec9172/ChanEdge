"""ICT generator: causality (prefix invariance), resumability, determinism, schema, registration, no-PnL guarantees."""

from __future__ import annotations

import inspect
import pickle
import re
import unittest
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd

from research import common as C
from research import run as R
from research import sim
from research.ict import generate as G
from research.ict import params as IP
from research.tests import ict_synth as Z

PLAN = C.ROOT / "research" / "plans" / "ict_phase1.md"


def random_walk(seed=7, n=6000):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.35, n))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.15, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 0.15, n))
    return list(zip(o.round(4), h.round(4), l.round(4), c.round(4)))


def cut_frames(b15, b1h, b4h, t_us):
    def keep(df):
        ct = df["close_time"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy().astype("int64")
        return df[ct <= t_us].reset_index(drop=True)

    return keep(b15), keep(b1h), keep(b4h)


def funding_for(b15, rng_seed=3):
    rng = np.random.default_rng(rng_seed)
    t0 = int(b15["open_time"].iloc[0].value // 1000)
    t = t0 + np.arange(0, len(b15) * 900_000_000, 8 * 3_600_000_000, dtype="int64")
    return t, rng.choice([-0.0006, -0.0001, 0.0001, 0.0006], size=len(t))


def ev_repr(events):
    return [repr(e) for e in events]


class GenerateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = random_walk()
        cls.b15, cls.b1h, cls.b4h = Z.frames(cls.rows)
        cls.fund = funding_for(cls.b15)

    def _cases(self):
        yield "rw1h", (self.b15, self.b1h, self.b4h), Z.P_for(setup_tf="1h", use_htf=True, use_session=True, use_funding=True, use_ltf=True), self.fund
        yield "rw15m", (self.b15, self.b1h, self.b4h), Z.P_for(setup_tf="15m", use_htf=True, use_fresh=True, use_ltf=True), self.fund
        try:
            btc = [C.load_bars_df("BTC/USDT", tf) for tf in ("15m", "1h", "4h")]
        except Exception:
            return
        lo, hi = pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-04-30", tz="UTC")
        # keep warm-up history before `lo` so the indicators are stable; only the cut points are limited to [lo, hi]
        btc = [d[d["close_time"] <= hi].reset_index(drop=True) for d in btc]
        yield "btc", tuple(btc), IP.validate(G.ict_params("ict_L7")), None

    def test_g01_prefix_invariance(self):
        for name, (b15, b1h, b4h), P, fund in self._cases():
            full_F = G.build_features(Z.SYMBOL, b15, b1h, b4h, fund, P)
            full_ev, _, full_info = G.run_symbol(Z.SYMBOL, full_F, P)
            ct = full_F.m_ct
            lo = 0
            if name == "btc":
                lo = int(np.searchsorted(ct, int(pd.Timestamp("2024-02-01", tz="UTC").value // 1000)))
            rng = np.random.default_rng(11)
            cuts = sorted(set(int(x) for x in rng.integers(max(lo, 3000) if name != "btc" else lo, len(ct) - 1, size=20)))
            self.assertGreater(len(full_ev), 0, name)
            for c in cuts:
                t = int(ct[c])
                Fp = G.build_features(Z.SYMBOL, *cut_frames(b15, b1h, b4h, t), fund, P)
                ev_p, _, info_p = G.run_symbol(Z.SYMBOL, Fp, P)
                ev_s, _, info_s = G.run_symbol(Z.SYMBOL, full_F, P, stop_at_us=t)
                want = [e for e in full_ev if e.time <= t]
                self.assertEqual(ev_repr(ev_p), ev_repr(want), (name, c))
                self.assertEqual(ev_repr(ev_s), ev_repr(want), (name, c))
                self.assertEqual(info_p["state"], info_s["state"], (name, c))

    def test_g02_incremental_equals_batch(self):
        P = Z.P_for(setup_tf="1h", use_htf=True, use_ltf=True, use_funding=True)
        F = G.build_features(Z.SYMBOL, self.b15, self.b1h, self.b4h, self.fund, P)
        ev_all, tr_all, _ = G.run_symbol(Z.SYMBOL, F, P)
        self.assertGreater(len(ev_all), 0)
        state, prev, evs, trs = None, None, [], []
        for end in list(range(96, len(F.m_ct), 97)) + [len(F.m_ct) - 1]:
            e, t, info = G.run_symbol(Z.SYMBOL, F, P, stop_at_us=int(F.m_ct[end]), state=state, start_after_us=prev)
            evs += e
            trs += t
            state = pickle.loads(pickle.dumps(info["state"]))
            prev = int(F.m_ct[end])
        self.assertEqual(ev_repr(evs), ev_repr(ev_all))
        self.assertEqual(trs, [t for t in tr_all if t.reason != "end_of_data"])

    def _job(self, P, key="k"):
        ranks = {d: 1.0 for d in pd.date_range("2024-01-01", "2024-12-31").date}
        with mock.patch.object(C, "load_bars_df", side_effect=lambda s, tf: {"15m": self.b15, "1h": self.b1h, "4h": self.b4h}[tf]):
            return G.symbol_job((Z.SYMBOL, [(key, P)], ranks, self.fund))

    def test_g03_deterministic(self):
        P = Z.P_for(use_htf=True, use_ltf=True)
        a, b = self._job(P)["variants"]["k"], self._job(P)["variants"]["k"]
        pd.testing.assert_frame_equal(a[0], b[0])
        pd.testing.assert_frame_equal(a[1], b[1])
        self.assertGreater(len(a[0]), 0)
        self.assertTrue(a[0]["signal_id"].is_unique)

    def test_g04_schema(self):
        P = Z.P_for(use_htf=True, use_ltf=True)
        ev, st = self._job(P)["variants"]["k"]
        self.assertEqual(list(ev.columns), list(G.EVENT_DTYPES))
        for c, kind in G.EVENT_DTYPES.items():
            s = ev[c]
            if kind == "ts":
                self.assertEqual(str(s.dtype), "datetime64[us, UTC]", c)
            elif kind == "str":
                self.assertTrue(pd.api.types.is_string_dtype(s) and not pd.api.types.is_object_dtype(s), c)
            elif kind in ("int64", "float64", "bool"):
                self.assertEqual(str(s.dtype), kind, c)
            else:
                self.assertEqual(str(s.dtype), "object", c)
        self.assertEqual(str(ev["time"].dt.tz), "UTC")
        self.assertEqual(ev["tf"].unique().tolist(), ["15m"])
        self.assertTrue(set(ev["type"]) <= {"ict_long", "ict_short"})
        self.assertIsInstance(ev["universe_date"].iloc[0], date)
        self.assertEqual(list(st.columns), list(G.SETUP_DTYPES))
        self.assertEqual(ev["in_top20"].tolist(), (~ev["rank"].isna()).tolist())
        # an empty table has the same schema
        e0 = G.empty_events()
        self.assertEqual(list(e0.columns), list(ev.columns))
        self.assertEqual([str(x) for x in e0.dtypes], [str(x) for x in ev.dtypes])

    def test_g05_warmup(self):
        P = Z.P_for(use_htf=True, warmup_until="2024-04-01")
        ev, st = self._job(P)["variants"]["k"]
        self.assertGreater(len(ev), 0)
        self.assertTrue((ev["time"] >= pd.Timestamp("2024-04-01", tz="UTC")).all())
        self.assertGreater(int((st["reason"] == "warmup_dropped").sum()), 0)
        self.assertEqual(int(st["signal_id"].notna().sum()), len(ev))

    def test_g06_params_key(self):
        base = IP.validate(IP.DEFAULTS)
        k0 = IP.table_key(base)
        change = {"setup_tf": "15m", "anchor": "confirmed", "warmup_until": "2024-02-01", "random": dict(seed=1, match="m"),
                  "session_start_h": 8, "session_end_h": 20, "ote_lo": 0.5, "ote_hi": 0.8}
        for name, v in IP.DEFAULTS.items():
            if name == "version":
                continue
            if name in change:
                nv = change[name]
            elif isinstance(v, bool):
                nv = not v
            else:
                nv = v + 1 if isinstance(v, int) else v * 0.9
            self.assertNotEqual(IP.table_key(dict(base, **{name: nv})), k0, name)
        d = dict(base)
        d.pop("fvg_k")
        with self.assertRaises(sim.ConfigError):
            IP.validate(d)
        d = dict(base, extra=1)
        with self.assertRaises(sim.ConfigError):
            IP.validate(d)
        with self.assertRaises(sim.ConfigError):
            IP.validate(dict(base, version="ict-p0"))
        with self.assertRaises(sim.ConfigError):
            IP.validate(dict(base, swing_n=True))

    def test_g07_registration_matches_plan(self):
        text = PLAN.read_text()
        sec5 = text.split("## 5.")[1].split("### 5.1")[0]
        names = []
        for m in re.finditer(r"^\|\s*([\d–]+)\s*\|\s*(ict_[\w…\s]+?)\s*\|", sec5, re.M):
            if "–" in m.group(1):
                names += [f"ict_rsv{i}" for i in range(1, 6)]
            else:
                names.append(m.group(2).strip())
        self.assertEqual(names, [n for n, _, _ in G.EXPERIMENTS])
        self.assertEqual(len(names), 24)
        sec6 = text.split("## 6.")[1].split("## 7.")[0]
        self.assertEqual(re.findall(r"^\|\s*(ict_L7__nb_\w+)\s*\|", sec6, re.M), [n for n, _ in G.NEIGHBORS])
        self.assertEqual(len(G.NEIGHBORS), 4)
        seen = R.read_registry(C.OUT / "registry.md")
        for n, kind, _ in G.EXPERIMENTS:
            self.assertNotIn(n, seen)
            if kind != "reserved":
                sim.SimConfig.from_dict(G.experiment_dict(n))
        for n, _ in G.NEIGHBORS:
            self.assertNotIn(n, seen)
            sim.SimConfig.from_dict(G.experiment_dict(n))
        self.assertEqual(R.n_main(seen) + len(G.EXPERIMENTS), R.MAX_EXPERIMENTS)

    def test_g08_random_counts(self):
        match = Z.P_for(use_htf=True, use_session=True)
        ev, _ = self._job(match, "m")["variants"]["m"]
        self.assertGreater(len(ev), 5)
        q = C.quarter_of_series(ev["time"])
        counts = {(int(s), qq): int(n) for (s, qq), n in ev.assign(q=q).groupby(["side", "q"]).size().items()}
        rp = dict(match, random={"seed": 5, "match": "m"})
        ranks = {d: 1.0 for d in pd.date_range("2024-01-01", "2024-12-31").date}

        def draw():
            with mock.patch.object(C, "load_bars_df", side_effect=lambda s, tf: {"15m": self.b15, "1h": self.b1h, "4h": self.b4h}[tf]):
                return G.symbol_job((Z.SYMBOL, [("r", rp)], ranks, self.fund, {"r": counts}))["variants"]["r"][0]

        a, b = draw(), draw()
        pd.testing.assert_frame_equal(a, b)
        qa = C.quarter_of_series(a["time"])
        got = {(int(s), qq): int(n) for (s, qq), n in a.assign(q=qa).groupby(["side", "q"]).size().items()}
        self.assertEqual(got, counts)
        self.assertTrue((a["trigger_kind"] == "random").all())
        self.assertTrue(a["signal_id"].is_unique)
        self.assertTrue(((a["side"] == -1) == (a["defending_price"] > a["close"])).all())

    def test_g09_count_no_pnl(self):
        def mk(oos):
            t = pd.to_datetime(["2024-03-01", "2025-05-01"] + (["2025-08-01"] if oos else []), utc=True).astype("datetime64[us, UTC]")
            smp = ["IS", "IS"] + (["OOS"] if oos else [])
            sid = [f"s{i}" for i in range(len(t))]
            return {
                "key": "abc",
                "setups": pd.DataFrame({"setup_id": sid, "side": [-1, 1, -1][:len(t)], "bos_time": t, "max_phase": ["TRIGGERED", "BOS", "IN_ZONE"][:len(t)],
                                        "reason": [None, "no_sweep", "session"][:len(t)], "sample": smp}),
                "events_raw": pd.DataFrame({"time": t, "side": [-1, 1, -1][:len(t)], "sample": smp}),
                "events_sel": pd.DataFrame({"time": t, "side": [-1, 1, -1][:len(t)], "symbol": ["A/USDT", "B/USDT", "A/USDT"][:len(t)], "sample": smp}),
            }

        with mock.patch.object(sim, "simulate", side_effect=AssertionError), mock.patch.object(sim, "simulate_symbol", side_effect=AssertionError):
            md = G.funnel_markdown({"ict_L7": mk(True)}, {"n_symbols": 591})
        md_is = G.funnel_markdown({"ict_L7": mk(False)}, {"n_symbols": 591})
        self.assertEqual(md, md_is)  # OOS rows are dropped on entry
        for bad in (r"2025Q3", r"2025-07", r"\bnet\b", r"\bR\b", r"gross", r"\bpf\b", r"pnl"):
            self.assertIsNone(re.search(bad, md, re.I if bad == r"pnl" else 0), bad)
        self.assertIn("ict_L7 IS 事件數 = 2", md)
        self.assertNotIn("simulate", inspect.getsource(G.count))


if __name__ == "__main__":
    unittest.main()
