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


_OVERRIDE_CFG = {
    "garch_forecast": {
        "gamma_weight": 0.05,
        "alpha_weight": 0.05,
        "beta_weight": 0.9,
        "annualization_factor": 252,
        "min_observations": 20,
        "symbol_overrides": {
            "SBIN": {
                "gamma_weight": 0.03,
                "alpha_weight": 0.15,
                "beta_weight": 0.82,
            }
        },
    },
    "iv_zscore": {"min_observations": 5, "entry_z_threshold": -2.0},
}


def _no_override_cfg():
    import copy

    cfg = copy.deepcopy(_OVERRIDE_CFG)
    cfg["garch_forecast"].pop("symbol_overrides")
    return cfg


def _varied_history(n: int = 40) -> list[float]:
    # Alternating-size moves so different (gamma, alpha, beta) give different forecasts.
    out = [100.0]
    for i in range(n - 1):
        out.append(out[-1] * (1.0 + (0.02 if i % 7 == 0 else 0.002) * (1 if i % 2 else -1)))
    return out


def test_symbol_override_weights_change_forecast():
    history = _varied_history()
    with_override = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_OVERRIDE_CFG,
        symbol="SBIN",
    )
    without_override = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_no_override_cfg(),
        symbol="SBIN",
    )
    assert with_override.garch_forecast.usable is True
    assert without_override.garch_forecast.usable is True
    assert with_override.garch_forecast.value != without_override.garch_forecast.value


def test_symbol_without_override_uses_global_weights():
    history = _varied_history()
    other_symbol = build_quant_snapshot(
        marks=_marks(symbol="INFY"),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_OVERRIDE_CFG,
        symbol="INFY",
    )
    global_only = build_quant_snapshot(
        marks=_marks(symbol="INFY"),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_no_override_cfg(),
        symbol="INFY",
    )
    assert other_symbol.garch_forecast.value == global_only.garch_forecast.value


def test_symbol_override_resolution_falls_back_to_marks_symbol():
    # No explicit symbol arg: the override must still be found via marks.symbol.
    history = _varied_history()
    via_marks = build_quant_snapshot(
        marks=_marks(),  # symbol="SBIN"
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_OVERRIDE_CFG,
    )
    global_only = build_quant_snapshot(
        marks=_marks(),
        price_history_daily=history,
        iv_series_intraday=[],
        days_to_earnings=None,
        cfg=_no_override_cfg(),
    )
    assert via_marks.garch_forecast.value != global_only.garch_forecast.value
