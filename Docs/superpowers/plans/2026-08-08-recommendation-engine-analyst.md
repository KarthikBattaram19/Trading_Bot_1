# Recommendation Engine Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only subagent that reviews the recommendation→paper-trade pipeline daily, tracks every recommendation from proposal to measured outcome, and publishes a pipeline-ordered HTML dashboard of performance, reliability, stability and P&L.

**Architecture:** The agent itself is a prompt file (`.claude/agents/recommendation-engine-analyst.md`); its durability comes from four git-tracked state files under `Docs/bot_health/`. Two of those are append-only JSONL, so they get real JSON Schemas and a pytest that validates every line — that is the only executable code this plan produces, and it is what stops the agent from silently corrupting its own history. Everything else is prose contract plus a scheduled routine that invokes the agent at 16:00 IST.

**Tech Stack:** Markdown agent definition, JSON Schema + `jsonschema` (already in `backend/requirements-dev.txt`), pytest, Claude Code scheduled routines, self-contained HTML/SVG for the dashboard.

**Spec:** `Docs/superpowers/specs/2026-08-08-recommendation-engine-analyst-agent-design.md`

## Global Constraints

- **Write scope.** The agent may write ONLY these five paths. Any other path — anything under `backend/`, `frontend/`, `.cursor/` — is out of bounds:
  - `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`
  - `Docs/bot_health/recommendation_metrics.jsonl`
  - `Docs/bot_health/recommendation_ledger.jsonl`
  - `Docs/bot_health/DAILY_JOURNAL.md`
  - `Docs/bot_health/dashboard.html` (dashboard source it publishes)
- **No `Edit` tool.** The agent's `tools:` frontmatter grants `Read, Grep, Glob, Bash, Write, Artifact` — never `Edit`. It cannot modify an existing source file even by mistake.
- **Seed exclusion.** Any `learning_store.json` record with `"seed": true`, or a `trade_id`/`outcome_id` matching `trd_seed_*`, is excluded from every metric. Currently ALL 3 outcomes and 1 open trade are seeds — real trade count is 0.
- **Maturity gate.** Below ~30 real closed trades per module (`architecture.md` §21), P&L numbers are reported as provisional/directional only. The agent must never characterize the vol edge as validated absent OOS walk-forward evidence (`.cursor/rules/must-fix-before-claiming-performance.mdc`).
- **Coverage relaxations are a test scaffold, never "settled".** `max_symbols=15`, `generation_budget_sec=90`, `min_coverage_ratio=0.60`, `min_eligible_symbols=6`, `response_cache_ttl_sec=900` were allowed only to test the 2026-08-10 first trade. After that date the agent treats each as an open question needing a reasoned position, and must never call them owner-approved defaults.
- **Dashboard privacy.** Published as a **private** Artifact. It holds the owner's trading performance data. Never share the URL beyond the repo owner; never present results as validated or externally endorsed.
- **Pipeline stage vocabulary** — use these exact seven strings everywhere (schemas, dashboard sections, ledger `stage` field):
  `signals`, `feature_assembly`, `strategy_selection`, `ranking_gating`, `execution_gates`, `fill`, `feedback`
- **Timezone.** All dates are IST (`Asia/Kolkata`). Dates in JSONL are `YYYY-MM-DD` session dates, timestamps are ISO-8601 with `+05:30` offset.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/schemas/recommendation_metrics.schema.json` | Shape of one daily metrics row |
| `backend/schemas/recommendation_ledger.schema.json` | Shape of one recommendation lifecycle record |
| `backend/tests/test_recommendation_analyst_state.py` | Validates every JSONL line in both files against its schema |
| `Docs/bot_health/recommendation_metrics.jsonl` | Append-only daily metrics history |
| `Docs/bot_health/recommendation_ledger.jsonl` | Append-only recommendation lifecycle store (agent memory) |
| `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md` | Narrative review, rewritten each run |
| `Docs/bot_health/DAILY_JOURNAL.md` | Append-only daily action/change record |
| `Docs/bot_health/dashboard.html` | Dashboard source, republished each run |
| `.claude/agents/recommendation-engine-analyst.md` | The agent definition |

Schemas live in `backend/schemas/` beside the existing `trading_parameters.schema.json` so the existing pytest run picks up their test without new config. State files live in `Docs/bot_health/` beside Guruji's `STATE.md`/`BACKLOG.md`.

---

### Task 1: Metrics record schema and validation test

**Files:**
- Create: `backend/schemas/recommendation_metrics.schema.json`
- Create: `backend/tests/test_recommendation_analyst_state.py`
- Create: `Docs/bot_health/recommendation_metrics.jsonl`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `METRICS_SCHEMA_PATH` / `METRICS_PATH` constants and `_iter_jsonl(path)` helper in `backend/tests/test_recommendation_analyst_state.py`, reused by Task 2. The seven stage strings become an enum reused by Task 2's `stage` field.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_recommendation_analyst_state.py`:

