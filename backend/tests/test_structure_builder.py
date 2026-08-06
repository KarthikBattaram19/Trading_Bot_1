"""Unit tests for backend/paper_sim/structure_builder.py's gamma_scalping
vega-neutral calendar-spread construction (Docs/Trading_Strategies.md Table GS-4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.integrations.icici_direct.models import InstrumentRecord, NormalizedTick
from backend.paper_sim.structure_builder import _resolve_far_expiry


def _expiry_str(days_from_now: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return dt.strftime("%d-%b-%Y")


class _ChainFeed:
    """Minimal feed stub exposing only list_options, for resolver-level tests."""

    def __init__(self, records: list[InstrumentRecord]) -> None:
        self._records = records

    def list_options(self, *, name, exchange="NFO", expiry=None, limit=500):
        rows = [r for r in self._records if (r.name or "").upper() == name.upper()]
        return rows[:limit]


def _opt(expiry: str, strike: float, right: str, token: str) -> InstrumentRecord:
    return InstrumentRecord(
        exchange="NFO",
        tradingsymbol=f"SBIN{token}{right}",
        symboltoken=token,
        name="SBIN",
        expiry=expiry,
        strike=strike,
        lotsize=25,
        instrumenttype="OPTSTK",
    )


def test_resolve_far_expiry_picks_nearest_expiry_clearing_the_gap():
    near = _expiry_str(15)
    just_short = _expiry_str(15 + 27)  # gap 27 < 28, must be skipped
    far = _expiry_str(15 + 30)  # gap 30 >= 28
    farther = _expiry_str(15 + 60)  # gap 60 >= 28, but not nearest
    feed = _ChainFeed(
        [
            _opt(near, 500.0, "CE", "1"),
            _opt(just_short, 500.0, "CE", "2"),
            _opt(far, 500.0, "CE", "3"),
            _opt(farther, 500.0, "CE", "4"),
        ]
    )
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is not None
    resolved_expiry, resolved_dte = result
    assert resolved_expiry == far


def test_resolve_far_expiry_returns_none_when_no_expiry_clears_the_gap():
    near = _expiry_str(15)
    only_short = _expiry_str(15 + 10)
    feed = _ChainFeed([_opt(near, 500.0, "CE", "1"), _opt(only_short, 500.0, "CE", "2")])
    result = _resolve_far_expiry(feed, name="SBIN", near_expiry=near, min_gap_days=28)
    assert result is None
