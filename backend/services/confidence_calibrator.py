"""Runtime loader for deployed confidence calibration maps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from backend.analytics.confidence_calibration import apply_map

CalibrationStatus = Literal["calibrated", "uncalibrated"]
ConfidenceSource = Literal["outcome_map", "heuristic"]

DEFAULT_ARTIFACT = (
    Path(__file__).resolve().parents[1] / "data" / "confidence_calibration.json"
)


class ConfidenceCalibrator:
    def __init__(self, artifact_path: Path | None = None) -> None:
        self.path = Path(artifact_path) if artifact_path else DEFAULT_ARTIFACT
        self._data: dict | None = None
        self.reload()

    def reload(self) -> None:
        self._data = None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("deployed") and raw.get("global", {}).get("x_knots"):
                self._data = raw
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self._data = None

    def apply(
        self, raw_confidence: float, strategy: str
    ) -> tuple[float, CalibrationStatus, ConfidenceSource]:
        raw = float(raw_confidence)
        data = self._data
        if not data:
            return raw, "uncalibrated", "heuristic"

        strat_map = (data.get("by_strategy") or {}).get(strategy)
        if strat_map and strat_map.get("x_knots") and strat_map.get("p_win"):
            p = apply_map(raw, list(strat_map["x_knots"]), list(strat_map["p_win"]))
            return p, "calibrated", "outcome_map"

        g = data.get("global") or {}
        if g.get("x_knots") and g.get("p_win"):
            p = apply_map(raw, list(g["x_knots"]), list(g["p_win"]))
            return p, "calibrated", "outcome_map"

        return raw, "uncalibrated", "heuristic"
