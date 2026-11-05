"""1h / 4h signals must not look into the future (user note 2-1). Synthetic bars unless a test says it reads the cache."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from research import augment, common as C, donchian, signals as S, sim
from research.tests.test_sim import BASE_CFG, BASE_US, FLAT, MAKER, SLIP, STEP, TAKER, col, ct, make_bars, make_cfg, make_sig, run

EXT = (100.0, 130.0, 80.0, 100.0)  # would hit any stop and any target


def htf_sig(tf, entry_idx, **kw):
    s = make_sig(entry_idx=entry_idx, **kw)
    s["tf"] = tf
    return s


class HtfTests(unittest.TestCase):
    def _entry_after_close(self, tf, entry_idx):
        exit_ = {"fixed_r": {"enabled": True, "r": 1.0}}
        rows = [EXT] * entry_idx + [FLAT, FLAT, FLAT, (100.0, 103.0, 99.5, 102.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, htf_sig(tf, entry_idx))
        R = 100.0 - 97.85
        pe = 100.0 * (1 + SLIP)
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_time"), BASE_US + entry_idx * STEP)
        self.assertAlmostEqual(col(out, "entry_price"), pe, places=12)
        self.assertEqual(col(out, "exit_reason"), "fixed_r")
        self.assertEqual(col(out, "bars_held"), 3)  # the extreme bars before the signal close are not on the path
        self.assertAlmostEqual(col(out, "mfe_r"), (103.0 - pe) / R, places=9)
        self.assertGreater(col(out, "mae_r"), -1.0)

    def test_h1_htf_entry_starts_after_signal_close(self):
        self._entry_after_close("1h", 4)
        self._entry_after_close("4h", 16)

    @unittest.skipUnless((C.CACHE / "signals_4h.parquet").exists(), "signal cache missing")
    def test_h2_htf_signal_time_is_tf_close(self):
        b15 = pd.read_parquet(C.CACHE / "bars_15m.parquet", columns=["symbol", "open_time"])
        for tf in ("1h", "4h"):
            df = pd.read_parquet(C.CACHE / f"signals_{tf}.parquet", columns=["symbol", "time", "in_top20"])
            t = df["time"].dt.tz_convert("UTC")
            self.assertTrue(((t.dt.minute == 0) & (t.dt.second == 0)).all())
            if tf == "4h":
                self.assertTrue((t.dt.hour % 4 == 0).all())
            # equals the close_time of a closed tf bar (3 symbols, all their signals)
            for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
                bars = C.load_bars_df(sym, tf)
                mine = df[df["symbol"] == sym]["time"]
                self.assertGreater(len(mine), 50)
                self.assertTrue(mine.isin(bars["close_time"]).all(), (tf, sym))
            # a 15m bar opening exactly at the signal time exists (the price path starts there)
            sub = df[df["in_top20"]].sample(300, random_state=1)
            m = sub.merge(b15, left_on=["symbol", "time"], right_on=["symbol", "open_time"], how="left")
            self.assertTrue(m["open_time"].notna().all(), tf)

    def test_h3_walk_1h_4h_truncation(self):
        for tf in ("1h", "4h"):
            bars = S.closed_bars(tf, "BTC/USDT")[:9000]
            full = S.walk(bars, tf)
            self.assertGreater(len(full.signals), 20)
            for frac in (0.4, 0.6, 0.85):
                n = int(len(bars) * frac)
                part = S.walk(bars[:n], tf)
                cut = bars[n - 1].close_time
                a = {(x.signal.id, x.signal.defending_price) for x in part.signals if x.signal.time <= cut}
                b = {(x.signal.id, x.signal.defending_price) for x in full.signals if x.signal.time <= cut}
                self.assertEqual(a, b, (tf, n))
                ea = part.bi_events[part.bi_events["confirm_time"] <= cut].reset_index(drop=True)
                eb = full.bi_events[full.bi_events["confirm_time"] <= cut].reset_index(drop=True)
                pd.testing.assert_frame_equal(ea, eb)

    def test_h4_bias_uses_closed_4h_only(self):
        t0 = pd.Timestamp("2025-01-01 00:00", tz="UTC")
        df = pd.DataFrame({"close_time": [t0, t0 + pd.Timedelta(hours=4)], "bias": ["up", "down"]})
        at = lambda ts: S._lookup_bias(df, pd.Timestamp(ts, tz="UTC").to_pydatetime())
        self.assertEqual(at("2025-01-01 03:45"), "up")
        self.assertEqual(at("2025-01-01 03:59:59"), "up")
        self.assertEqual(at("2025-01-01 04:00"), "down")
        # 1h bias exit: a flag that changes at the 01:00 close affects only 15m bars closing at or after 01:00
        bias = (np.array([BASE_US + 4 * STEP], dtype="int64"), np.array([True]), np.array([False]))  # 01:00 = ct(3)
        rows = [FLAT] * 7
        out, _ = run(make_cfg(exit={"bias_1h": {"enabled": True}}), rows, make_sig(), bias=bias)
        self.assertEqual(col(out, "exit_reason"), "bias_1h")
        self.assertEqual(col(out, "exit_time"), BASE_US + 4 * STEP)  # bar 3 (close 01:00) reviews, bar 4 opens the exit

    def test_h5_htf_filter_and_vol_band(self):
        rows = []
        for i, (side, bias, atr) in enumerate(
            [(1, "breakout_up", 0.002), (1, "up", 0.002), (1, "down", 0.002), (1, "range", 0.002),
             (-1, "breakout_down", 0.002), (-1, "down", 0.002), (-1, "up", 0.002), (-1, "breakout_up", 0.002),
             (1, "up", 0.001), (1, "up", 0.03), (1, "up", 0.00099), (1, "up", 0.0301), (1, "up", np.nan)]
        ):
            rows.append({"signal_id": f"s{i}", "symbol": "A/USDT", "tf": "1h", "type": "second_buy" if side == 1 else "second_sell",
                         "side": side, "time": pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=i + 1), "in_top20": True,
                         "bias_4h": bias, "atr15_pct": atr})
        df = pd.DataFrame(rows)
        cfg = make_cfg(filters={**BASE_CFG["filters"], "htf_4h": True}, signals={**BASE_CFG["signals"], "tf": "1h", "types": ["second_buy", "second_sell"]})
        with mock.patch.object(sim, "load_signal_table", return_value=df):
            got = sim.select_signals(cfg)
            self.assertEqual(list(got["signal_id"]), ["s0", "s1", "s4", "s5", "s8", "s9", "s10", "s11", "s12"])
            cfg2 = make_cfg(filters={**BASE_CFG["filters"], "vol_band": True}, signals={**BASE_CFG["signals"], "tf": "1h", "types": ["second_buy", "second_sell"]})
            got2 = sim.select_signals(cfg2)
            # closed interval [0.001, 0.03]; NaN rejected
            self.assertEqual(sorted(got2["signal_id"]), sorted(f"s{i}" for i in list(range(0, 8)) + [8, 9]))

    def test_h6_atr15_pct_at_signal_close(self):
        rng = np.random.default_rng(7)
        n = 80
        c = 100 + np.cumsum(rng.normal(0, 0.3, n))
        h, l = c + 0.4, c - 0.4
        ct_ns = (BASE_US * 1000 + (np.arange(n) + 1) * STEP * 1000).astype("int64")
        k = 50
        base = augment.atr15_pct_at(ct_ns, h, l, c, ct_ns[[k]])[0]
        h2, l2, c2 = h.copy(), l.copy(), c.copy()
        h2[k + 1 :], l2[k + 1 :], c2[k + 1 :] = 500.0, 1.0, 250.0  # the future turns extreme
        self.assertEqual(augment.atr15_pct_at(ct_ns, h2, l2, c2, ct_ns[[k]])[0], base)
        expect = donchian.wilder_atr_np(h[: k + 1], l[: k + 1], c[: k + 1], 14)[k] / c[k]
        self.assertAlmostEqual(base, expect, places=12)
        self.assertTrue(np.isnan(augment.atr15_pct_at(ct_ns, h, l, c, np.array([ct_ns[k] + 1]))[0]))

    def test_h7_htf_ratchet_uses_tf_bi_at_its_close(self):
        exit_ = {"breakeven": {"enabled": True, "arm_r": 1.0}, "ratchet": {"enabled": True}}
        # break-even armed on bar 1; the 1h bi event is confirmed at the close of bar 2 (ct(2)) -> stop moves for bar 3
        rows = [FLAT, (100.0, 102.5, 99.5, 102.0), (102.0, 103.0, 101.0, 102.5), (103.5, 104.0, 102.8, 103.0), FLAT]
        bi = (np.array([ct(2)], dtype="int64"), np.array([np.nan]), np.array([103.0]))
        out, _ = run(make_cfg(exit=exit_), rows, htf_sig("1h", 1), bi=bi)
        self.assertEqual(col(out, "exit_reason"), "ratchet_stop")
        self.assertEqual(col(out, "exit_time"), BASE_US + 3 * STEP)  # stop 102.85 set after bar 2, hit by bar 3 (low 102.8)
        # an event one bar later cannot act earlier
        bi_late = (np.array([ct(3)], dtype="int64"), np.array([np.nan]), np.array([103.0]))
        out2, _ = run(make_cfg(exit=exit_), rows, htf_sig("1h", 1), bi=bi_late)
        self.assertEqual(col(out2, "exit_time"), BASE_US + 4 * STEP)  # acts one bar later, never earlier

    def test_h8_htf_tp1_uses_tp_columns(self):
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5}}
        sig = htf_sig("1h", 1, up_end=103.0)
        sig["tp_up_end"] = 105.0
        sig["tp_down_end"] = np.nan
        rows = [FLAT, (100.0, 104.0, 99.5, 103.5), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, sig)
        self.assertFalse(col(out, "tp1_hit"))  # last_up_end 103 would have been hit; tp_up_end 105 is not
        rows = [FLAT, (100.0, 105.5, 99.5, 103.5), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, sig)
        self.assertTrue(col(out, "tp1_hit"))


if __name__ == "__main__":
    unittest.main()
