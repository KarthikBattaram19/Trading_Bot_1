"""
Kill-switch armed state — architecture PS-08 / Phase 1.6.

Persisted to disk (not a process global) so an armed kill-switch survives a
process restart instead of silently un-arming — Docs/bot_health/BACKLOG.md P0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "kill_switch_state.json"


class KillSwitchState:
    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or STORE_PATH

    def _read(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {"armed": False}
        with open(self.store_path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, state: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def is_armed(self) -> bool:
        return bool(self._read().get("armed", False))

    def set_armed(self, armed: bool) -> None:
        self._write({"armed": armed})


# Process singleton (mirrors backend/services/learning_service.py's pattern)
_kill_switch_state: KillSwitchState | None = None


def get_kill_switch_state() -> KillSwitchState:
    global _kill_switch_state
    if _kill_switch_state is None:
        _kill_switch_state = KillSwitchState()
    return _kill_switch_state
