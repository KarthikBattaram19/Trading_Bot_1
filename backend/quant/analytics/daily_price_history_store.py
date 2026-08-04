"""JSON store of daily close-price history per symbol, for GARCH walk-forward
evidence (Improve_Recoemmendation_Engine.md §3.4 / Docs/bot_health/BACKLOG.md P1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "daily_price_history.json"


class DailyPriceHistoryStore:
    """JSON store of {date, close} rows keyed by SYMBOL, chronological order."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH

    def _key(self, symbol: str) -> str:
        return symbol.upper().strip()

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        with open(self.store_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def replace(self, *, symbol: str, rows: list[dict[str, Any]]) -> None:
        """Overwrite the full stored series for `symbol` (backfill is idempotent per-run)."""
        cleaned: list[dict[str, Any]] = []
        for r in rows:
            date = r.get("date")
            try:
                close = float(r.get("close"))
            except (TypeError, ValueError):
                continue
            if not date or close <= 0:
                continue
            cleaned.append({"date": str(date), "close": close})
        cleaned.sort(key=lambda r: r["date"])
        data = self._read()
        data[self._key(symbol)] = cleaned
        self._write(data)

    def rows(self, *, symbol: str) -> list[dict[str, Any]]:
        data = self._read()
        return list(data.get(self._key(symbol)) or [])

    def series(self, *, symbol: str) -> list[float]:
        return [float(r["close"]) for r in self.rows(symbol=symbol)]

    def date_range(self, *, symbol: str) -> tuple[str, str] | None:
        rows = self.rows(symbol=symbol)
        if not rows:
            return None
        return rows[0]["date"], rows[-1]["date"]

    def symbols(self) -> list[str]:
        return sorted(self._read().keys())
