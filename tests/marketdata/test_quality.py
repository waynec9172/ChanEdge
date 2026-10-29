from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chanedge.domain.enums import Timeframe, VetoCode
from chanedge.marketdata.quality import assess_quality, closed_window, measure_gaps

UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def test_missing_one_bar_is_not_a_gap_and_missing_two_is(make_bar) -> None:
    one_hole = (
        make_bar(open_time=T0),
        make_bar(open_time=T0 + timedelta(minutes=15)),
        make_bar(open_time=T0 + timedelta(minutes=45)),
    )
    checked = measure_gaps(one_hole, max_gap_bars=1)
    assert checked.is_gap is False
    assert checked.missing_bar_count == 1

    two_hole = (
        make_bar(open_time=T0),
        make_bar(open_time=T0 + timedelta(minutes=15)),
        make_bar(open_time=T0 + timedelta(hours=1)),
    )
    checked = measure_gaps(two_hole, max_gap_bars=1)
    assert checked.is_gap is True
    assert checked.missing_bar_count == 2


def test_missing_bar_count_sums_every_positive_hole_and_is_not_the_threshold(make_bar) -> None:
    bars = tuple(
        make_bar(open_time=T0 + timedelta(minutes=30 * step))
        for step in range(4)
    )
    checked = measure_gaps(bars, max_gap_bars=1)
    assert checked.missing_bar_count == 3
    assert checked.is_gap is False


def test_unclosed_4h_does_not_enter_the_window(make_bar) -> None:
    closed = make_bar(timeframe=Timeframe.H4, open_time=T0, is_closed=True)
    unclosed = make_bar(timeframe=Timeframe.H4, open_time=T0 + timedelta(hours=4), is_closed=False)
    as_of = T0 + timedelta(hours=6)
    window = closed_window((closed, unclosed), as_of=as_of)
    assert window == (closed,)
    late_but_marked_closed = make_bar(
        timeframe=Timeframe.H4,
        open_time=T0 + timedelta(hours=4),
        is_closed=True,
    )
    assert closed_window((closed, late_but_marked_closed), as_of=as_of) == (closed,)


def test_any_timeframe_gap_records_gap_data_and_backtest_is_not_stale(make_bar) -> None:
    m15 = (make_bar(open_time=T0), make_bar(open_time=T0 + timedelta(minutes=15)))
    h1 = (
        make_bar(timeframe=Timeframe.H1, open_time=T0),
        make_bar(timeframe=Timeframe.H1, open_time=T0 + timedelta(hours=1)),
    )
    h4 = (
        make_bar(timeframe=Timeframe.H4, open_time=T0),
        make_bar(timeframe=Timeframe.H4, open_time=T0 + timedelta(hours=12)),
    )
    now = datetime(2024, 1, 3, tzinfo=UTC)
    quality = assess_quality(
        {Timeframe.M15: m15, Timeframe.H1: h1, Timeframe.H4: h4},
        max_gap_bars={Timeframe.M15: 1, Timeframe.H1: 1, Timeframe.H4: 1},
        now=now,
        backtest=True,
    )
    assert quality.stale is False
    assert quality.reasons == (VetoCode.GAP_DATA.value,)
    assert quality.missing_bar_count == 2
    assert quality.max_gap_bars == 1

    live = assess_quality(
        {Timeframe.M15: m15, Timeframe.H1: h1, Timeframe.H4: h4},
        max_gap_bars={Timeframe.M15: 1, Timeframe.H1: 1, Timeframe.H4: 1},
        now=m15[-1].close_time + timedelta(minutes=15, seconds=91),
        backtest=False,
    )
    assert live.stale is True
    assert VetoCode.STALE_DATA.value in live.reasons
    assert VetoCode.GAP_DATA.value in live.reasons
