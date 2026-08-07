"""NSE session phases in IST for the trading scheduler.

Phases: closed → pre_open (09:15) → entry (09:20) → no_entry (14:30)
→ flatten (15:15) → closed (15:30). Weekends are always closed.
No NSE holiday calendar yet — weekday-only check (tracked in BACKLOG).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"

_DEFAULT_SCHEDULE: dict[str, str] = {
    "market_open": "09:15",
    "entry_start": "09:20",
    "entry_cutoff": "14:30",
    "flatten_start": "15:15",
    "market_close": "15:30",
}


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_weekday(d: date) -> bool:
    return d.weekday() < 5


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def load_session_schedule() -> dict[str, str]:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            section = json.load(f).get("session_schedule", {})
    except (OSError, ValueError):
        section = {}
    return {**_DEFAULT_SCHEDULE, **{k: v for k, v in section.items() if k in _DEFAULT_SCHEDULE}}


def session_phase(
    now: datetime | None = None,
    *,
    schedule: dict[str, Any] | None = None,
) -> str:
    """Return the current session phase: closed | pre_open | entry | no_entry | flatten."""
    moment = now or now_ist()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IST)
    else:
        moment = moment.astimezone(IST)
    if not is_trading_weekday(moment.date()):
        return "closed"

    sched = {**_DEFAULT_SCHEDULE, **(schedule or load_session_schedule())}
    t = moment.time()
    market_open = _parse_hhmm(sched["market_open"])
    entry_start = _parse_hhmm(sched["entry_start"])
    entry_cutoff = _parse_hhmm(sched["entry_cutoff"])
    flatten_start = _parse_hhmm(sched["flatten_start"])
    market_close = _parse_hhmm(sched["market_close"])

    if t < market_open or t >= market_close:
        return "closed"
    if t < entry_start:
        return "pre_open"
    if t < entry_cutoff:
        return "entry"
    if t < flatten_start:
        return "no_entry"
    return "flatten"
