"""Phase 1.5 — GARCH(1,1) unit tests (Trading_Strategies.md VT-4 / Part H)."""

from __future__ import annotations

import math

import pytest

from backend.quant.signals.garch import (
    detect_price_gaps,
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