```python
"""Schema lockstep for the recommendation-engine-analyst's state files.

The analyst agent appends to Docs/bot_health/*.jsonl on every run. These
files are its memory across runs and the sole input to its dashboard, so a
malformed line silently corrupts trend and impact analysis. This test is the
guard: every line in every state file must validate against its schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMAS = _ROOT / "backend" / "schemas"
_STATE = _ROOT / "Docs" / "bot_health"

METRICS_SCHEMA_PATH = _SCHEMAS / "recommendation_metrics.schema.json"
METRICS_PATH = _STATE / "recommendation_metrics.jsonl"

PIPELINE_STAGES = [
    "signals",
    "feature_assembly",
    "strategy_selection",
    "ranking_gating",
    "execution_gates",
    "fill",
    "feedback",
]


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_jsonl(path: Path):
    """Yield (line_number, parsed_object) for each non-blank line."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            if not raw.strip():
                continue
            try:
                yield lineno, json.loads(raw)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{path.name}:{lineno} is not valid JSON: {exc}")


def test_metrics_schema_is_itself_valid() -> None:
    schema = _load_json(METRICS_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_metrics_schema_stage_enum_matches_canonical_stages() -> None:
    schema = _load_json(METRICS_SCHEMA_PATH)
    funnel = schema["properties"]["reliability"]["properties"]["stage_funnel"]
    assert funnel["propertyNames"]["enum"] == PIPELINE_STAGES


def test_every_metrics_line_validates() -> None:
    schema = _load_json(METRICS_SCHEMA_PATH)
    for lineno, record in _iter_jsonl(METRICS_PATH):
        try:
            jsonschema.validate(instance=record, schema=schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(f"{METRICS_PATH.name}:{lineno} failed schema: {exc.message}")


def test_metrics_session_dates_are_unique_and_ordered() -> None:
    dates = [r["session_date"] for _, r in _iter_jsonl(METRICS_PATH)]
    assert len(dates) == len(set(dates)), "duplicate session_date rows corrupt trend charts"
    assert dates == sorted(dates), "metrics history must be append-only in date order"


def test_schema_rejects_extra_key_in_nested_change_entry() -> None:
    """An otherwise-valid changes[] entry with one extra key must be rejected.

    The fixture keeps every required key so the only thing that can fail it is
    additionalProperties: false — a fixture that dropped 'sha' would fail on
    'required' instead and pass even with the guard reverted.
    """
    schema = _load_json(METRICS_SCHEMA_PATH)
    record = {
        "session_date": "2026-08-10",
        "run_at": "2026-08-10T16:00:00+05:30",
        "head_sha": "abc1234",
        "session_traded": True,
        "real_closed_trades": 0,
        "changes": [
            {"sha": "abc1234", "subject": "x", "stage": "fill", "shas": "typo"}
        ],
    }
    with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
        jsonschema.validate(instance=record, schema=schema)


def test_schema_rejects_extra_key_in_calibration_bucket() -> None:
    """Same guard, calibration_buckets[] side — previously untested entirely."""
    schema = _load_json(METRICS_SCHEMA_PATH)
    record = {
        "session_date": "2026-08-10",
        "run_at": "2026-08-10T16:00:00+05:30",
        "head_sha": "abc1234",
        "session_traded": True,
        "real_closed_trades": 0,
        "stability": {
            "calibration_buckets": [
                {"bucket": "0.7-0.8", "predicted": 0.75, "realized": 0.5, "n": 2, "oops": 1}
            ]
        },
    }
    with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
        jsonschema.validate(instance=record, schema=schema)


def test_schema_rejects_non_iso_run_at() -> None:
    schema = _load_json(METRICS_SCHEMA_PATH)
    record = {
        "session_date": "2026-08-10",
        "run_at": "tomorrow",
        "head_sha": "abc1234",
        "session_traded": True,
        "real_closed_trades": 0,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=record, schema=schema)


def test_schema_accepts_a_well_formed_row() -> None:
    """Guards against over-tightening: a valid row must still pass."""
    schema = _load_json(METRICS_SCHEMA_PATH)
    record = {
        "session_date": "2026-08-10",
        "run_at": "2026-08-10T16:00:00+05:30",
        "head_sha": "abc1234",
        "session_traded": True,
        "real_closed_trades": 0,
        "changes": [{"sha": "abc1234", "subject": "x", "stage": "fill", "files": ["a.py"]}],
        "stability": {
            "calibration_buckets": [
                {"bucket": "0.7-0.8", "predicted": 0.75, "realized": 0.5, "n": 2}
            ]
        },
    }
    jsonschema.validate(instance=record, schema=schema)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: FAIL — `FileNotFoundError` on `recommendation_metrics.schema.json`.

- [ ] **Step 3: Write the schema**

Create `backend/schemas/recommendation_metrics.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Recommendation engine daily metrics row",
  "type": "object",
  "required": ["session_date", "run_at", "head_sha", "session_traded", "real_closed_trades"],
  "additionalProperties": false,
  "properties": {
    "session_date": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
    "run_at": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}([.]\\d+)?[+-]\\d{2}:\\d{2}$" },
    "head_sha": { "type": "string", "minLength": 7 },
    "session_traded": {
      "type": "boolean",
      "description": "false on non-trading days; downstream trend charts skip these rows"
    },
    "no_session_reason": { "type": ["string", "null"] },
    "real_closed_trades": { "type": "integer", "minimum": 0 },
    "test_result": { "type": ["string", "null"] },
    "performance": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "session_pnl_inr": { "type": ["number", "null"] },
        "cumulative_pnl_inr": { "type": ["number", "null"] },
        "equity_inr": { "type": ["number", "null"] },
        "win_rate": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
        "avg_win_inr": { "type": ["number", "null"] },
        "avg_loss_inr": { "type": ["number", "null"] },
        "profit_factor": { "type": ["number", "null"] },
        "max_drawdown_inr": { "type": ["number", "null"] },
        "pnl_by_strategy": { "type": "object", "additionalProperties": { "type": "number" } },
        "pnl_by_underlying": { "type": "object", "additionalProperties": { "type": "number" } }
      }
    },
    "reliability": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "cycles_attempted": { "type": "integer", "minimum": 0 },
        "cycles_completed": { "type": "integer", "minimum": 0 },
        "coverage_aborts": { "type": "integer", "minimum": 0 },
        "coverage_abort_reasons": { "type": "object", "additionalProperties": { "type": "integer" } },
        "enrichment_attempted": { "type": "integer", "minimum": 0 },
        "enrichment_usable": { "type": "integer", "minimum": 0 },
        "spot_fetch_failures": { "type": "integer", "minimum": 0 },
        "chain_fetch_failures": { "type": "integer", "minimum": 0 },
        "flatten_complete": { "type": ["boolean", "null"] },
        "stage_funnel": {
          "type": "object",
          "description": "candidates surviving each pipeline stage, in canonical order",
          "propertyNames": {
            "enum": [
              "signals",
              "feature_assembly",
              "strategy_selection",
              "ranking_gating",
              "execution_gates",
              "fill",
              "feedback"
            ]
          },
          "additionalProperties": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "stability": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "pnl_variance": { "type": ["number", "null"] },
        "calibration_error": {
          "type": ["number", "null"],
          "description": "mean |predicted confidence - realized win rate| across buckets"
        },
        "calibration_buckets": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["bucket", "predicted", "realized", "n"],
            "additionalProperties": false,
            "properties": {
              "bucket": { "type": "string" },
              "predicted": { "type": "number" },
              "realized": { "type": "number" },
              "n": { "type": "integer", "minimum": 0 }
            }
          }
        },
        "strategy_mix": { "type": "object", "additionalProperties": { "type": "integer" } },
        "config_drift": { "type": "array", "items": { "type": "string" } }
      }
    },
    "changes": {
      "type": "array",
      "description": "in-scope commits landed since the previous run",
      "items": {
        "type": "object",
        "required": ["sha", "subject", "stage"],
        "additionalProperties": false,
        "properties": {
          "sha": { "type": "string", "minLength": 7 },
          "subject": { "type": "string" },
          "stage": {
            "enum": [
              "signals",
              "feature_assembly",
              "strategy_selection",
              "ranking_gating",
              "execution_gates",
              "fill",
              "feedback"
            ]
          },
          "files": { "type": "array", "items": { "type": "string" } }
        }
      }
    }
  }
}
```

- [ ] **Step 4: Create the empty history file**

An empty file is a valid append-only history with zero rows — the tests iterate zero lines and pass.

```bash
: > Docs/bot_health/recommendation_metrics.jsonl
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 6: Add a fixture row and confirm the schema actually bites**

