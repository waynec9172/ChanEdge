"""ICT P2 S0 tools: cooldown, bootstrap, DSR, gate A', OOS A1.1 functions, gen, audit allowance, compare_frames."""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from research import common as C
from research import metrics as M
from research import phase1b as P1B
from research import run as R
from research import sim
from research.ict import generate as G
from research.ict import oos_a1 as OA
from research.ict import report_is as RI
from research.ict import stats as S

T0 = pd.Timestamp("2024-03-01 00:00", tz="UTC")
H = 3_600_000_000

LEGACY_SHA = {
    "donchian_1h_n20.yaml": "84a0bcbc2647",
    "donchian_4h_n55.yaml": "5676294a19f3",
    "neighbors/p1b_tr_4h_n20__nb_dcn_16.yaml": "f1fda4791329",
    "neighbors/p1b_tr_4h_n20__nb_dcn_24.yaml": "2be186a92d70",
    "neighbors/p1b_tr_4h_n20__nb_stop_1p6.yaml": "ca20254e5a4a",
    "neighbors/p1b_tr_4h_n20__nb_stop_2p4.yaml": "1c4c6531f594",
    "p0_perf_15m_all.yaml": "9b64a9e432ea",
    "p0_validate_current_15m.yaml": "422b2b9d5ca3",
    "p1b_base_1h_n20.yaml": "a7f6dc5034d4",
    "p1b_base_1h_n20_bias.yaml": "f8efcf0b8ced",
    "p1b_base_1h_n20_nozs.yaml": "eeb74d16b643",
    "p1b_base_4h_n55.yaml": "ee75906aeada",
    "p1b_base_4h_n55_bias.yaml": "3230935ca39f",
    "p1b_base_4h_n55_nozs.yaml": "3680c62a8212",
    "p1b_tr_1d_n20.yaml": "dd945175e84e",
    "p1b_tr_1d_n55.yaml": "17b24cb34702",
    "p1b_tr_4h_n20.yaml": "f3d79ea95641",
    "p1b_tr_4h_n55.yaml": "605096e5bbe9",
    "p1s1_15m_at2.yaml": "3900eef11a97",
    "p1s1_15m_at3.yaml": "f00d19bb7826",
    "p1s1_15m_cur.yaml": "58b8b1e54b35",
    "p1s1_15m_cur_jevref.yaml": "1bc476ad618e",
    "p1s1_15m_fx2.yaml": "1be33ad938b7",
    "p1s1_15m_fx3.yaml": "e9fef2677122",
    "p1s1_15m_opp.yaml": "fb6166121755",
    "p1s1_15m_rat.yaml": "1a98545ad6df",
    "p1s1_1h_at2.yaml": "2f06a1362729",
    "p1s1_1h_at3.yaml": "9200212e7de8",
    "p1s1_1h_cur.yaml": "ec7bfe9fe3dc",
    "p1s1_1h_fx2.yaml": "3c04d3ab59ee",
    "p1s1_1h_fx3.yaml": "a99943168ed2",
    "p1s1_1h_opp.yaml": "9b16733fdeed",
    "p1s1_1h_rat.yaml": "e45340b19ca2",
    "p1s1_4h_at2.yaml": "aac9b5ee6bac",
    "p1s1_4h_at3.yaml": "8f7b106633df",
    "p1s1_4h_cur.yaml": "9f9bc47d6b65",
    "p1s1_4h_fx2.yaml": "733afc03df09",
    "p1s1_4h_fx3.yaml": "836b3c31b455",
    "p1s1_4h_opp.yaml": "3714aba5d2de",
    "p1s1_4h_rat.yaml": "2179705d7a11",
}


def att(aid, sym, minutes, end_minutes, side=1, status="filled", sample="IS"):
    return {
        "attempt_id": aid, "signal_id": f"s{aid}", "symbol": sym, "tf": "15m", "type": "ict_long" if side == 1 else "ict_short",
        "side": side, "signal_time": T0 + pd.Timedelta(minutes=minutes), "status": status,
        "end_time": T0 + pd.Timedelta(minutes=end_minutes), "sample": sample,
    }


