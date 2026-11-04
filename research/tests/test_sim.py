"""Simulator unit tests on synthetic bars. No real data."""

from __future__ import annotations

import copy
import math
import unittest

import numpy as np
import pandas as pd

from research import sim

BASE_US = int(pd.Timestamp("2025-01-01", tz="UTC").value // 1000)
STEP = 900_000_000
SLIP = 1e-4
TAKER = 5e-4
MAKER = 2e-4

BASE_CFG = {
    "name": "t",
    "description": "t",
    "signals": {"source": "chan", "tf": "15m", "types": ["second_buy"], "donchian_n": None},
    "filters": {"in_top20": True, "candidate_only": False, "gate_pass": False, "jev_min": None, "max_cost_r": None, "exclude_reemit": False},
    "entry": {"mode": "market_next_open"},
    "stop": {"buffer_atr": 0.15, "round_to_tick": True},
    "exit": {},
    "costs": {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1},
}


def make_cfg(**over):
    d = copy.deepcopy(BASE_CFG)
    for k, v in over.items():
        d[k] = v
    return sim.SimConfig.from_dict(d)


def make_bars(rows):
    """rows: list of (o, h, l, c). Bar i opens at BASE + i * 15m."""
    n = len(rows)
    a = np.array(rows, dtype=float)
    return {"ot": np.array([BASE_US + i * STEP for i in range(n)], dtype="int64"), "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def ct(i):
    return BASE_US + (i + 1) * STEP


def make_sig(entry_idx=1, side=1, close=100.0, defending=98.0, atr=1.0, typ="second_buy", up_end=math.nan, dn_end=math.nan, prior=math.nan, zg=math.nan, zd=math.nan):
    """Signal confirmed at the close of bar entry_idx - 1, i.e. time == open of bar entry_idx."""
    t = pd.Timestamp(BASE_US + entry_idx * STEP, unit="us", tz="UTC")
    return pd.DataFrame(
        [
            {
                "signal_id": "s1", "tf": "15m", "type": typ, "side": side, "time": t, "close": close,
                "defending_price": defending, "prior_extreme": prior, "zs_zg": zg, "zs_zd": zd, "atr": atr,
                "last_up_end": up_end, "last_down_end": dn_end,
            }
        ]
    )


def run(cfg, rows, sig, bias=((), (), ()), bi=None, opp=None, tick=0.01):
    out, cnt = sim.simulate_symbol(cfg, "X/USDT", sig, make_bars(rows), bias, bi, opp or {}, tick)
    return out, cnt


def col(out, name):
    return out[0][sim._COLS.index(name)]


FLAT = (100.0, 100.5, 99.5, 100.0)  # does not reach stop 97.85 or +1R 102.15


class SimTests(unittest.TestCase):
    def test_01_entry_next_open_with_slippage(self):
        rows = [(50.0, 200.0, 1.0, 60.0), (100.0, 100.5, 99.5, 100.0), FLAT]  # bar 0 is the signal bar: wild prices unused
        out, _ = run(make_cfg(), rows, make_sig())
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(col(out, "entry_price"), 100.0 * (1 + SLIP), places=12)
        self.assertEqual(col(out, "entry_time"), BASE_US + STEP)
        self.assertEqual(col(out, "entry_reference"), 100.0)

    def test_02_stop_beats_tp1_on_same_bar(self):
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "r", "r_fallback": 1.5}}
        rows = [FLAT, (100.0, 110.0, 90.0, 100.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertFalse(col(out, "tp1_hit"))
        self.assertEqual(col(out, "bars_held"), 0)  # stopped on the entry bar

    def test_03_gap_through_stop_fills_at_open(self):
        rows = [FLAT, (100.0, 100.5, 99.5, 100.0), (90.0, 91.0, 89.0, 90.0), FLAT]
        out, _ = run(make_cfg(), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertAlmostEqual(col(out, "exit_price"), 90.0 * (1 - SLIP), places=12)

    def test_04_limit_strict_cross_and_maker_fee(self):
        lim = {"mode": "limit", "limit": {"price": "signal_close", "offset": 0.5, "valid_bars": 1}}
        # L = 100 - 0.5 * 1 = 99.5. low == L does not fill
        out, cnt = run(make_cfg(entry=lim), [FLAT, (100.0, 100.5, 99.5, 100.0), FLAT], make_sig())
        self.assertEqual(len(out), 0)
        self.assertEqual(cnt["unfilled"], 1)
        rows = [FLAT, (100.0, 100.5, 99.4, 100.0), FLAT]
        out, _ = run(make_cfg(entry=lim), rows, make_sig())
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "entry_price"), 99.5)  # no slippage
        R = 99.5 - 97.85
        p_exit = 100.0 * (1 - SLIP)  # end of data at last close
        self.assertAlmostEqual(col(out, "fee_r"), (99.5 * MAKER + p_exit * TAKER) / R, places=9)
        self.assertEqual(col(out, "exit_reason"), "end_of_data")

    def test_05_confirm_mode(self):
        conf = {"mode": "confirm", "confirm": {"bars": 1, "require_close_beyond": True}}
        # stop touched while waiting -> no trade
        out, cnt = run(make_cfg(entry=conf), [FLAT, (100.0, 100.5, 97.0, 100.0), FLAT, FLAT], make_sig())
        self.assertEqual(len(out), 0)
        self.assertEqual(cnt["confirm_abandoned"], 1)
        # passes: close >= signal close -> enter at the open of the next bar (index 2)
        rows = [FLAT, (100.0, 101.0, 99.5, 100.5), (101.0, 101.5, 100.5, 101.0), FLAT]
        out, _ = run(make_cfg(entry=conf), rows, make_sig())
        self.assertEqual(col(out, "entry_time"), BASE_US + 2 * STEP)
        self.assertAlmostEqual(col(out, "entry_price"), 101.0 * (1 + SLIP), places=12)
        self.assertEqual(col(out, "entry_reference"), 100.5)

    def test_06_breakeven_then_stop(self):
        exit_ = {"breakeven": {"enabled": True, "arm_r": 1.0}}
        # R = 2.15; +1R = 102.15. bar1 high 102.5 arms; stop = 100 from bar 2 on
        rows = [FLAT, (100.0, 102.5, 99.5, 102.0), (101.0, 101.5, 99.9, 100.5), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "breakeven_stop")
        self.assertAlmostEqual(col(out, "exit_price"), 100.0 * (1 - SLIP), places=12)
        self.assertEqual(col(out, "bars_held"), 1)

    def test_07_ratchet_moves_stop_to_floor_tick(self):
        exit_ = {"breakeven": {"enabled": True, "arm_r": 1.0}, "ratchet": {"enabled": True}}
        rows = [FLAT, (100.0, 102.5, 99.5, 102.0), (102.0, 103.0, 101.0, 102.5), (103.5, 104.0, 102.8, 103.0), FLAT]
        bi = (np.array([ct(2)], dtype="int64"), np.array([np.nan]), np.array([103.0]))
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(), bi=bi)
        # buffer 0.15 -> floor_to_tick(103 - 0.15) = 102.85
        self.assertEqual(col(out, "exit_reason"), "ratchet_stop")
        self.assertAlmostEqual(col(out, "exit_price"), 102.85 * (1 - SLIP), places=12)

    def test_08_tp1_partial_hand_computed(self):
        exit_ = {"tp1": {"enabled": True, "fraction": 0.5, "target": "prior_swing", "r_fallback": 1.5}}
        rows = [FLAT, (100.0, 103.5, 99.0, 102.0), (102.0, 102.5, 97.0, 98.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(up_end=103.0))
        R = 100.0 - 97.85
        pe = 100.0 * (1 + SLIP)
        p1 = 103.0 * (1 - SLIP)
        p2 = 97.85 * (1 - SLIP)
        gross = 0.5 * (p1 - pe) + 0.5 * (p2 - pe)
        fee = pe * TAKER + 0.5 * p1 * TAKER + 0.5 * p2 * TAKER
        self.assertTrue(col(out, "tp1_hit"))
        self.assertAlmostEqual(col(out, "gross_r"), gross / R, places=9)
        self.assertAlmostEqual(col(out, "fee_r"), fee / R, places=9)
        self.assertAlmostEqual(col(out, "net_r"), (gross - fee) / R, places=9)
        self.assertAlmostEqual(col(out, "exit_price"), 0.5 * p1 + 0.5 * p2, places=9)
        self.assertEqual(col(out, "exit_reason"), "structure_stop")

    def test_09a_opposite_signal_exits_next_open(self):
        exit_ = {"opposite_signal": {"enabled": True, "tf": "15m"}}
        rows = [FLAT, FLAT, FLAT, (101.0, 101.5, 100.5, 101.0), FLAT]
        opp = {"X/USDT": {-1: np.array([ct(2)], dtype="int64")}}
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(), opp=opp)
        self.assertEqual(col(out, "exit_reason"), "opposite_signal")
        self.assertEqual(col(out, "exit_time"), BASE_US + 3 * STEP)
        self.assertAlmostEqual(col(out, "exit_price"), 101.0 * (1 - SLIP), places=12)

    def test_09b_bias_1h_exits_next_open(self):
        exit_ = {"bias_1h": {"enabled": True}}
        rows = [FLAT, FLAT, FLAT, (101.0, 101.5, 100.5, 101.0), FLAT]
        bias = (np.array([ct(2)], dtype="int64"), np.array([True]), np.array([False]))
        out, _ = run(make_cfg(exit=exit_), rows, make_sig(), bias=bias)
        self.assertEqual(col(out, "exit_reason"), "bias_1h")
        self.assertEqual(col(out, "exit_time"), BASE_US + 3 * STEP)

    def test_09c_time_stop(self):
        exit_ = {"time_stop": {"enabled": True, "bars": 2}}
        rows = [FLAT, FLAT, FLAT, (101.0, 101.5, 100.5, 101.0), FLAT]
        out, _ = run(make_cfg(exit=exit_), rows, make_sig())
        self.assertEqual(col(out, "exit_reason"), "time_stop")
        self.assertEqual(col(out, "exit_time"), BASE_US + 3 * STEP)

    def test_10_stopped_on_entry_bar(self):
        rows = [FLAT, (100.0, 100.2, 97.0, 98.0), FLAT]
        out, _ = run(make_cfg(), rows, make_sig())
        self.assertEqual(col(out, "bars_held"), 0)
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertEqual(col(out, "exit_time"), col(out, "entry_time"))

    def test_11_short_mirror(self):
        rows = [FLAT, (100.0, 100.5, 99.5, 100.0), (100.0, 103.0, 99.8, 102.0), FLAT]
        out, _ = run(make_cfg(), rows, make_sig(side=-1, defending=102.0, typ="second_sell"))
        # stop = ceil_to_tick(102 + 0.15) = 102.15 ; touched on bar 2
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertAlmostEqual(col(out, "exit_price"), 102.15 * (1 + SLIP), places=12)
        self.assertAlmostEqual(col(out, "entry_price"), 100.0 * (1 - SLIP), places=12)

    def test_12_config_rejects_unknown_and_missing(self):
        bad = copy.deepcopy(BASE_CFG)
        bad["filters"]["oops"] = 1
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(bad)
        bad = copy.deepcopy(BASE_CFG)
        del bad["costs"]
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(bad)
        bad = copy.deepcopy(BASE_CFG)
        bad["exit"] = {"tp1": {"enabled": True, "fraction": "half"}}
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
