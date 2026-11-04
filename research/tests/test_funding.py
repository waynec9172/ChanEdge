"""Funding rate (user note 3): boundaries, weights, sign, mark price, net definitions, missing months, rounding."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research import augment, sim
from research.tests.test_sim import BASE_US, FLAT, STEP, col, ct, make_bars, make_cfg, make_sig

FUND_KEY = "X/USDT"
R_LONG = 100.0 - 97.85
RATE = 0.0001
IDX = {n: i for i, n in enumerate(sim._COLS)}


def ot(i):
    return BASE_US + i * STEP


def run_f(cfg, rows, sig, f_times, rates, months=("2025-01",), bias=((), (), ()), opp=None, mk=None):
    funding = ({FUND_KEY: (np.array(f_times, dtype="int64"), np.array(rates, dtype=float))}, {FUND_KEY: set(months)})
    return sim.simulate_symbol(cfg, FUND_KEY, sig, mk or make_bars(rows), bias, None, opp or {}, 0.01, funding=funding), None


class FundingTests(unittest.TestCase):
    def test_f1_boundaries(self):
        # entry at the open of bar 1 (F1 = ot(1): not paid), F2 = ot(4) paid, exit at the open of bar 8 (F3 = ot(8): paid), F4 = ot(9) after exit
        exit_ = {"opposite_signal": {"enabled": True, "tf": "15m"}}
        opp = {FUND_KEY: {-1: np.array([ct(7)], dtype="int64")}}  # reviewed at bar 7's close -> exit at bar 8's open
        (out, _), _ = run_f(make_cfg(exit=exit_), [FLAT] * 11, make_sig(), [ot(1), ot(4), ot(8), ot(9)], [RATE] * 4, opp=opp)
        self.assertEqual(col(out, "exit_time"), ot(8))
        self.assertEqual(out[0][IDX["n_funding"]], 2)
        self.assertAlmostEqual(out[0][IDX["funding_r"]], 2 * RATE * 100.0 / R_LONG, places=12)

    def test_f2_weight_after_tp1(self):
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5}}
        rows = [FLAT, FLAT, FLAT, (100.0, 103.5, 99.5, 102.0)] + [FLAT] * 4  # TP1 fills on bar 3
        (out, _), _ = run_f(make_cfg(exit=exit_), rows, make_sig(up_end=103.0), [ot(3), ot(5)], [RATE, RATE])
        marks = (100.0, 100.0)  # closes of bars 2 and 4
        self.assertAlmostEqual(out[0][IDX["funding_r"]], (1.0 * RATE * marks[0] + 0.5 * RATE * marks[1]) / R_LONG, places=12)
        self.assertEqual(out[0][IDX["n_funding"]], 2)

    def test_f3_sign(self):
        rows = [FLAT] * 6
        (out, _), _ = run_f(make_cfg(), rows, make_sig(), [ot(3)], [RATE])
        self.assertGreater(out[0][IDX["funding_r"]], 0)  # long pays at a positive rate
        sig = make_sig(side=-1, defending=102.0, typ="second_sell")
        (out, _), _ = run_f(make_cfg(), rows, sig, [ot(3)], [RATE])
        self.assertLess(out[0][IDX["funding_r"]], 0)  # short receives
        (out, _), _ = run_f(make_cfg(), rows, make_sig(), [ot(3)], [-RATE])
        self.assertLess(out[0][IDX["funding_r"]], 0)

    def test_f4_mark_price(self):
        rows = [FLAT, FLAT, (100.0, 101.5, 99.8, 101.0), FLAT, FLAT, FLAT]
        (out, _), _ = run_f(make_cfg(), rows, make_sig(), [ot(3)], [RATE])
        self.assertAlmostEqual(out[0][IDX["funding_r"]], RATE * 101.0 / R_LONG, places=12)  # close of the bar that closes at F
        # no bar closes at F (bar 2 missing) but a bar opens at F: mark = that open
        rows = [FLAT, FLAT, FLAT, (100.7, 101.0, 100.0, 100.5), FLAT, FLAT]
        mk = make_bars(rows)
        mk = {k: np.delete(v, 2) for k, v in mk.items()}
        (out, _), _ = run_f(make_cfg(), None, make_sig(), [ot(3)], [RATE], mk=mk)
        self.assertAlmostEqual(out[0][IDX["funding_r"]], RATE * 100.7 / R_LONG, places=12)
        self.assertFalse(out[0][IDX["funding_missing"]])
        # neither: the event is skipped and flagged
        (out, _), _ = run_f(make_cfg(), [FLAT] * 6, make_sig(), [ot(3) + 5 * 60_000_000], [RATE])
        self.assertEqual(out[0][IDX["n_funding"]], 0)
        self.assertTrue(out[0][IDX["funding_missing"]])

    def test_f5_net_definitions(self):
        (out, _), _ = run_f(make_cfg(), [FLAT] * 6, make_sig(), [ot(3)], [RATE])
        r = out[0]
        self.assertAlmostEqual(r[IDX["net_r"]], r[IDX["gross_r"]] - r[IDX["fee_r"]] - r[IDX["funding_r"]], places=12)
        self.assertAlmostEqual(r[IDX["net_r_ex_funding"]], r[IDX["gross_r"]] - r[IDX["fee_r"]], places=12)
        # without funding data the two coincide
        out, _ = sim.simulate_symbol(make_cfg(), FUND_KEY, make_sig(), make_bars([FLAT] * 6), ((), (), ()), None, {}, 0.01)
        self.assertEqual(out[0][IDX["funding_r"]], 0.0)
        self.assertEqual(out[0][IDX["net_r"]], out[0][IDX["net_r_ex_funding"]])

    def test_f6_missing_month_flag(self):
        (out, _), _ = run_f(make_cfg(), [FLAT] * 6, make_sig(), [ot(3)], [RATE], months=())
        self.assertTrue(out[0][IDX["funding_missing"]])
        (out, _), _ = run_f(make_cfg(), [FLAT] * 6, make_sig(), [ot(3)], [RATE], months=("2025-01",))
        self.assertFalse(out[0][IDX["funding_missing"]])
        # a position held across the month end needs both months
        jan31 = int(pd.Timestamp("2025-01-31 23:00", tz="UTC").value // 1000)
        feb01 = int(pd.Timestamp("2025-02-01 02:00", tz="UTC").value // 1000)
        args = (FUND_KEY, 1, 2.0, jan31, feb01, [feb01], [1.0], [jan31, feb01], [100.0, 100.0], [100.0, 100.0])
        fund = {FUND_KEY: (np.array([], dtype="int64"), np.array([]))}
        self.assertTrue(sim.funding_for_trade(fund, {FUND_KEY: {"2025-01"}}, *args)[2])
        self.assertFalse(sim.funding_for_trade(fund, {FUND_KEY: {"2025-01", "2025-02"}}, *args)[2])

    def test_f7_calc_time_rounding(self):
        s = pd.Series([1693584000001, 1693583999999, 1693584000000])
        got = augment.round_calc_time_us(s).tolist()
        self.assertEqual(got, [1693584000000 * 1000] * 3)


if __name__ == "__main__":
    unittest.main()