def trades_of(a, net=0.1):
    f = a[a["status"] == "filled"]
    return pd.DataFrame({"attempt_id": f["attempt_id"], "sample": f["sample"], "net_r": net, "symbol": f["symbol"]})


class T01Cooldown(unittest.TestCase):
    def v2(self, rows, cd=0):
        a = pd.DataFrame(rows)
        t, a2 = M.one_per_symbol(a, trades_of(a), cooldown_us=cd) if cd else M.one_per_symbol(a, trades_of(a))
        return sorted(a2["attempt_id"])

    def test_default_is_zero_and_old_behaviour(self):
        rows = [att(1, "A/USDT", 0, 60), att(2, "A/USDT", 61, 120), att(3, "A/USDT", 60, 90)]
        a = pd.DataFrame(rows)
        self.assertEqual(inspect.signature(M.one_per_symbol).parameters["cooldown_us"].default, 0)
        r0 = M.one_per_symbol(a, trades_of(a))
        r1 = M.one_per_symbol(a, trades_of(a), cooldown_us=0)
        pd.testing.assert_frame_equal(r0[1], r1[1])
        pd.testing.assert_frame_equal(r0[0], r1[0])
        self.assertEqual(sorted(r0[1]["attempt_id"]), [1, 2])  # 60 is not > 60 (strict); 61 is

    def test_cooldown_blocks_until_strictly_after(self):
        four_h = 4 * H
        rows = [att(1, "A/USDT", 0, 60), att(2, "A/USDT", 60 + 4 * 60, 400), att(3, "A/USDT", 60 + 4 * 60 + 1, 500)]
        self.assertEqual(self.v2(rows, four_h), [1, 3])  # exactly end+4h is blocked, one minute later is taken

    def test_cooldown_counts_from_the_taken_attempt_only(self):
        four_h = 4 * H
        rows = [att(1, "A/USDT", 0, 10), att(2, "A/USDT", 100, 200), att(3, "A/USDT", 300, 330), att(4, "A/USDT", 500, 520)]
        # 2 blocked (<=10m+240m), 3 taken (300>250)... 1 ends 10, busy until 250; 2 at 100 blocked; 3 at 300 taken -> busy 570; 4 at 500 blocked
        self.assertEqual(self.v2(rows, four_h), [1, 3])

    def test_cooldown_is_per_symbol_and_long_short_tie_still_skipped(self):
        rows = [att(1, "A/USDT", 0, 10), att(2, "B/USDT", 5, 15), att(3, "A/USDT", 20, 30, side=-1), att(4, "A/USDT", 20, 30, side=1)]
        self.assertEqual(self.v2(rows, 4 * H), [1, 2])

    def test_negative_cooldown_rejected(self):
        a = pd.DataFrame([att(1, "A/USDT", 0, 10)])
        with self.assertRaises(ValueError):
            M.one_per_symbol(a, trades_of(a), cooldown_us=-1)


