"""Persisted approve/reject state for decisions.py — survives a process restart.

Decisions themselves are still derived (recommendation cache + learning store,
see decision_log.py) — this store only records what an operator decided about
a given decision_id.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "decision_state.json"


class DecisionState(BaseModel):
    status: Literal["approved", "rejected"]
    trade_id: str | None = None
    reason: str | None = None
    acted_at: datetime


class DecisionStateStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or STORE_PATH

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {}
        with open(self.store_path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, decision_id: str) -> DecisionState | None:
        raw = self._read().get(decision_id)
        if raw is None:
            return None
        return DecisionState.model_validate(raw)

    def set(self, decision_id: str, state: DecisionState) -> None:
        data = self._read()
        data[decision_id] = json.loads(state.model_dump_json())
        self._write(data)


_decision_state_store: DecisionStateStore | None = None


def get_decision_state_store() -> DecisionStateStore:
    global _decision_state_store
    if _decision_state_store is None:
        _decision_state_store = DecisionStateStore()
    return _decision_state_store