Verify the schema rejects a bad row (do NOT commit this row):

```bash
echo '{"session_date":"2026-08-10","run_at":"2026-08-10T16:00:00+05:30","head_sha":"abc1234","session_traded":true,"real_closed_trades":1,"bogus_field":1}' >> Docs/bot_health/recommendation_metrics.jsonl
pytest backend/tests/test_recommendation_analyst_state.py::test_every_metrics_line_validates -q
```
Expected: FAIL, message naming `bogus_field`. Then revert:
```bash
: > Docs/bot_health/recommendation_metrics.jsonl
```
Re-run the file's tests — expected PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/schemas/recommendation_metrics.schema.json backend/tests/test_recommendation_analyst_state.py Docs/bot_health/recommendation_metrics.jsonl
git commit -m "Add metrics schema + JSONL validation for analyst agent state"
```

---

### Task 2: Recommendation ledger schema and validation

**Files:**
- Create: `backend/schemas/recommendation_ledger.schema.json`
- Modify: `backend/tests/test_recommendation_analyst_state.py` (append to the file created in Task 1)
- Create: `Docs/bot_health/recommendation_ledger.jsonl`

**Interfaces:**
- Consumes: `_load_json`, `_iter_jsonl`, `PIPELINE_STAGES`, `_SCHEMAS`, `_STATE` from Task 1's test module.
- Produces: the ledger record shape that Task 4's agent prompt writes and Task 5's dashboard reads. Field names here are contractual — the agent prompt must use them verbatim.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_recommendation_analyst_state.py`:

