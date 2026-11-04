"""Phase 1b delist rule on synthetic bars (decision 1793825540, plan 4.1)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research import augment, sim
from research.tests.test_sim import BASE_US, FLAT, SLIP, STEP, TAKER, col, make_bars, make_cfg, make_sig

SYM = "X/USDT"
IDX = {n: i for i, n in enumerate(sim._COLS)}


def ot(i):
    return BASE_US + i * STEP


def dl_tuple(run_start_idx, run_end_idx, delist_idx):
    return (np.array([ot(run_start_idx)], dtype="int64"), np.array([ot(run_end_idx)], dtype="int64"), np.array([ot(delist_idx) if delist_idx is not None else -1], dtype="int64"))


def run_dl(cfg, rows, sig, delist=None, funding=None, opp=None, attempts=None):
    return sim.simulate_symbol(cfg, SYM, sig, make_bars(rows), ((), (), ()), None, opp or {}, 0.01, funding=funding, attempts_out=attempts, delist=delist)


def flat_df(n_flat, start="2025-01-01", gap_at=None, vol_at=None, lead=3):
    """lead normal rows, then n_flat flat-line rows (h = l = c, volume 0), then 2 normal rows."""
    n = lead + n_flat + 2
    t = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    if gap_at is not None:
        t = t.where(np.arange(n) < gap_at, t + pd.Timedelta(minutes=15))
    px = np.r_[np.full(lead, 10.0) + np.arange(lead) * 0.1, np.full(n_flat, 10.3), [10.4, 10.5]]
    h = px.copy()
    lo = px.copy()
    h[:lead] += 0.2
    lo[:lead] -= 0.2
    h[-2:] += 0.2
    lo[-2:] -= 0.2
    vol = np.r_[np.full(lead, 5.0), np.zeros(n_flat), [5.0, 5.0]]
    if vol_at is not None:
        vol[vol_at] = 1.0
    return pd.DataFrame({"open_time": t, "high": h, "low": lo, "close": px, "volume": vol})


class DelistTests(unittest.TestCase):
    def test_x1_detect_runs(self):
        self.assertEqual(augment.flat_runs(flat_df(95)), [])
        r = augment.flat_runs(flat_df(96))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["n_bars"], 96)
        self.assertEqual(r[0]["delist_bar"], flat_df(96)["open_time"].iloc[2])  # last normal row before the run
        self.assertFalse(r[0]["to_end"])  # trading resumed afterwards
        self.assertFalse(r[0]["has_gap"])
        self.assertAlmostEqual(r[0]["delist_close"], 10.2)
        # one row with volume > 0 inside breaks a 96-row run into two shorter ones
        self.assertEqual(augment.flat_runs(flat_df(96, vol_at=3 + 40)), [])
        # run that reaches the last row
        d = flat_df(100).iloc[:-2].reset_index(drop=True)
        r = augment.flat_runs(d)
        self.assertTrue(r[0]["to_end"])
        # run that starts at the first row: no delist bar
        d = flat_df(100, lead=0).reset_index(drop=True)
        r = augment.flat_runs(d)
        self.assertEqual(len(r), 1)
        self.assertTrue(pd.isna(r[0]["delist_bar"]))
        self.assertEqual(r[0]["run_start"], d["open_time"].iloc[0])
        # a time gap inside the run does not split it
        r = augment.flat_runs(flat_df(96, gap_at=3 + 50))
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["has_gap"])
        self.assertEqual(r[0]["n_bars"], 96)

    def test_x2_forced_close_at_delist_close(self):
        rows = [FLAT] * 6 + [(100.0, 100.0, 100.0, 100.0)] * 3
        dl = dl_tuple(5, 8, 4)  # bar 4 is the last normal bar
        out, cnt = run_dl(make_cfg(filters={**make_cfg().filters, "delist_rule": True}), rows, make_sig(), delist=dl)
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(t[IDX["exit_reason"]], "delisted")
        self.assertEqual(t[IDX["exit_time"]], ot(4))
        self.assertEqual(t[IDX["bars_held"]], 3)
        self.assertAlmostEqual(t[IDX["exit_price"]], 100.0 * (1 - 3 * SLIP), places=9)
        R = t[IDX["r_dist"]]
        p_entry = 100.0 * (1 + SLIP)
        fee = (p_entry * TAKER + 100.0 * (1 - 3 * SLIP) * TAKER) / R
        self.assertAlmostEqual(t[IDX["fee_r"]], fee, places=9)  # taker both legs
        self.assertAlmostEqual(t[IDX["slip_r"]], (100.0 * SLIP + 100.0 * 3 * SLIP) / R, places=9)  # 1x on entry + 3x on the forced leg
        self.assertAlmostEqual(t[IDX["gross_r"]], (100.0 * (1 - 3 * SLIP) - p_entry) / R, places=9)
        # short mirror
        sig = make_sig(side=-1, defending=102.0, typ="second_sell")
        out, _ = run_dl(make_cfg(types=None) if False else make_cfg(signals={"source": "chan", "tf": "15m", "types": ["second_sell"], "donchian_n": None}, filters={**make_cfg().filters, "delist_rule": True}), rows, sig, delist=dl)
        self.assertEqual(out[0][IDX["exit_reason"]], "delisted")
        self.assertAlmostEqual(out[0][IDX["exit_price"]], 100.0 * (1 + 3 * SLIP), places=9)
        # funding: F <= ot[d] counts, later events never
        rate = 0.0001
        fund = ({SYM: (np.array([ot(3), ot(4), ot(5), ot(7)], dtype="int64"), np.full(4, rate))}, {SYM: {"2025-01"}})
        out, _ = run_dl(make_cfg(filters={**make_cfg().filters, "delist_rule": True}), rows, make_sig(), delist=dl, funding=fund)
        self.assertEqual(out[0][IDX["n_funding"]], 2)  # ot(3) and ot(4); ot(5), ot(7) are in the flat run
        self.assertEqual(out[0][IDX["exit_reason"]], "delisted")

    def test_x3_stop_in_delist_bar_wins(self):
        rows = [FLAT] * 4 + [(100.0, 100.5, 90.0, 95.0)] + [(95.0, 95.0, 95.0, 95.0)] * 3
        out, _ = run_dl(make_cfg(filters={**make_cfg().filters, "delist_rule": True}), rows, make_sig(), delist=dl_tuple(5, 7, 4))
        self.assertEqual(out[0][IDX["exit_reason"]], "structure_stop")
        self.assertEqual(out[0][IDX["exit_time"]], ot(4))

    def test_x4_pending_exit_at_delist_open(self):
        exit_ = {"opposite_signal": {"enabled": True, "tf": "15m"}}
        rows = [FLAT] * 3 + [(100.0, 100.5, 99.5, 100.0)] + [(101.0, 101.0, 100.0, 100.0)] + [(100.0, 100.0, 100.0, 100.0)] * 3
        opp = {SYM: {-1: np.array([ot(3) + STEP], dtype="int64")}}  # reviewed at bar 3's close -> queued, filled at bar 4's open
        cfg = make_cfg(exit=exit_, filters={**make_cfg().filters, "delist_rule": True})
        out, _ = run_dl(cfg, rows, make_sig(), delist=dl_tuple(5, 7, 4), opp=opp)
        self.assertEqual(out[0][IDX["exit_reason"]], "opposite_signal")
        self.assertAlmostEqual(out[0][IDX["exit_price"]], 101.0 * (1 - SLIP), places=9)  # the open of the delisting bar, 1x slippage

    def test_x5_signals_in_flat_filtered(self):
        T0 = pd.Timestamp("2025-03-01 00:00", tz="UTC")
        rs, re_ = T0 + pd.Timedelta(hours=10), T0 + pd.Timedelta(hours=20)
        times = [rs - pd.Timedelta(minutes=15), rs, rs + pd.Timedelta(hours=1), re_, re_ + pd.Timedelta(minutes=15), re_ + pd.Timedelta(minutes=30), re_ + pd.Timedelta(days=3)]
        keep = [True, False, False, False, False, True, True]  # the relisted signals (last two) stay: option A of the decision
        df = pd.DataFrame({"symbol": SYM, "time": pd.Series(times).astype("datetime64[us, UTC]")})
        m = pd.Series(True, index=df.index)
        us = lambda x: int(x.value // 1000)
        n = sim._delist_filter(df, m, {SYM: (np.array([us(rs)]), np.array([us(re_)]), np.array([us(rs) - STEP]))})
        self.assertEqual(list(m), keep)
        self.assertEqual(n, 4)
        # other symbol untouched
        df2 = df.assign(symbol="Y/USDT")
        m2 = pd.Series(True, index=df2.index)
        self.assertEqual(sim._delist_filter(df2, m2, {SYM: (np.array([us(rs)]), np.array([us(re_)]), np.array([-1]))}), 0)

    def test_x6_rule_off_identical(self):
        rows = [FLAT] * 6 + [(100.0, 100.0, 100.0, 100.0)] * 3
        off, c0 = run_dl(make_cfg(), rows, make_sig(), delist=None)
        # data present but rule off: the simulator is called without delist (sim._work passes None when the rule is off)
        again, c1 = run_dl(make_cfg(), rows, make_sig(), delist=None)
        self.assertEqual(off, again)
        self.assertEqual(c0, c1)
        self.assertNotEqual(off[0][IDX["exit_reason"]], "delisted")
        self.assertNotIn("delist_rule", make_cfg().resolved()["filters"])
        # through sim.simulate with a Market that carries delist data: rule off == no delist data at all; rule on differs
        mk = make_bars(rows)
        sig = make_sig().assign(attempt_id=0, symbol=SYM)
        dl = {SYM: dl_tuple(5, 8, 4)}

        def go(cfg, delist):
            mkt = sim.Market({SYM: mk}, {}, {}, {SYM: 0.01}, delist=delist)
            tr, cnt = sim.simulate(cfg, mkt, sig, workers=1, opp={})
            return tr, cnt

        t_none, c_none = go(make_cfg(), None)
        t_data, c_data = go(make_cfg(), dl)
        pd.testing.assert_frame_equal(t_none, t_data)
        self.assertEqual(c_none, c_data)
        t_on, _ = go(make_cfg(filters={**make_cfg().filters, "delist_rule": True}), dl)
        self.assertEqual(t_on["exit_reason"].iloc[0], "delisted")

    def test_x7_entry_in_flat_not_occupying(self):
        from research import metrics as M

        cfg = make_cfg(entry={"mode": "limit", "limit": {"price": "signal_close", "offset": 0.0, "valid_bars": 6}}, filters={**make_cfg().filters, "delist_rule": True})
        # bars 1-2 stay above the limit (99.5 < 100 is needed to fill: a bar trading through 100 from above), the fill happens in bar 5 inside the flat run
        rows = [FLAT, (103.0, 104.0, 102.0, 103.0), (103.0, 104.0, 102.0, 103.0), (103.0, 104.0, 102.0, 103.0), (103.0, 104.0, 102.0, 103.0), (102.0, 102.5, 99.0, 100.0), (100.0, 100.0, 100.0, 100.0)]
        att: list = []
        out, cnt = run_dl(cfg, rows, make_sig(entry_idx=1), delist=dl_tuple(5, 6, 3), attempts=att)
        self.assertEqual(out, [])
        self.assertEqual(cnt["delisted_no_entry"], 1)
        self.assertEqual(att[0][7], "delisted_no_entry")
        a = pd.DataFrame(att, columns=sim._ATT_COLS)
        a["signal_time"] = pd.Timestamp("2025-01-01", tz="UTC")
        a["end_time"] = a["signal_time"]
        a["sample"] = "IS"
        a["status"] = a["status"]
        t, a2 = M.one_per_symbol(a, pd.DataFrame({"attempt_id": [], "sample": []}))
        self.assertEqual(len(a2), 0)  # does not occupy the symbol


if __name__ == "__main__":
    unittest.main()
