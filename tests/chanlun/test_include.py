from __future__ import annotations

from chanedge.chanlun.include import include_merge


def test_six_bar_sample_merges_high_and_low(bars_from_prices) -> None:
    """Open and close sit inside the range and do not enter the merge."""
    highs = [20, 18, 25, 24, 30, 28]
    lows = [10, 12, 19, 21, 22, 23]
    mids = [(high + low) / 2 for high, low in zip(highs, lows)]
    bars = bars_from_prices(mids, highs=highs, lows=lows)
    merged = include_merge(bars)
    assert [(bar.low, bar.high) for bar in merged] == [(12, 20), (21, 25), (23, 30)]
