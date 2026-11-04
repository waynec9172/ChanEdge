"""Donchian benchmark (user note 2-4): breakouts use closed bars only, entry at the next open."""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from research import common as C, donchian, sim
from research.tests.test_sim import BASE_US, FLAT, SLIP, STEP, col, make_cfg, make_sig, run


def rising_series(n_flat=100, n_up=20):
    h = np.r_[np.full(n_flat, 101.0), 101.0 + 5.0 * np.arange(1, n_up + 1)]
    lo = np.r_[np.full(n_flat, 99.0), 99.0 + 5.0 * np.arange(1, n_up + 1)]
    c = np.r_[np.full(n_flat, 100.0), 100.0 + 5.0 * np.arange(1, n_up + 1)]
    return h, lo, c


class DonchianTests(unittest.TestCase):
    def test_d1_breakout_uses_closed_bars_only(self):
        h, lo, c = rising_series()
        rng = np.random.default_rng(3)
        rc = 100 + np.cumsum(rng.normal(0, 1.0, 500))
        rh, rl = rc + rng.uniform(0.1, 1.0, 500), rc - rng.uniform(0.1, 1.0, 500)
        for n in donchian.NS:
            up, dn = donchian.breakouts(h, lo, c, n)
            self.assertEqual(list(np.flatnonzero(up)), [100], n)  # only the first breakout bar fires
            self.assertFalse(dn.any())
            fu, fd = donchian.breakouts(rh, rl, rc, n)
            for t in (150, 260, 399):
                pu, pd_ = donchian.breakouts(rh[: t + 1], rl[: t + 1], rc[: t + 1], n)
                self.assertTrue((pu == fu[: t + 1]).all() and (pd_ == fd[: t + 1]).all(), (n, t))  # nothing after t matters
            # the signal at t is a pure function of bars <= t: perturb the future
            h2 = rh.copy()
            h2[300:] += 1000
            up2, _ = donchian.breakouts(h2, rl, rc, n)
            self.assertTrue((up2[:300] == fu[:300]).all())

    def test_d2_entry_next_open(self):
        n = 25
        t = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
        h, lo, c = rising_series(20, 5)
        bars = pd.DataFrame({"open_time": t, "close_time": t + pd.Timedelta(hours=1), "high": h, "low": lo, "close": c})
        with mock.patch.object(C, "load_bars_df", return_value=bars):
            df = donchian.signals_for("X/USDT", "1h", {})
        d = df[(df["n"] == 16) & (df["side"] == 1)]
        self.assertEqual(len(d), 1)
        self.assertEqual(d["time"].iloc[0], bars["close_time"].iloc[20])  # time = close_time of the breakout bar
        # simulation: enters at the open of the 15m bar whose open_time == time, never earlier
        sig = make_sig(entry_idx=4, defending=95.0, atr=2.0)
        sig["tf"] = "1h"
        rows = [(50.0, 60.0, 40.0, 50.0)] * 4 + [FLAT, FLAT]
        out, _ = run(make_cfg(), rows, sig)
        self.assertEqual(col(out, "entry_time"), BASE_US + 4 * STEP)
        self.assertAlmostEqual(col(out, "entry_price"), 100.0 * (1 + SLIP), places=12)

    @unittest.skipUnless(all((C.CACHE / f"signals_donchian_{tf}.p0.parquet").exists() for tf in ("1h", "4h")), "phase 0 copy missing")
    def test_d3_rebuilt_tables_keep_20_55(self):
        for tf in ("1h", "4h"):
            new = pd.read_parquet(C.CACHE / f"signals_donchian_{tf}.parquet")
            old = pd.read_parquet(C.CACHE / f"signals_donchian_{tf}.p0.parquet")
            self.assertEqual(sorted(new["n"].unique()), sorted(donchian.NS_BY_TF[tf]))  # phase 1b: 4h now carries NS_ALL, 1h is unchanged
            keys = ["time", "symbol", "n", "type"]
            a = new[new["n"].isin([20, 55])].sort_values(keys).reset_index(drop=True)
            b = old.sort_values(keys).reset_index(drop=True)
            pd.testing.assert_frame_equal(a[b.columns], b)

    def test_d4_opposite_same_n_only(self):
        t = pd.Timestamp("2025-01-01 05:00", tz="UTC")
        df = pd.DataFrame(
            {
                "symbol": ["X/USDT"] * 3,
                "side": [-1, -1, -1],
                "time": [t, t + pd.Timedelta(hours=1), t + pd.Timedelta(hours=2)],
                "n": [20, 55, 20],
            }
        )
        cfg = make_cfg(
            signals={"source": "donchian", "tf": "1h", "types": ["dc20_long", "dc20_short"], "donchian_n": 20},
            exit={"opposite_signal": {"enabled": True, "tf": "1h"}},
        )
        with mock.patch.object(sim, "load_signal_table", return_value=df):
            opp = sim.opposite_times(cfg)
        got = [int(x) for x in opp["X/USDT"][-1]]
        want = [int(pd.Timestamp(x).value // 1000) for x in (t, t + pd.Timedelta(hours=2))]
        self.assertEqual(got, want)  # the N = 55 breakout is ignored

    @unittest.skipUnless((C.CACHE / "signals_donchian_4h.p1.parquet").exists() and (C.CACHE / "signals_donchian_1d.parquet").exists(), "phase 1b tables missing")
    def test_d8_rebuilt_4h_keeps_old_n(self):
        new = pd.read_parquet(C.CACHE / "signals_donchian_4h.parquet")
        old = pd.read_parquet(C.CACHE / "signals_donchian_4h.p1.parquet")
        keys = ["symbol", "type", "time"]
        a = new[new["n"].isin(donchian.NS_BY_TF["1h"])].sort_values(keys).reset_index(drop=True)
        b = old.sort_values(keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(a[b.columns], b)
        self.assertEqual(sorted(new["n"].unique()), sorted(donchian.NS_ALL))
        d1 = pd.read_parquet(C.CACHE / "signals_donchian_1d.parquet")
        self.assertEqual(sorted(d1["n"].unique()), sorted(donchian.NS_ALL))
        self.assertTrue((d1["time"].dt.hour == 0).all() and (d1["time"].dt.minute == 0).all())


if __name__ == "__main__":
    unittest.main()