```python
LEDGER_SCHEMA_PATH = _SCHEMAS / "recommendation_ledger.schema.json"
LEDGER_PATH = _STATE / "recommendation_ledger.jsonl"

"""Statuses that assert the change actually landed, so a SHA and a frozen
pre-change baseline must exist. 'rejected'/'superseded' are excluded — those
close a recommendation without ever implementing it."""
LANDED_STATUSES = {"implemented", "measured", "validated", "regressed", "inconclusive"}


def test_ledger_schema_is_itself_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(_load_json(LEDGER_SCHEMA_PATH))


def test_ledger_schema_stage_enum_matches_canonical_stages() -> None:
    schema = _load_json(LEDGER_SCHEMA_PATH)
    assert schema["properties"]["stage"]["enum"] == PIPELINE_STAGES


def test_every_ledger_line_validates() -> None:
    schema = _load_json(LEDGER_SCHEMA_PATH)
    for lineno, record in _iter_jsonl(LEDGER_PATH):
        try:
            jsonschema.validate(instance=record, schema=schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(f"{LEDGER_PATH.name}:{lineno} failed schema: {exc.message}")


def test_ledger_ids_are_unique() -> None:
    ids = [r["id"] for _, r in _iter_jsonl(LEDGER_PATH)]
    assert len(ids) == len(set(ids)), "each recommendation must appear once; update in place, do not re-append"


def test_implemented_records_carry_sha_and_baseline() -> None:
    """A record can only claim measurable impact if we froze the 'before' state."""
    for lineno, record in _iter_jsonl(LEDGER_PATH):
        if record["status"] in LANDED_STATUSES:
            assert record.get("implemented_sha"), f"{LEDGER_PATH.name}:{lineno} implemented without a SHA"
            assert record.get("baseline_metrics") is not None, (
                f"{LEDGER_PATH.name}:{lineno} implemented without frozen baseline_metrics — "
                "impact for this recommendation is unmeasurable"
            )


def test_verdicts_state_their_sample_size() -> None:
    """Guards the spec's honesty constraint: no verdict without a stated n."""
    for lineno, record in _iter_jsonl(LEDGER_PATH):
        if record["status"] in {"validated", "regressed"}:
            effect = record.get("observed_effect") or {}
            assert isinstance(effect.get("sample_size"), int), (
                f"{LEDGER_PATH.name}:{lineno} claims '{record['status']}' with no sample_size"
            )


def test_ledger_schema_rejects_extra_key_in_expected_impact() -> None:
    schema = _load_json(LEDGER_SCHEMA_PATH)
    record = {
        "id": "rec-2026-08-08-guard-check",
        "proposed_date": "2026-08-08",
        "stage": "fill",
        "problem": "x",
        "proposed_change": "y",
        "expected_impact": {"metric": "performance.win_rate", "direction": "up", "oops": 1},
        "status": "proposed",
    }
    with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
        jsonschema.validate(instance=record, schema=schema)


def test_ledger_schema_accepts_a_well_formed_record() -> None:
    """Guards against over-tightening: a full valid record must still pass."""
    schema = _load_json(LEDGER_SCHEMA_PATH)
    record = {
        "id": "rec-2026-08-08-spot-code-fallback",
        "proposed_date": "2026-08-08",
        "stage": "feature_assembly",
        "problem": "spot LTP sends display symbol",
        "evidence": ["backend/services/universe_enrichment.py:609"],
        "proposed_change": "pass resolved stock_code",
        "expected_impact": {"metric": "reliability.enrichment_usable", "direction": "up", "rationale": "z"},
        "effort": "low",
        "status": "validated",
        "implemented_date": "2026-08-09",
        "implemented_sha": "abc1234",
        "match_confidence": "high",
        "baseline_metrics": {"reliability": {"enrichment_usable": 6}},
        "observed_effect": {"metric_before": 6, "metric_after": 12, "sample_size": 40, "sessions_observed": 3},
        "verdict": "did what it should",
        "last_updated": "2026-08-09T16:00:00+05:30",
        "notes": ["n"],
    }
    jsonschema.validate(instance=record, schema=schema)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: FAIL — `FileNotFoundError` on `recommendation_ledger.schema.json`.

- [ ] **Step 3: Write the schema**

Create `backend/schemas/recommendation_ledger.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Recommendation lifecycle record",
  "type": "object",
  "required": ["id", "proposed_date", "stage", "problem", "proposed_change", "expected_impact", "status"],
  "additionalProperties": false,
  "properties": {
    "id": {
      "type": "string",
      "pattern": "^rec-\\d{4}-\\d{2}-\\d{2}-[a-z0-9-]+$",
      "description": "stable slug, e.g. rec-2026-08-08-spot-code-fallback"
    },
    "proposed_date": { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
    "stage": {
      "enum": [
        "signals",
        "feature_assembly",
        "strategy_selection",
        "ranking_gating",
        "execution_gates",
        "fill",
        "feedback"
      ]
    },
    "problem": { "type": "string", "minLength": 1 },
    "evidence": {
      "type": "array",
      "items": { "type": "string", "description": "file:line citation" }
    },
    "proposed_change": { "type": "string", "minLength": 1 },
    "expected_impact": {
      "type": "object",
      "required": ["metric", "direction"],
      "additionalProperties": false,
      "properties": {
        "metric": { "type": "string", "description": "dotted path into a metrics row, e.g. reliability.enrichment_usable" },
        "direction": { "enum": ["up", "down"] },
        "rationale": { "type": "string" }
      }
    },
    "effort": { "enum": ["low", "medium", "high"] },
    "status": {
      "enum": [
        "proposed",
        "implemented",
        "measured",
        "validated",
        "regressed",
        "inconclusive",
        "rejected",
        "superseded"
      ]
    },
    "implemented_date": { "type": ["string", "null"] },
    "implemented_sha": { "type": ["string", "null"] },
    "match_confidence": {
      "enum": ["high", "medium", "low", null],
      "description": "confidence that implemented_sha really implements this recommendation"
    },
    "baseline_metrics": {
      "type": ["object", "null"],
      "description": "metric snapshot frozen immediately before implementation"
    },
    "observed_effect": {
      "type": ["object", "null"],
      "required": ["metric_before", "metric_after", "sample_size"],
      "additionalProperties": false,
      "properties": {
        "metric_before": { "type": ["number", "null"] },
        "metric_after": { "type": ["number", "null"] },
        "sample_size": { "type": "integer", "minimum": 0 },
        "sessions_observed": { "type": "integer", "minimum": 0 }
      }
    },
    "verdict": { "type": ["string", "null"] },
    "last_updated": { "type": "string" },
    "notes": { "type": "array", "items": { "type": "string" } }
  }
}
```

- [ ] **Step 4: Create the empty ledger**

```bash
: > Docs/bot_health/recommendation_ledger.jsonl
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: PASS — 10 passed.

