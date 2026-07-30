"""Phase 1.5 — IV z-score unit tests (Trading_Parameters Part N4 / Q-15)."""

from __future__ import annotations

from backend.quant.signals.iv_zscore import compute_iv_zscore, vega_entry_signal


def test_iv_zscore_entry_at_minus_two():
    mean = 0.30
    std = 0.02
    series = [mean - std, mean + std] * 15
    current = mean - 2.01 * std  # clearly ≤ −2 after float noise
    result = compute_iv_zscore(series, current_iv=current)
    assert result.usable
    assert result.iv_z_score is not None
    assert result.iv_z_score <= -2.0
    assert vega_entry_signal(result, entry_z_threshold=-2.0)


def test_q15_zero_std_rejects_vega():
    series = [0.25] * 20
    result = compute_iv_zscore(series, current_iv=0.25)
    assert result.reject_vega
    assert result.iv_z_score is None
    assert result.reason == "zero_iv_std"
    assert not vega_entry_signal(result)


def test_q15_insufficient_iv_history():
    result = compute_iv_zscore([0.2, 0.21], min_observations=5)
    assert result.reject_vega
    assert result.reason == "insufficient_iv_history"


def test_never_enter_on_positive_two_sigma():
    mean = 0.30
    std = 0.02
    series = [mean - std, mean + std] * 15
    current = mean + 2.0 * std
    result = compute_iv_zscore(series, current_iv=current)
    assert result.usable
    assert result.iv_z_score is not None and result.iv_z_score > 0
    assert not vega_entry_signal(result, entry_z_threshold=-2.0)
