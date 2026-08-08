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


def test_ledger_schema_rejects_non_iso_last_updated() -> None:
    """`last_updated`'s pattern is otherwise untested — the accepts-a-well-formed-record
    test above uses a valid `+05:30` offset either way, so it would pass even if the
    pattern constraint were deleted. This pins the rejection side."""
    schema = _load_json(LEDGER_SCHEMA_PATH)
    record = {
        "id": "rec-2026-08-08-guard-check",
        "proposed_date": "2026-08-08",
        "stage": "fill",
        "problem": "x",
        "proposed_change": "y",
        "expected_impact": {"metric": "performance.win_rate", "direction": "up"},
        "status": "proposed",
        "last_updated": "tomorrow",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=record, schema=schema)
