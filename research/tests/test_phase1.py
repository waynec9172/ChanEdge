"""Config keys, registry rules, check mode, S1 list, neighbour table, quarters / gate A, promotion ranking."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from research import common as C, metrics as M, phase1, run, sim
from research.tests.test_sim import BASE_CFG, make_cfg


def sha_of(name):
    return run.config_sha(sim.SimConfig.from_dict(C.read_yaml(C.EXPERIMENTS / f"{name}.yaml")).resolved())


def trade_rows(per_quarter, net=0.1, tf="1h"):
    """Synthetic trade set: per_quarter = list of (quarter index, count, net_r)."""
    starts = ["2024-01-15", "2024-04-15", "2024-07-15", "2024-10-15", "2025-01-15", "2025-04-15"]
    rows = []
    for qi, cnt, nr in per_quarter:
        for k in range(cnt):
            rows.append({
                "symbol": "BTC/USDT", "tf": tf, "side": 1, "signal_time": pd.Timestamp(starts[qi], tz="UTC") + pd.Timedelta(hours=k),
                "exit_time": pd.Timestamp(starts[qi], tz="UTC") + pd.Timedelta(hours=k + 1), "net_r": nr, "gross_r": nr + 0.05, "fee_r": 0.05,
                "funding_r": 0.0, "mfe_r": 1.0, "mae_r": -0.5, "bars_held": 3, "exit_reason": "fixed_r", "funding_missing": False,
            })
    return pd.DataFrame(rows)


class ConfigTests(unittest.TestCase):
    def test_p1_existing_shas_unchanged(self):
        self.assertEqual(sha_of("p0_validate_current_15m"), "422b2b9d5ca3")
        self.assertEqual(sha_of("p0_perf_15m_all"), "9b64a9e432ea")
        self.assertEqual(sha_of("donchian_1h_n20"), "84a0bcbc2647")
        self.assertEqual(sha_of("donchian_4h_n55"), "5676294a19f3")

    def test_p2_new_keys_optional_and_validated(self):
        sim.SimConfig.from_dict(copy.deepcopy(BASE_CFG))  # without any new key
        f = lambda **kw: dict(BASE_CFG["filters"], **kw)
        cfg = make_cfg(filters=f(htf_4h=True, min_stop_atr=1.3))
        self.assertEqual(cfg.resolved()["filters"]["htf_4h"], True)
        self.assertNotIn("vol_band", cfg.resolved()["filters"])  # defaults are not printed
        with self.assertRaises(sim.ConfigError):
            make_cfg(filters=f(surprise=1))
        for bad in (f(min_stop_atr=0), f(min_stop_pct=-0.01), f(min_stop_atr="x")):
            with self.assertRaises(sim.ConfigError):
                make_cfg(filters=bad)
        dsig = {"source": "donchian", "tf": "1h", "types": ["dc20_long", "dc20_short"], "donchian_n": 20}
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals=dsig, filters=f(htf_4h=True))
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals=dsig, filters=f(vol_band=True))
        with self.assertRaises(sim.ConfigError):
            make_cfg(signals={**BASE_CFG["signals"], "tf": "1h"}, filters=f(jev_min=0.6))
        make_cfg(signals={**dsig, "donchian_n": 66, "types": ["dc66_long", "dc66_short"]})


class RegistryTests(unittest.TestCase):
    def _reg(self, td):
        reg = Path(td) / "registry.md"
        reg.write_text("# Experiment registry\n| time_utc | name | config_sha | summary |\n| --- | --- | --- | --- |\n")
        return reg

    def test_p3_registry_rules(self):
        with tempfile.TemporaryDirectory() as td:
            reg = self._reg(td)
            for i in range(60):
                run.check_registry(reg, f"exp{i}", "aaa")
                run.append_registry(reg, f"exp{i}", "aaa", "s")
            with self.assertRaises(run.RegistryError):
                run.check_registry(reg, "exp60", "aaa")  # 61st main experiment
            run.check_registry(reg, "exp60__nb_x_1", "aaa")  # neighbours are not counted
            run.append_registry(reg, "exp60__nb_x_1", "aaa", "NEIGHBOR")
            run.check_registry(reg, "exp61__nb_x_1", "aaa")
            self.assertEqual(run.n_main(run.read_registry(reg)), 60)
            with self.assertRaises(run.RegistryError):  # same name without --rerun
                run.check_registry(reg, "exp5", "aaa", require_rerun=True)
            run.check_registry(reg, "exp5", "aaa", rerun="bug fix", require_rerun=True)  # same sha with a reason
            with self.assertRaises(run.RegistryError):  # different sha is never allowed
                run.check_registry(reg, "exp5", "bbb", rerun="bug fix", require_rerun=True)

    def test_p3b_name_and_flag_must_agree(self):
        with tempfile.TemporaryDirectory() as td:
            reg = self._reg(td)
            src = (C.EXPERIMENTS / "p0_validate_current_15m.yaml").read_text()
            d = json.loads(json.dumps(C.read_yaml(C.EXPERIMENTS / "p0_validate_current_15m.yaml")))
            nb = Path(td) / "p0x__nb_a_1.yaml"
            d["name"] = "p0x__nb_a_1"
            nb.write_text(json.dumps(d))
            self.assertEqual(run.main([str(nb), "--registry", str(reg)]), 2)  # '__nb_' without --neighbor
            self.assertEqual(run.main([str(nb), "--registry", str(reg), "--neighbor"]), 2)  # not in neighbors/ and wrong description
            plain = Path(td) / "p0x.yaml"
            d["name"] = "p0x"
            plain.write_text(json.dumps(d))
            self.assertEqual(run.main([str(plain), "--registry", str(reg), "--neighbor"]), 2)  # --neighbor without '__nb_'
            sha = run.config_sha(sim.SimConfig.from_dict(d).resolved())
            run.append_registry(reg, "p0x", sha, "s")
            self.assertEqual(run.main([str(plain), "--registry", str(reg)]), 3)  # already ran, no --rerun
            run.append_registry(reg, "p0y", "000000000000", "s")
            d["name"] = "p0y"
            other = Path(td) / "p0y.yaml"
            other.write_text(json.dumps(d))
            self.assertEqual(run.main([str(other), "--registry", str(reg), "--rerun", "x"]), 3)  # sha differs
            self.assertTrue(src)

    def test_p4_check_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            reg = self._reg(td)
            before = reg.read_text()
            cache = Path(td) / "cache"
            (cache / "results").mkdir(parents=True)
            trades = pd.DataFrame({
                "attempt_id": [0, 1], "signal_time": pd.to_datetime(["2024-02-01", "2024-02-02"], utc=True), "symbol": ["A", "B"], "type": ["t", "t"],
                "net_r": [0.5, -0.5], "net_r_ex_funding": [0.5, -0.5], "exit_reason": ["x", "y"], "funding_missing": [False, False],
            })
            att = pd.DataFrame({"attempt_id": [0, 1], "status": ["filled", "filled"], "end_time": pd.to_datetime(["2024-02-01", "2024-02-02"], utc=True)})
            trades.to_parquet(cache / "results" / "p0x.parquet")
            att.to_parquet(cache / "results" / "p0x.attempts.parquet")
            d = json.loads(json.dumps(C.read_yaml(C.EXPERIMENTS / "p0_validate_current_15m.yaml")))
            d["name"] = "p0x"
            y = Path(td) / "p0x.yaml"
            y.write_text(json.dumps(d))
            snap = {p.name: p.read_bytes() for p in (cache / "results").iterdir()}
            with mock.patch.object(C, "CACHE", cache), mock.patch.object(run, "compute", return_value=(None, trades.copy(), att.copy(), {})):
                self.assertEqual(run.main([str(y), "--registry", str(reg), "--check"]), 0)
                bad = trades.copy()
                bad.loc[0, "net_r_ex_funding"] = 0.6
                bad.loc[0, "net_r"] = 0.6
                with mock.patch.object(run, "compute", return_value=(None, bad, att.copy(), {})):
                    self.assertEqual(run.main([str(y), "--registry", str(reg), "--check"]), 4)
            self.assertEqual(reg.read_text(), before)  # no registry row
            self.assertEqual({p.name: p.read_bytes() for p in (cache / "results").iterdir()}, snap)  # no result file touched
            self.assertTrue((cache / "logs" / "checks.log").exists())
            self.assertFalse((cache / "logs" / "runs.log").exists())


S1_EXPECT_EXIT = {
    "cur": lambda tf: {"preset": "current", "opposite_signal": {"enabled": True, "tf": tf}},
    "rat": lambda tf: {"preset": "ratchet_only"},
    "fx2": lambda tf: {"fixed_r": {"enabled": True, "r": 2.0}},
    "fx3": lambda tf: {"fixed_r": {"enabled": True, "r": 3.0}},
    "at2": lambda tf: {"atr_trail": {"enabled": True, "mult": 2.0, "arm_r": 0.0}},
    "at3": lambda tf: {"atr_trail": {"enabled": True, "mult": 3.0, "arm_r": 0.0}},
    "opp": lambda tf: {"opposite_signal": {"enabled": True, "tf": tf}},
}


class GenTests(unittest.TestCase):
    def test_p5_gen_s1_matches_plan(self):
        want = [f"p1s1_{tf}_{e}" for tf in ("15m", "1h", "4h") for e in ("cur", "rat", "fx2", "fx3", "at2", "at3", "opp")]
        want += ["donchian_1h_n20", "donchian_4h_n55", "p1s1_15m_cur_jevref"]
        specs = phase1.gen_specs("S1")
        self.assertEqual([s["name"] for s in specs], want)
        self.assertEqual(len(specs), 24)
        for s in specs:
            if s["existing"]:
                continue
            y = s["yaml"]
            self.assertEqual(y["name"], s["name"])
            self.assertEqual(y["signals"]["tf"], s["tf"])
            self.assertEqual(y["signals"]["types"], ["second_buy", "third_buy", "second_sell", "third_sell"])
            self.assertEqual(y["entry"], {"mode": "market_next_open"})
            self.assertEqual(y["stop"], {"buffer_atr": 0.15, "round_to_tick": True})
            self.assertEqual(y["costs"], {"taker_bps": 5, "maker_bps": 2, "slippage_bps": 1})
            exp = {"in_top20": True, "candidate_only": False, "gate_pass": False, "jev_min": None, "max_cost_r": None,
                   "exclude_reemit": False, "htf_4h": True, "vol_band": True}
            if s["name"].endswith("jevref"):
                exp["jev_min"] = 0.62
                self.assertEqual(y["exit"], S1_EXPECT_EXIT["cur"]("15m"))
            else:
                self.assertEqual(y["exit"], S1_EXPECT_EXIT[s["exit"]](s["tf"]))
            self.assertEqual(y["filters"], exp)
            sim.SimConfig.from_dict(y)  # parses
        self.assertEqual(sum(1 for s in specs if s["ranked"]), 14)  # plan 8.5: the seven 4h rows are reference only
        for s in specs:
            if s["tf"] == "4h" and s["name"].startswith("p1s1_"):
                self.assertFalse(s["ranked"], s["name"])
            if s["tf"] in ("15m", "1h") and s["exit"] != "dc" and not s["name"].endswith("jevref"):
                self.assertTrue(s["ranked"], s["name"])
        # the YAML files on disk (if generated) are the same
        for s in specs:
            p = C.EXPERIMENTS / f"{s['name']}.yaml"
            if p.exists():
                self.assertEqual(C.read_yaml(p), json.loads(json.dumps(s["yaml"])))

    def test_p6_neighbor_table(self):
        S1 = {s["name"]: s["yaml"] for s in phase1.gen_specs("S1")}
        nb = lambda name, y: {(n["code"], n["value"]) for n in phase1.neighbor_specs(name, y)}
        self.assertEqual(nb("p1s1_1h_fx2", S1["p1s1_1h_fx2"]), {("fixr", 1.6), ("fixr", 2.4)})
        self.assertEqual(nb("p1s1_1h_fx3", S1["p1s1_1h_fx3"]), {("fixr", 2.4), ("fixr", 3.6)})
        self.assertEqual(nb("p1s1_4h_at3", S1["p1s1_4h_at3"]), {("atrm", 2.4), ("atrm", 3.6)})
        self.assertEqual(nb("p1s1_4h_at2", S1["p1s1_4h_at2"]), {("atrm", 1.6), ("atrm", 2.4)})
        for tf in ("15m", "1h"):
            for e in ("cur", "rat", "opp"):  # plan 8.2: no other table parameter -> stop-buffer neighbours
                got = phase1.neighbor_specs(f"p1s1_{tf}_{e}", S1[f"p1s1_{tf}_{e}"])
                self.assertEqual({(n["code"], n["value"]) for n in got}, {("sbuf", 0.12), ("sbuf", 0.18)})
                self.assertEqual({n["yaml"]["stop"]["buffer_atr"] for n in got}, {0.12, 0.18})
                self.assertEqual(sorted(n["name"] for n in got), [f"p1s1_{tf}_{e}__nb_sbuf_0p12", f"p1s1_{tf}_{e}__nb_sbuf_0p18"])
                self.assertTrue(all(n["yaml"]["description"].startswith(f"NEIGHBOR of p1s1_{tf}_{e}: stop.buffer_atr=") for n in got))
        # fx2 has fixr only (no sbuf); a fallback forces sbuf on top and flags it
        self.assertEqual({n["code"] for n in phase1.neighbor_specs("p1s1_1h_fx2", S1["p1s1_1h_fx2"])}, {"fixr"})
        forced = phase1.neighbor_specs("p1s1_1h_fx2", S1["p1s1_1h_fx2"], force_sbuf=True)
        self.assertEqual({(n["code"], n["fallback_only"]) for n in forced}, {("fixr", False), ("sbuf", True)})
        # S2 lc on a cur base: only limn; S3 no4h / xtf on a cur base: sbuf; S3 ms13a on cur: only msa
        cur = S1["p1s1_1h_cur"]
        lc_cur = copy.deepcopy(cur)
        lc_cur["entry"] = phase1.ENTRY_S2["lc"]
        self.assertEqual({(n["code"], n["value"]) for n in phase1.neighbor_specs("x", lc_cur)}, {("limn", 3), ("limn", 5)})
        for key, val in (("htf_4h", False), ("exclude_tradfi", True)):
            y = copy.deepcopy(cur)
            y["filters"][key] = val
            self.assertEqual({n["code"] for n in phase1.neighbor_specs("x", y)}, {"sbuf"})
        y = copy.deepcopy(cur)
        y["filters"]["min_stop_atr"] = 1.3
        self.assertEqual({n["code"] for n in phase1.neighbor_specs("x", y)}, {"msa"})
        self.assertEqual(phase1.neighbor_specs("p1s1_15m_cur_jevref", S1["p1s1_15m_cur_jevref"])[0]["yaml"]["filters"]["jev_min"], 0.496)
        self.assertEqual(nb("p1s1_15m_cur_jevref", S1["p1s1_15m_cur_jevref"]), {("jev", 0.496), ("jev", 0.744)})
        base = S1["p1s1_1h_fx2"]
        lm = copy.deepcopy(base)
        lm["entry"] = phase1.ENTRY_S2["lm"]
        self.assertEqual({(c, v) for c, v in nb("p1s2_1h_fx2_lm", lm) if c != "fixr"}, {("limn", 3), ("limn", 5), ("limf", 0.4), ("limf", 0.6)})
        lc = copy.deepcopy(base)
        lc["entry"] = phase1.ENTRY_S2["lc"]
        self.assertEqual({(c, v) for c, v in nb("x", lc) if c != "fixr"}, {("limn", 3), ("limn", 5)})  # offset 0: no price neighbour
        cf = copy.deepcopy(S1["p1s1_1h_cur"])
        cf["entry"] = phase1.ENTRY_S2["cf1"]
        got = {n["code"] + str(n["value"]): n for n in phase1.neighbor_specs("p1s2_1h_cur_cf1", cf)}
        self.assertEqual(set(got), {"cfk0", "cfk2"})
        self.assertEqual(got["cfk0"]["yaml"]["entry"], {"mode": "market_next_open"})  # K = 0 is the market entry
        self.assertEqual(got["cfk2"]["yaml"]["entry"]["confirm"]["bars"], 2)
        ms = copy.deepcopy(base)
        ms["filters"]["min_stop_atr"] = 1.3
        self.assertEqual({(c, v) for c, v in nb("x", ms) if c == "msa"}, {("msa", 1.04), ("msa", 1.56)})
        ms["filters"]["min_stop_atr"] = None
        ms["filters"]["min_stop_pct"] = 0.015
        self.assertEqual({(c, v) for c, v in nb("x", ms) if c == "msp"}, {("msp", 0.012), ("msp", 0.018)})
        d1 = C.read_yaml(C.EXPERIMENTS / "donchian_1h_n20.yaml")
        got = phase1.neighbor_specs("donchian_1h_n20", d1)
        self.assertEqual({(n["code"], n["value"]) for n in got}, {("dcn", 16), ("dcn", 24)})
        for n in got:
            v = n["value"]
            self.assertEqual(n["yaml"]["signals"]["types"], [f"dc{v}_long", f"dc{v}_short"])
            self.assertEqual(n["name"], f"donchian_1h_n20__nb_dcn_{v}")
            self.assertTrue(n["yaml"]["description"].startswith("NEIGHBOR of donchian_1h_n20: "))
            sim.SimConfig.from_dict(n["yaml"])
        d4 = C.read_yaml(C.EXPERIMENTS / "donchian_4h_n55.yaml")
        self.assertEqual({n["value"] for n in phase1.neighbor_specs("donchian_4h_n55", d4)}, {44, 66})
        # the 2.4R neighbour of fx2 and of fx3 are the same configuration
        a = [n for n in phase1.neighbor_specs("p1s1_1h_fx2", S1["p1s1_1h_fx2"]) if n["value"] == 2.4][0]
        b = [n for n in phase1.neighbor_specs("p1s1_1h_fx3", S1["p1s1_1h_fx3"]) if n["value"] == 2.4][0]
        self.assertEqual(phase1.core_of(a["yaml"]), phase1.core_of(b["yaml"]))
        self.assertEqual(a["name"], "p1s1_1h_fx2__nb_fixr_2p4")


class MetricsTests(unittest.TestCase):
    def test_p7_quarters_and_gate_a(self):
        def gate(per_q, nb=None):
            s = M.summarize(trade_rows(per_q))
            return s, M.gate_a(s, nb)

        five = [(0, 100, 0.2), (1, 100, 0.2), (2, 100, 0.2), (3, 100, 0.2), (4, 100, 0.2), (5, 100, -0.01)]
        s, g = gate(five)
        self.assertEqual(s["pos_q"], 5)
        self.assertTrue(g["pos_q"][1])
        four = [(0, 100, 0.2), (1, 100, 0.2), (2, 100, 0.2), (3, 100, 0.2), (4, 100, -0.01), (5, 100, -0.01)]
        s, g = gate(four)
        self.assertEqual(s["pos_q"], 4)
        self.assertFalse(g["pos_q"][1])
        s, g = gate([(0, 100, 0.2), (1, 100, 0.2), (2, 100, 0.2), (3, 100, 0.2), (4, 100, 0.2)])  # an empty quarter is not positive
        self.assertEqual(s["pos_q"], 5)
        s, g = gate([(0, 100, 0.2), (1, 100, 0.2), (2, 100, 0.2), (3, 100, 0.2)])
        self.assertEqual(s["pos_q"], 4)
        self.assertFalse(g["pos_q"][1])
        # count, net R and PF are compared as raw floats
        base = dict(net_r=0.1, pf=1.3, n=500, pos_q=6, net_fee15=0.05)
        nb2 = [0.1, 0.1]
        self.assertTrue(M.gate_a(base, nb2)["pass"])
        self.assertFalse(M.gate_a({**base, "n": 499}, nb2)["pass"])
        self.assertFalse(M.gate_a({**base, "net_r": 0.0799999}, nb2)["pass"])
        self.assertTrue(M.gate_a({**base, "net_r": 0.08}, nb2)["pass"])
        self.assertFalse(M.gate_a({**base, "pf": 1.1999999}, nb2)["pass"])
        self.assertFalse(M.gate_a({**base, "net_fee15": 0.0}, nb2)["pass"])
        self.assertFalse(M.gate_a(base, [0.1, -0.01])["pass"])
        self.assertTrue(M.gate_a(base, [0.1, 0.02])["pass"])
        for missing in ([], None):  # plan 8.2: missing neighbour results fail the sixth condition (no "untestable = holds")
            g = M.gate_a(base, missing)
            self.assertFalse(g["neighbors"][1])
            self.assertFalse(g["pass"])
            self.assertEqual(g["neighbors_note"], "missing neighbour results")
        self.assertEqual(M.gate_a(base, [0.1])["neighbors_note"], "tested")
        # a 5th-decimal rounding must not rescue 0.0799999
        self.assertEqual(f"{0.0799999:.2f}", "0.08")

    def test_p7b_summary_values(self):
        t = trade_rows([(0, 4, 0.5), (1, 4, -0.25)])
        s = M.summarize(t)
        self.assertAlmostEqual(s["net_r"], 0.125)
        self.assertAlmostEqual(s["pf"], 2.0)
        self.assertAlmostEqual(s["net_fee15"], 0.125 - 0.5 * 0.05, places=12)  # gross - 1.5 fee = net - 0.5 fee
        self.assertEqual(s["n_cross"], 0)
        self.assertEqual(s["groups"]["major"]["n"], 8)

    def test_p8_eligibility_ranking(self):
        mk = lambda net, fee15, n=100: {"net_r": net, "net_fee15": fee15, "n": n}
        e = M.eligibility
        self.assertTrue(e(mk(0.01, -0.02), [0.1])["eligible"])
        self.assertFalse(e(mk(0.0, 0.0), [0.1])["P1"])
        self.assertFalse(e(mk(0.05, -0.0200001), [0.1])["P2"])
        self.assertFalse(e(mk(0.05, 0.0), [0.1, -0.1])["P3"])
        miss = e(mk(0.05, 0.0), None)
        self.assertTrue(miss["missing_neighbor"])
        self.assertFalse(miss["P3"])  # missing neighbour results are not "pass"
        self.assertFalse(e(mk(0.05, 0.0), [])["eligible"])
        nbok = [0.1, 0.1]
        items = [("c", mk(0.05, 0.0, 300), e(mk(0.05, 0.0), nbok)), ("b", mk(0.05, 0.0, 300), e(mk(0.05, 0.0), nbok)),
                 ("a", mk(0.05, 0.0, 200), e(mk(0.05, 0.0), nbok)), ("d", mk(0.09, 0.0, 10), e(mk(0.09, 0.0), nbok)),
                 ("x", mk(0.2, 0.0, 10), e(mk(0.2, 0.0), [-1.0]))]
        self.assertEqual(M.rank_eligible(items), ["d", "b"])  # net R first, then more trades, then name; x fails P3
        self.assertEqual(M.rank_eligible(items[-1:]), [])  # never padded
        self.assertEqual(M.rank_eligible(items[:1]), ["c"])  # only one eligible -> one


class PromoteModeTests(unittest.TestCase):
    def _write(self, td, text):
        p = Path(td) / "promote.md"
        p.write_text(text)
        return str(p)

    def test_p9_promote_mode_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            for mode in ("normal", "fallback", "none"):
                self.assertEqual(phase1.read_mode(self._write(td, f"PROMOTED: a\nMODE: {mode}\nPROMOTE_COUNT: 1\n")), mode)
            with self.assertRaises(SystemExit):
                phase1.read_mode(self._write(td, "PROMOTED: a\nPROMOTE_COUNT: 1\n"))  # missing line
            with self.assertRaises(SystemExit):
                phase1.read_mode(self._write(td, "MODE: sideways\n"))  # wrong value
            # fallback generates only lc and lm; normal generates lc, lm, cf1
            m0 = phase1.load_manifest()
            S1 = {s["name"]: s["yaml"] for s in phase1.gen_specs("S1")}
            for mode, want in (("fallback", {"lc", "lm"}), ("normal", {"lc", "lm", "cf1"})):
                pf = self._write(td, f"PROMOTED: p1s1_1h_fx2\nMODE: {mode}\nPROMOTE_COUNT: 1\n")
                saved = {}
                with mock.patch.object(phase1, "load_manifest", return_value={"S1": [{"name": "p1s1_1h_fx2"}], "S2": [], "S3": [], "neighbors": {}, "skipped": []}), \
                        mock.patch.object(phase1, "save_manifest", side_effect=lambda m: saved.update(m)), \
                        mock.patch.object(phase1, "existing_core_shas", return_value={}), \
                        mock.patch.object(phase1.C, "read_yaml", return_value=copy.deepcopy(S1["p1s1_1h_fx2"])), \
                        mock.patch.object(phase1, "write_yaml"):
                    phase1.gen_s2(pf)
                new = {r["entry"] for r in saved["S2"] if r.get("base") and not r.get("reuse_of")}
                self.assertEqual(new, want)
                base_row = [r for r in saved["S2"] if r.get("reuse_of")][0]
                self.assertEqual(base_row["ranked"], mode == "normal")  # fallback: the market row is a comparison, not a candidate
                self.assertTrue(all(r["fallback"] == (mode == "fallback") for r in saved["S2"]))
            self.assertTrue(m0 is not None)


class FallbackTests(unittest.TestCase):
    def test_p10_fallback_s1(self):
        mk = lambda g, net=0.0, n=100: {"gross_r": g, "net_r": net, "n": n}
        both = [0.01, 0.02]
        f = M.fallback_s1
        self.assertFalse(f([("a", mk(0.0499999), both)])["rows"][0]["F1"])  # raw float boundary
        self.assertTrue(f([("a", mk(0.05), both)])["rows"][0]["F1"])
        self.assertTrue(f([("a", mk(0.06), both)])["rows"][0]["F2"])
        self.assertFalse(f([("a", mk(0.06), [0.01, 0.0])])["rows"][0]["F2"])  # both neighbours must be > 0
        self.assertFalse(f([("a", mk(0.06), [0.01, -0.01])])["rows"][0]["F2"])
        self.assertFalse(f([("a", mk(0.06), None)])["rows"][0]["F2"])  # missing neighbours do not pass
        self.assertEqual(f([("a", mk(0.06), None)])["promoted"], [])
        # ranking: net R desc, then n desc, then name; at most two; a lone candidate is not padded
        items = [("c", mk(0.06, -0.01, 300), both), ("b", mk(0.06, -0.01, 300), both), ("a", mk(0.06, -0.01, 200), both),
                 ("d", mk(0.07, -0.02, 10), both), ("e", mk(0.04, 0.0, 10), both)]
        self.assertEqual(f(items)["promoted"], ["b", "c"])
        self.assertEqual(f(items[3:4])["promoted"], ["d"])
        self.assertEqual(f(items[4:])["promoted"], [])
        self.assertEqual(f(items)["f1_names"], ["c", "b", "a", "d"])

    def test_p10b_pool_has_no_4h_donchian_or_jev(self):
        names = [s["name"] for s in phase1.gen_specs("S1") if s["ranked"] and s["tf"] in ("15m", "1h") and s["exit"] != "dc"]
        self.assertEqual(len(names), 14)
        self.assertFalse(any("4h" in n or n.startswith("donchian") or n.endswith("jevref") for n in names))


if __name__ == "__main__":
    unittest.main()
