"""Config/schema lockstep for trading_parameters.defaults.json.

The scheduler cadence, enrichment budget, and coverage floors are sized
together against Breeze's rate envelope (~100 calls/min, ~5000/day). They are
no longer independently tunable numbers: the scan cap and eligible floor are
*derived* (backend/services/scan_capacity.py) and validated at boot, so this
file asserts the inputs, and test_scan_capacity.py asserts the arithmetic.
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


def test_enrichment_budget_inputs() -> None:
    cfg = _load(CONFIG_PATH)["recommendation_universe_enrichment"]
    assert cfg["generation_budget_sec"] == 120
    assert cfg["enrichment_budget_frac"] == 0.70
    # 6 = up to 2 spot-LTP fallbacks + 2 chain rights × 2 product_type retries;
    # mirrors universe_enrichment._spot_ltp / _fetch_option_chain_sides.
    assert cfg["breeze_calls_per_symbol"] == 6
    assert cfg["breeze_history_calls_per_symbol"] == 2
    assert cfg["breeze_daily_call_budget"] == 3500
    # No hand-tuned symbol cap: it is derived from these inputs.
    assert "max_symbols" not in cfg


def test_response_cache_outlives_scheduler_cadence() -> None:
    cfg = _load(CONFIG_PATH)
    ttl = cfg["recommendation_universe_enrichment"]["response_cache_ttl_sec"]
    cadence = cfg["scheduler"]["recommendation_cadence_sec"]
    assert ttl == 1200
    assert ttl > cadence + cfg["recommendation_universe_enrichment"]["generation_budget_sec"]


def test_coverage_ratio_is_the_strict_one() -> None:
    coverage = _load(CONFIG_PATH)["strategy_coverage"]
    assert coverage["min_coverage_ratio"] == 0.80
    assert coverage["min_scan_symbols"] == 10
    # The eligible floor is derived from the scan cap, never hardcoded here.
    assert "min_eligible_symbols" not in coverage


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
    # 900s, not 600s: 21 cycles/day keeps the derived scan inside the ~5000
    # calls/day Breeze envelope (see test_scan_capacity.py).
    assert sched["recommendation_cadence_sec"] == 900
    assert sched["flatten_retry_max"] == 30


def test_confidence_floor_has_no_bootstrap_phase() -> None:
    ec = _load(CONFIG_PATH)["execution_constraints"]
    assert ec["min_recommendation_confidence"] == 0.80
    assert "bootstrap_min_confidence" not in ec


def test_automation_tick_is_sixty_seconds() -> None:
    assert _load(CONFIG_PATH)["gamma_theta_breakeven"]["automation_tick_sec"] == 60


def test_gamma_scalping_calendar_construction_min_gap_days_present():
    from backend.services.strategy_selection import load_trading_config

    cfg = load_trading_config()
    gap = cfg["strategies"]["gamma_scalping"]["calendar_construction"]["long_expiry_min_gap_days"]
    assert gap == 28
