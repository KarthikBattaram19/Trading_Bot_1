"""Derived scan capacity — the gate arithmetic that used to fail silently.

Regression guard for the state that produced zero recommendations for weeks:
40 symbols × 5 paced Breeze calls × 700ms = 140s of work inside a 20s budget,
so `eligible/scanned` could never reach 0.80 of 20+ underlyings and no error
was ever raised. That configuration must now refuse to boot.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.services.scan_capacity import (
    UnsatisfiableScanConfig,
    scan_capacity,
    validate_scan_capacity,
)

CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "trading_parameters.defaults.json"
)


def _defaults() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cfg(**overrides) -> dict:
    cfg = {
        "recommendation_universe_enrichment": {
            "generation_budget_sec": 120,
            "enrichment_budget_frac": 0.70,
            "breeze_calls_per_symbol": 5,
            "breeze_history_calls_per_symbol": 2,
            "breeze_daily_call_budget": 3500,
            "min_interval_ms": 700,
            "response_cache_ttl_sec": 1200,
        },
        "strategy_coverage": {"min_coverage_ratio": 0.80, "min_scan_symbols": 10},
        "session_schedule": {"entry_start": "09:20", "entry_cutoff": "14:30"},
        "scheduler": {"recommendation_cadence_sec": 900},
    }
    for section, values in overrides.items():
        cfg[section] = {**cfg[section], **values}
    return cfg


def test_cap_is_what_the_paced_call_budget_can_actually_finish() -> None:
    cap = scan_capacity(_cfg())
    # 120s × 0.70 = 84s usable; 5 calls × 0.7s = 3.5s per symbol → 24.
    assert cap.enrichment_window_sec == pytest.approx(84.0)
    assert cap.max_symbols <= 84 // 3.5


def test_min_eligible_is_derived_from_the_cap_not_hardcoded() -> None:
    cap = scan_capacity(_cfg())
    assert cap.min_eligible_symbols == math.ceil(0.80 * cap.max_symbols)
    assert cap.min_eligible_symbols <= cap.max_symbols


def test_daily_envelope_can_bind_before_wall_clock() -> None:
    cap = scan_capacity(
        _cfg(recommendation_universe_enrichment={"breeze_daily_call_budget": 700})
    )
    assert cap.limited_by == "daily_envelope"
    assert cap.max_symbols < scan_capacity(_cfg()).max_symbols


def test_the_old_impossible_config_now_refuses_to_boot() -> None:
    """40 symbols in a 20s budget: the exact silent-failure state, pre-scaffold."""
    cfg = _cfg(
        recommendation_universe_enrichment={"generation_budget_sec": 20},
        strategy_coverage={"min_coverage_ratio": 0.80, "min_scan_symbols": 10},
    )
    assert scan_capacity(cfg).max_symbols < 10
    with pytest.raises(UnsatisfiableScanConfig, match="below the min_scan_symbols"):
        validate_scan_capacity(cfg)


def test_explicit_eligible_override_above_the_cap_is_rejected() -> None:
    cfg = _cfg(strategy_coverage={"min_coverage_ratio": 0.80, "min_eligible_symbols": 500})
    with pytest.raises(UnsatisfiableScanConfig, match="exceeds the derived scan cap"):
        validate_scan_capacity(cfg)


def test_cycles_over_the_vendor_daily_envelope_are_rejected() -> None:
    cfg = _cfg(
        recommendation_universe_enrichment={"breeze_daily_call_budget": 50_000},
        scheduler={"recommendation_cadence_sec": 60},
    )
    with pytest.raises(UnsatisfiableScanConfig, match="vendor envelope"):
        validate_scan_capacity(cfg)


def test_response_cache_must_outlive_a_cadence_plus_a_generation() -> None:
    cfg = _cfg(recommendation_universe_enrichment={"response_cache_ttl_sec": 90})
    with pytest.raises(UnsatisfiableScanConfig, match="response_cache_ttl_sec"):
        validate_scan_capacity(cfg)


def test_shipped_defaults_are_satisfiable() -> None:
    cap = validate_scan_capacity(_defaults())
    assert cap.max_symbols >= 10
    assert cap.min_eligible_symbols == math.ceil(
        cap.min_coverage_ratio * cap.max_symbols
    )
    assert cap.calls_per_day <= 5000


def test_no_hardcoded_scan_cap_survives_in_config() -> None:
    """The relaxation lever is gone: capacity is derived, not tuned."""
    enrich = _defaults()["recommendation_universe_enrichment"]
    coverage = _defaults()["strategy_coverage"]
    assert "max_symbols" not in enrich
    assert "min_eligible_symbols" not in coverage
    assert coverage["min_coverage_ratio"] == 0.80
