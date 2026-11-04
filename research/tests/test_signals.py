"""Signal cache tests. Real BTC/USDT 15m bars, truncated; cache checks run when the cache exists."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from research import common as C
from research import donchian, signals as S

_UTC = timezone.utc
_BARS = None


def bars20k():
    global _BARS
    if _BARS is None:
        _BARS = S.closed_bars("15m", "BTC/USDT")[:20000]
    return _BARS


class WalkTests(unittest.TestCase):
    def test_walk_matches_engine_compute(self):
        bars = bars20k()
        w = S.walk(bars, "15m")
        snap = S.make_engine().compute(bars, timeframe=S._tf_enum("15m"), as_of=bars[-1].close_time, identify=False)
        self.assertEqual({x.signal.id for x in w.signals}, {s.id for s in snap.signals})
        self.assertGreater(len(snap.signals), 100)

    def test_no_lookahead_on_truncation(self):
        bars = bars20k()
        full = S.walk(bars, "15m")
        for n in (6000, 12000, 18000):
            part = S.walk(bars[:n], "15m")
            cut = bars[n - 1].close_time
            a = {(x.signal.id, x.signal.defending_price) for x in part.signals if x.signal.time <= cut}
            b = {(x.signal.id, x.signal.defending_price) for x in full.signals if x.signal.time <= cut}
            self.assertEqual(a, b, f"signals before bar {n} changed when later bars were added")
            self.assertGreater(len(a), 0)

    def test_signal_time_is_a_bar_close(self):
        bars = bars20k()
        closes = {b.close_time for b in bars}
        for x in S.walk(bars, "15m").signals:
            self.assertIn(x.signal.time, closes)


class UniverseDateTests(unittest.TestCase):
    def test_boundaries(self):
        d = lambda *a: C.universe_date(datetime(*a, tzinfo=_UTC))
        self.assertEqual(d(2024, 3, 2, 0, 0, 0).isoformat(), "2024-03-01")
        self.assertEqual(d(2024, 3, 2, 0, 5, 0).isoformat(), "2024-03-02")
        self.assertEqual(d(2024, 3, 2, 0, 4, 59).isoformat(), "2024-03-01")

    def test_vector_matches_scalar(self):
        s = pd.Series(pd.to_datetime(["2024-03-02 00:00:00", "2024-03-02 00:05:00", "2024-03-02 00:04:59"], utc=True))
        self.assertEqual([x.isoformat() for x in C.universe_dates(s)], ["2024-03-01", "2024-03-02", "2024-03-01"])


class DonchianTests(unittest.TestCase):
    def test_first_breakout_only_and_no_future(self):
        high = np.array([1, 2, 3, 4, 5, 6, 5, 6, 9, 10, 11, 12.0])
        low = high - 1
        close = high - 0.1
        close[8], high[8] = 9.0, 9.0
        up, dn = donchian.breakouts(high, low, close, 3)
        self.assertEqual(list(np.flatnonzero(up)), [8])  # bars 9..11 keep breaking out but are not the first
        self.assertFalse(dn.any())
        # changing a bar after t must not change the flag at t
        high2, low2, close2 = high.copy(), low.copy(), close.copy()
        high2[10:], close2[10:] = 0.5, 0.4
        low2[10:] = 0.3
        up2, _ = donchian.breakouts(high2, low2, close2, 3)
        self.assertTrue(up2[8])

    def test_short_symmetry(self):
        high = np.array([12, 11, 10, 9, 8, 7, 8, 7, 4, 3.0])
        low = high - 1
        close = low + 0.1
        close[8], low[8] = 3.0, 3.0
        up, dn = donchian.breakouts(high, low, close, 3)
        self.assertEqual(list(np.flatnonzero(dn)), [8])


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = C.CACHE / "signals_15m.parquet"
        if not cls.path.exists():
            raise AssertionError("signals_15m.parquet is missing; build the cache before running the tests")
        cls.df = pd.read_parquet(cls.path)

    def test_columns(self):
        need = {
            "signal_id", "symbol", "tf", "type", "side", "time", "close", "defending_price", "prior_extreme", "zs_zg", "zs_zd",
            "atr", "bias_4h", "bias_1h", "bias_15m", "universe_date", "rank", "in_top20", "reemit", "last_up_end",
            "last_down_end", "candidate", "ambiguous", "in_window", "gate_pass", "veto_codes", "jev_score", "jev_action",
            "atr_pct", "session_bucket", "hist_ok", "gap_veto",
        } | {f"ch_{c}_{k}" for c in ("structure", "location", "resonance", "volatility_volume", "signal_bar", "session") for k in ("subscore", "penalty")}
        self.assertEqual(need - set(self.df.columns), set())
        self.assertEqual(self.df[self.df["in_top20"]]["jev_score"].isna().sum(), 0)

    def test_times_are_bar_closes_for_btc(self):
        sub = self.df[self.df["symbol"] == "BTC/USDT"]
        self.assertGreater(len(sub), 0)
        bars = C.load_bars_df("BTC/USDT", "15m")
        closes = set(pd.to_datetime(bars["close_time"], utc=True))
        self.assertTrue(all(pd.Timestamp(t) in closes for t in sub["time"]))
        self.assertTrue(((sub["time"].dt.minute % 15) == 0).all())
        self.assertTrue((sub["time"].dt.second == 0).all())

    def test_other_timeframes_exist(self):
        for tf in ("1h", "4h"):
            d = pd.read_parquet(C.CACHE / f"signals_{tf}.parquet")
            self.assertGreater(len(d), 0)
            step = 60 if tf == "1h" else 240
            mins = d["time"].dt.hour * 60 + d["time"].dt.minute
            self.assertTrue(((mins % step) == 0).all())


if __name__ == "__main__":
    unittest.main()
