"""JSON persistence for rolling ATM volume/OI session history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.services.atm_liquidity import AtmHistoryPoint

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "atm_liquidity_history.json"


class AtmLiquidityHistoryStore:
    """Single-process JSON store keyed by UNDERLYING|expiry_key."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH

    def _key(self, underlying: str, expiry_key: str) -> str:
        return f"{underlying.upper().strip()}|{expiry_key}"

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

    def upsert_snapshot(
        self,
        *,
        underlying: str,
        expiry_key: str,
        session_date: str,
        atm_strike: float,
        atm_volume: int,
        atm_oi: int,
    ) -> None:
        data = self._read()
        key = self._key(underlying, expiry_key)
        rows: list[dict[str, Any]] = list(data.get(key) or [])
        row = {
            "session_date": session_date,
            "atm_strike": float(atm_strike),
            "atm_volume": int(atm_volume),
            "atm_oi": int(atm_oi),
        }
        replaced = False
        for i, existing in enumerate(rows):
            if existing.get("session_date") == session_date:
                rows[i] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        rows.sort(key=lambda r: str(r.get("session_date") or ""))
        data[key] = rows
        self._write(data)

    def prior_points(
        self,
        *,
        underlying: str,
        expiry_key: str,
        before_date: str,
        lookback_days: int = 20,
    ) -> list[AtmHistoryPoint]:
        data = self._read()
        key = self._key(underlying, expiry_key)
        rows = [r for r in (data.get(key) or []) if str(r.get("session_date") or "") < before_date]
        rows.sort(key=lambda r: str(r.get("session_date") or ""))
        rows = rows[-lookback_days:]
        return [
            AtmHistoryPoint(
                session_date=str(r["session_date"]),
                atm_volume=int(r["atm_volume"]),
                atm_oi=int(r["atm_oi"]),
            )
            for r in rows
        ]

    def prune(self, *, keep_days: int = 60) -> None:
        data = self._read()
        changed = False
        for key, rows in list(data.items()):
            if not rows:
                continue
            dates = sorted(str(r.get("session_date") or "") for r in rows if r.get("session_date"))
            if not dates:
                continue
            # Keep the last keep_days rows by date order (session count proxy).
            kept = sorted(rows, key=lambda r: str(r.get("session_date") or ""))[-keep_days:]
            if len(kept) != len(rows):
                data[key] = kept
                changed = True
        if changed:
            self._write(data)
