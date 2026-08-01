"""File-backed earnings calendar for days_to_earnings (G6 / SH-4)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "earnings_calendar.json"
)


class EarningsCalendarStore:
    """Curated map of SYMBOL → list of ISO earnings dates."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        with open(self.store_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def days_to_earnings(self, symbol: str, *, as_of_date: str) -> int | None:
        """Return calendar days until next earnings on/after as_of_date, or None."""
        as_of = date.fromisoformat(as_of_date)
        raw = self._read().get(symbol.upper().strip())
        if not raw:
            return None
        dates: list[date] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                dates.append(date.fromisoformat(str(item)[:10]))
            except ValueError:
                continue
        future = sorted(d for d in dates if d >= as_of)
        if not future:
            return None
        return (future[0] - as_of).days


def session_date_ist() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:  # noqa: BLE001
        return datetime.now().date().isoformat()
