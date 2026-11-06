"""sim.py extensions for ICT (row_target, time_barrier, ambiguity counters, ict signal table) + old-sha regression."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from research import common as C
from research import run as R
from research import sim
from research.ict import generate as G
from research.ict import params as IP
from research.tests import test_sim as TS

STEP = TS.STEP
BASE_US = TS.BASE_US
COLS = sim._COLS + sim._ICT_COLS


def ict_cfg(**over):
    d = G.experiment_dict("ict_L7")
    for k, v in over.items():
        d[k] = v
    return sim.SimConfig.from_dict(d)


def sig(entry_idx=1, side=-1, close=100.0, defending=103.0, atr=2.0, tp2=92.0):
    t = pd.Timestamp(BASE_US + entry_idx * STEP, unit="us", tz="UTC")
    return pd.DataFrame([{
        "signal_id": "s1", "tf": "15m", "type": "ict_short" if side == -1 else "ict_long", "side": side, "time": t,
        "close": close, "defending_price": defending, "atr": atr, "tp2": tp2,
    }])


def runc(cfg, rows, s, tick=0.01):
    out, cnt = sim.simulate_symbol(cfg, "X/USDT", s, TS.make_bars(rows), ((), (), ()), None, {}, tick)
    return out, cnt


def col(out, name, i=0):
    return out[i][COLS.index(name)]


FLAT = TS.FLAT


class IctSimTests(unittest.TestCase):
    def test_x01_old_40_shas_unchanged(self):
        seen = R.read_registry(C.OUT / "registry.md")
        files = sorted(C.EXPERIMENTS.glob("*.yaml"))
        nb = sorted((C.EXPERIMENTS / "neighbors").glob("*.yaml"))
        self.assertEqual((len(files), len(nb)), (36, 4))
        for p in files + nb:
            raw = C.read_yaml(p)
            sha = R.config_sha(sim.SimConfig.from_dict(raw).resolved())
            self.assertIn(sha, seen[raw["name"]], p.name)
        self.assertEqual(len(files) + len(nb), 40)

    def test_x02_defaults_untouched(self):
        self.assertEqual(sim.resolve_exit({}), copy.deepcopy(sim.EXIT_MODULES))
        out = sim.resolve_exit({})
        self.assertNotIn("time_barrier", out)
        self.assertNotIn("row_target", out)
        self.assertEqual(sim.resolve_exit({"time_barrier": {"enabled": False}}), out)
        self.assertEqual(sim.resolve_exit({"row_target": {"enabled": False}}), out)
        self.assertNotIn("ict", TS.make_cfg().resolved()["signals"])

    def test_x03_config_validation(self):
        base = G.experiment_dict("ict_L7")

        def bad(mut, msg):
            d = copy.deepcopy(base)
            mut(d)
            with self.assertRaises(sim.ConfigError, msg=msg):
                sim.SimConfig.from_dict(d)

        bad(lambda d: d["signals"].pop("ict"), "no ict key")
        bad(lambda d: d["signals"].update(tf="1h"), "tf 1h")
        bad(lambda d: d["signals"].update(types=["second_buy"]), "types")
        bad(lambda d: d["signals"]["ict"].pop("fvg_k"), "ict params keys")
        bad(lambda d: d["exit"].update(opposite_signal={"enabled": True, "tf": "15m"}), "opposite")
        bad(lambda d: d["exit"]["tp1"].update(target="prior_swing"), "tp1 target")
        bad(lambda d: d["exit"].update(fixed_r={"enabled": True, "r": 2.0}), "fixed_r + row_target")
        for tb in ({"enabled": True, "bars": 0, "min_r": 0.5}, {"enabled": True, "bars": 1.5, "min_r": 0.5},
                   {"enabled": True, "bars": 12, "min_r": 0}, {"enabled": True, "bars": 12}):
            bad(lambda d, tb=tb: d["exit"].update(time_barrier=tb), f"time_barrier {tb}")
        chan = copy.deepcopy(TS.BASE_CFG)
        c1 = copy.deepcopy(chan)
        c1["signals"]["ict"] = IP.validate(IP.DEFAULTS)
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(c1)
        c2 = copy.deepcopy(chan)
        c2["exit"] = {"row_target": {"enabled": True}}
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(c2)
        sim.SimConfig.from_dict(base)  # the good one passes

    def test_x04_time_barrier_fires(self):
        rows = [FLAT] * 13 + [(100.2, 100.5, 99.5, 100.0), FLAT]
        out, cnt = runc(ict_cfg(), rows, sig())
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(col(out, "stop_initial"), 103.6, places=9)
        self.assertAlmostEqual(col(out, "r_dist"), 3.6, places=9)
        self.assertEqual(col(out, "exit_reason"), "time_barrier")
        self.assertEqual(col(out, "bars_held"), 12)
        self.assertEqual(col(out, "exit_time"), BASE_US + 13 * STEP)
        self.assertAlmostEqual(col(out, "exit_price"), 100.2 * (1 + 1e-4), places=9)

    def test_x05_time_barrier_not_fired(self):
        rows = [FLAT] * 20
        rows[11] = (100.0, 100.5, 98.2, 100.0)  # low == entry_ref - 0.5R, on the 11th bar (inside the window)
        out, _ = runc(ict_cfg(), rows, sig())
        self.assertNotEqual(col(out, "exit_reason"), "time_barrier")
        out, _ = runc(ict_cfg(), [FLAT] * 20, sig())
        self.assertEqual(col(out, "exit_reason"), "time_barrier")
        # TP1 (94.6) fills before the barrier -> never fires
        rows = [FLAT, FLAT, (100.0, 100.2, 94.0, 94.5)] + [(94.5, 99.0, 94.5, 95.0)] * 20
        out, _ = runc(ict_cfg(), rows, sig())
        self.assertTrue(col(out, "tp1_hit"))
        self.assertNotEqual(col(out, "exit_reason"), "time_barrier")
        # bars=12: only the 12th bar is evaluated; later bars are never judged
        cfg = ict_cfg(exit={**G.experiment_dict("ict_L7")["exit"], "time_barrier": {"enabled": True, "bars": 2, "min_r": 0.5}})
        rows = [FLAT, (100.0, 100.5, 97.0, 98.0), FLAT, FLAT, FLAT, FLAT, FLAT, FLAT]  # bar 2 (the 2nd) reaches 0.5R? best=97 -> yes
        out, _ = runc(cfg, rows, sig())
        self.assertNotEqual(col(out, "exit_reason"), "time_barrier")
        rows = [FLAT] * 3 + [(100.0, 100.5, 96.0, 97.0)] + [FLAT] * 6  # weak start, strong move on the 3rd bar: not judged any more
        out, _ = runc(cfg, rows, sig())
        self.assertEqual(col(out, "exit_reason"), "time_barrier")
        self.assertEqual(col(out, "bars_held"), 2)

    def _hand(self, rows3):
        rows = [FLAT] + rows3 + [FLAT] * 3
        cfg = ict_cfg(stop={"buffer_atr": 0.3, "round_to_tick": True})
        return runc(cfg, rows, sig(tp2=92.0))

    def test_x06_hand_reconciliation(self):
        out, cnt = self._hand([(99.9, 100.2, 99.0, 99.5), (99.5, 99.6, 94.0, 94.5), (94.5, 94.8, 91.5, 92.2)])
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(col(out, "stop_initial"), 103.6, places=9)
        self.assertAlmostEqual(col(out, "r_dist"), 3.6, places=9)
        self.assertAlmostEqual(col(out, "entry_price"), 99.89001, places=9)
        self.assertEqual(col(out, "exit_reason"), "row_target")
        self.assertTrue(col(out, "tp1_hit"))
        self.assertTrue(col(out, "tp2_hit"))
        self.assertAlmostEqual(col(out, "gross_r"), 1.8279666666666698, places=9)
        self.assertAlmostEqual(col(out, "fee_r"), 0.026833241666666712, places=9)
        self.assertAlmostEqual(col(out, "net_r_ex_funding"), 1.801133425000003, places=9)

    def test_x07_tp1_tp2_same_bar(self):
        rows = [FLAT, (99.9, 100.2, 99.0, 99.5), (99.5, 99.6, 90.0, 91.0), FLAT]
        out, _ = runc(ict_cfg(), rows, sig(tp2=92.0))
        self.assertEqual(col(out, "exit_reason"), "row_target")
        self.assertTrue(col(out, "tp1_hit") and col(out, "tp2_hit"))
        self.assertIn(col(out, "bars_held"), (0, 1))

    def test_x08_ambiguity(self):
        rows = [FLAT, (100.0, 100.5, 99.5, 100.0), (100.0, 104.0, 94.0, 100.0), FLAT]
        out, cnt = runc(ict_cfg(), rows, sig())
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertTrue(col(out, "amb_stop_target"))
        self.assertEqual(cnt["amb_stop_target"], 1)
        rows = [FLAT, (100.0, 100.5, 99.5, 100.0), (99.5, 100.2, 94.0, 94.5), FLAT]  # TP1 bar whose high also reaches entry_ref
        out, cnt = runc(ict_cfg(), rows, sig())
        self.assertTrue(col(out, "tp1_hit"))
        self.assertTrue(col(out, "amb_tp1_entry"))
        self.assertEqual(cnt["amb_tp1_entry"], 1)
        # a clean trade carries no flags
        rows = [FLAT, (99.9, 100.2, 99.0, 99.5), (99.5, 99.6, 94.0, 94.5), (94.5, 94.8, 91.5, 92.2), FLAT]
        out, cnt = runc(ict_cfg(), rows, sig())
        self.assertEqual((cnt["amb_stop_target"], cnt["amb_tp1_entry"]), (0, 0))

    def test_x09_non_ict_unchanged(self):
        cfg = TS.make_cfg()
        out, cnt = TS.run(cfg, [FLAT, FLAT, FLAT], TS.make_sig())
        self.assertEqual(set(cnt), {"signals", "no_entry_bar", "invalid_stop", "tick_missing", "cost_rejected", "unfilled",
                                    "confirm_abandoned", "minstop_rejected", "delisted_no_entry"})
        for r in out:
            self.assertEqual(len(r), len(sim._COLS))
        mk = TS.make_bars([FLAT, FLAT, FLAT])
        market = sim.Market(bars={"X/USDT": mk}, bias_down={}, bi_new={}, ticks={"X/USDT": 0.01})
        s = TS.make_sig()
        s["symbol"] = "X/USDT"
        df, total = sim.simulate(cfg, market, s)
        self.assertEqual(list(df.columns), sim._COLS + ["sample"])

    def test_x10_row_target_invalid(self):
        rows = [FLAT, FLAT, (100.0, 104.0, 99.5, 103.7), FLAT]  # stop hit, tp2 above entry is ignored
        out, cnt = runc(ict_cfg(), rows, sig(tp2=105.0))
        self.assertEqual(cnt["row_target_invalid"], 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(col(out, "exit_reason"), "structure_stop")
        self.assertFalse(col(out, "tp2_hit"))

    def test_x12_run_summary_labels(self):
        d = G.experiment_dict("ict_L7")
        cfg = sim.SimConfig.from_dict(d)
        s = R.summarize(cfg, d["exit"])
        self.assertIn(f"ict={IP.table_key(cfg.signals['ict'])}", s)
        self.assertIn("exit=tp1+breakeven+tb12+tp2", s)

    def test_x11_table_sidecar_mismatch(self):
        cfg = ict_cfg()
        P = cfg.signals["ict"]
        key = IP.table_key(P)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(C, "CACHE", Path(td)):
            with self.assertRaises(FileNotFoundError):
                sim.load_signal_table(cfg, "15m")
            d = Path(td) / "ict"
            d.mkdir()
            pd.DataFrame({"a": [1]}).to_parquet(d / f"events_{key}.parquet")
            (d / f"events_{key}.json").write_text(json.dumps({"params": P}))
            self.assertEqual(len(sim.load_signal_table(cfg, "15m")), 1)
            (d / f"events_{key}.json").write_text(json.dumps({"params": {**P, "fvg_k": 0.9}}))
            with self.assertRaises(ValueError):
                sim.load_signal_table(cfg, "15m")


if __name__ == "__main__":
    unittest.main()
