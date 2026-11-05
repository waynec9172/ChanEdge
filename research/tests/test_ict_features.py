"""ICT swings, FVG, HTF helpers (synthetic data only)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research.ict import fvg as FV
from research.ict import htf as HT
from research.ict.swings import swings
from research.tests import ict_synth as Z


class FeatureTests(unittest.TestCase):
    def test_i01_swing_confirm_time(self):
        h = np.array([1, 2, 5, 3, 4, 1, 1], dtype=float)
        ph, pp, _, _ = swings(h, h - 0.5, 2)
        self.assertEqual(list(ph), [2])
        self.assertEqual(float(pp[0]), 5.0)
        self.assertEqual(int(ph[0]) + 2, 4)
        self.assertNotIn(2, list(swings(h[:4], (h - 0.5)[:4], 2)[0]))
        self.assertIn(2, list(swings(h[:5], (h - 0.5)[:5], 2)[0]))

    def test_i02_swing_ties(self):
        h = np.array([1, 5, 5, 3, 2, 1], dtype=float)
        ph, _, _, _ = swings(h, h - 0.5, 1)
        self.assertEqual(list(ph), [1])  # left strict, right may be equal
        lo = np.array([5, 1, 1, 3, 4, 5], dtype=float)
        _, _, pl, _ = swings(lo + 0.5, lo, 1)
        self.assertEqual(list(pl), [1])

    def test_i03_swing_n(self):
        from research.ict import generate as G

        for n in (1, 3):
            P = Z.P_for(swing_n=n)
            F = Z.features(Z.SHORT_BASE, P, htf=(True, True))
            self.assertGreater(len(F.sh_pivot), 0)
            self.assertTrue((F.sh_conf == F.sh_pivot + n).all())
            self.assertTrue((F.sl_conf == F.sl_pivot + n).all())
            self.assertTrue((F.m_sh_conf == F.m_sh_pivot + n).all())
        self.assertIs(G.Features, type(F))

    def test_i04_fvg_boundary(self):
        k = 0.5
        atr = np.array([np.nan, np.nan, 2.0])
        low = np.array([10.0, 9.0, 8.5])
        high = np.array([11.0, 10.0, 9.0])
        self.assertEqual(len(FV.fvgs(high, low, atr, k)["idx"]), 0)  # gap == k*atr exactly
        high2 = high.copy()
        high2[2] = 9.0 - 1e-9
        g = FV.fvgs(high2, low, atr, k)
        self.assertEqual(list(g["idx"]), [2])
        self.assertEqual(list(g["side"]), [-1])
        self.assertEqual(g["lo"][0], high2[2])
        self.assertEqual(g["hi"][0], low[0])
        self.assertEqual(len(FV.fvgs(high2, low, np.full(3, np.nan), k)["idx"]), 0)
        # bullish mirror
        lowb = np.array([8.5, 9.0, 10.0])
        highb = np.array([9.0, 10.0, 11.0])
        self.assertEqual(len(FV.fvgs(highb, lowb, atr, k)["idx"]), 0)
        lowb2 = lowb.copy()
        lowb2[2] = 10.0 + 1e-9
        g = FV.fvgs(highb, lowb2, atr, k)
        self.assertEqual((list(g["idx"]), list(g["side"])), ([2], [1]))
        self.assertEqual((g["lo"][0], g["hi"][0]), (highb[0], lowb2[2]))

    def test_i05_fvg_touch_kill(self):
        step = 900_000_000
        created = 10 * step
        ot = np.arange(6) * step + 9 * step  # first bar opens one step before the creation close
        h = np.array([105.0, 99.0, 99.5, 100.5, 102.0, 103.0])
        l = h - 1
        side, lo, hi = np.array([-1]), np.array([100.0]), np.array([101.0])
        t = FV.first_touch(side, lo, hi, np.array([created]), ot, h, l)
        self.assertEqual(int(t[0]), int(ot[3] + step))  # bar 0 (open < created, h >= lo) is ignored; bar 3 is the first with h >= lo
        none = FV.first_touch(side, np.array([200.0]), np.array([201.0]), np.array([created]), ot, h, l)
        self.assertEqual(int(none[0]), FV.INT64_MAX)
        bull = FV.first_touch(np.array([1]), np.array([90.0]), np.array([100.0]), np.array([created]), ot, h, l)
        self.assertEqual(int(bull[0]), int(ot[1] + step))  # l = 98 <= hi = 100 on bar 1
        s_close = np.array([100.0, 100.0, 100.0, 100.5, 101.5, 99.0])
        s_ct = (np.arange(6) + 1) * step
        k = FV.kill_time(side, lo, hi, np.array([2]), s_close, s_ct)
        self.assertEqual(int(k[0]), int(s_ct[4]))  # first close > hi after idx 2
        kb = FV.kill_time(np.array([1]), lo, hi, np.array([2]), s_close, s_ct)
        self.assertEqual(int(kb[0]), int(s_ct[5]))  # first close < lo

    def test_i06_htf_alignment(self):
        h = 3_600_000_000
        ct = np.array([4 * h, 8 * h, 12 * h])
        self.assertEqual(list(HT.align(ct, np.array([8 * h, 8 * h - 900_000_000, 3 * h]))), [1, 0, -1])
        e = HT.ema(np.arange(1.0, 61.0), 50)
        self.assertTrue(np.isnan(e[:49]).all())
        self.assertFalse(np.isnan(e[49]))
        b4 = _h4(low=np.linspace(100, 90, 10), close=np.linspace(100, 90, 10))
        _, bear, bull = HT.htf_flags(b4, 2, 50)
        self.assertFalse(bear.any())  # EMA NaN and no two swing lows

    def test_i07_htf_either(self):
        lows = np.array([10, 9, 7, 9, 10, 9, 8, 5, 8, 9, 10], dtype=float)
        _, bear, _ = HT.htf_flags(_h4(low=lows, close=lows + 0.5), 2, 50)  # only the swing-low condition can hold (EMA is NaN)
        self.assertEqual([bool(x) for x in bear], [False] * 9 + [True, True])
        c = np.r_[np.linspace(100, 160, 59), 90.0]  # rising line then a close far below the EMA
        b = _h4(low=c - 1, close=c)
        _, bear, bull = HT.htf_flags(b, 2, 50)
        self.assertTrue(bear[59])  # close < EMA only
        self.assertFalse(bear[58])  # neither condition
        self.assertTrue(bull[58])
        self.assertFalse(bull[59])


def _h4(low, close):
    n = len(low)
    ot = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC").astype("datetime64[us, UTC]")
    return pd.DataFrame({
        "open_time": ot, "close_time": ot + pd.Timedelta(hours=4), "open": close, "high": np.asarray(low) + 1.0,
        "low": low, "close": close, "volume": np.ones(n),
    })


if __name__ == "__main__":
    unittest.main()
