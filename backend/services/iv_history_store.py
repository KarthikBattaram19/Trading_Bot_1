"""Session IV sample history for intraday IV z-score (N4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "iv_history.json"


class IvHistoryStore:
    """JSON store of intraday ATM IV samples keyed by SYMBOL|session_date."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH

    def _key(self, symbol: str, session_date: str) -> str:
        return f"{symbol.upper().strip()}|{session_date}"

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

    def append(
        self,
        *,
        symbol: str,
        session_date: str,
        ts_iso: str,
        iv: float,
    ) -> None:
        if iv <= 0:
            return
        data = self._read()
        key = self._key(symbol, session_date)
        rows: list[dict[str, Any]] = list(data.get(key) or [])
        rows.append({"ts": ts_iso, "iv": float(iv)})
        data[key] = rows
        self._write(data)

    def series(self, *, symbol: str, session_date: str) -> list[float]:
        data = self._read()
        rows = list(data.get(self._key(symbol, session_date)) or [])
        out: list[float] = []
        for r in rows:
            try:
                v = float(r.get("iv"))
            except (TypeError, ValueError):
                continue
            if v > 0:
                out.append(v)
        return out
