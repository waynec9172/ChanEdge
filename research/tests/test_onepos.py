"""Metrics: at most one position per symbol (user note 5), strictly in-sample."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from research import common as C, metrics as M

T0 = pd.Timestamp("2024-03-01 00:00", tz="UTC")


def att(aid, sym, minutes, status, end_minutes, side=1, typ="second_buy", sid=None, sample="IS"):
    return {
        "attempt_id": aid, "signal_id": sid or f"s{aid}", "symbol": sym, "tf": "1h", "type": typ, "side": side,
        "signal_time": T0 + pd.Timedelta(minutes=minutes), "status": status, "end_time": T0 + pd.Timedelta(minutes=end_minutes), "sample": sample,
    }


def trades_for(a):
    f = a[a["status"] == "filled"]
    return pd.DataFrame({"attempt_id": f["attempt_id"], "sample": f["sample"], "net_r": 0.1})


def v2(rows):
    a = pd.DataFrame(rows)
    return M.one_per_symbol(a, trades_for(a))


class OnePosTests(unittest.TestCase):
    def test_v1_overlap_skipped_strict(self):
        _, a2 = v2([
            att(0, "A", 0, "filled", 600),
            att(1, "A", 600, "filled", 700),  # signal_time == end_time of the open trade: skipped
            att(2, "A", 601, "filled", 700),  # strictly later: taken
            att(3, "B", 300, "filled", 400),  # other symbol is independent
        ])
        self.assertEqual(sorted(a2["attempt_id"]), [0, 2, 3])

    def test_v2_simultaneous_signals(self):
        _, a2 = v2([
            att(0, "A", 0, "filled", 50, side=1), att(1, "A", 0, "filled", 50, side=-1, typ="second_sell"),  # both sides -> nothing
            att(2, "A", 100, "filled", 150, typ="second_buy", sid="z"), att(3, "A", 100, "filled", 160, typ="third_buy", sid="a"),
        ])
        self.assertEqual(list(a2["attempt_id"]), [3])  # third_* beats second_*
        _, a2 = v2([att(0, "A", 0, "filled", 50, sid="b"), att(1, "A", 0, "filled", 50, sid="a")])
        self.assertEqual(list(a2["attempt_id"]), [1])  # same class: smallest signal_id

    def test_v3_rejected_do_not_occupy(self):
        _, a2 = v2([
            att(0, "A", 0, "minstop_rejected", 5000),
            att(1, "A", 10, "invalid_stop", 5000),
            att(2, "A", 20, "filled", 100),
        ])
        self.assertEqual(list(a2["attempt_id"]), [2])

    def test_v4_unfilled_and_abandoned_occupy(self):
        t2, a2 = v2([
            att(0, "A", 0, "unfilled", 60),
            att(1, "A", 30, "filled", 90),  # inside the pending order window: skipped
            att(2, "A", 61, "abandoned", 70),
            att(3, "A", 65, "filled", 90),  # inside the abandoned confirmation: skipped
            att(4, "A", 71, "filled", 90),
        ])
        self.assertEqual(list(a2["attempt_id"]), [0, 2, 4])
        self.assertEqual(list(t2["attempt_id"]), [4])  # only filled attempts become trades

    def test_v5_only_in_sample(self):
        rows = [att(0, "A", 0, "filled", 10), att(1, "A", 100, "filled", 110, sample="OOS"), att(2, "A", 200, "filled", 210, sample="OOS")]
        t2, a2 = v2(rows)
        self.assertEqual(list(a2["attempt_id"]), [0])
        self.assertTrue((t2["sample"] == "IS").all())
        a = pd.DataFrame(rows)
        with tempfile.TemporaryDirectory() as td:
            res = Path(td) / "results"
            res.mkdir()
            trades_for(a).assign(net_r=0.1).to_parquet(res / "e.parquet")
            a.to_parquet(res / "e.attempts.parquet")
            with mock.patch.object(C, "CACHE", Path(td)):
                t, aa = M.load_is("e")
        self.assertEqual(list(t["attempt_id"]), [0])
        self.assertEqual(list(aa["attempt_id"]), [0])


if __name__ == "__main__":
    unittest.main()
