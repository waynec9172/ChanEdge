"""Limit orders (user note 2-2) and cost model (user note 2-3), synthetic bars."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research import common as C, metrics as M, sim
from research.tests.test_sim import BASE_CFG, BASE_US, FLAT, MAKER, SLIP, STEP, TAKER, col, ct, make_bars, make_cfg, make_sig, run

R_LONG = 100.0 - 97.85  # stop = floor_tick(98 - 0.15) = 97.85
LIM = lambda price="signal_close", offset=0.5, n=2: {"mode": "limit", "limit": {"price": price, "offset": offset, "valid_bars": n}}
CROSS = (100.0, 100.5, 99.4, 100.0)  # low 99.4 < 99.5


def htf_sig(tf, entry_idx, **kw):
    s = make_sig(entry_idx=entry_idx, **kw)
    s["tf"] = tf
    return s


def run_att(cfg, rows, sig, **kw):
    att: list = []
    out, cnt = sim.simulate_symbol(cfg, "X/USDT", sig, make_bars(rows), ((), (), ()), None, kw.get("opp") or {}, 0.01, attempts_out=att)
    return out, cnt, att


class LimitTests(unittest.TestCase):
    def test_l1_strict_cross_long_short(self):
        # long: L = 100 - 0.5 * 1 = 99.5
        out, _ = run(make_cfg(entry=LIM()), [FLAT, (100.0, 100.5, 99.5, 100.0), FLAT, FLAT], make_sig())
        self.assertEqual(len(out), 0)  # low == L: touching is not a fill
        out, _ = run(make_cfg(entry=LIM()), [FLAT, (100.0, 100.5, 99.49, 100.0), FLAT, FLAT], make_sig())
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_price"), 99.5)
        # short: defending 102 -> stop 102.15; L = 100 + 0.5 = 100.5
        sig = make_sig(side=-1, defending=102.0, typ="second_sell")
        out, _ = run(make_cfg(entry=LIM()), [FLAT, (100.0, 100.5, 99.5, 100.0), FLAT, FLAT], sig)
        self.assertEqual(len(out), 0)  # high == L
        out, _ = run(make_cfg(entry=LIM()), [FLAT, (100.0, 100.51, 99.5, 100.0), FLAT, FLAT], sig)
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_price"), 100.5)

    def test_l2_cancel_after_n_tf_bars(self):
        cfg = make_cfg(entry=LIM(n=2))
        # 15m, N = 2: bars j0 (1) and j0+1 (2) are valid, j0+2 (3) is not
        out, _ = run(cfg, [FLAT, FLAT, CROSS, FLAT, FLAT], make_sig())
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_time"), BASE_US + 2 * STEP)
        out, cnt = run(cfg, [FLAT, FLAT, FLAT, CROSS, FLAT], make_sig())
        self.assertEqual((len(out), cnt["unfilled"]), (0, 1))
        # 1h signal, N = 1: bars 4..7 are valid, 8 is not
        cfg = make_cfg(entry=LIM(n=1))
        rows = [FLAT] * 7 + [CROSS, FLAT, FLAT]
        out, _ = run(cfg, rows, htf_sig("1h", 4))
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_time"), BASE_US + 7 * STEP)
        rows = [FLAT] * 8 + [CROSS, FLAT]
        out, cnt = run(cfg, rows, htf_sig("1h", 4))
        self.assertEqual((len(out), cnt["unfilled"]), (0, 1))

    def test_l3_unfilled_not_counted_but_reported(self):
        cfg = make_cfg(entry=LIM(n=2))
        out, cnt, att = run_att(cfg, [FLAT, FLAT, FLAT, CROSS, FLAT], make_sig())
        self.assertEqual(len(out), 0)
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0][7], "unfilled")
        self.assertEqual(att[0][8], BASE_US + 2 * STEP)  # open_time of the last valid bar
        out2, _, att2 = run_att(cfg, [FLAT, CROSS, FLAT], make_sig())
        self.assertEqual(att2[0][7], "filled")
        cols = sim._ATT_COLS
        a = pd.DataFrame([("a", "filled"), ("b", "unfilled"), ("c", "unfilled")], columns=["signal_id", "status"])
        s = M.summarize(pd.DataFrame(columns=["net_r"]), a)
        self.assertEqual(s["n"], 0)  # unfilled orders are not trades
        self.assertAlmostEqual(s["fill_rate"], 1 / 3)
        self.assertEqual(cols[7], "status")

    def test_l4_defend_frac_price(self):
        cfg = make_cfg(entry=LIM("defend_frac", 0.5, 2))
        out, _ = run(cfg, [FLAT, (100.0, 100.5, 98.9, 100.0), FLAT], make_sig())  # L = 100 - 0.5 * (100 - 98) = 99
        self.assertEqual(col(out, "entry_price"), 99.0)
        self.assertEqual(col(out, "entry_reference"), 99.0)
        sig = make_sig(side=-1, defending=102.0, typ="second_sell")  # L = 100 - 0.5 * (100 - 102) = 101
        out, _ = run(cfg, [FLAT, (100.0, 101.2, 99.5, 100.0), FLAT], sig)
        self.assertEqual(col(out, "entry_price"), 101.0)

    def test_l5_minstop_rejects_before_order(self):
        for entry in ({"mode": "market_next_open"}, LIM(n=2)):
            cfg = make_cfg(entry=entry, filters={**BASE_CFG["filters"], "min_stop_atr": 2.5})
            out, cnt, att = run_att(cfg, [FLAT, CROSS, FLAT], make_sig())
            self.assertEqual(len(out), 0)
            self.assertEqual(cnt["minstop_rejected"], 1)
            self.assertEqual(att[0][7], "minstop_rejected")
            self.assertEqual(att[0][8], BASE_US + STEP)  # = signal_time: does not occupy the symbol
        cfg = make_cfg(entry={"mode": "market_next_open"}, filters={**BASE_CFG["filters"], "min_stop_atr": 2.0})
        self.assertEqual(len(run(cfg, [FLAT, FLAT, FLAT], make_sig())[0]), 1)  # R/ATR = 2.15
        cfg = make_cfg(entry={"mode": "market_next_open"}, filters={**BASE_CFG["filters"], "min_stop_pct": 0.03})
        self.assertEqual(len(run(cfg, [FLAT, FLAT, FLAT], make_sig())[0]), 0)  # R/price = 2.15%
        cfg = make_cfg(entry={"mode": "market_next_open"}, filters={**BASE_CFG["filters"], "min_stop_pct": 0.02})
        self.assertEqual(len(run(cfg, [FLAT, FLAT, FLAT], make_sig())[0]), 1)
        # confirm mode: decided after the confirmation -> abandoned (occupies until the confirmation bar)
        conf = {"mode": "confirm", "confirm": {"bars": 1, "require_close_beyond": True}}
        cfg = make_cfg(entry=conf, filters={**BASE_CFG["filters"], "min_stop_atr": 2.5})
        out, cnt, att = run_att(cfg, [FLAT, FLAT, FLAT, FLAT], make_sig())
        self.assertEqual(len(out), 0)
        self.assertEqual(att[0][7], "abandoned")
        self.assertEqual(att[0][8], BASE_US + STEP)


class CostTests(unittest.TestCase):
    def _fee(self, pe, p_exit_list, weights=(1.0,), fees=None):
        fees = fees or [TAKER] * len(p_exit_list)
        return (pe * TAKER + sum(w * p * f for w, p, f in zip(weights, p_exit_list, fees))) / R_LONG

    def test_k1_stop_exits_taker_plus_slippage(self):
        pe = 100.0 * (1 + SLIP)
        # structure stop (touch)
        out, _ = run(make_cfg(), [FLAT, (100.0, 100.2, 97.0, 98.0), FLAT], make_sig())
        p = 97.85 * (1 - SLIP)
        self.assertAlmostEqual(col(out, "exit_price"), p, places=12)
        self.assertAlmostEqual(col(out, "fee_r"), self._fee(pe, [p]), places=9)
        # gap through the stop fills at the open (plus slippage)
        out, _ = run(make_cfg(), [FLAT, (96.0, 97.0, 95.0, 96.0), FLAT], make_sig())
        self.assertAlmostEqual(col(out, "exit_price"), 96.0 * (1 - SLIP), places=12)
        # break-even stop
        rows = [FLAT, (100.0, 102.5, 99.5, 102.0), (101.0, 101.5, 99.9, 100.5), FLAT]
        out, _ = run(make_cfg(exit={"breakeven": {"enabled": True, "arm_r": 1.0}}), rows, make_sig())
        p = 100.0 * (1 - SLIP)
        self.assertEqual(col(out, "exit_reason"), "breakeven_stop")
        self.assertAlmostEqual(col(out, "exit_price"), p, places=12)
        self.assertAlmostEqual(col(out, "fee_r"), self._fee(pe, [p]), places=9)
        # ratchet stop
        exit_ = {"breakeven": {"enabled": True, "arm_r": 1.0}, "ratchet": {"enabled": True}}
        rows = [FLAT, (100.0, 102.5, 99.5, 102.0), (102.0, 103.0, 101.0, 102.5), (103.5, 104.0, 102.8, 103.0), FLAT]
        bi = (np.array([ct(2)], dtype="int64"), np.array([np.nan]), np.array([103.0]))
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(), bi=bi)
        p = 102.85 * (1 - SLIP)
        self.assertEqual(col(out, "exit_reason"), "ratchet_stop")
        self.assertAlmostEqual(col(out, "fee_r"), self._fee(pe, [p]), places=9)
        # ATR trail stop: stop = best close 101 - 1 ATR = 100
        rows = [FLAT, (100.0, 101.0, 99.8, 101.0), (100.5, 100.6, 99.9, 100.2), FLAT]
        out, _ = run(make_cfg(exit={"atr_trail": {"enabled": True, "mult": 1.0, "arm_r": 0.0}}), rows, make_sig())
        p = 100.0 * (1 - SLIP)
        self.assertEqual(col(out, "exit_reason"), "trail_stop")
        self.assertAlmostEqual(col(out, "exit_price"), p, places=12)
        self.assertAlmostEqual(col(out, "fee_r"), self._fee(pe, [p]), places=9)

    def test_k2_fixed_r_maker_strict(self):
        fix = 100.0 + 2.0 * (100.0 - 97.85)
        cfg = make_cfg(exit={"fixed_r": {"enabled": True, "r": 2.0}})
        pe = 100.0 * (1 + SLIP)
        out, _ = run(cfg, [FLAT, (100.0, fix, 99.5, 103.0), FLAT], make_sig())  # high == target: resting order not filled
        self.assertEqual(col(out, "exit_reason"), "end_of_data")
        out, _ = run(cfg, [FLAT, (100.0, fix + 0.01, 99.5, 103.0), FLAT], make_sig())
        self.assertEqual(col(out, "exit_reason"), "fixed_r")
        self.assertEqual(col(out, "exit_price"), fix)  # no slippage
        self.assertAlmostEqual(col(out, "fee_r"), (pe * TAKER + fix * MAKER) / R_LONG, places=9)
        self.assertAlmostEqual(col(out, "gross_r"), (fix - pe) / R_LONG, places=9)
        out, _ = run(cfg, [FLAT, FLAT, (fix + 1.0, fix + 2.0, fix + 0.5, fix + 1.5), FLAT], make_sig())  # gaps over the target
        self.assertEqual(col(out, "exit_reason"), "fixed_r")
        self.assertEqual(col(out, "exit_price"), fix)
        self.assertAlmostEqual(col(out, "fee_r"), (pe * TAKER + fix * MAKER) / R_LONG, places=9)
        # short mirror: low == target does not fill
        sig = make_sig(side=-1, defending=102.0, typ="second_sell")
        fixs = 100.0 - 2.0 * (102.15 - 100.0)
        out, _ = run(cfg, [FLAT, (100.0, 100.5, fixs, 99.0), FLAT], sig)
        self.assertEqual(col(out, "exit_reason"), "end_of_data")
        out, _ = run(cfg, [FLAT, (100.0, 100.5, fixs - 0.01, 99.0), FLAT], sig)
        self.assertEqual(col(out, "exit_reason"), "fixed_r")
        self.assertEqual(col(out, "exit_price"), fixs)

    def test_k3_tp1_current_stays_taker(self):
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5}}
        rows = [FLAT, (100.0, 103.5, 99.0, 102.0), (102.0, 102.5, 97.0, 98.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(up_end=103.0))
        pe = 100.0 * (1 + SLIP)
        p1, p2 = 103.0 * (1 - SLIP), 97.85 * (1 - SLIP)
        self.assertTrue(col(out, "tp1_hit"))
        self.assertAlmostEqual(col(out, "fee_r"), (pe * TAKER + 0.5 * p1 * TAKER + 0.5 * p2 * TAKER) / R_LONG, places=9)

    def test_k4_next_open_exits_taker(self):
        pe = 100.0 * (1 + SLIP)
        p = 101.0 * (1 - SLIP)
        rows = [FLAT, FLAT, FLAT, (101.0, 101.5, 100.5, 101.0), FLAT]
        cases = [
            ("opposite_signal", {"opposite_signal": {"enabled": True, "tf": "15m"}}, {"opp": {"X/USDT": {-1: np.array([ct(2)], dtype="int64")}}}),
            ("bias_1h", {"bias_1h": {"enabled": True}}, {"bias": (np.array([ct(2)], dtype="int64"), np.array([True]), np.array([False]))}),
            ("time_stop", {"time_stop": {"enabled": True, "bars": 2}}, {}),
        ]
        for reason, exit_, kw in cases:
            out, _ = run(make_cfg(exit=exit_), rows, make_sig(), **kw)
            self.assertEqual(col(out, "exit_reason"), reason)
            self.assertAlmostEqual(col(out, "exit_price"), p, places=12)
            self.assertAlmostEqual(col(out, "fee_r"), self._fee(pe, [p]), places=9)

    def test_k5_fee15(self):
        from research.tests.test_funding import FUND_KEY, run_f

        rows = [FLAT] * 8
        fund = ([BASE_US + 4 * STEP], [0.0004])
        (out, _), _ = run_f(make_cfg(), rows, make_sig(), *fund)
        r = out[0]
        gross, fee, fr = r[sim._COLS.index("gross_r")], r[sim._COLS.index("fee_r")], r[sim._COLS.index("funding_r")]
        self.assertGreater(fr, 0)
        df = pd.DataFrame(out, columns=sim._COLS)
        df["exit_time"] = pd.to_datetime(df["exit_time"], unit="us", utc=True)
        s = M.summarize(df)
        self.assertAlmostEqual(s["net_fee15"], gross - 1.5 * fee - fr, places=12)
        self.assertAlmostEqual(s["net_r"], gross - fee - fr, places=12)


    def test_k6_slip_r_and_slip3(self):
        IDX = {n: i for i, n in enumerate(sim._COLS)}
        # (a) market entry + structure stop: slip_r = (O*slip + stop*slip) / R
        rows = [FLAT, FLAT, (100.0, 100.2, 97.0, 97.5), FLAT]
        out, _ = run(make_cfg(), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        stop = col(out, "stop_initial")
        self.assertAlmostEqual(out[0][IDX["slip_r"]], (100.0 * SLIP + stop * SLIP) / R_LONG, places=12)
        # gap through the stop: the open is the raw price
        rows = [FLAT, FLAT, (96.0, 96.5, 95.0, 95.5), FLAT]
        out, _ = run(make_cfg(), rows, make_sig())
        self.assertAlmostEqual(out[0][IDX["slip_r"]], (100.0 * SLIP + 96.0 * SLIP) / R_LONG, places=12)
        # (b) limit entry + fixed_r maker exit: no slippage at all
        fx = {"fixed_r": {"enabled": True, "r": 1.0}}
        rows = [FLAT, (100.0, 100.5, 99.4, 100.0), (99.6, 105.0, 99.5, 104.0), FLAT]
        out, _ = run(make_cfg(entry=LIM(n=2), exit=fx), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "fixed_r")
        self.assertEqual(out[0][IDX["slip_r"]], 0.0)
        # (c) current preset with TP1: the TP1 leg enters with weight 0.5
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5}}
        rows = [FLAT, FLAT, (100.0, 103.5, 99.5, 102.0), (102.0, 102.0, 90.0, 91.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(up_end=103.0))
        self.assertTrue(col(out, "tp1_hit"))
        r = out[0]
        want = (100.0 * SLIP + 0.5 * 103.0 * SLIP + 0.5 * r[IDX["stop_initial"]] * SLIP) / R_LONG
        self.assertAlmostEqual(r[IDX["slip_r"]], want, places=12)
        # (d) the same data with 3 bp: identical exits, net_r == net_r(1bp) - 2 * slip_r
        for cfg_kw, rws in (({}, [FLAT, FLAT, (100.0, 100.2, 97.0, 97.5), FLAT]), ({"exit": exit_}, rows)):
            sig = make_sig(up_end=103.0)
            o1, _ = run(make_cfg(**cfg_kw), rws, sig)
            c3 = make_cfg(costs={"taker_bps": 5, "maker_bps": 2, "slippage_bps": 3}, **cfg_kw)
            o3, _ = run(c3, rws, sig)
            self.assertEqual((o1[0][IDX["exit_time"]], o1[0][IDX["exit_reason"]]), (o3[0][IDX["exit_time"]], o3[0][IDX["exit_reason"]]))
            self.assertLess(abs(o3[0][IDX["net_r"]] - (o1[0][IDX["net_r"]] - 2 * o1[0][IDX["slip_r"]])), 1e-4)


if __name__ == "__main__":
    unittest.main()
