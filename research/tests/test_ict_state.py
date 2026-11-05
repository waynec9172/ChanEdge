"""ICT state machine on hand-built 15m paths (setup TF = 15m so a bar is both a setup bar and a trigger bar)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research.ict import state as ST
from research.tests import ict_synth as Z
from research.tests.ict_synth import SHORT_BASE as B

STEP = 900_000_000


def ct(i, start=Z.START):
    return int(start.value // 1000) + (i + 1) * STEP


def inv(tr, side=-1):
    return [t.reason for t in tr if t.side == side and t.to == "INVALID"]


def run(rows, P=None, **kw):
    return Z.run(rows, P or Z.P_for(), **kw)


def with_bars(rows, upto, extra):
    return list(rows[:upto]) + list(extra)


FILL = (99.0, 99.25, 98.5, 99.0)


class StateTests(unittest.TestCase):
    def test_base_scenario_event(self):
        _, ev, tr, _ = run(B)
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0].side, ev[0].time, ev[0].trigger_kind), (-1, ct(50), "touch"))
        self.assertEqual(ev[0].defending, 101.5)
        self.assertAlmostEqual(ev[0].tp2, 95.5 - 0.618 * (101.5 - 95.5), places=9)

    def test_s01_bos_needs_close(self):
        eq = with_bars(B, 43, [(100.5, 100.5, 97.5, 98.0)])
        _, ev, tr, _ = run(eq)
        self.assertEqual([t for t in tr if t.side == -1], [])
        lt = with_bars(B, 43, [(100.5, 100.5, 97.5, 97.75)])
        _, ev, tr, _ = run(lt)
        bos = [t for t in tr if t.side == -1 and t.reason == "bos"]
        self.assertEqual(len(bos), 1)
        self.assertEqual(bos[0].to, "BOS_CONFIRMED")

    def test_s02_sweep_vs_bos(self):
        base = with_bars(B, 43, [B[42]])
        eq = base + [(101.0, 102.0, 100.75, 101.5)]
        F, _, tr, _ = run(eq)
        self.assertTrue(F.sweep_dn[44])
        self.assertEqual([t for t in tr if t.side == 1], [])
        up = base + [(101.0, 102.0, 100.75, 101.75)]
        F, _, tr, _ = run(up)
        self.assertFalse(F.sweep_dn[44])
        self.assertEqual([(t.to, t.reason) for t in tr if t.side == 1][:1], [("BOS_CONFIRMED", "bos")])

    def test_s03_causal_anchor(self):
        rows = with_bars(B, 43, [
            (100.5, 100.5, 97.5, 97.75),   # b = 43
            (97.75, 99.5, 97.0, 97.5),     # b+1 new low
            (97.5, 98.0, 97.25, 97.75),    # b+2 higher low
            (97.75, 97.75, 96.0, 96.25),   # b+3 new low
            (96.25, 97.0, 96.25, 96.75),   # b+4
            (96.75, 97.0, 96.5, 96.75),
        ])
        P = Z.P_for()
        F = Z.features(rows, P, htf=(True, True))
        from research.ict import generate as G

        def st(k):
            return G.run_symbol(Z.SYMBOL, F, P, stop_at_us=ct(k))[2]["state"][0]

        self.assertIsNone(st(44).setup.a0)
        self.assertEqual(st(45).setup.a0, 97.0)
        self.assertEqual(st(45).setup.a0, float(F.S_l[44]))
        zt = st(45).setup.zone_time
        self.assertEqual(zt, ct(45))
        self.assertEqual(st(46).setup.a0, 97.0)  # new low on b+3 is not usable on its own close
        s47 = st(47)
        self.assertEqual(s47.setup.a0, 96.0)
        self.assertEqual(s47.setup.zone_time, zt)
        _, tr, _ = G.run_symbol(Z.SYMBOL, F, P, stop_at_us=ct(47))
        self.assertEqual([t.reason for t in tr if t.reason == "reanchor"], ["reanchor"])
        self.assertEqual([t.time for t in tr if t.reason == "reanchor"], [ct(47)])

    def test_s04_freshness(self):
        rows = with_bars(B, 43, [
            (100.5, 100.5, 97.5, 97.75),
            (97.75, 99.5, 97.0, 97.5),
            (97.5, 99.75, 97.25, 97.75),   # b+2 touches the FVG (h >= 99.5) before the zone exists
            (97.75, 98.0, 97.25, 97.5),
            (97.5, 98.0, 97.25, 97.5),
            (97.5, 98.0, 97.25, 97.5),
        ])
        _, _, tr, _ = run(rows, Z.P_for(use_fresh=True))
        self.assertEqual(inv(tr)[0], "stale_fvg")
        _, _, tr, _ = run(rows, Z.P_for(use_fresh=False))
        self.assertIn("zone_built", [t.reason for t in tr])
        _, _, tr, _ = run(rows, Z.P_for(use_fresh=True, anchor="confirmed"))
        self.assertEqual(inv(tr)[0], "stale_fvg")
        _, _, tr, _ = run(rows, Z.P_for(use_fresh=False, anchor="confirmed"))
        self.assertIn("zone_built", [t.reason for t in tr])

    def test_s05_no_anchor1(self):
        rows = [Z.FLAT] * 30 + [
            (99.75, 100.0, 99.0, 99.25), (99.25, 99.5, 98.5, 98.75), (98.75, 99.0, 98.0, 98.25),
            (98.25, 98.75, 98.0, 98.5), (98.5, 98.9, 98.25, 98.6), (98.6, 98.7, 96.9, 97.0),
        ]
        _, ev, tr, _ = run(rows)
        self.assertEqual(inv(tr), ["no_anchor1"])
        self.assertEqual(ev, [])

    def test_s06_htf_reject_and_lost(self):
        P = Z.P_for(use_htf=True)
        _, ev, tr, _ = run(B, P, htf=(False, False))
        self.assertEqual((inv(tr), ev), (["htf_reject"], []))
        _, ev, tr, _ = run(B, P, htf=([True, True, False], [False] * 3))
        self.assertEqual(inv(tr)[0], "htf_lost")
        self.assertEqual(ev, [])
        _, ev, tr, _ = run(B, P, htf=(True, False))
        self.assertEqual(len(ev), 1)
        self.assertTrue(dict(ev[0].setup.flags)["htf"])

    def test_s07_no_expansion(self):
        _, ev, tr, _ = run(B, Z.P_for(use_expansion=True, exp_tr_atr=100.0, exp_vol_mult=100.0))
        self.assertEqual((inv(tr), ev), (["no_expansion"], []))
        _, ev, _, _ = run(B, Z.P_for(use_expansion=True))
        self.assertEqual(len(ev), 1)

    def test_s08_no_sweep(self):
        _, ev, tr, _ = run(B, Z.P_for(use_sweep=True))
        self.assertEqual((inv(tr), ev), (["no_sweep"], []))
        swept = Z.replace_bar(B, 38, (98.5, 104.25, 98.5, 99.5))
        # the tall bar 38 inflates the ATR, so a smaller fvg_k keeps the same FVG qualifying
        F, ev, _, _ = run(swept, Z.P_for(use_sweep=True, fvg_k=0.2))
        self.assertTrue(F.sweep_dn[38])
        self.assertEqual(len(ev), 1)
        self.assertTrue(dict(ev[0].setup.flags)["sweep"])

    def test_s09_replaced(self):
        rows = with_bars(B, 48, [(97.0, 97.0, 94.5, 94.75)])
        _, ev, tr, _ = run(rows)
        self.assertEqual(inv(tr)[0], "replaced")
        self.assertEqual(ev, [])

    def test_s10_close_above_anchor1(self):
        rows = with_bars(B, 48, [(97.0, 102.0, 96.75, 101.75)])
        _, ev, tr, _ = run(rows)
        self.assertEqual((inv(tr)[0], ev), ("close_above_anchor1", []))

    def test_s11_zone_empty(self):
        _, ev, tr, _ = run(B, Z.P_for(ote_lo=0.9, ote_hi=0.95))
        self.assertEqual((inv(tr)[0], ev), ("zone_empty", []))

    def test_s12_close_above_zone(self):
        rows = with_bars(B, 48, [(97.0, 101.0, 96.75, 100.75)])
        _, ev, tr, _ = run(rows)
        self.assertEqual((inv(tr)[0], ev), ("close_above_zone", []))

    def test_s13_zone_expired(self):
        # zone is built at the close of bar 44; the touch is on bar 50, i.e. the 6th setup bar after creation
        _, ev, _, _ = run(B, Z.P_for(zone_valid_bars=6))
        self.assertEqual(len(ev), 1)
        _, ev, tr, _ = run(B, Z.P_for(zone_valid_bars=5))
        self.assertEqual((inv(tr)[0], ev), ("zone_expired", []))

    def _ltf_rows(self, wick_at, n_fill_until=None):
        rows = list(B[:51])
        for i in range(51, 80):
            rows.append(Z.replace_bar([FILL], 0, FILL)[0])
        rows[wick_at] = (98.0, 100.0, 97.75, 98.25)  # R 2.25: wick 1.75 >= 1.125, close <= low + 0.75
        return rows

    def test_s14_no_trigger(self):
        P = Z.P_for(use_ltf=True)
        _, ev, tr, _ = run(self._ltf_rows(65), P)  # touch bar is #1 -> bar 65 is #16
        self.assertEqual((len(ev), ev[0].trigger_kind, ev[0].time), (1, "wick", ct(65)))
        _, ev, tr, _ = run(self._ltf_rows(66), P)
        self.assertEqual((inv(tr)[0], ev), ("no_trigger", []))

    def test_s15_session(self):
        P = Z.P_for(use_session=True)
        # decision time T = close of bar 50 = start + 51 bars
        for start, ok in (("2024-03-04 08:15", False), ("2024-03-03 18:15", True), ("2024-03-09 00:00", False), ("2024-03-04 08:00", True)):
            s = pd.Timestamp(start, tz="UTC")
            _, ev, tr, _ = run(B, P, start=s)
            self.assertEqual(len(ev), 1 if ok else 0, start)
            if not ok:
                self.assertEqual(inv(tr)[0], "session")
            else:
                self.assertTrue(ev[0].f_session)

    def test_s16_funding(self):
        T = ct(50)

        def fund(rate, age_h=3.0):
            return (np.array([T - int(age_h * 3_600_000_000)], dtype="int64"), np.array([rate]))

        P = Z.P_for(use_funding=True)
        _, ev, tr, _ = run(B, P, funding=fund(-0.0005))
        self.assertEqual((inv(tr)[0], ev), ("funding", []))
        _, ev, _, _ = run(B, P, funding=fund(-0.00049))
        self.assertEqual((len(ev), ev[0].funding_rate), (1, -0.00049))
        _, ev, _, _ = run(B, P, funding=fund(-0.0005, age_h=25))  # stale: unknown -> pass
        self.assertEqual(len(ev), 1)
        self.assertTrue(np.isnan(ev[0].funding_rate))
        _, ev, _, _ = run(B, P, funding=fund(0.01))  # positive funding never blocks a short
        self.assertEqual(len(ev), 1)
        m = Z.mirror_rows(B)
        _, ev, tr, _ = run(m, P, funding=fund(0.0005))
        self.assertEqual((inv(tr, 1)[0], ev), ("funding", []))
        _, ev, _, _ = run(m, P, funding=fund(0.00049))
        self.assertEqual(len(ev), 1)

    def test_s17_ltf_boundaries(self):
        P = Z.P_for(use_ltf=True)

        def with_bar51(bar):
            return list(B[:51]) + [bar]

        _, ev, _, _ = run(with_bar51((98.5, 100.0, 97.0, 98.0)))  # wick exactly 0.5R, close exactly low + R/3 (P_for default: no ltf -> touch)
        self.assertEqual(ev[0].trigger_kind, "touch")
        _, ev, _, _ = run(with_bar51((98.5, 100.0, 97.0, 98.0)), P)
        self.assertEqual((len(ev), ev[0].trigger_kind, ev[0].time), (1, "wick", ct(51)))
        _, ev, _, _ = run(with_bar51((98.500000001, 100.0, 97.0, 98.0)), P)
        self.assertEqual(ev, [])
        # MSS: swing low pivot 51 (97.75) is confirmed at bar 53; bar 54 closes below it
        mss = list(B[:51]) + [
            (99.0, 99.25, 97.75, 98.75), (98.75, 99.0, 98.0, 98.5), (98.5, 98.75, 98.0, 98.5), (98.5, 98.5, 97.0, 97.5),
        ]
        _, ev, _, _ = run(mss, P)
        self.assertEqual((len(ev), ev[0].trigger_kind, ev[0].time), (1, "mss", ct(54)))
        # the confirming bar itself cannot fire: a bar 53 closing at the pivot low would still be inside the window
        early = list(B[:51]) + [(99.0, 99.25, 97.75, 98.75), (98.75, 99.0, 98.0, 98.5), (98.5, 98.75, 97.75, 97.75)]
        _, ev, _, _ = run(early, P)
        self.assertEqual(ev, [])

    def test_s18_touch_order(self):
        _, ev, tr, _ = run(B)
        built = [t.time for t in tr if t.reason == "zone_built"][0]
        touch = [t.time for t in tr if t.reason == "touch" and t.to == "IN_ZONE"][0]
        self.assertEqual(built, ct(44))
        self.assertGreater(touch, built)
        # bar 44 has h == zone_lo (99.5) but closes the very bar that builds the zone
        self.assertEqual(touch, ct(50))

    def test_s19_long_mirror(self):
        for over in ({}, {"use_ltf": True}):
            P = Z.P_for(**over)
            rows = self._ltf_rows(52) if over else list(B)
            if over:
                rows[52] = (98.0, 100.0, 97.75, 98.25)
            m = Z.mirror_rows(rows)
            _, ev_s, tr_s, _ = run(rows, P)
            _, ev_l, tr_l, _ = run(m, P)
            self.assertEqual(len(ev_s), 1)
            self.assertEqual(len(ev_l), 1)
            sig = lambda tr, sd: [(t.time, t.frm, t.to, t.reason) for t in tr if t.side == sd]
            self.assertEqual(sig(tr_s, -1), sig(tr_l, 1))
            self.assertEqual([t for t in tr_s if t.side == 1], [])
            self.assertEqual([t for t in tr_l if t.side == -1], [])
            a, b = ev_s[0], ev_l[0]
            self.assertEqual((a.time, a.trigger_kind), (b.time, b.trigger_kind))
            for f in ("close", "defending", "tp2"):
                self.assertLessEqual(abs((1000.0 - getattr(a, f)) - getattr(b, f)), 1e-9, f)
            self.assertEqual(a.atr, b.atr)

    def test_s20_pure_step(self):
        F = Z.features(B, Z.P_for(), htf=(True, True))
        from research.ict import generate as G

        P = Z.P_for()
        s0 = G.run_symbol(Z.SYMBOL, F, P, stop_at_us=ct(49))[2]["state"][0]
        before = s0
        a = ST.step15(s0, 50, F, P)
        b = ST.step15(s0, 50, F, P)
        self.assertEqual(repr(a), repr(b))
        self.assertEqual(s0, before)
        self.assertIsNotNone(a[2])
        c = ST.stepS(s0, 49, F, P)
        d = ST.stepS(s0, 49, F, P)
        self.assertEqual(repr(c), repr(d))
        self.assertEqual(s0, before)
        with self.assertRaises(Exception):
            s0.phase = ST.Phase.IDLE  # frozen


if __name__ == "__main__":
    unittest.main()
