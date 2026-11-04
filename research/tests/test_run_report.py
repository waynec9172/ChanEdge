"""run.py / report.py discipline tests. Temp files only: the real registry and oos_log are never touched."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research import common as C
from research import report, run, sim

ROOT = Path(__file__).resolve().parents[2]


class ConfigTests(unittest.TestCase):
    def test_unknown_key_and_name_mismatch(self):
        good = C.read_yaml(C.EXPERIMENTS / "p0_validate_current_15m.yaml")
        sim.SimConfig.from_dict(good)
        bad = dict(good, surprise=1)
        with self.assertRaises(sim.ConfigError):
            sim.SimConfig.from_dict(bad)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "other_name.yaml"
            p.write_text((C.EXPERIMENTS / "p0_validate_current_15m.yaml").read_text())
            self.assertEqual(run.main([str(p), "--registry", str(Path(td) / "reg.md")]), 2)
            q = Path(td) / "p0_validate_current_15m.yaml"
            q.write_text((C.EXPERIMENTS / "p0_validate_current_15m.yaml").read_text().replace("jev_min: 0.62", "jev_min: 0.62\n  nope: 1"))
            self.assertEqual(run.main([str(q), "--registry", str(Path(td) / "reg.md")]), 2)

    def test_all_shipped_experiments_parse(self):
        for p in sorted(C.EXPERIMENTS.glob("*.yaml")):
            cfg = sim.SimConfig.from_dict(C.read_yaml(p))
            self.assertEqual(cfg.name, p.stem)
        names = {p.stem for p in C.EXPERIMENTS.glob("*.yaml")}
        self.assertTrue({"donchian_1h_n20", "donchian_4h_n55"} <= names)


class RegistryTests(unittest.TestCase):
    def test_limit_and_changed_config(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "registry.md"
            reg.write_text("# Experiment registry\n| time_utc | name | config_sha | summary |\n| --- | --- | --- | --- |\n")
            for i in range(60):
                run.check_registry(reg, f"exp{i}", "aaa")
                run.append_registry(reg, f"exp{i}", "aaa", "s")
            with self.assertRaises(run.RegistryError):
                run.check_registry(reg, "exp60", "aaa")
            run.check_registry(reg, "exp5", "aaa")  # same name, same config: allowed
            with self.assertRaises(run.RegistryError):
                run.check_registry(reg, "exp5", "bbb")
            self.assertEqual(run.RegistryError.exit_code, 3)


class ReportTests(unittest.TestCase):
    def test_default_is_in_sample_only(self):
        df = pd.DataFrame({"sample": ["IS", "OOS", "IS", None], "net_r": [1.0, 2.0, 3.0, 4.0]})
        self.assertEqual(list(report.select_sample(df, oos=False)["net_r"]), [1.0, 3.0])
        self.assertEqual(list(report.select_sample(df, oos=True)["net_r"]), [2.0])

    def test_oos_log_once_per_name(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "oos_log.md"
            log.write_text("")
            report.log_oos("e1", "python -m research.report e1 --oos", log)
            self.assertIn("e1", log.read_text())
            with self.assertRaises(report.OosRefused):
                report.log_oos("e1", "again", log)
            report.log_oos("e2", "cmd", log)
            self.assertEqual(len([ln for ln in log.read_text().splitlines() if ln.startswith("|")]), 2)

    def test_real_oos_log_untouched(self):
        self.assertEqual((C.OUT / "oos_log.md").stat().st_size, 0)

    def test_sample_labels(self):
        import datetime as dt

        self.assertEqual(C.sample_of(dt.date(2024, 1, 1)), "IS")
        self.assertEqual(C.sample_of(dt.date(2025, 6, 30)), "IS")
        self.assertEqual(C.sample_of(dt.date(2025, 7, 1)), "OOS")
        self.assertEqual(C.sample_of(dt.date(2026, 10, 27)), "OOS")
        self.assertIsNone(C.sample_of(dt.date(2023, 12, 31)))


class ImportTests(unittest.TestCase):
    def test_only_allowed_imports(self):
        allowed = set(sys.stdlib_module_names) | {"numpy", "pandas", "pyarrow", "chanedge", "research"}
        bad = []
        for path in (ROOT / "research").rglob("*.py"):
            if "cache" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                for m in mods:
                    if m.split(".")[0] not in allowed:
                        bad.append((str(path), m))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
