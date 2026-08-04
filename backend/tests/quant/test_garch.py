"""Phase 1.5 — GARCH(1,1) unit tests (Trading_Strategies.md VT-4 / Part H)."""

from __future__ import annotations

import math
import random

import pytest

from backend.quant.signals.garch import (
    FittedGarchWeights,
    detect_price_gaps,
    fit_garch_11_mle,
    forecast_garch_11,
    garch_one_step,
    log_returns_from_prices,
)


def test_vt4_worked_example_annualized_vol():
    """Table VT-4: σ_annual ≈ 30.23% from source variance components."""
    # Source numbers are percent-variance (0.030753% → 0.00030753 as decimal variance)
    vl = 0.030753 / 100.0
    u2 = 0.036051 / 100.0
    sigma2_prev = 0.036595 / 100.0
    result = garch_one_step(vl=vl, prior_u2=u2, prior_sigma2=sigma2_prev)
    assert result.usable
    assert result.sigma_daily is not None
    assert result.sigma_annual is not None
    assert abs(result.sigma_daily - 0.019046) < 1e-5
    assert abs(result.sigma_annual - 0.3023) < 5e-4


def test_garch_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        forecast_garch_11([0.01, -0.01] * 20, gamma=0.1, alpha=0.1, beta=0.9)


def test_q14_insufficient_history_marks_distorted():
    result = forecast_garch_11([0.01, -0.005, 0.002], min_observations=20)
    assert result.insufficient_history
    assert result.garch_distorted
    assert not result.usable
    assert result.reason == "insufficient_history"


def test_md10_gap_blocks_garch():
    prices = [100.0, 101.0, 0.0, 102.0]  # non-positive bar
    assert detect_price_gaps(prices) is True
    returns = log_returns_from_prices(prices)
    result = forecast_garch_11(returns, min_observations=1, gap_detected=True)
    assert result.garch_distorted
    assert result.reason == "ohlcv_gap"


def test_forecast_from_price_history_usable():
    prices = [100 * (1 + 0.01 * math.sin(i / 4)) for i in range(80)]
    returns = log_returns_from_prices(prices)
    result = forecast_garch_11(returns, min_observations=20)
    assert result.usable
    assert result.sigma_annual is not None
    assert 0.01 < result.sigma_annual < 2.0


def test_vl_is_mean_centered_not_mean_of_squares():
    """§3.4 secondary issue: VL must be mean((r-r̄)²), not mean(r²), for drifting series."""
    # Constant positive drift: every return is 0.01, so r̄ = 0.01 and
    # mean-centered variance is exactly 0.0 -- but mean(r²) would be 0.0001.
    returns = [0.01] * 25
    result = forecast_garch_11(returns, min_observations=20)
    assert result.vl is not None
    assert result.vl == pytest.approx(0.0, abs=1e-12)


def _simulate_garch_returns(
    n: int, *, gamma: float, alpha: float, beta: float, vl: float, seed: int = 7
) -> list[float]:
    """Simulate a GARCH(1,1) return series from known weights (for fit-recovery tests)."""
    rng = random.Random(seed)
    sigma2 = vl
    returns: list[float] = []
    for _ in range(n):
        r = rng.gauss(0.0, math.sqrt(sigma2))
        returns.append(r)
        sigma2 = gamma * vl + alpha * (r * r) + beta * sigma2
    return returns


def test_fit_garch_11_mle_recovers_known_weights_approximately():
    true_gamma, true_alpha, true_beta = 0.10, 0.15, 0.75
    vl = 0.0002
    returns = _simulate_garch_returns(
        400, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl
    )
    fitted = fit_garch_11_mle(returns, vl)
    assert fitted is not None
    assert isinstance(fitted, FittedGarchWeights)
    assert abs((fitted.gamma + fitted.alpha + fitted.beta) - 1.0) < 1e-6
    # Loose tolerance: MLE on a single 400-point path is noisy, this only
    # asserts the fit lands in the right neighborhood, not exact recovery.
    assert abs(fitted.alpha - true_alpha) < 0.15
    assert abs(fitted.beta - true_beta) < 0.20


def test_fit_garch_11_mle_returns_none_on_degenerate_input():
    # All-zero returns: sigma2 path collapses toward 0, likelihood is degenerate.
    fitted = fit_garch_11_mle([0.0] * 100, vl=0.0)
    assert fitted is None


def test_below_fit_floor_uses_fixed_weights_not_distorted():
    """20 <= n < fit_min_observations: fixed weights, fitted=False, still usable."""
    returns = [0.01, -0.008, 0.005, -0.003] * 10  # n=40
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.usable
    assert result.fitted is False
    assert result.gamma_used == pytest.approx(0.05)
    assert result.alpha_used == pytest.approx(0.05)
    assert result.beta_used == pytest.approx(0.90)


def test_at_fit_floor_fits_and_marks_fitted():
    true_gamma, true_alpha, true_beta = 0.08, 0.12, 0.80
    vl = 0.0002
    returns = _simulate_garch_returns(
        90, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl, seed=11
    )
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.usable
    assert result.fitted is True
    assert result.gamma_used is not None
    assert abs(result.gamma_used + result.alpha_used + result.beta_used - 1.0) < 1e-6
    # Fit must actually move off the fixed defaults (0.05, 0.05, 0.90) —
    # catches a fit that silently no-ops back to the fixed weights.
    fixed_gamma, fixed_alpha, fixed_beta = 0.05, 0.05, 0.90
    tol = 1e-3
    assert (
        abs(result.gamma_used - fixed_gamma) > tol
        or abs(result.alpha_used - fixed_alpha) > tol
        or abs(result.beta_used - fixed_beta) > tol
    )


def test_below_tier_boundary_n59_uses_fixed_weights():
    """n = fit_min_observations - 1: still below the floor, must not fit."""
    true_gamma, true_alpha, true_beta = 0.08, 0.12, 0.80
    vl = 0.0002
    returns = _simulate_garch_returns(
        59, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl, seed=11
    )
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.fitted is False


def test_at_tier_boundary_n60_fits():
    """n = fit_min_observations exactly: the floor must be inclusive (n >= floor)."""
    true_gamma, true_alpha, true_beta = 0.08, 0.12, 0.80
    vl = 0.0002
    returns = _simulate_garch_returns(
        60, gamma=true_gamma, alpha=true_alpha, beta=true_beta, vl=vl, seed=11
    )
    result = forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.fitted is True


def test_fit_failure_forces_distorted(monkeypatch):
    import backend.quant.signals.garch as garch_module

    monkeypatch.setattr(garch_module, "fit_garch_11_mle", lambda *a, **k: None)
    returns = [0.01, -0.008, 0.005, -0.003] * 20  # n=80, above fit_min_observations
    result = garch_module.forecast_garch_11(
        returns, min_observations=20, fit_weights=True, fit_min_observations=60
    )
    assert result.garch_distorted is True
    assert result.usable is False
    assert result.reason == "garch_fit_failed"


def test_fit_weights_false_is_default_and_unaffected_by_fit_floor():
    """Backward compatibility: fit_weights defaults False, existing callers untouched."""
    returns = [0.01, -0.008, 0.005, -0.003] * 25  # n=100, would clear fit floor
    result = forecast_garch_11(returns, min_observations=20)
    assert result.usable
    assert result.fitted is False
