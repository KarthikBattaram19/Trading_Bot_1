# Confidence Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recommendation `confidence` an outcome-calibrated P(win) via `analytics/confidence_calibration.py` and runtime apply, with heuristic cold-start.

**Architecture:** Fit monotone score→P(win) maps from learning outcomes (hybrid global/per-strategy); walk-forward gate before deploy; recommendation engine applies map after failure-memory; rank stays on heuristic score.

**Tech Stack:** Python 3, pydantic models, JSON artifact under `backend/data/`, pytest.

## Global Constraints

- Spec: `Docs/superpowers/specs/2026-08-01-confidence-calibration-design.md`
- Min samples: 30 global / 30 per strategy
- Win v1: `realized_pnl_inr > 0`; scratch excluded
- Rank by `score`; gate by calibrated `confidence`
- Seed outcomes (`*_seed_*`) excluded from fit
- No full §10.4 RAG/regime stack

---

### Task 1: Fit library (`analytics/confidence_calibration.py`)

**Files:**
- Create: `analytics/__init__.py`
- Create: `analytics/confidence_calibration.py`
- Test: `backend/tests/test_confidence_calibration.py`

**Interfaces:**
- Produces: `is_win(pnl: float, outcome_label: str | None, strategy: str) -> bool | None`
- Produces: `fit_and_maybe_deploy(outcomes: list[dict], artifact_path: Path, prior_path: Path | None = None) -> dict` (returns fit report; writes artifact only on walk-forward pass)
- Produces: `apply_map(raw_x: float, knots: list[float], p_win: list[float]) -> float`

- [ ] **Step 1: Write failing tests** for `is_win`, too-small fit, happy-path deploy, seed exclusion, walk-forward fail retains prior, hybrid grain, `apply_map`
- [ ] **Step 2: Run tests — expect FAIL** (`pytest backend/tests/test_confidence_calibration.py -v`)
- [ ] **Step 3: Implement fit library** (bin/isotonic via pool-adjacent-violators or sorted bin means + monotone enforce; Brier; 70/30 WF)
- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit** with message covering calibration fit library

---

### Task 2: Runtime calibrator service

**Files:**
- Create: `backend/services/confidence_calibrator.py`
- Modify: `backend/tests/test_confidence_calibration.py` (apply missing / calibrated cases)

**Interfaces:**
- Produces: `CalibrationStatus = Literal["calibrated", "uncalibrated"]`
- Produces: `ConfidenceSource = Literal["outcome_map", "heuristic"]`
- Produces: `class ConfidenceCalibrator: load(path); apply(raw_confidence: float, strategy: str) -> tuple[float, CalibrationStatus, ConfidenceSource]`

- [ ] **Step 1: Write failing tests** for missing artifact and known knots apply
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement loader + interpolate apply**
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit**

---

### Task 3: Model + recommendation wiring

**Files:**
- Modify: `backend/models/recommendations.py` — add `calibration_status`, `confidence_source`
- Modify: `backend/models/learning.py` — add `raw_confidence_at_entry` on open/outcome records
- Modify: `backend/services/recommendation_engine.py` — apply calibrator after failure-memory; notes
- Test: `backend/tests/test_confidence_calibration.py` or extend existing recommendation tests

**Interfaces:**
- Consumes: `ConfidenceCalibrator.apply`
- Produces: recommendations with required status fields; sort by score; floor on calibrated confidence

- [ ] **Step 1: Write failing wiring test** (mock/temp artifact: floor uses P(win); sort by score; uncalibrated note)
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Wire models + engine**
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit**

---

### Task 4: Learning open/close + refit

**Files:**
- Modify: `backend/services/learning_service.py` — persist `raw_confidence_at_entry`; call `fit_and_maybe_deploy` after `record_outcome`
- Test: extend `backend/tests/test_confidence_calibration.py`

- [ ] **Step 1: Write failing test** — after enough synthetic closes, artifact deploys; seeds ignored
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement persistence + refit hook**
- [ ] **Step 4: Run full related pytest — expect PASS**
- [ ] **Step 5: Commit** (include design spec + plan if not yet committed)

---

## Spec coverage checklist

| Spec item | Task |
|---|---|
| `analytics/confidence_calibration.py` | 1 |
| Artifact JSON | 1 |
| Runtime calibrator | 2 |
| Recommendation apply + status fields | 3 |
| Rank by score / gate by confidence | 3 |
| Cold-start uncalibrated | 2–3 |
| `raw_confidence_at_entry` + refit | 4 |
| Seed exclusion | 1, 4 |
| Walk-forward gate | 1 |
| Hybrid grain | 1 |
