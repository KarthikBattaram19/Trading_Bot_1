# Confidence Calibration (Score → P(win)) — Design Spec

| Field | Value |
|---|---|
| Date | 2026-08-01 |
| Status | Approved for implementation |
| Approach | Offline isotonic/bin map + runtime apply; hybrid global→per-strategy |
| Scope | Recommendation confidence gating/display (Approach A) |

## 1. Goal

Make recommendation `confidence` an **outcome-calibrated win probability** when enough closed trades exist, instead of the heuristic `min(0.95, score + 0.05)`.

- Implement architecture §10.4 calibration artifact path: `analytics/confidence_calibration.py`.
- Wire the recommendation path to use the deployed map for the ≥80% floor and display.
- Keep heuristic `score` as the top-3 ranking key.
- Cold-start: unchanged heuristic gating with explicit `calibration_status=uncalibrated`.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Product scope | Recommendation path only (not full §10.4 RAG/regime stack) |
| Ranking | Always by heuristic `score` |
| Confidence when calibrated | P(win \| raw confidence after failure-memory) from deployed map |
| Cold-start gating | Heuristic confidence + `calibration_status=uncalibrated` (still surface top-3) |
| Win label (v1) | `realized_pnl_inr > 0`; `scratch` excluded from fit; strategy-specific `is_win` hook for later |
| Grain | Hybrid: global map at ≥30 outcomes; per-strategy map when that strategy has ≥30 |
| Fit method | Monotone bin / isotonic regression on raw confidence vs win |
| Deploy gate | Walk-forward must pass before overwriting deployed artifact |
| Seed data | `*_seed_*` outcomes excluded from fit |
| Out of scope | Full §10.4 weight stack, Optuna param deploy, rank-by-P(win), broker margin |

## 3. Components & boundaries

| Unit | Responsibility |
|---|---|
| `analytics/confidence_calibration.py` | Fit maps from learning outcomes; walk-forward accept/reject; write artifact |
| `backend/data/confidence_calibration.json` | Versioned deployed map(s) + metadata |
| `backend/services/confidence_calibrator.py` | Runtime load + `apply(raw_confidence, strategy) → (p_win, status)` |
| `recommendation_engine` | Rank by `score`; set `confidence` via calibrator after failure-memory; expose status |
| `learning_service` | Outcome store; after `record_outcome`, attempt refit; swap file only if walk-forward passes |
| `is_win(outcome, strategy)` | Pluggable label; v1 = `pnl > 0` |

## 4. Data flow

### 4.1 Fit

```
learning_store outcomes (non-seed)
  → is_win label
  → raw_x = raw_confidence_at_entry if present
           else min(0.95, score_at_entry + 0.05)
  → fit global map (n ≥ 30)
  → fit per-strategy maps where n_strategy ≥ 30
  → walk-forward validate
  → on pass: write confidence_calibration.json (deployed=true)
  → on fail: keep prior artifact (or none)
```

### 4.2 Recommend

```
gates → score
  → raw = min(0.95, score + 0.05)
  → raw_after = raw − 0.10 if failure-memory match (floor 0.05)
  → if usable map (strategy else global):
        confidence = P(win | raw_after); status = calibrated
    else:
        confidence = raw_after; status = uncalibrated
  → filter confidence ≥ min_recommendation_confidence (default 0.80)
  → sort by score; top-3
```

### 4.3 Persistence alignment

- On open trade: store `score`, `confidence` (post-calibrator value shown to operator), and **`raw_confidence_at_entry`** (pre-calibrator `raw_after`) so future fits train on the same scale the map is applied to.
- Legacy outcomes without `raw_confidence_at_entry`: reconstruct as `min(0.95, score_at_entry + 0.05)` (no failure penalty reconstruction).

## 5. Artifact schema

```json
{
  "version": 1,
  "deployed": true,
  "fitted_at": "ISO-8601",
  "walk_forward_ok": true,
  "walk_forward_metrics": {
    "brier_oos": 0.0,
    "brier_is": 0.0,
    "ece_oos": 0.0
  },
  "min_samples": 30,
  "global": {
    "n": 0,
    "x_knots": [],
    "p_win": []
  },
  "by_strategy": {
    "simple_volatility": { "n": 0, "x_knots": [], "p_win": [] }
  },
  "fit_notes": []
}
```

Runtime apply: piecewise-linear interpolate `raw_after` on `x_knots` → `p_win`; clamp to `[0.05, 0.95]`.

## 6. Walk-forward gate

- Sort outcomes by `closed_at`.
- **Global deploy gate:** train on first 70%; score last 30% (require ≥10 OOS points or skip deploy).
- Accept global deploy if: OOS Brier ≤ in-sample Brier + 0.05 **and** fitted mapping is monotone non-decreasing in `x`.
- **Per-strategy maps:** included in the artifact only when that strategy has ≥30 samples **and** either (a) its own OOS slice has ≥10 points and passes the same Brier+monotone rule, or (b) its OOS slice has &lt;10 points — then attach the in-sample strategy map only if global deploy already passed (thin OOS; rely on global gate).
- Failed first fit → no artifact (`uncalibrated`).
- Failed refit → retain previous deployed artifact.
- `ece_oos` is recorded for diagnostics; it is not an accept/reject criterion in v1.

## 7. API / insight surfaces

- `InstrumentRecommendation.calibration_status`: `calibrated` | `uncalibrated` (required)
- `InstrumentRecommendation.confidence_source`: `outcome_map` | `heuristic` (required)
- `LearningInsight` may mirror status for the overlay
- `analysis_notes` includes a one-liner when the cycle used uncalibrated confidence
- Status is `calibrated` whenever a usable map was applied (strategy-specific **or** global fallback)

## 8. Error handling

| Condition | Behavior |
|---|---|
| Missing/corrupt artifact | `uncalibrated` heuristic; cycle continues |
| Global n &lt; 30 | No deploy; heuristic |
| Strategy n &lt; 30 | Use global if deployed; else heuristic |
| Walk-forward fail | Do not overwrite good artifact |
| Refit exception | Log; leave prior artifact |

## 9. Tests

| Test | Asserts |
|---|---|
| `is_win` v1 | pnl &gt; 0 → win; else not; scratch excluded |
| Fit too-small | &lt;30 → no deploy |
| Fit happy path | Monotone synthetic → `walk_forward_ok` + global map |
| Hybrid grain | Strategy with ≥30 gets own map; others use global |
| Apply calibrated | Known knots → expected P(win) |
| Apply missing | Heuristic passthrough + `uncalibrated` |
| Seed exclusion | Seed outcomes not counted in fit `n` |
| Recommendation wiring | Floor uses calibrated confidence; sort by score; status on notes |
| Walk-forward fail | Prior artifact retained |

## 10. Out of scope

- Rebuilding full §10.4 confidence inputs (RAG ±0.15, regime +0.05, multi-module +0.10)
- Changing top-3 sort key to P(win)
- Optuna / full §12.5 parameter adaptation deploy pipeline (beyond this map’s walk-forward)
- Frontend redesign beyond consuming new fields when present
