"""Effective recommendation-confidence floor with a bootstrap phase.

Owner decision (2026-08-07): until the learning store holds at least one
real (non-seed) closed trade, the floor is `bootstrap_min_confidence`
(0.70); from the first real close onward it reverts automatically to
`min_recommendation_confidence` (0.80). The `MIN_RECOMMENDATION_CONFIDENCE`
env var is a manual emergency lever that overrides both, clamped to
[0.5, 0.95]. If the learning store is unreadable we fail closed to the
stricter config floor.
"""

from __future__ import annotations

import os
from typing import Any

from backend.services.learning_service import get_learning_service

ENV_OVERRIDE = "MIN_RECOMMENDATION_CONFIDENCE"
_CLAMP_LOW = 0.5
_CLAMP_HIGH = 0.95


def effective_min_confidence(cfg: dict[str, Any]) -> tuple[float, str]:
    """Return (floor, source) where source is "env" | "bootstrap" | "config"."""
    constraints = cfg.get("execution_constraints", {})
    config_floor = float(constraints.get("min_recommendation_confidence", 0.80))
    bootstrap_floor = float(constraints.get("bootstrap_min_confidence", config_floor))

    raw_env = os.getenv(ENV_OVERRIDE, "").strip()
    if raw_env:
        try:
            return min(_CLAMP_HIGH, max(_CLAMP_LOW, float(raw_env))), "env"
        except ValueError:
            pass  # unparsable override → fall through to bootstrap/config logic

    try:
        if get_learning_service().real_closed_trade_count() == 0:
            return bootstrap_floor, "bootstrap"
    except Exception:  # noqa: BLE001 — unreadable store fails closed to strict floor
        return config_floor, "config"

    return config_floor, "config"
