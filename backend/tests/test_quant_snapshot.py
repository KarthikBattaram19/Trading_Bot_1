"""Unit tests for QuantSnapshot builder — no synthetic GARCH/flat history."""

from __future__ import annotations

import math

from backend.services.quant_snapshot import (
    SignalField,
    build_quant_snapshot,
)
from backend.services.universe_enrichment import LiveMarks


def _marks(**overrides) -> LiveMarks:
    base = dict(
        symbol="SBIN",
        und_price=800.0,
        atm_premium_inr=95.0,
        volume=22000,
        open_interest=35000,
        spread_pct=0.4,
        dte=20,
        iv_annualized=0.27,
        atm_strike=800.0,
        expiry="28-Mar-2026",
        stock_code="STABAN",
    )
    base.update(overrides)
    return LiveMarks(**base)


def test_flat_spot_history_marks_garch_unusable():
    history = [800.0] * 5
    snap = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg={
            "garch_forecast": {
                "gamma_weight": 0.05,
                "alpha_weight": 0.05,
                "beta_weight": 0.9,
                "annualization_factor": 252,
                "min_observations": 20,
            },
            "iv_zscore": {"min_observations": 5, "entry_z_threshold": -2.0},
        },
    )
    assert snap.garch_forecast.usable is False
    assert snap.garch_distorted is True
    # Must not invent 0.28 as a trusted forecast
    if snap.garch_forecast.value is not None:
        assert not math.isclose(snap.garch_forecast.value, 0.28) or not snap.garch_forecast.usable


def test_real_history_yields_usable_garch():
    # Mildly varying closes so log-returns exist and length >= 20 prices → >=19 returns;
    # need 21 prices for 20 returns.
    history = [100.0 * (1.0 + 0.001 * ((i % 5) - 2)) for i in range(40)]
    snap = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[0.25, 0.26, 0.24, 0.23, 0.22, 0.21],
        days_to_earnings=5,
        cfg={
            "garch_forecast": {
                "gamma_weight": 0.05,
                "alpha_weight": 0.05,
                "beta_weight": 0.9,
                "annualization_factor": 252,
                "min_observations": 20,
            },
            "iv_zscore": {"min_observations": 5, "entry_z_threshold": -2.0},
        },
    )
    assert snap.marks_live is True
    assert snap.garch_forecast.usable is True
    assert snap.iv_z_score.usable is True
    assert snap.days_to_earnings.usable is True
    assert snap.days_to_earnings.value == 5


def test_enable_mle_fit_true_wires_through_to_forecast():
    """cfg["garch_forecast"]["enable_mle_fit"]/"fit_min_observations" must reach
    forecast_garch_11's fit_weights/fit_min_observations params — a typo in
    either config key would otherwise silently disable the feature with all
    other tests still green."""
    history = [100.0 * (1.0 + 0.001 * ((i % 5) - 2)) for i in range(65)]
    snap = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[0.25, 0.26, 0.24, 0.23, 0.22, 0.21],
        days_to_earnings=5,
        cfg={
            "garch_forecast": {
                "gamma_weight": 0.05,
                "alpha_weight": 0.05,
                "beta_weight": 0.9,
                "annualization_factor": 252,
                "min_observations": 20,
                "enable_mle_fit": True,
                "fit_min_observations": 60,
            },
            "iv_zscore": {"min_observations": 5, "entry_z_threshold": -2.0},
        },
    )
    assert snap.garch_forecast.usable is True


def test_enable_mle_fit_false_still_usable_via_fixed_weights():
    history = [100.0 * (1.0 + 0.001 * ((i % 5) - 2)) for i in range(65)]
    snap = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[0.25, 0.26, 0.24, 0.23, 0.22, 0.21],
        days_to_earnings=5,
        cfg={
            "garch_forecast": {
                "gamma_weight": 0.05,
                "alpha_weight": 0.05,
                "beta_weight": 0.9,
                "annualization_factor": 252,
                "min_observations": 20,
                "enable_mle_fit": False,
                "fit_min_observations": 60,
            },
            "iv_zscore": {"min_observations": 5, "entry_z_threshold": -2.0},
        },
    )
    assert snap.garch_forecast.usable is True


def test_signal_field_defaults():
    f = SignalField(value=None, usable=False, reason="missing")
    assert f.usable is False
    assert f.reason == "missing"
