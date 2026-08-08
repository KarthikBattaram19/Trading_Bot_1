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


def test_schema_rejects_typo_in_nested_change_entry() -> None:
    """A typo'd key inside changes[] must not validate silently."""
    schema = _load_json(METRICS_SCHEMA_PATH)
    record = {
        "session_date": "2026-08-10",
        "run_at": "2026-08-10T16:00:00+05:30",
        "head_sha": "abc1234",
        "session_traded": True,
        "real_closed_trades": 0,
        "changes": [{"shas": "abc1234", "subject": "x", "stage": "fill"}],
    }
    with pytest.raises(jsonschema.ValidationError):
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