class T02Bootstrap(unittest.TestCase):
    def test_week_index(self):
        s = pd.Series(pd.to_datetime(["2024-01-01 00:00", "2024-01-07 23:59:59", "2024-01-08 00:00", "2025-06-30 12:00"], utc=True, format="ISO8601"))
        self.assertEqual(list(S.week_index(s)), [0, 0, 1, 78])
        self.assertEqual(S.IS_WEEKS, 79)
        self.assertEqual(S.WEEK_ORIGIN.day_of_week, 0)

    def test_deterministic_and_matches_manual_recipe(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0.1, 1.0, 300)
        w = rng.integers(0, 79, 300)
        a, b = S.block_bootstrap_lb(x, w), S.block_bootstrap_lb(x, w)
        self.assertEqual(a, b)
        idx = np.random.default_rng(20261105).integers(0, 79, size=(2000, 79))
        sums = np.array([x[w == k].sum() for k in range(79)])
        cnts = np.array([(w == k).sum() for k in range(79)])
        st = np.array([sums[i].sum() / cnts[i].sum() if cnts[i].sum() else 0.0 for i in idx])
        self.assertAlmostEqual(a["lb"], float(np.quantile(st, 0.10)), places=12)
        self.assertEqual((a["n_boot"], a["seed"], a["q"]), (2000, 20261105, 0.10))

    def test_signs(self):
        w = np.arange(200) % 79
        self.assertGreater(S.block_bootstrap_lb(np.full(200, 0.2), w)["lb"], 0)
        z = np.tile([1.0, -1.0], 100)
        self.assertLess(S.block_bootstrap_lb(z, w)["lb"], 0.05)
        self.assertLess(S.block_bootstrap_lb(np.full(200, -0.2), w)["lb"], 0)

    def test_empty_weeks_count_and_zero_draws(self):
        # one trade in week 0 of 79: replicates that miss week 0 have no trades -> statistic 0; lb = quantile includes those zeros
        r = S.block_bootstrap_lb([5.0], [0])
        self.assertEqual(r["lb"], 0.0)  # P(miss) = (78/79)^79 ~ 0.37 > 0.10, so the 10% quantile is 0
        self.assertEqual(S.block_bootstrap_lb([], [])["lb"], 0.0)

    def test_out_of_grid_rejected(self):
        with self.assertRaises(ValueError):
            S.block_bootstrap_lb([1.0], [79])


class T03Dsr(unittest.TestCase):
    def test_formula(self):
        rng = np.random.default_rng(3)
        x = rng.normal(0.05, 1.0, 400)
        v, n = 0.0004, 60
        d = S.deflated_sharpe(x, v, n)
        from statistics import NormalDist as ND

        nd = ND()
        g = 0.5772156649
        sr0 = math.sqrt(v) * ((1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e)))
        m, sd = x.mean(), x.std(ddof=1)
        sr = m / sd
        z = (x - m) / x.std(ddof=0)
        sk, ku = (z**3).mean(), (z**4).mean()
        want = nd.cdf((sr - sr0) * math.sqrt(len(x) - 1) / math.sqrt(1 - sk * sr + (ku - 1) / 4 * sr**2))
        self.assertAlmostEqual(d["dsr"], want, places=12)
        self.assertAlmostEqual(d["sr0"], sr0, places=12)
        self.assertEqual(d["n_trials"], 60)

    def test_monotone_in_n_and_nan_cases(self):
        x = np.random.default_rng(4).normal(0.1, 1.0, 300)
        self.assertGreater(S.deflated_sharpe(x, 0.001, 30)["dsr"], S.deflated_sharpe(x, 0.001, 60)["dsr"])
        self.assertTrue(math.isnan(S.deflated_sharpe(x, math.nan, 60)["dsr"]))
        self.assertTrue(math.isnan(S.deflated_sharpe([0.5, 0.5, 0.5], 0.001, 60)["dsr"]))  # zero variance
        self.assertTrue(math.isnan(S.var_of_srs([0.1])))
        self.assertAlmostEqual(S.var_of_srs([0.1, 0.3, math.nan]), 0.02)


def good_summary(**kw):
    s = {"n": 200, "net_r": 0.15, "pf": 1.4, "net_fee15": 0.05, "pos_q": 5, "long": {"n": 100, "net_r": 0.1, "pf": 1.3},
         "short": {"n": 100, "net_r": 0.2, "pf": 1.5}, "boot": {"lb": 0.01}}
    s.update(kw)
    return s


NB_OK = [0.1, 0.1, 0.1, 0.1]