- [ ] **Step 6: Confirm the honesty guards bite**

Append a record claiming a verdict with no sample size (do NOT commit):

```bash
echo '{"id":"rec-2026-08-08-test-guard","proposed_date":"2026-08-08","stage":"fill","problem":"x","proposed_change":"y","expected_impact":{"metric":"performance.win_rate","direction":"up"},"status":"validated","implemented_sha":"abc1234","baseline_metrics":{},"last_updated":"2026-08-08T16:00:00+05:30"}' >> Docs/bot_health/recommendation_ledger.jsonl
pytest backend/tests/test_recommendation_analyst_state.py::test_verdicts_state_their_sample_size -q
```
Expected: FAIL with "claims 'validated' with no sample_size". Then revert:
```bash
: > Docs/bot_health/recommendation_ledger.jsonl
```
Re-run the file's tests — expected PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/schemas/recommendation_ledger.schema.json backend/tests/test_recommendation_analyst_state.py Docs/bot_health/recommendation_ledger.jsonl
git commit -m "Add recommendation lifecycle ledger schema with honesty guards"
```

---

### Task 3: Seed the narrative state files

**Files:**
- Create: `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`
- Create: `Docs/bot_health/DAILY_JOURNAL.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the exact section headings the agent prompt (Task 4) rewrites and appends to. Heading text is contractual — the agent locates its insertion points by these strings.

- [ ] **Step 1: Create the review doc skeleton**

Create `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`:

```markdown
# Recommendation Engine — Analyst Review

Maintained by the `recommendation-engine-analyst` agent. Rewritten in full on
every run except the Findings and Change ledger sections, which are append-only.

Scope: the signal → strategy selection → ranking/gating → execution gates →
paper_sim fill → learning feedback path. Repo-wide health (P0–P2 backlog, CI,
safety invariants) belongs to `Guruji_for_Bhale_Bullodu` — see `BACKLOG.md`.

## Run header

Last reviewed commit: _(none yet — first run pending)_
Last reviewed at: _(none yet)_
Real (non-seed) closed trades: 0
Last test result: _(none yet)_

## Pipeline map

_Rewritten each run from the current code. Empty until the first run._

## Findings

_Append-only. Resolved findings are checked off with `resolved <date>,
evidence: <file:line>` and never deleted._

## Change ledger

_Append-only. In-scope commits since the previous review, paired with the
metric deltas observed after they landed._

## Trend notes

_How the numbers moved since the previous run. Empty until two runs exist._
```

- [ ] **Step 2: Create the journal skeleton**

Create `Docs/bot_health/DAILY_JOURNAL.md`:

```markdown
# Recommendation Engine — Daily Journal

Append-only record of what the bot did and what changed, newest entry first.
Written by the `recommendation-engine-analyst` agent after each session.

Entry format — the agent inserts each new `## <YYYY-MM-DD>` section directly
below the `<!-- ENTRIES BELOW -->` marker at the bottom of this preamble, so the
newest entry is always first and this format spec always stays above them:

- **Session summary** — cycles run, recommendations published, trades
  opened/closed, session P&L.
- **Decisions** — every decision the bot made and why (strategy, confidence,
  gates passed/failed).
- **Changes landed** — in-scope commits that day, with SHA and pipeline stage.
- **Recommendations implemented** — pulled from `recommendation_ledger.jsonl`,
  with SHA and current measurement status.
- **Recommended today** — new recommendations, plus running status of all open
  prior ones.

<!-- ENTRIES BELOW -->
```

- [ ] **Step 3: Verify the full suite still passes**

Run: `pytest -q -m "not integration"`
Expected: PASS, count ≥ 355 (the Task 1–2 tests add 10 to the prior baseline).

- [ ] **Step 4: Commit**

```bash
git add Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md Docs/bot_health/DAILY_JOURNAL.md
git commit -m "Seed analyst narrative state files"
```

---

### Task 4: Write the agent definition

**Files:**
- Create: `.claude/agents/recommendation-engine-analyst.md`

**Interfaces:**
- Consumes: the schemas from Tasks 1–2 (field names are contractual), the heading strings from Task 3.
- Produces: an agent invocable as `subagent_type: "recommendation-engine-analyst"`, referenced by Task 6's scheduled routine.

- [ ] **Step 1: Write the agent file**

Create `.claude/agents/recommendation-engine-analyst.md`:

```markdown
---
name: recommendation-engine-analyst
description: Use when asked about recommendation quality, strategy selection, confidence calibration, paper-trade performance, P&L, why the engine isn't trading well, or for the daily post-market review. Analyzes the signal → strategy → gating → paper_sim fill → learning path and tracks whether past recommendations actually helped. For repo-wide health (P0-P2 backlog, CI, safety invariants) use Guruji_for_Bhale_Bullodu instead.
tools: Read, Grep, Glob, Bash, Write, Artifact
---

# Recommendation Engine Analyst

## Objective

Drive this bot toward being consistently profitable, reliable and stable — and
prove it with measurement rather than assertion. Every run answers: what did the
recommendation engine do, what did it earn or lose, and what single change would
most improve tomorrow.

