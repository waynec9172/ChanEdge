from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from chanedge.marketdata.universe import (
    UniverseFileError,
    UniverseTooSmall,
    atomic_replace,
    load_universe,
    members_from_selection,
    reconstruct_dates,
    select_universe,
    symbol_allowed,
    universe_date,
    universe_path,
    write_fallback,
    write_universe_file,
)
from chanedge.marketdata.vision import DailyQuote, ranking_open_time

UTC = timezone.utc
EXCLUDE = ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "EUR")
FILE_DATE = date(2024, 1, 2)
AS_OF = datetime(2024, 1, 2, 0, 5, tzinfo=UTC)


def _name(index: int) -> str:
    return f"N{index:02d}USDT"


def _quotes(count: int, *, volume_at=None, min_qty=None, open_time=None) -> list[DailyQuote]:
    moment = ranking_open_time(FILE_DATE) if open_time is None else open_time
    rows = []
    for index in range(count):
        volume = Decimal(1000 - index) if volume_at is None else volume_at(index)
        rows.append(DailyQuote(_name(index), moment, volume, min_qty))
    return rows


def test_symbol_filter_and_zero_quote_volume_and_tie_break() -> None:
    assert symbol_allowed("BTCUSDT", EXCLUDE) is True
    assert symbol_allowed("BTCUSDT_240329", EXCLUDE) is False
    assert symbol_allowed("ETHBTC", EXCLUDE) is False
    assert symbol_allowed("USDCUSDT", EXCLUDE) is False
    assert symbol_allowed("EURUSDT", EXCLUDE) is False

    open_time = ranking_open_time(FILE_DATE)
    rows = [
        DailyQuote("BBBUSDT", open_time, Decimal(50), None),
        DailyQuote("AAAUSDT", open_time, Decimal(50), None),
        DailyQuote("CCCUSDT", open_time, Decimal(10), None),
        DailyQuote("ZZZUSDT", open_time, Decimal(0), None),
        DailyQuote("USDCUSDT", open_time, Decimal(999), None),
        DailyQuote("BTCUSDT_240329", open_time, Decimal(999), None),
        DailyQuote("ETHBTC", open_time, Decimal(999), None),
        DailyQuote("AAUSDT", open_time + timedelta(days=1), Decimal(9999), None),
    ]
    selected = select_universe(
        rows,
        file_date=FILE_DATE,
        size=2,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=False,
    )
    assert [item[0] for item in selected] == ["AAA/USDT", "BBB/USDT"]
    assert selected[0][1] == "AAA/USDT:USDT"


def test_fewer_than_twenty_names_fails_and_twenty_keeps_rank() -> None:
    with pytest.raises(UniverseTooSmall) as raised:
        select_universe(
            _quotes(19),
            file_date=FILE_DATE,
            size=20,
            exclude_bases=EXCLUDE,
            require_positive_min_qty=False,
        )
    assert raised.value.found == 19
    selected = select_universe(
        _quotes(21),
        file_date=FILE_DATE,
        size=20,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=False,
    )
    assert len(selected) == 20
    assert selected[0][0] == "N00/USDT"
    assert selected[-1][0] == "N19/USDT"
    assert all(item[2].quote_volume > 0 for item in selected)


def test_paper_min_qty_filter_does_not_apply_to_reconstruct() -> None:
    rows = _quotes(20, min_qty=None)
    rows.append(DailyQuote("ZZUSDT", ranking_open_time(FILE_DATE), Decimal(5000), None))
    reconstruct = select_universe(
        rows,
        file_date=FILE_DATE,
        size=20,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=False,
    )
    assert reconstruct[0][0] == "ZZ/USDT"
    with pytest.raises(UniverseTooSmall):
        select_universe(
            rows,
            file_date=FILE_DATE,
            size=20,
            exclude_bases=EXCLUDE,
            require_positive_min_qty=True,
        )
    paper_rows = _quotes(20, min_qty=Decimal("0.001"))
    paper_rows.append(DailyQuote("ZZUSDT", ranking_open_time(FILE_DATE), Decimal(5000), None))
    paper = select_universe(
        paper_rows,
        file_date=FILE_DATE,
        size=20,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=True,
    )
    assert "ZZ/USDT" not in [item[0] for item in paper]
    assert len(paper) == 20