class T04GateAPrime(unittest.TestCase):
    def test_pass_and_each_condition_fails_alone(self):
        self.assertTrue(RI.gate_a_prime(good_summary(), NB_OK)["pass"])
        cases = {
            "n": good_summary(n=149), "net_r": good_summary(net_r=0.0799), "pf": good_summary(pf=1.19),
            "fee15": good_summary(net_fee15=0.0), "pos_q": good_summary(pos_q=4), "boot_lb": good_summary(boot={"lb": 0.0}),
            "long": good_summary(long={"n": 1, "net_r": 0.0, "pf": 1}), "short": good_summary(short={"n": 1, "net_r": -0.1, "pf": 1}),
        }
        for k, s in cases.items():
            g = RI.gate_a_prime(s, NB_OK)
            self.assertFalse(g[k][1], k)
            self.assertFalse(g["pass"], k)

    def test_boundaries_inclusive(self):
        g = RI.gate_a_prime(good_summary(n=150, net_r=0.08, pf=1.2, pos_q=5), NB_OK)
        self.assertTrue(g["pass"])

    def test_neighbors(self):
        for nb in (None, [], [0.1] * 3, [0.1, 0.1, 0.1, 0.0], [0.1, 0.1, 0.1, math.nan]):
            g = RI.gate_a_prime(good_summary(), nb)
            self.assertFalse(g["pass"])
            self.assertFalse(g["neighbors"][1])
        self.assertEqual(RI.gate_a_prime(good_summary(), None)["neighbors_note"], "missing neighbour results")

    def test_nan_never_passes(self):
        g = RI.gate_a_prime(good_summary(net_r=math.nan, pf=math.nan, net_fee15=math.nan, boot={"lb": math.nan}), NB_OK)
        self.assertFalse(any(g[k][1] for k in ("net_r", "pf", "fee15", "boot_lb")))

    def test_rank_candidates(self):
        def row(n, nr, cnt, ok=True):
            return n, good_summary(net_r=nr, n=cnt), {"pass": ok}

        rows = [row("ict_b", 0.2, 160), row("ict_a", 0.2, 160), row("ict_rand", 0.9, 300), row("ict_c", 0.3, 151), row("ict_d", 0.5, 400, ok=False)]
        self.assertEqual(RI.rank_candidates(rows), ["ict_c", "ict_a"])
        self.assertEqual(RI.rank_candidates([row("ict_rand", 0.9, 300)]), [])
        self.assertEqual(RI.rank_candidates(rows[:1]), ["ict_b"])  # no padding

    def test_analyse_and_render_on_synthetic_trades(self):
        rng = np.random.default_rng(9)
        n = 240
        st = pd.Timestamp("2024-01-15", tz="UTC") + pd.to_timedelta(rng.integers(0, 24 * 60 * 500, n), unit="m")
        t = pd.DataFrame({
            "signal_time": st, "side": rng.choice([-1, 1], n), "net_r": rng.normal(0.2, 1.0, n), "gross_r": rng.normal(0.25, 1.0, n),
            "fee_r": 0.03, "funding_r": 0.0, "exit_reason": "structure_stop", "bars_held": 3, "tf": "15m", "mfe_r": 1.0, "mae_r": 0.5,
            "symbol": "BTC/USDT", "funding_missing": False, "exit_time": st + pd.Timedelta(hours=1), "slip_r": 0.01,
            "amb_stop_target": rng.random(n) < 0.1, "amb_tp1_entry": False,
        })
        s = RI.analyse(t)
        self.assertEqual(s["n"], n)
        self.assertIn("lb", s["boot"])
        self.assertGreater(s["amb"], 0)
        data = {"ict_L7": {"s": s, "trades": t, "dsr": S.deflated_sharpe(t["net_r"], 0.001, 55)},
                "_dsr_ctx": {"var_sr": 0.001, "n_trials": 55, "n_srs": 3}}
        with mock.patch.object(RI, "nb_values", return_value=[]):
            md = RI.render(data, ["ict_L7"])
        self.assertIn("ict_L7", md)
        self.assertIn("missing neighbour results", md)
        self.assertIn("H-ICT 未通過", md)  # no neighbours -> A' cannot pass

    def test_ambiguous_ratio(self):
        t = pd.DataFrame({"amb_stop_target": [True, False, False, False], "amb_tp1_entry": [False, True, False, False]})
        self.assertEqual(RI.ambiguous_trade_ratio(t), 0.5)
        self.assertTrue(math.isnan(RI.ambiguous_trade_ratio(pd.DataFrame({"net_r": [1.0]}))))


