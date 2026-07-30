"""Intraday IV z-score — Trading_Parameters Part N4 / Vega scalping entry.

z = (IV − mean) / std
Entry when z ≤ −2.0; never short vol at +2σ (N4.5–N4.6).
Q-15: NaN / σ=0 → reject vega frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class IvZScoreResult:
    """Intraday IV mean-reversion signal components."""

    iv_z_score: float | None
    iv_intraday_mean: float | None
    iv_intraday_std: float | None
    current_iv: float | None
    reject_vega: bool
    stationarity_ok: bool
    reason: str | None = None
    observations: int = 0

    @property
    def usable(self) -> bool:
        return (
            not self.reject_vega
            and self.iv_z_score is not None
            and not math.isnan(self.iv_z_score)
        )


def compute_iv_zscore(
    intraday_iv_series: Sequence[float],
    *,
    current_iv: float | None = None,
    min_observations: int = 5,
    entry_z_threshold: float = -2.0,
) -> IvZScoreResult:
    """Compute (IV − mean) / std over an intraday IV series (N4.1–N4.4).

    When ``current_iv`` is omitted, the last point in the series is used.
    """
    cleaned = [
        float(v)
        for v in intraday_iv_series
        if v is not None and not math.isnan(float(v)) and not math.isinf(float(v)) and float(v) > 0
    ]
    n = len(cleaned)
    if n < min_observations:
        return IvZScoreResult(
            iv_z_score=None,
            iv_intraday_mean=None,
            iv_intraday_std=None,
            current_iv=current_iv,
            reject_vega=True,
            stationarity_ok=False,
            reason="insufficient_iv_history",
            observations=n,
        )

    iv = float(current_iv) if current_iv is not None else cleaned[-1]
    if iv <= 0 or math.isnan(iv) or math.isinf(iv):
        return IvZScoreResult(
            iv_z_score=None,
            iv_intraday_mean=None,
            iv_intraday_std=None,
            current_iv=iv,
            reject_vega=True,
            stationarity_ok=False,
            reason="invalid_current_iv",
            observations=n,
        )

    mean = sum(cleaned) / n
    var = sum((x - mean) ** 2 for x in cleaned) / n
    std = math.sqrt(var)

    # Q-15: σ=0 → reject vega
    if std <= 0 or math.isnan(std):
        return IvZScoreResult(
            iv_z_score=None,
            iv_intraday_mean=mean,
            iv_intraday_std=0.0,
            current_iv=iv,
            reject_vega=True,
            stationarity_ok=False,
            reason="zero_iv_std",
            observations=n,
        )

    z = (iv - mean) / std
    if math.isnan(z) or math.isinf(z):
        return IvZScoreResult(
            iv_z_score=None,
            iv_intraday_mean=mean,
            iv_intraday_std=std,
            current_iv=iv,
            reject_vega=True,
            stationarity_ok=False,
            reason="nan_zscore",
            observations=n,
        )

    # Crude stationarity: variance of first vs second half not wildly divergent
    mid = n // 2
    if mid >= 2 and n - mid >= 2:
        m1 = sum(cleaned[:mid]) / mid
        m2 = sum(cleaned[mid:]) / (n - mid)
        v1 = sum((x - m1) ** 2 for x in cleaned[:mid]) / mid
        v2 = sum((x - m2) ** 2 for x in cleaned[mid:]) / (n - mid)
        ratio = (max(v1, v2) / min(v1, v2)) if min(v1, v2) > 0 else float("inf")
        stationarity_ok = ratio < 25.0
    else:
        stationarity_ok = True

    reject = not stationarity_ok
    return IvZScoreResult(
        iv_z_score=z,
        iv_intraday_mean=mean,
        iv_intraday_std=std,
        current_iv=iv,
        reject_vega=reject,
        stationarity_ok=stationarity_ok,
        reason=None if stationarity_ok else "iv_stationarity_fail",
        observations=n,
    )


def vega_entry_signal(
    result: IvZScoreResult,
    *,
    entry_z_threshold: float = -2.0,
) -> bool:
    """True when long-vol vega scalp entry is allowed (z ≤ −2, usable)."""
    if not result.usable or result.iv_z_score is None:
        return False
    return result.iv_z_score <= entry_z_threshold
