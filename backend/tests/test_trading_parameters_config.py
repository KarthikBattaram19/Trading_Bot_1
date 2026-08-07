"""Config/schema lockstep for trading_parameters.defaults.json.

The Monday-readiness numbers here are load-bearing: the scheduler cadence,
enrichment budget, and coverage floors were sized together against Breeze's
rate envelope (~100 calls/min, 5000/day). If you change one, re-check the
arithmetic in Docs/MONDAY_RUNBOOK.md before shipping.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = _ROOT / "config" / "trading_parameters.defaults.json"
SCHEMA_PATH = _ROOT / "schemas" / "trading_parameters.schema.json"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_defaults_validate_against_schema() -> None:
    jsonschema.validate(instance=_load(CONFIG_PATH), schema=_load(SCHEMA_PATH))


def test_enrichment_budget_fits_symbol_count() -> None:
    cfg = _load(CONFIG_PATH)["recommendation_universe_enrichment"]
    assert cfg["max_symbols"] == 15
    assert cfg["generation_budget_sec"] == 90
    # ~5 Breeze calls per symbol at min_interval_ms spacing must fit the budget.
    per_symbol_calls = 5
    spacing_sec = cfg["min_interval_ms"] / 1000.0
    assert cfg["max_symbols"] * per_symbol_calls * spacing_sec <= cfg["generation_budget_sec"]


def test_response_cache_outlives_scheduler_cadence() -> None:
    cfg = _load(CONFIG_PATH)
    ttl = cfg["recommendation_universe_enrichment"]["response_cache_ttl_sec"]
    cadence = cfg["scheduler"]["recommendation_cadence_sec"]
    assert ttl == 900
    assert ttl > cadence + cfg["recommendation_universe_enrichment"]["generation_budget_sec"]


def test_coverage_floors_are_satisfiable_within_scan_cap() -> None:
    cfg = _load(CONFIG_PATH)
    coverage = cfg["strategy_coverage"]
    max_symbols = cfg["recommendation_universe_enrichment"]["max_symbols"]
    assert coverage["min_coverage_ratio"] == 0.60
    assert coverage["min_eligible_symbols"] == 6
    assert coverage["min_eligible_symbols"] <= max_symbols
    assert coverage["min_coverage_ratio"] * max_symbols <= max_symbols


def test_session_schedule_section() -> None:
    sched = _load(CONFIG_PATH)["session_schedule"]
    assert sched == {
        "market_open": "09:15",
        "entry_start": "09:20",
        "entry_cutoff": "14:30",
        "flatten_start": "15:15",
        "market_close": "15:30",
    }


def test_scheduler_section() -> None:
    sched = _load(CONFIG_PATH)["scheduler"]
    assert sched["enabled"] is True
    assert sched["tick_sec"] == 30
    assert sched["recommendation_cadence_sec"] == 600
    assert sched["flatten_retry_max"] == 30


def test_bootstrap_confidence_floor_keys() -> None:
    ec = _load(CONFIG_PATH)["execution_constraints"]
    assert ec["min_recommendation_confidence"] == 0.80
    assert ec["bootstrap_min_confidence"] == 0.70


def test_automation_tick_is_sixty_seconds() -> None:
    assert _load(CONFIG_PATH)["gamma_theta_breakeven"]["automation_tick_sec"] == 60


def test_gamma_scalping_calendar_construction_min_gap_days_present():
    from backend.services.strategy_selection import load_trading_config

    cfg = load_trading_config()
    gap = cfg["strategies"]["gamma_scalping"]["calendar_construction"]["long_expiry_min_gap_days"]
    assert gap == 28