class T05NoOosPath(unittest.TestCase):
    def test_report_is_has_no_oos_path(self):
        src = inspect.getsource(RI)
        self.assertNotIn("oos_a1", src)
        self.assertNotIn("read_parquet", src)  # results only via metrics.load_is
        self.assertIn("M.load_is", src)
        self.assertNotIn("--oos", src)

    def test_v2_uses_load_is_and_cooldown(self):
        a = pd.DataFrame([att(1, "A/USDT", 0, 60), att(2, "A/USDT", 120, 180), att(3, "A/USDT", 400, 420)])
        with mock.patch.object(M, "load_is", return_value=(trades_of(a), a)) as li, mock.patch.object(pd, "read_parquet", side_effect=AssertionError("direct read")):
            t, a2 = RI.v2("x")
        li.assert_called_once_with("x")
        self.assertEqual(sorted(a2["attempt_id"]), [1, 3])  # 120 is inside end(60)+4h

    def test_nothing_imports_oos_module_by_default(self):
        for mod in (RI, G, S):
            self.assertNotIn("oos_a1", inspect.getsource(mod), mod.__name__)
        self.assertFalse(hasattr(OA, "main"))
        src = inspect.getsource(OA)
        self.assertNotIn("read_parquet", src)
        self.assertNotIn("argparse", src)
        self.assertNotIn("__main__", src)


def oos_trades(n_per_period, mean=0.2, sides=(1, -1), tradfi=False):
    rows = []
    starts = {"2025Q3": "2025-07-10", "2025Q4": "2025-10-10", "2026Q1": "2026-01-10", "2026Q2": "2026-04-10", "2026Q3+": "2026-09-10"}
    for p, d in starts.items():
        for i in range(n_per_period.get(p, 0)):
            rows.append({"signal_time": pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=i), "side": sides[i % len(sides)],
                         "net_r": mean + (0.5 if (i // 2) % 2 else -0.5) * 0.5, "gross_r": mean + 0.03, "fee_r": 0.02, "funding_r": 0.0,
                         "exit_reason": "structure_stop", "bars_held": 3, "tf": "15m", "mfe_r": 1.0, "mae_r": 0.5, "symbol": "BTC/USDT",
                         "funding_missing": False, "exit_time": pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=i + 1), "attempt_id": len(rows)})
    return pd.DataFrame(rows)