**Honesty constraint.** "High profit" is the destination, not a claim you may
make on the way there. Report observed numbers and call them provisional until
there is OOS walk-forward evidence and a real sample. An agent that flatters this
bot is worse than no agent, because it destroys the signal the owner relies on.

## Hard rules

**Write scope — you may write ONLY these five paths:**
- `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`
- `Docs/bot_health/recommendation_metrics.jsonl`
- `Docs/bot_health/recommendation_ledger.jsonl`
- `Docs/bot_health/DAILY_JOURNAL.md`
- `Docs/bot_health/dashboard.html`

Never write anywhere else. Never modify `backend/`, `frontend/`, `.cursor/`, or
any config. You propose changes; a human applies them. This separation is
load-bearing: an agent that could both tune a threshold and grade the result
would be marking its own homework on a system where the grade is money.

**Seed exclusion.** Exclude every `learning_store.json` record with
`"seed": true` or an id matching `trd_seed_*` from all metrics. As of
2026-08-08 that is all 4 records — real trade count is 0.

**Maturity gate.** Below ~30 real closed trades per module, P&L is directional
only. Never call the vol edge validated without OOS walk-forward evidence
(`.cursor/rules/must-fix-before-claiming-performance.mdc`).

**Coverage relaxations are a test scaffold.** `max_symbols=15`,
`generation_budget_sec=90`, `min_coverage_ratio=0.60`, `min_eligible_symbols=6`,
`response_cache_ttl_sec=900` were allowed only to test whether a paper trade
lands on 2026-08-10. Past that date, treat each as an open question and give a
reasoned position each run. Never describe them as settled or owner-approved.
Note the trap: if a trade lands *because* the gate was loosened, that is evidence
the loop works end-to-end — not evidence the gate was too tight. Keep those two
conclusions separate.

**Pipeline stages** — use these exact strings everywhere:
`signals`, `feature_assembly`, `strategy_selection`, `ranking_gating`,
`execution_gates`, `fill`, `feedback`

## Scope

| Stage | Files |
|---|---|
| `signals` | `backend/quant/signals/{garch,iv_zscore}.py`, `backend/quant/{pricing,risk,costs,gamma,analytics}/` |
| `feature_assembly` | `backend/services/{quant_snapshot,signals,universe_enrichment,atm_liquidity,atm_liquidity_history,iv_history_store,candle_history,earnings_calendar,market_news}.py` |
| `strategy_selection` | `backend/services/{strategy_selection,strategy_coverage}.py` |
| `ranking_gating` | `backend/services/{recommendation_engine,recommendation_cycle,confidence_calibrator,confidence_floor}.py` |
| `execution_gates` | `backend/execution/{risk_gate,circuit_breakers,options_only,broker_router}.py`, `backend/services/trade_executor.py` |
| `fill` | `backend/paper_sim/*.py` |
| `feedback` | `backend/services/learning_service.py`, `backend/analytics/confidence_calibration.py` |
| trigger | `backend/services/{trading_scheduler,market_session}.py` |

Out of scope: CI, deploy, frontend, Breeze vendor mechanics, `knowledge/`. If you
hit a finding in Guruji's territory, note it in one line and move on.

## Process

**1. Model the pipeline as-built.** Read the in-scope files. Describe each
stage: what it consumes, emits, and what makes it drop a candidate. Never trust
a docstring's claim about behavior — read the code path.

**2. Read the evidence.**
- `backend/data/learning_store.json` — `outcomes`, `open_trades`, minus seeds.
- `backend/data/{atm_liquidity_history,iv_history,daily_price_history}.json` for
  feed coverage and staleness.
- The deployed backend's read-only endpoints if reachable:
  `/api/v1/learning/dashboard`, `/api/v1/paper-sim/positions|account`,
  `/api/v1/decisions`, `/api/v1/risk/snapshot`, `/api/v1/scheduler/status`.
- `pytest backend/tests/ -q -m "not integration"` — a newly failing
  recommendation-path test is itself a finding.

You may run read-only Bash: `git log`, `git diff`, `pytest`, `python` for
reading JSON. Never run anything that mutates repo or broker state.

**3. Compare against spec.** Cross-reference `Docs/Trading_Strategies.md`
(SH-4 table), `Docs/Trading_Parameters.md`, and
`backend/config/trading_parameters.defaults.json` against actual behavior.

**4. Compute metrics.** Build one row conforming exactly to
`backend/schemas/recommendation_metrics.schema.json` and append it to
`Docs/bot_health/recommendation_metrics.jsonl`. On a non-trading day set
`session_traded: false` with a `no_session_reason` and omit the metric objects —
never write a row of zeros, it would corrupt the trend series.

Metric families:
- **Performance:** session and cumulative P&L, equity, win rate, avg win/loss,
  profit factor, max drawdown, P&L by strategy and underlying.
- **Reliability:** cycles attempted/completed, coverage aborts and reason mix,
  enrichment usable/attempted, spot and chain fetch failures, flatten completion,
  and the `stage_funnel` — candidates surviving each pipeline stage.
- **Stability:** P&L variance, calibration error (predicted confidence vs
  realized win rate, bucketed), strategy mix, config drift since last run.

**5. Attribute change.** `git log <last_sha>..HEAD` for in-scope files. Record
each commit in the row's `changes` array, tagged to its pipeline stage.

