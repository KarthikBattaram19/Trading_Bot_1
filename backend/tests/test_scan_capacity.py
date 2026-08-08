"""Derived scan capacity — the gate arithmetic that used to fail silently.

Regression guard for the state that produced zero recommendations for weeks:
40 symbols × ~6 paced Breeze calls × 700ms ≈ 170s of work inside a 20s budget,
so `eligible/scanned` could never reach 0.80 of 20+ underlyings and no error
was ever raised. That configuration must now refuse to boot — and refuse
per-cycle too, since the config file is re-read from disk every cycle.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.services.scan_capacity import (
    DEFAULT_RECOMMENDATION_CADENCE_SEC,
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
            "breeze_calls_per_symbol": 6,
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
    # 120s × 0.70 = 84s enrichment; 6 calls × 0.7s = 4.2s per symbol → 20.
    assert cap.enrichment_window_sec == pytest.approx(84.0)
    assert cap.history_window_sec == pytest.approx(36.0)
    assert cap.max_symbols == 20


def test_min_eligible_is_derived_from_the_cap_not_hardcoded() -> None:
    cap = scan_capacity(_cfg())
    assert cap.min_eligible_symbols == math.ceil(0.80 * cap.max_symbols)
    assert cap.min_eligible_symbols <= cap.max_symbols


def test_history_window_can_bind_when_history_calls_dominate() -> None:
    cap = scan_capacity(
        _cfg(recommendation_universe_enrichment={"breeze_history_calls_per_symbol": 8})
    )
    # 36s / (8 × 0.7s) = 6 — history becomes the binding constraint.
    assert cap.limited_by == "history_window"
    assert cap.max_symbols == 6


def test_daily_envelope_can_bind_before_wall_clock() -> None:
    cap = scan_capacity(
        _cfg(recommendation_universe_enrichment={"breeze_daily_call_budget": 700})
    )
    assert cap.limited_by == "daily_envelope"
    assert cap.max_symbols < scan_capacity(_cfg()).max_symbols


def test_the_old_impossible_config_now_refuses_to_boot() -> None:
    """40 symbols in a 20s budget: the exact silent-failure state, pre-scaffold."""
    cfg = _cfg(recommendation_universe_enrichment={"generation_budget_sec": 20})
    assert scan_capacity(cfg).max_symbols < 10
    with pytest.raises(UnsatisfiableScanConfig, match="below the min_scan_symbols"):
        validate_scan_capacity(cfg)


def test_min_eligible_override_is_rejected_in_any_direction() -> None:
    """The key must not exist at all — a low value is a silent loosening lever
    (a truncated 5-symbol scan publishing on 4/5), a high one a stealth
    tightening; both classes of drift are what derivation removes."""
    for value in (1, 500):
        cfg = _cfg(strategy_coverage={"min_eligible_symbols": value})
        with pytest.raises(UnsatisfiableScanConfig, match="no longer a config key"):
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


def test_missing_ttl_key_is_validated_at_the_engine_fallback_not_zero() -> None:
    """The validator must reason about the TTL the engine would actually use
    (90s fallback in recommendation_engine._response_cache_ttl_sec)."""
    cfg = _cfg()
    del cfg["recommendation_universe_enrichment"]["response_cache_ttl_sec"]
    with pytest.raises(UnsatisfiableScanConfig, match="response_cache_ttl_sec=90"):
        validate_scan_capacity(cfg)


def test_malformed_session_time_is_a_named_config_error_not_a_traceback() -> None:
    cfg = _cfg(session_schedule={"entry_start": "0920"})
    with pytest.raises(UnsatisfiableScanConfig, match="session_schedule.entry_start"):
        validate_scan_capacity(cfg)


def test_scheduler_fallback_cadence_matches_the_capacity_model() -> None:
    """If these fallbacks diverged, boot validation would certify a daily call
    budget for a cadence the scheduler doesn't actually run (the pre-review
    state: scheduler fell back to 600s while the model assumed 900s)."""
    from backend.services import trading_scheduler

    assert (
        trading_scheduler._load_scheduler_config()["recommendation_cadence_sec"]
        == DEFAULT_RECOMMENDATION_CADENCE_SEC
        == 900.0
    )
    cfg = _cfg()
    del cfg["scheduler"]
    assert scan_capacity(cfg).cycles_per_day == scan_capacity(_cfg()).cycles_per_day


def test_history_calls_are_actually_paced() -> None:
    """The capacity model's history arithmetic assumes 700ms spacing; that is
    only honest if candle_history routes through the shared pacer."""
    import inspect

    from backend.services import candle_history
    from backend.services.breeze_pacing import history_pacer

    assert candle_history.history_pacer is history_pacer
    assert history_pacer._min_interval == pytest.approx(0.7)
    for fn in (candle_history.fetch_daily_closes, candle_history.fetch_realized_vol_intraday):
        assert "history_pacer.acquire" in inspect.getsource(fn)


def test_shipped_defaults_are_satisfiable() -> None:
    cap = validate_scan_capacity(_defaults())
    assert cap.max_symbols == 20
    assert cap.min_eligible_symbols == 16
    assert cap.calls_per_day == 3360
    assert cap.calls_per_day <= 5000


def test_no_hardcoded_scan_cap_survives_in_config() -> None:
    """The relaxation levers are gone: capacity is derived, not tuned."""
    enrich = _defaults()["recommendation_universe_enrichment"]
    coverage = _defaults()["strategy_coverage"]
    assert "max_symbols" not in enrich
    assert "min_eligible_symbols" not in coverage
    assert coverage["min_coverage_ratio"] == 0.80
