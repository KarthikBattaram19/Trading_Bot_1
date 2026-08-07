"""NSE session-phase helper — the clock that gates the trading scheduler."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.services.market_session import IST, now_ist, session_phase


def _ist(day: int, hh: int, mm: int) -> datetime:
    # August 2026: Mon=10, Sat=8, Sun=9.
    return datetime(2026, 8, day, hh, mm, tzinfo=IST)


def test_weekend_is_closed() -> None:
    assert session_phase(_ist(8, 11, 0)) == "closed"  # Saturday
    assert session_phase(_ist(9, 11, 0)) == "closed"  # Sunday


def test_phase_boundaries_on_a_trading_weekday() -> None:
    assert session_phase(_ist(10, 9, 14)) == "closed"
    assert session_phase(_ist(10, 9, 15)) == "pre_open"
    assert session_phase(_ist(10, 9, 19)) == "pre_open"
    assert session_phase(_ist(10, 9, 20)) == "entry"
    assert session_phase(_ist(10, 14, 29)) == "entry"
    assert session_phase(_ist(10, 14, 30)) == "no_entry"
    assert session_phase(_ist(10, 15, 14)) == "no_entry"
    assert session_phase(_ist(10, 15, 15)) == "flatten"
    assert session_phase(_ist(10, 15, 29)) == "flatten"
    assert session_phase(_ist(10, 15, 30)) == "closed"
    assert session_phase(_ist(10, 2, 0)) == "closed"


def test_aware_utc_input_is_converted_to_ist() -> None:
    # 04:00 UTC == 09:30 IST on Monday 2026-08-10 → entry phase.
    now_utc = datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc)
    assert session_phase(now_utc) == "entry"


def test_naive_input_is_treated_as_ist() -> None:
    assert session_phase(datetime(2026, 8, 10, 10, 0)) == "entry"


def test_schedule_override_times() -> None:
    schedule = {
        "market_open": "10:00",
        "entry_start": "10:05",
        "entry_cutoff": "11:00",
        "flatten_start": "11:30",
        "market_close": "12:00",
    }
    assert session_phase(_ist(10, 9, 30), schedule=schedule) == "closed"
    assert session_phase(_ist(10, 10, 2), schedule=schedule) == "pre_open"
    assert session_phase(_ist(10, 10, 30), schedule=schedule) == "entry"
    assert session_phase(_ist(10, 11, 15), schedule=schedule) == "no_entry"
    assert session_phase(_ist(10, 11, 45), schedule=schedule) == "flatten"
    assert session_phase(_ist(10, 12, 0), schedule=schedule) == "closed"


def test_now_ist_returns_aware_ist_datetime() -> None:
    now = now_ist()
    assert now.tzinfo is not None
    assert now.utcoffset() == _ist(10, 0, 0).utcoffset()