class T06OosA1(unittest.TestCase):
    def test_period_of(self):
        s = pd.Series(pd.to_datetime(["2025-07-01", "2025-09-30 23:59", "2025-10-01", "2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01",
                                      "2026-06-30 23:00", "2026-07-01", "2026-10-27", "2025-06-30"], utc=True, format="ISO8601"))
        self.assertEqual(list(OA.period_of(s).fillna("none")), ["2025Q3", "2025Q3", "2025Q4", "2025Q4", "2026Q1", "2026Q1", "2026Q2", "2026Q2",
                                                                 "2026Q3+", "2026Q3+", "none"])

    def test_pass(self):
        t = oos_trades({p: 30 for p in OA.PERIODS})
        r = OA.evaluate(t)
        self.assertEqual(r["verdict"], "PASS", r["cond"])
        self.assertEqual(r["n_long"] + r["n_short"], 150)

    def test_insufficient_total_and_side(self):
        self.assertEqual(OA.evaluate(oos_trades({p: 19 for p in OA.PERIODS}))["verdict"], "INSUFFICIENT")  # 95 < 100
        self.assertEqual(OA.evaluate(oos_trades({p: 30 for p in OA.PERIODS}, sides=(1,)))["verdict"], "INSUFFICIENT")  # shorts = 0
        self.assertEqual(OA.evaluate(oos_trades({}))["verdict"], "INSUFFICIENT")

    def test_fail_when_concentrated_in_one_period(self):
        t = oos_trades({p: 30 for p in OA.PERIODS})
        per = OA.period_of(t["signal_time"])
        t.loc[per == "2026Q1", "net_r"] += 10.0   # one huge period
        t.loc[per != "2026Q1", "net_r"] -= 0.4    # the rest are losers
        r = OA.evaluate(t)
        self.assertEqual(r["best_period"], "2026Q1")
        self.assertFalse(r["cond"]["drop_best"][1])
        self.assertFalse(r["cond"]["pos_periods"][1])
        self.assertEqual(r["verdict"], "FAIL")

    def test_each_condition_can_fail(self):
        base = oos_trades({p: 30 for p in OA.PERIODS})
        low = base.assign(net_r=base["net_r"] - base["net_r"].mean() + 0.04)
        self.assertFalse(OA.evaluate(low)["cond"]["net_r"][1])
        sd = base.copy()
        sd.loc[sd["side"] == -1, "net_r"] -= 5
        self.assertFalse(OA.evaluate(sd)["cond"]["sides"][1])
        fee = base.copy()
        fee["gross_r"] = fee["net_r"]
        fee["fee_r"] = 0.5
        self.assertFalse(OA.evaluate(fee)["cond"]["fee15"][1])

    def test_v2_oos_excludes_tradfi_and_applies_cooldown(self):
        rows = [att(1, "BTC/USDT", 0, 60, sample="OOS"), att(2, "BTC/USDT", 120, 180, sample="OOS"), att(3, "XAU/USDT", 0, 60, sample="OOS"),
                att(4, "BTC/USDT", 600, 660, sample="OOS"), att(5, "ETH/USDT", 0, 60, sample="IS")]
        a = pd.DataFrame(rows)
        t, a2 = OA.v2_oos(a, trades_of(a))
        self.assertEqual(sorted(a2["attempt_id"]), [1, 4])
        self.assertEqual(sorted(t["attempt_id"]), [1, 4])

    def test_bootstrap_report_runs(self):
        r = OA.bootstrap_report(oos_trades({p: 30 for p in OA.PERIODS}))
        self.assertEqual(r["n_weeks"], 70)


