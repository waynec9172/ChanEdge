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


    def test_f8_imputed_events_cost_only(self):
        # an imputed event (3-tuple record: times, rates, imputed flags) is a cost for long and short alike
        fund_long = {FUND_KEY: (np.array([ot(3)], dtype="int64"), np.array([RATE]), np.array([True]), np.array([False]))}
        for side, sig in ((1, make_sig()), (-1, make_sig(side=-1, defending=102.0, typ="second_sell"))):
            out, _ = sim.simulate_symbol(make_cfg(), FUND_KEY, sig, make_bars([FLAT] * 6), ((), (), ()), None, {}, 0.01, funding=(fund_long, {FUND_KEY: set()}))
            self.assertGreater(out[0][IDX["funding_r"]], 0)
            self.assertEqual(out[0][IDX["n_funding_imputed"]], 1)
            self.assertTrue(out[0][IDX["funding_missing"]])  # affected flag
        # a real event still follows the side
        (out, _), _ = run_f(make_cfg(), [FLAT] * 6, make_sig(side=-1, defending=102.0, typ="second_sell"), [ot(3)], [RATE])
        self.assertLess(out[0][IDX["funding_r"]], 0)
        self.assertEqual(out[0][IDX["n_funding_imputed"]], 0)

    def test_f9_impute_prior3_median_and_schedule(self):
        hist = np.array([0.0001, -0.0003, 0.0002, 0.0004, -0.0001])
        ev, rate, h, basis = augment.impute_month_events("2026-10", np.abs(hist), np.array([9.0]), 8, 10**18)
        self.assertEqual((rate, basis, h), (float(np.median(np.abs(hist))), "own", 8))
        self.assertEqual(len(ev), 31 * 3)
        self.assertEqual(ev[0], augment.month_start_us("2026-10"))
        self.assertEqual(ev[1] - ev[0], 8 * 3_600_000_000)
        ev4, _r, h4, _b = augment.impute_month_events("2026-10", np.abs(hist), np.empty(0), 4, 10**18)
        self.assertEqual((h4, len(ev4)), (4, 31 * 6))
        evd, _r, hd, _b = augment.impute_month_events("2026-10", np.abs(hist), np.empty(0), None, 10**18)
        self.assertEqual(hd, 8)  # no interval known -> 8 h
        # events stop at the last bar
        cut = augment.month_start_us("2026-10") + 20 * 3_600_000_000
        self.assertEqual(len(augment.impute_month_events("2026-10", np.abs(hist), np.empty(0), 8, cut)[0]), 3)
        # no own history -> market median, basis market; nothing at all -> None
        _e, rate, _h, basis = augment.impute_month_events("2026-10", np.empty(0), np.array([0.0002, 0.0004, 0.0009]), 8, 10**18)
        self.assertEqual((rate, basis), (0.0004, "market"))
        self.assertIsNone(augment.impute_month_events("2026-10", np.empty(0), np.empty(0), 8, 10**18))
        # the window is the three calendar months before the month
        self.assertEqual(augment.shift_month("2026-10", -3), "2026-07")
        self.assertEqual(augment.shift_month("2026-01", -1), "2025-12")

    def test_f10_fetch_validation(self):
        import hashlib
        import io
        import zipfile

        def mkzip(member, text):
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as z:
                z.writestr(member, text)
            return b.getvalue()

        name = "BTCUSDT-fundingRate-2026-10.csv"
        lo, hi = augment.month_start_us("2026-10"), augment.month_start_us("2026-11")
        csv = "calc_time,funding_interval_hours,last_funding_rate\n1790812800000,8,0.0001\n"
        good = mkzip(name, csv)
        ck = hashlib.sha256(good).hexdigest() + "  x.zip\n"
        df = augment.validate_funding_zip(good, ck, name, lo, hi)
        self.assertEqual(len(df), 1)
        bad_cases = {
            "checksum": (good, "0" * 64 + "  x.zip", name),
            "member name": (mkzip("other.csv", csv), None, name),
            "path": (mkzip("sub/" + name, csv), None, name),
            "columns": (mkzip(name, "calc_time,rate\n1790812800000,0.1\n"), None, name),
            "outside month": (mkzip(name, "calc_time,funding_interval_hours,last_funding_rate\n1700000000000,8,0.0001\n"), None, name),
        }
        for label, (z, cks, member) in bad_cases.items():
            cks = cks or hashlib.sha256(z).hexdigest() + "  x.zip"
            with self.assertRaises(ValueError, msg=label):
                augment.validate_funding_zip(z, cks, member, lo, hi)
        with self.assertRaises(ValueError):
            augment.validate_funding_zip(b"not a zip", hashlib.sha256(b"not a zip").hexdigest(), name, lo, hi)

    def test_f11_url_percent_encoded(self):
        u = augment.vision_url("monthly", "币安人生USDT", "2026-10")
        self.assertTrue(u.isascii(), u)
        self.assertIn("%E5%B8%81%E5%AE%89%E4%BA%BA%E7%94%9F", u)
        self.assertEqual(
            augment.vision_url("monthly", "BTCUSDT", "2025-07"),
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-07.zip",
        )
        self.assertEqual(
            augment.vision_url("daily", "BTCUSDT", "2026-10-01"),
            "https://data.binance.vision/data/futures/um/daily/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-10-01.zip",
        )
        # the member-name check still uses the raw (unencoded) name
        import hashlib
        import io
        import zipfile

        name = "币安人生USDT-fundingRate-2026-10.csv"
        b = io.BytesIO()
        csv = "calc_time,funding_interval_hours,last_funding_rate\n1790812800000,8,0.0001\n"
        with zipfile.ZipFile(b, "w") as z:
            z.writestr(name, csv)
        good = b.getvalue()
        lo, hi = augment.month_start_us("2026-10"), augment.month_start_us("2026-11")
        df = augment.validate_funding_zip(good, hashlib.sha256(good).hexdigest() + "  x.zip", name, lo, hi)
        self.assertEqual(len(df), 1)
        with self.assertRaises(ValueError):
            augment.validate_funding_zip(good, hashlib.sha256(good).hexdigest(), name.replace("币安人生", "%E5%B8%81"), lo, hi)


if __name__ == "__main__":
    unittest.main()
