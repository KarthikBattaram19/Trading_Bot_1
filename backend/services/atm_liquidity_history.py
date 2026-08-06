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

    def latest_liquidity_by_underlying(
        self, underlyings: set[str] | None = None
    ) -> dict[str, float]:
        """Most recent atm_volume + atm_oi per underlying, across any expiry_key.

        Used as an ADV/liquidity proxy to rank which symbols get the limited
        enrichment budget (see recommendation_engine._build_universe) — real
        history once the bot has run a few sessions, 0.0 (neutral) for anything
        never enriched before, which preserves today's alphabetical ordering
        for a cold store.
        """
        data = self._read()
        wanted = {u.upper().strip() for u in underlyings} if underlyings else None
        latest: dict[str, tuple[str, float]] = {}
        for key, rows in data.items():
            underlying, _, _expiry_key = key.partition("|")
            if wanted is not None and underlying not in wanted:
                continue
            if not rows:
                continue
            best_row = max(rows, key=lambda r: str(r.get("session_date") or ""))
            session_date = str(best_row.get("session_date") or "")
            liquidity = float(best_row.get("atm_volume") or 0) + float(
                best_row.get("atm_oi") or 0
            )
            prior = latest.get(underlying)
            if prior is None or session_date > prior[0]:
                latest[underlying] = (session_date, liquidity)
        return {underlying: value for underlying, (_, value) in latest.items()}

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
