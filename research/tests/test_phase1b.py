"""Phase 1b: config keys and shas, the 10 experiments, neighbours, channel exit, 1d bars, Chan filters, filter delta."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from research import common as C, donchian, phase1b, run, sim
from research.tests.test_sim import BASE_CFG, BASE_US, SLIP, STEP, TAKER, col, make_bars, make_cfg, make_sig

DSIG = {"source": "donchian", "tf": "1h", "types": ["dc20_long", "dc20_short"], "donchian_n": 20}
FLT = BASE_CFG["filters"]


def sha_of_yaml(y):
    return run.config_sha(sim.SimConfig.from_dict(y).resolved())


class Phase1bTests(unittest.TestCase):
    def test_b1_all_registry_shas_unchanged(self):
        reg = run.read_registry(C.OUT / "registry.md")
        self.assertGreaterEqual(len(reg), 26)
        n = 0
        for name, shas in reg.items():
            p = (C.EXPERIMENTS / "neighbors" if run.NB_MARK in name else C.EXPERIMENTS) / f"{name}.yaml"
            self.assertTrue(p.exists(), name)
            self.assertIn(sha_of_yaml(C.read_yaml(p)), shas, name)
            n += 1
        self.assertGreaterEqual(n, 26)

    def test_b2_new_keys_validation(self):
        # delist_rule: bool, optional
        sim.SimConfig.from_dict(copy.deepcopy(BASE_CFG))
        cfg = make_cfg(filters={**FLT, "delist_rule": True})
        self.assertTrue(cfg.resolved()["filters"]["delist_rule"])
        self.assertNotIn("delist_rule", make_cfg().resolved()["filters"])
        for bad in ("yes", 1, None):
            with self.assertRaises(sim.ConfigError):
                make_cfg(filters={**FLT, "delist_rule": bad})
        # dc_* only donchian 1h / 4h
        make_cfg(signals=DSIG, filters={**FLT, "dc_bias_4h": True, "dc_not_in_zs4h": True})
        make_cfg(signals={**DSIG, "tf": "4h"}, filters={**FLT, "dc_bias_4h": True})
        for kw in ({"dc_bias_4h": True}, {"dc_not_in_zs4h": True}):
            with self.assertRaises(sim.ConfigError):
                make_cfg(filters={**FLT, **kw})  # chan
            with self.assertRaises(sim.ConfigError):
                make_cfg(signals={**DSIG, "tf": "1d"}, filters={**FLT, **kw})
        d = make_cfg(signals=DSIG, filters={**FLT, "dc_bias_4h": True}).resolved()
        self.assertNotIn("dc_not_in_zs4h", d["filters"])
        # donchian_exit
        ok = make_cfg(signals={**DSIG, "tf": "4h", "types": ["dc55_long", "dc55_short"], "donchian_n": 55}, exit={"donchian_exit": {"enabled": True, "n": 27}})
        self.assertEqual(ok.exit["donchian_exit"], {"enabled": True, "n": 27})
        self.assertNotIn("donchian_exit", make_cfg().exit)  # absent unless enabled
        with self.assertRaises(sim.ConfigError):
            make_cfg(exit={"donchian_exit": {"enabled": True, "n": 10}})  # chan
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals=DSIG, exit={"donchian_exit": {"enabled": True, "n": 7}})  # not in NS_BY_TF
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals=DSIG, exit={"donchian_exit": {"enabled": True, "n": 10}, "opposite_signal": {"enabled": True, "tf": "1h"}})
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals=DSIG, exit={"donchian_exit": {"enabled": True, "n": 5}})
        # 1d only for donchian
        make_cfg(signals={**DSIG, "tf": "1d"}, exit={"donchian_exit": {"enabled": True, "n": 10}})
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals={"source": "chan", "tf": "1d", "types": ["second_buy"], "donchian_n": None})
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals={**DSIG, "tf": "1h", "donchian_n": 10, "types": ["dc10_long", "dc10_short"]})  # 1h keeps its old set

    def test_b3_gen_matches_plan(self):
        want = [
            ("p1b_base_1h_n20", "base", "1h", 20, "same_n", None, None, None),
            ("p1b_base_4h_n55", "base", "4h", 55, "same_n", None, None, None),
            ("p1b_tr_4h_n20", "tr", "4h", 20, "half", 10, None, None),
            ("p1b_tr_4h_n55", "tr", "4h", 55, "half", 27, None, None),
            ("p1b_tr_1d_n20", "tr", "1d", 20, "half", 10, None, None),
            ("p1b_tr_1d_n55", "tr", "1d", 55, "half", 27, None, None),
            ("p1b_base_1h_n20_bias", "filter", "1h", 20, "same_n", None, "bias4h", "p1b_base_1h_n20"),
            ("p1b_base_4h_n55_bias", "filter", "4h", 55, "same_n", None, "bias4h", "p1b_base_4h_n55"),
            ("p1b_base_1h_n20_nozs", "filter", "1h", 20, "same_n", None, "nozs4h", "p1b_base_1h_n20"),
            ("p1b_base_4h_n55_nozs", "filter", "4h", 55, "same_n", None, "nozs4h", "p1b_base_4h_n55"),
        ]
        specs = phase1b.gen_specs()
        self.assertEqual([(s["name"], s["kind"], s["tf"], s["n"], s["exit"], s["exit_n"], s["filter"], s["control"]) for s in specs], want)
        for s in specs:
            y = s["yaml"]
            self.assertIs(y["filters"]["delist_rule"], True)
            self.assertEqual(y["signals"]["types"], [f"dc{s['n']}_long", f"dc{s['n']}_short"])
            self.assertEqual(y["stop"]["buffer_atr"], 2.0)
            if s["exit"] == "half":
                self.assertEqual(y["exit"], {"donchian_exit": {"enabled": True, "n": s["n"] // 2}})
            else:
                self.assertEqual(y["exit"], {"opposite_signal": {"enabled": True, "tf": s["tf"]}})
            self.assertEqual(bool(y["filters"].get("dc_bias_4h")), s["filter"] == "bias4h")
            self.assertEqual(bool(y["filters"].get("dc_not_in_zs4h")), s["filter"] == "nozs4h")
            sim.SimConfig.from_dict(y)
        for new, old in phase1b.OLD_BASE.items():
            y = copy.deepcopy(next(s for s in specs if s["name"] == new)["yaml"])
            del y["filters"]["delist_rule"]
            self.assertEqual(phase1b.P1.core_of(y), phase1b.P1.core_of(C.read_yaml(C.EXPERIMENTS / f"{old}.yaml")))
        cores = {phase1b.P1.core_of(s["yaml"]) for s in specs}
        self.assertEqual(len(cores), 10)

    def test_b4_neighbor_specs(self):
        specs = {s["name"]: s["yaml"] for s in phase1b.gen_specs()}
        nb = {x["name"]: x["yaml"] for x in phase1b.neighbor_specs("p1b_tr_4h_n55", specs["p1b_tr_4h_n55"])}
        self.assertEqual(sorted(nb), sorted(f"p1b_tr_4h_n55__nb_{c}" for c in ("dcn_44", "dcn_66", "stop_1p6", "stop_2p4")))
        self.assertEqual(nb["p1b_tr_4h_n55__nb_dcn_44"]["signals"]["donchian_n"], 44)
        self.assertEqual(nb["p1b_tr_4h_n55__nb_dcn_44"]["exit"]["donchian_exit"]["n"], 22)
        self.assertEqual(nb["p1b_tr_4h_n55__nb_dcn_66"]["exit"]["donchian_exit"]["n"], 33)
        self.assertEqual(nb["p1b_tr_4h_n55__nb_stop_1p6"]["stop"]["buffer_atr"], 1.6)
        self.assertEqual(nb["p1b_tr_4h_n55__nb_stop_2p4"]["stop"]["buffer_atr"], 2.4)
        self.assertTrue(nb["p1b_tr_4h_n55__nb_dcn_44"]["description"].startswith("NEIGHBOR of p1b_tr_4h_n55: signals.donchian_n=44 (exit n=22)"))
        nb = {x["name"]: x["yaml"] for x in phase1b.neighbor_specs("p1b_base_1h_n20_bias", specs["p1b_base_1h_n20_bias"])}
        self.assertEqual(sorted(nb), sorted(f"p1b_base_1h_n20_bias__nb_{c}" for c in ("dcn_16", "dcn_24", "stop_1p6", "stop_2p4")))
        for v in (16, 24):
            y = nb[f"p1b_base_1h_n20_bias__nb_dcn_{v}"]
            self.assertEqual(y["signals"]["types"], [f"dc{v}_long", f"dc{v}_short"])
            self.assertIs(y["filters"]["dc_bias_4h"], True)
            self.assertIs(y["filters"]["delist_rule"], True)
            self.assertEqual(y["exit"], {"opposite_signal": {"enabled": True, "tf": "1h"}})
            self.assertEqual(y["stop"]["buffer_atr"], 2.0)
        for x in nb.values():
            sim.SimConfig.from_dict(x)
        nb = {x["name"]: x["yaml"] for x in phase1b.neighbor_specs("p1b_tr_1d_n20", specs["p1b_tr_1d_n20"])}
        self.assertEqual(nb["p1b_tr_1d_n20__nb_dcn_16"]["exit"]["donchian_exit"]["n"], 8)
        self.assertEqual(nb["p1b_tr_1d_n20__nb_dcn_24"]["exit"]["donchian_exit"]["n"], 12)
        for x in nb.values():
            sim.SimConfig.from_dict(x)

    def test_b5_half_channel_exit(self):
        # 4h series: 30 flat bars, an upside breakout at bar 30, a rise, and the first close below the previous 10 lows at bar 36
        h = np.r_[np.full(30, 101.0), 111.0, 112, 113, 114, 115, 116, 117, 118, 119]
        lo = np.r_[np.full(30, 99.0), 100.0, 105, 106, 107, 108, 109, 110, 90, 90]
        c = np.r_[np.full(30, 100.0), 110.0, 111, 112, 113, 114, 115, 116, 90, 90]
        up, dn = donchian.breakouts(h, lo, c, 10)
        self.assertEqual(list(np.flatnonzero(up)), [30])
        self.assertEqual(list(np.flatnonzero(dn)), [37])  # bar 37: the first close under the 10-bar low
        t0 = pd.Timestamp(BASE_US, unit="us", tz="UTC")
        close_time = t0 + pd.to_timedelta((np.arange(len(c)) + 1) * 4, unit="h")
        table = pd.DataFrame({"symbol": "X/USDT", "side": -1, "time": [close_time[i] for i in np.flatnonzero(dn)], "n": 10})
        cfg = make_cfg(
            signals={"source": "donchian", "tf": "4h", "types": ["dc20_long", "dc20_short"], "donchian_n": 20},
            exit={"donchian_exit": {"enabled": True, "n": 10}},
            stop={"buffer_atr": 2.0, "round_to_tick": True},
        )
        with mock.patch.object(sim, "load_signal_table", return_value=table):
            opp = sim.opposite_times(cfg)
        self.assertEqual(int(opp["X/USDT"][-1][0]), int(close_time[37].value // 1000))
        entry_idx = 31 * 16
        rows = [(110.0, 110.5, 109.5, 110.0)] * (40 * 16)
        sig = make_sig(entry_idx=entry_idx, close=110.0, defending=110.0, atr=2.0)
        sig["tf"] = "4h"
        out, _ = sim.simulate_symbol(cfg, "X/USDT", sig, make_bars(rows), ((), (), ()), None, opp, 0.01)
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "exit_reason"), "channel_exit")
        self.assertEqual(col(out, "exit_time"), BASE_US + 38 * 16 * STEP)  # next 15m open after bar 37's close
        self.assertAlmostEqual(col(out, "exit_price"), 110.0 * (1 - SLIP), places=9)
        # a breakout that happened before the entry is not a signal: strictly later than the entry bar's open
        self.assertEqual(40 // 2, 20)
        self.assertEqual([s["exit_n"] for s in phase1b.gen_specs() if s["n"] == 55 and s["exit"] == "half"], [27, 27])

    def test_b6_daily_bars_utc(self):
        t = pd.date_range("2025-01-01", periods=96 * 10, freq="15min", tz="UTC")
        rng = np.arange(len(t), dtype=float)
        base = pd.DataFrame({"open_time": t, "close_time": t + pd.Timedelta(minutes=15), "open": 100 + rng * 0.0, "high": 101 + rng * 0.0, "low": 99 + rng * 0.0,
                             "close": np.full(len(t), 100.0), "volume": np.full(len(t), 2.0)})
        base.loc[96 * 9 :, ["high", "close"]] = [150.0, 150.0]  # last day breaks out upside
        base.loc[96 + 5, "low"] = 90.0
        d = donchian.daily_bars(base)
        self.assertEqual(len(d), 10)
        self.assertEqual(d["open_time"].iloc[1], pd.Timestamp("2025-01-02", tz="UTC"))
        self.assertEqual(d["close_time"].iloc[1], pd.Timestamp("2025-01-03", tz="UTC"))
        self.assertEqual(d["low"].iloc[1], 90.0)
        self.assertEqual(d["volume"].iloc[1], 192.0)
        self.assertEqual(d["n15"].iloc[1], 96)
        self.assertEqual(d["open"].iloc[1], 100.0)
        self.assertEqual(d["close"].iloc[9], 150.0)
        # a partial last day is still a bar
        part = donchian.daily_bars(base.iloc[: 96 * 9 + 10])
        self.assertEqual((len(part), part["n15"].iloc[-1]), (10, 10))
        with mock.patch.object(C, "load_bars_df", return_value=base):
            sg = donchian.signals_for("X/USDT", "1d", {})
        x = sg[(sg["n"] == 8) & (sg["side"] == 1)]
        self.assertEqual(len(x), 1)
        self.assertEqual(x["time"].iloc[0], pd.Timestamp("2025-01-11", tz="UTC"))  # close_time of day 10: UTC 00:00 of the next day
        self.assertTrue((sg["time"].dt.hour == 0).all() and (sg["time"].dt.minute == 0).all())
        # entry at the open of the 15m bar whose open_time equals the signal time
        sig = make_sig(entry_idx=96, defending=95.0, atr=2.0)
        out, _ = sim.simulate_symbol(make_cfg(), "X/USDT", sig, make_bars([(100.0, 100.5, 99.5, 100.0)] * 200), ((), (), ()), None, {}, 0.01)
        self.assertEqual(col(out, "entry_time"), BASE_US + 96 * STEP)

    def test_b7_dc_filters(self):
        n = 8
        df = pd.DataFrame(
            {
                "symbol": "X/USDT", "type": "dc20_long", "n": 20, "in_top20": True, "time": pd.Timestamp("2025-01-01", tz="UTC") + pd.to_timedelta(np.arange(n), unit="h"),
                "side": [1, 1, 1, 1, -1, -1, -1, -1],
                "close": 100.0,
                "bias4_snap": ["up", "breakout_up", "down", None, "down", "breakout_down", "up", None],
                "zs4_zg": [np.nan, 110, 110, 110, 100, 100, 100, np.nan],
                "zs4_zd": [np.nan, 100, 90, 101, 99, 99, 99, np.nan],
                "zs4_count": [0, 1, 1, 1, 1, 1, 1, np.nan],
            }
        )
        df["type"] = np.where(df["side"] == 1, "dc20_long", "dc20_short")

        def sel(**kw):
            cfg = make_cfg(signals=DSIG, filters={**FLT, **kw})
            with mock.patch.object(sim, "load_signal_table", return_value=df.copy()):
                return list(sim.select_signals(cfg)["time"].dt.hour)

        self.assertEqual(sel(), list(range(8)))
        self.assertEqual(sel(dc_bias_4h=True), [0, 1, 4, 5])  # long: up / breakout_up; short: down / breakout_down; None and opposite blocked
        # zone [zd, zg]: close == zg (rows 4, 5: 100 <= 100) and close == zd (row 1: zd == 100) are inside; outside passes; count 0 / NaN passes
        self.assertEqual(sel(dc_not_in_zs4h=True), [0, 3, 7])  # row 2: 90 <= 100 <= 110 inside; row 3: zd 101 > 100 outside; row 6: inside
        self.assertEqual(sel(dc_bias_4h=True, dc_not_in_zs4h=True), [0])

    def test_b8_dcaug_no_lookahead(self):
        from research import signals

        p = C.CACHE / "signals_donchian_4h_aug.parquet"
        if not p.exists():
            self.skipTest("dcaug not built")
        aug = pd.read_parquet(p)
        tab = pd.read_parquet(C.CACHE / "signals_donchian_4h.parquet", columns=["symbol", "in_top20"])
        idx = np.flatnonzero((tab["symbol"] == "BTC/USDT").to_numpy() & tab["in_top20"].to_numpy(bool))
        self.assertGreaterEqual(len(idx), 3)
        eng = signals.make_engine()
        bars = signals.closed_bars("4h", "BTC/USDT")
        for i in (idx[0], idx[len(idx) // 2], idx[-1]):
            row = aug.iloc[i]
            T = row["time"].to_pydatetime()
            seen = [b for b in bars if b.close_time <= T]  # only bars closed by T
            snap = signals.snapshot(eng, seen[-C.WINDOWS["4h"] :], "4h")
            self.assertEqual(row["bias4_snap"], snap.structure_bias.value)
            if snap.zhongshus:
                self.assertEqual(row["zs4_count"], len(snap.zhongshus))
                self.assertAlmostEqual(row["zs4_zg"], float(snap.zhongshus[-1].zg), places=9)
                self.assertAlmostEqual(row["zs4_zd"], float(snap.zhongshus[-1].zd), places=9)
            else:
                self.assertEqual(row["zs4_count"], 0)
            # dropping every later bar changes nothing
            snap2 = signals.snapshot(eng, seen[-C.WINDOWS["4h"] :][:], "4h")
            self.assertEqual(snap2.structure_bias.value, snap.structure_bias.value)

    def test_b9_filter_delta(self):
        ctl = {"net_r": -0.0050, "gross_r": 0.0250, "n": 6000}
        flt = {"net_r": 0.0150, "gross_r": 0.0400, "n": 2500}
        d = phase1b.filter_delta(flt, ctl, {"net_r": 0.01}, {"net_r": -0.02})
        self.assertAlmostEqual(d["delta"], 0.02)
        self.assertAlmostEqual(d["gross_delta"], 0.015)
        self.assertAlmostEqual(d["delta_ind"], 0.03)
        self.assertEqual((d["n_filter"], d["n_control"]), (2500, 6000))
        self.assertLess(phase1b.filter_delta(ctl, flt)["delta"], 0)


if __name__ == "__main__":
    unittest.main()