class T07Gen(unittest.TestCase):
    def test_registered_files(self):
        files = G.planned_files()
        self.assertEqual(len(files), 19 + 4 + 1)
        names = G.registered_names()
        self.assertEqual(len(names), 19)
        self.assertFalse([n for n in names if "rsv" in n])
        self.assertEqual(names[:8], [f"ict_L{i}" for i in range(8)])
        shas = set()
        for p, text in files.items():
            if p.suffix != ".yaml":
                continue
            y = json.loads(text)
            self.assertEqual(y["name"], p.stem)
            self.assertEqual(p.parent.name == "neighbors", G.NB_MARK in p.stem)
            cfg = sim.SimConfig.from_dict(y)
            shas.add(R.config_sha(cfg.resolved()))
            if G.NB_MARK in p.stem:
                self.assertTrue(y["description"].startswith("NEIGHBOR of ict_L7: "))
            self.assertTrue(y["filters"]["exclude_tradfi"] and y["filters"]["delist_rule"])
        self.assertEqual(len(shas), 23)  # all distinct

    def test_experiments_match_the_plan(self):
        d = {n: G.experiment_dict(n) for n in G.registered_names()}
        self.assertEqual(d["ict_L0"]["signals"]["ict"]["use_htf"], False)
        self.assertTrue(all(d["ict_L7"]["signals"]["ict"][k] for k in G._LADDER_ORDER))
        self.assertTrue(d["ict_x_trail"]["exit"]["ratchet"]["enabled"])
        self.assertNotIn("row_target", d["ict_x_trail"]["exit"])
        self.assertNotIn("time_barrier", d["ict_x_notb"]["exit"])
        self.assertEqual(d["ict_rand"]["signals"]["ict"]["random"], {"seed": 20261105, "match": "ict_L7"})
        self.assertEqual(d["ict_anchor_conf"]["signals"]["ict"]["anchor"], "confirmed")
        self.assertEqual(d["ict_setup15m"]["signals"]["ict"]["setup_tf"], "15m")
        nb = {n: G.experiment_dict(n) for n in G.neighbor_names("ict_L7")}
        self.assertEqual(nb["ict_L7__nb_fvgk_0p4"]["signals"]["ict"]["fvg_k"], 0.4)
        self.assertEqual(nb["ict_L7__nb_fvgk_0p6"]["signals"]["ict"]["fvg_k"], 0.6)
        self.assertEqual(nb["ict_L7__nb_sl_0p2"]["stop"]["buffer_atr"], 0.2)
        self.assertEqual(nb["ict_L7__nb_sl_0p4"]["stop"]["buffer_atr"], 0.4)
        self.assertEqual(nb["ict_L7__nb_sl_0p2"]["signals"]["ict"], d["ict_L7"]["signals"]["ict"])
        self.assertEqual(d["ict_L7"]["stop"]["buffer_atr"], 0.3)

    def test_manifest(self):
        m = G.manifest_dict()
        self.assertEqual([r["name"] for r in m["run"]], G.registered_names())
        self.assertEqual(m["reserved"], [f"ict_rsv{i}" for i in range(1, 6)])
        self.assertEqual(m["order"]["S1"], ["ict_L7"] + G.neighbor_names("ict_L7"))
        self.assertEqual(len(m["order"]["S2"]), 18)
        self.assertEqual(sorted(m["order"]["S1"][:1] + m["order"]["S2"]), sorted(G.registered_names()))
        self.assertEqual(R.n_main({n: set() for n in G.registered_names()}) + 5 + 36, 60)

    def test_files_on_disk_match_generator(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = G.gen(check=True)
        self.assertEqual(rc, 0, buf.getvalue())

    def test_gen_writes_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "ict"
            with mock.patch.object(G, "ICT_EXP_DIR", d), mock.patch.object(G, "ICT_NB_DIR", d / "neighbors"), mock.patch.object(G, "ICT_MANIFEST", d / "ict_manifest.json"):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(G.gen(check=True), 1)
                    self.assertEqual(G.gen(), 0)
                    self.assertEqual(G.gen(check=True), 0)
                    self.assertEqual(G.gen(), 0)  # idempotent
                    (d / "ict_L7.yaml").write_text("tampered")
                    self.assertEqual(G.gen(check=True), 1)
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(G.gen(), 2)  # refuses to overwrite
                self.assertEqual((d / "ict_L7.yaml").read_text(), "tampered")
                self.assertEqual(len(list((d / "neighbors").glob("*.yaml"))), 4)

    def test_neighbors_of_other_experiment(self):
        files = G.planned_files(("ict_x_trail",))
        extra = [p for p in files if p.stem.startswith("ict_x_trail__nb_")]
        self.assertEqual(len(extra), 4)
        y = json.loads(files[[p for p in extra if p.stem.endswith("sl_0p2")][0]])
        self.assertTrue(y["exit"]["ratchet"]["enabled"])
        self.assertEqual(y["stop"]["buffer_atr"], 0.2)
        self.assertTrue(y["description"].startswith("NEIGHBOR of ict_x_trail: "))
        sim.SimConfig.from_dict(y)
        with self.assertRaises(SystemExit):
            G.planned_files(("ict_rand",))
        with self.assertRaises(SystemExit):
            G.planned_files(("ict_rsv1",))


class T08Audit(unittest.TestCase):
    def test_yaml_path_and_allow_list(self):
        self.assertEqual(P1B.yaml_path("ict_L7"), C.EXPERIMENTS / "ict" / "ict_L7.yaml")
        self.assertEqual(P1B.yaml_path("ict_L7__nb_sl_0p2"), C.EXPERIMENTS / "ict" / "neighbors" / "ict_L7__nb_sl_0p2.yaml")
        self.assertEqual(P1B.yaml_path("p1s1_4h_cur"), C.EXPERIMENTS / "p1s1_4h_cur.yaml")
        self.assertEqual(P1B.yaml_path("p1b_tr_4h_n20__nb_dcn_16"), C.EXPERIMENTS / "neighbors" / "p1b_tr_4h_n20__nb_dcn_16.yaml")
        names = P1B.ict_manifest_names()
        self.assertEqual(len(names), 23)
        self.assertIn("ict_L7", names)
        self.assertIn("ict_L7__nb_fvgk_0p6", names)
        self.assertFalse([n for n in names if "rsv" in n])

    def test_unregistered_ict_name_is_rejected(self):
        reg_text = (C.OUT / "registry.md").read_text() + "| 2026-11-06T00:00:00Z | ict_rsv1 | abcdef123456 | x |\n"
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "registry.md"
            fake.write_text(reg_text)
            real = C.OUT
            with mock.patch.object(P1B.C, "OUT", Path(td)):
                (Path(td) / "oos_log.md").write_text("")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = P1B.audit()
        self.assertEqual(rc, 1)
        self.assertIn("ict_rsv1", buf.getvalue())
        self.assertIn("not in the manifest lists", buf.getvalue())
        self.assertIsNotNone(real)

    @unittest.skipUnless((C.CACHE / "results" / "p1s1_4h_cur.parquet").exists(), "no result cache")
    def test_audit_numbers_unchanged(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = P1B.audit()
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual(buf.getvalue().strip().splitlines()[-1], "OK: main experiments 36, neighbours 4")


class T09CompareFrames(unittest.TestCase):
    def frames(self):
        old = pd.DataFrame({"attempt_id": [1, 2, 3], "a": [1.0, 2.0, 3.0], "b": [1.0, 2.0, 3.0], "s": ["x", "y", "z"], "k": [1, 2, 3]})
        return old, old.copy()

    def test_equal(self):
        old, new = self.frames()
        self.assertEqual(R.compare_frames(old, new), (True, 0.0, ""))

    def test_lists_every_differing_column(self):
        old, new = self.frames()
        new.loc[1, "a"] = 2.5
        new.loc[2, "b"] = 3.0 + 1e-3
        new.loc[0, "s"] = "q"
        new.loc[0, "k"] = 9
        ok, worst, note = R.compare_frames(old, new)
        self.assertFalse(ok)
        for c in ("a", "b", "s", "k"):
            self.assertIn(f"column {c}:", note)
        self.assertIn("4 column(s) differ", note)
        self.assertAlmostEqual(worst, 8.0)

    def test_within_tolerance_and_nan_and_rowcount(self):
        old, new = self.frames()
        new.loc[0, "a"] += 1e-12
        self.assertTrue(R.compare_frames(old, new)[0])
        new.loc[0, "b"] = np.nan
        ok, worst, note = R.compare_frames(old, new)
        self.assertFalse(ok)
        self.assertIn("column b: NaN mismatch", note)
        self.assertTrue(math.isnan(worst))
        self.assertFalse(R.compare_frames(old, new.iloc[:2])[0])


class T10LegacyShaUnchanged(unittest.TestCase):
    def test_forty_config_shas(self):
        got = {}
        for p in sorted(C.EXPERIMENTS.glob("*.yaml")) + sorted((C.EXPERIMENTS / "neighbors").glob("*.yaml")):
            got[str(p.relative_to(C.EXPERIMENTS))] = R.config_sha(sim.SimConfig.from_dict(C.read_yaml(p)).resolved())
        self.assertEqual(len(got), 40)
        self.assertEqual(got, LEGACY_SHA)


if __name__ == "__main__":
    unittest.main()