Attribution is correlational — label it so. State sample size beside every
attribution claim. Below a usable sample, report the change and the metric
movement together without asserting causation. Lean on the asymmetry:
reliability metrics are hundreds of events per day and reach usable samples fast;
P&L is one trade a day and will not for a long time.

**6. Reconcile the ledger.** For each `proposed` record in
`recommendation_ledger.jsonl`, check whether a commit since the last run touches
the files/symbols it named. On a match: set `status: implemented`, stamp
`implemented_sha`/`implemented_date`, set `match_confidence`, and freeze the
previous metrics row as `baseline_metrics`. Detection is a heuristic — always
state confidence so a wrong link is correctable rather than silently poisoning
impact measurement.

For `implemented` records, track the `expected_impact.metric` forward; move to
`measured`, then to `validated`/`regressed`/`inconclusive` once the sample
supports it. **A record that moved the wrong way is `regressed` and gets raised
prominently — never quietly dropped.** Apply the same sample-size rigor to
positive verdicts as negative ones.

Update records **in place** (rewrite the file), one line per `id`. Never append a
duplicate id.

**7. Write outputs.** Review doc, journal entry, dashboard (below), and a chat
summary: what changed, headline metrics, recommendations implemented since last
run and their measured effect, top open findings, dashboard URL, and one "next
best action" — the single highest-leverage open item.

## Dashboard

Write `Docs/bot_health/dashboard.html`, then publish it with the `Artifact` tool
as a **private** artifact. Reuse the same file path every run so it redeploys to
the same URL. Favicon: `📊`. Keep it stable across runs.

Before writing it, load the `artifact-design` skill; load `dataviz` before
writing any chart code. Charts are inline SVG — the artifact CSP blocks all
external resources, so no CDN libraries.

**Organizing principle: the pipeline.** Lay events and changes out in the order a
candidate flows through the engine, so the failure location is obvious at a
glance. Sections, in order:

1. **Headline strip** — session P&L, cumulative P&L, real closed trades, win
   rate, cycles completed; each with its delta vs the previous session.
2. **Pipeline walkthrough** — the seven stages in sequence. Per stage: the
   funnel (candidates in/out), this session's events, changes that landed there,
   and open recommendations targeting it.
3. **Impact** — the ledger as a timeline: proposed → implemented (with SHA) →
   measured, each with its target metric plotted before/after the implementation
   date and a verdict badge. **Regressions at the top of this section.**
4. **Optimization** — ranked open recommendations with expected metric movement;
   the largest funnel drop-offs; parameters still pinned to test-scaffold values
   with the case for revisiting each.
5. **Progress** — equity curve with commit markers; win rate and profit factor
   trends; reliability trends; calibration plot against the diagonal; rolling
   P&L variance; and cumulative counts of recommendations validated vs regressed
   vs open. Those three counts are headline numbers: a ledger where everything
   quietly passes should look suspicious at a glance.
6. **Journal excerpt** — the latest entry, linking to the full file.

**Degrade honestly at low sample size.** An equity curve with two points is drawn
as two points, never smoothed into a trend line. Panels without enough data say
so rather than rendering an empty axis. A Progress section implying a trend from
three points would actively mislead the decision it exists to inform.

## Common mistakes

- Counting seed records. All 4 current `learning_store.json` records are seeds.
- Asserting a commit caused a P&L move at n=1. State the n; let it speak.
- Calling the coverage relaxations settled because a trade got through.
- Marking your own recommendation `validated` on thinner evidence than you would
  demand for `regressed`.
- Rewriting the Findings section instead of appending — resolution history is
  part of the value.
- Duplicating Guruji's P0–P2 checklist instead of going deep on quant quality.
```

- [ ] **Step 2: Verify the agent is registered**

Run: `claude --debug 2>&1 | grep -i "recommendation-engine-analyst" | head -3`

If that surface is unavailable, confirm by inspection instead: the file exists at
`.claude/agents/recommendation-engine-analyst.md`, its frontmatter parses as YAML
with `name`, `description`, and `tools` keys, and `name` matches the filename
stem exactly.

Expected: the agent name appears, or all four inspection conditions hold.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/recommendation-engine-analyst.md
git commit -m "Add recommendation-engine-analyst agent definition"
```

---

### Task 5: First real run and output verification

**Files:**
- Modify (by the agent, not by hand): all five state files.

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: the first metrics row and the first dashboard URL, which Task 6's scheduled routine then continues appending to.

This task verifies the contract end-to-end. It is the first time anything checks
that the agent's prose instructions actually produce schema-valid output — a
plan that shipped without it would be asserting, not verifying.

- [ ] **Step 1: Invoke the agent**

Use the Agent tool with `subagent_type: "recommendation-engine-analyst"` and this
prompt:

```
Perform your first full review of the recommendation engine. There are no prior
runs, so seed all state files rather than diffing: use the repo's first commit as
the baseline for the change ledger, or simply note "first run — no baseline" and
skip change attribution entirely. Publish the dashboard and report back.
```

- [ ] **Step 2: Validate the agent's output against the schemas**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: PASS. A failure here means the agent wrote a malformed record — fix the
agent's prompt wording for the offending field, do not hand-edit the JSONL to
make the test pass.

- [ ] **Step 3: Verify write scope was respected**

Run: `git status --short`
Expected: modified paths are ONLY the five allowed files. Any change under
`backend/`, `frontend/`, or `.cursor/` is a scope violation — revert it and
tighten the "Hard rules" section of the agent file before re-running.