def test_reconstruct_skips_an_existing_file_of_any_source(tmp_path) -> None:
    root = tmp_path
    path = universe_path(root, "binanceusdm", FILE_DATE)
    path.parent.mkdir(parents=True)
    path.write_text("KEEP", encoding="utf-8")
    written, skipped = reconstruct_dates(
        root,
        "binanceusdm",
        (FILE_DATE,),
        {FILE_DATE: _quotes(20)},
        size=20,
        exclude_bases=EXCLUDE,
        as_of=AS_OF,
    )
    assert written == ()
    assert skipped == (FILE_DATE,)
    assert path.read_text(encoding="utf-8") == "KEEP"
    with pytest.raises(UniverseFileError) as raised:
        load_universe(path)
    message = str(raised.value)
    assert str(path) in message
    assert "universe --reconstruct" in message
    assert path.read_text(encoding="utf-8") == "KEEP"


def test_new_reconstructed_file_roundtrips_and_is_not_daily_kline(tmp_path) -> None:
    root = tmp_path
    written, skipped = reconstruct_dates(
        root,
        "binanceusdm",
        (FILE_DATE,),
        {FILE_DATE: _quotes(20)},
        size=20,
        exclude_bases=EXCLUDE,
        as_of=AS_OF,
    )
    assert written == (FILE_DATE,)
    assert skipped == ()
    members = load_universe(universe_path(root, "binanceusdm", FILE_DATE))
    assert members[0].source == "reconstructed"
    assert members[0].fallback_from is None
    assert members[0].rank == 1
    assert members[0].bar_open_time == ranking_open_time(FILE_DATE)
    assert members[0].bar_close_time == ranking_open_time(FILE_DATE) + timedelta(days=1)
    assert members[0].quote_volume == Decimal(1000)
    again, skipped_again = reconstruct_dates(
        root,
        "binanceusdm",
        (FILE_DATE,),
        {FILE_DATE: _quotes(20, volume_at=lambda index: Decimal(1))},
        size=20,
        exclude_bases=EXCLUDE,
        as_of=AS_OF,
    )
    assert again == ()
    assert skipped_again == (FILE_DATE,)
    assert load_universe(universe_path(root, "binanceusdm", FILE_DATE))[0].quote_volume == Decimal(1000)


def test_fallback_copies_source_and_does_not_overwrite(tmp_path) -> None:
    root = tmp_path
    yesterday = FILE_DATE - timedelta(days=1)
    selected = select_universe(
        _quotes(2, open_time=ranking_open_time(yesterday)),
        file_date=yesterday,
        size=2,
        exclude_bases=EXCLUDE,
        require_positive_min_qty=False,
    )
    members = members_from_selection(selected, source="daily_kline", as_of=AS_OF)
    write_universe_file(universe_path(root, "binanceusdm", yesterday), members)
    result = write_fallback(root, "binanceusdm", FILE_DATE, as_of=AS_OF, error="daily fetch failed")
    assert result.written is True
    assert result.error == "daily fetch failed"
    copied = load_universe(result.path)
    assert copied[0].source == "daily_kline"
    assert copied[0].fallback_from == yesterday
    assert "daily fetch failed" not in result.path.read_text(encoding="utf-8")
    blocked = write_fallback(root, "binanceusdm", FILE_DATE, as_of=AS_OF, error="again")
    assert blocked.written is False
    missing = write_fallback(root, "binanceusdm", FILE_DATE + timedelta(days=3), as_of=AS_OF, error="no prior")
    assert missing.written is False
    assert missing.previous_missing is True


def test_universe_date_uses_refresh_minute_in_utc() -> None:
    assert universe_date(datetime(2024, 1, 1, 0, 0, tzinfo=UTC), 5) == date(2023, 12, 31)
    assert universe_date(datetime(2024, 1, 1, 0, 15, tzinfo=UTC), 5) == date(2024, 1, 1)
    plus_8 = timezone(timedelta(hours=8))
    assert universe_date(datetime(2024, 1, 1, 8, 0, tzinfo=plus_8), 5) == date(2023, 12, 31)


def test_replace_retries_then_raises_without_publishing_the_tmp(tmp_path) -> None:
    final = tmp_path / "2024-01-02.json"
    sleeps: list[float] = []

    def fail(src, dst) -> None:
        raise PermissionError("busy")

    with pytest.raises(PermissionError):
        atomic_replace(final, b"{}", replace=fail, sleep=sleeps.append, attempts=5)
    assert not final.exists()
    assert (tmp_path / "2024-01-02.json.tmp").exists()
    assert len(sleeps) == 4

    calls = {"n": 0}

    def flaky(src, dst) -> None:
        calls["n"] += 1
        if calls["n"] < 5:
            raise PermissionError("busy")
        os.replace(src, dst)

    atomic_replace(final, b"{\"ok\": true}\n", replace=flaky, sleep=sleeps.append, attempts=5)
    assert final.read_bytes() == b"{\"ok\": true}\n"
    assert calls["n"] == 5