- [ ] **Step 4: Verify the dashboard**

Open the published Artifact URL. Confirm:
- All six sections render in order, pipeline stages in canonical sequence.
- With zero real trades, the P&L panels say so explicitly rather than drawing an
  empty or misleading axis.
- The page renders correctly in both light and dark theme.
- No horizontal scroll on the page body.

- [ ] **Step 5: Verify the honesty constraints held**

Read the chat summary and `RECOMMENDATION_ENGINE_REVIEW.md`. Confirm the agent:
- Reported 0 real closed trades and did not count the 4 seed records.
- Made no claim that the edge is validated or the bot is profitable.
- Treated the coverage relaxations as open questions, not settled defaults.

If any of these failed, that is a prompt bug — fix the agent file and re-run.

- [ ] **Step 6: Commit the first run's state**

```bash
git add Docs/bot_health/
git commit -m "First recommendation-engine-analyst run: seed metrics, review, journal"
```

---

### Task 6: Daily scheduled routine

**Files:**
- Create: a scheduled routine (created via the `schedule` skill, stored in Claude Code's routine config — not a repo file).

**Interfaces:**
- Consumes: the agent from Task 4, verified working in Task 5.
- Produces: nothing other tasks depend on. This is the last task.

- [ ] **Step 1: Create the routine**

Invoke the `schedule` skill to create a routine with:

- **Schedule:** `0 16 * * 1-5` in `Asia/Kolkata` — 16:00 IST, Monday–Friday, 30
  minutes after the 15:30 flatten window so the session's trades are settled.
- **Prompt:**

```
Run the recommendation-engine-analyst agent for today's post-market review.

First check whether NSE traded today. This repo has no holiday calendar, so a
weekday is not proof of a session: confirm via the backend's scheduler status
and whether any cycles ran. If there was no session, write a short "no session"
journal entry, append a metrics row with session_traded=false and a
no_session_reason, and stop — do not compute metrics or republish the dashboard.

If there was a session, run the full process: metrics, change attribution,
ledger reconciliation, review doc, journal entry, and republish the dashboard.
Also check for missing dates since the last metrics row and note any gaps — a
silent scheduler failure would otherwise leave an invisible hole in the trends.

You are running in the cloud without the owner's .env or live Breeze
credentials. Read committed state and the deployed backend's read-only
endpoints only. Never depend on a live broker session.
```

- [ ] **Step 2: Verify the routine is registered**

Run the `schedule` skill's list action.
Expected: the routine appears with the `0 16 * * 1-5` schedule and `Asia/Kolkata`
timezone.

- [ ] **Step 3: Trigger a manual test run**

Trigger the routine once manually via the `schedule` skill rather than waiting
for 16:00.

Expected: it completes, and `git status` shows changes confined to the five
allowed paths. If it ran on a non-trading day, expect a `session_traded: false`
row and no dashboard republish.

- [ ] **Step 4: Validate the scheduled run's output**

Run: `pytest backend/tests/test_recommendation_analyst_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Docs/bot_health/
git commit -m "Verify scheduled analyst routine end-to-end"
```

---

### Task 7: Cross-reference from project docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md`

**Interfaces:**
- Consumes: the agent name from Task 4.
- Produces: nothing.

Without this, a future session finds Guruji and never learns the analyst exists —
and the two would duplicate each other's work.

- [ ] **Step 1: Add a section to CLAUDE.md**

Insert directly above the `## Priority backlog` section:

```markdown
## Recommendation engine review

The `recommendation-engine-analyst` agent (`.claude/agents/`) owns depth on the
signal → strategy → gating → `paper_sim` fill → learning path: metrics, P&L,
and whether past recommendations actually helped. It runs daily at 16:00 IST and
on demand, is read-only with respect to trading code, and keeps its state in
`Docs/bot_health/{RECOMMENDATION_ENGINE_REVIEW.md,DAILY_JOURNAL.md,recommendation_metrics.jsonl,recommendation_ledger.jsonl}`.

Use it for "how is the engine performing / why isn't it trading well". Use
`Guruji_for_Bhale_Bullodu` for repo-wide health (P0–P2 backlog, CI, safety
invariants). They are complements — don't run one expecting the other's output.
```

- [ ] **Step 2: Add the pointer to Guruji's SKILL.md**

In the `## Quick reference` table, add a final row:

```markdown
| How is the recommendation engine performing? | The `recommendation-engine-analyst` agent — `Docs/bot_health/RECOMMENDATION_ENGINE_REVIEW.md`. Don't duplicate its quant/P&L analysis here. |
```

- [ ] **Step 3: Verify the full suite still passes**

Run: `pytest -q -m "not integration"`
Expected: PASS, no regressions.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude/skills/Guruji_for_Bhale_Bullodu/SKILL.md
git commit -m "Cross-reference analyst agent from CLAUDE.md and Guruji"
```

---

## Notes on what this plan does not build

- **Backtesting / OOS walk-forward replay.** The agent reads existing evidence.
  Building replay is the separate open P1 item.
- **Autonomous tuning.** The agent never adjusts a threshold. Deliberate — see
  the write-scope rationale in Task 4.
- **NSE holiday calendar.** Still absent repo-wide. Task 6's routine works around
  it by checking whether cycles actually ran rather than trusting the weekday.
- **A profitability guarantee.** This builds the instrument that measures
  progress. It cannot make an edge exist where none is proven.
