"""GARCH(1,1) annualized volatility forecast — Trading_Parameters Part H / VT-3–VT-4.

Formula: σ²_n = γ·VL + α·u²_(n-1) + β·σ²_(n-1)
Annualize: σ_annual = σ_daily × √252

Edge cases:
- Q-14 insufficient history → no cheap-vol (``garch_distorted`` / stand_aside)
- MD-10 OHLCV gaps / bad bars → ``garch_distorted``
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class GarchForecastResult:
    """One-step GARCH(1,1) forecast with distortion / sufficiency flags."""

    sigma_daily: float | None
    sigma_annual: float | None
    vl: float | None
    prior_u2: float | None
    prior_sigma2: float | None
    forecast_sigma2: float | None
    garch_distorted: bool
    insufficient_history: bool
    reason: str | None = None
    observations: int = 0

    @property
    def usable(self) -> bool:
        return (
            not self.garch_distorted
            and not self.insufficient_history
            and self.sigma_annual is not None
            and self.sigma_annual > 0
        )


def log_returns_from_prices(prices: Sequence[float]) -> list[float]:
    """Compute contiguous log returns; skip non-positive prices (caller should flag gaps)."""
    out: list[float] = []
    prev: float | None = None
    for p in prices:
        if p is None or p <= 0 or math.isnan(float(p)) or math.isinf(float(p)):
            prev = None
            continue
        px = float(p)
        if prev is not None and prev > 0:
            out.append(math.log(px / prev))
        prev = px
    return out


def garch_one_step(
    *,
    vl: float,
    prior_u2: float,
    prior_sigma2: float,
    gamma: float = 0.05,
    alpha: float = 0.05,
    beta: float = 0.90,
    annualization_factor: int = 252,
) -> GarchForecastResult:
    """Single forecast step from explicit components (VT-4 worked example)."""
    _assert_weights(gamma, alpha, beta)
    if vl < 0 or prior_u2 < 0 or prior_sigma2 < 0:
        return GarchForecastResult(
            sigma_daily=None,
            sigma_annual=None,
            vl=vl,
            prior_u2=prior_u2,
            prior_sigma2=prior_sigma2,
            forecast_sigma2=None,
            garch_distorted=True,
            insufficient_history=False,
            reason="negative_variance_component",
        )
    sigma2 = gamma * vl + alpha * prior_u2 + beta * prior_sigma2
    daily = math.sqrt(max(sigma2, 0.0))
    annual = daily * math.sqrt(float(annualization_factor))
    return GarchForecastResult(
        sigma_daily=daily,
        sigma_annual=annual,
        vl=vl,
        prior_u2=prior_u2,
        prior_sigma2=prior_sigma2,
        forecast_sigma2=sigma2,
        garch_distorted=False,
        insufficient_history=False,
        reason=None,
        observations=1,
    )


def forecast_garch_11(
    log_returns: Sequence[float],
    *,
    gamma: float = 0.05,
    alpha: float = 0.05,
    beta: float = 0.90,
    annualization_factor: int = 252,
    min_observations: int = 20,
    gap_detected: bool = False,
) -> GarchForecastResult:
    """Walk GARCH(1,1) through a log-return series; return one-step-ahead annualized vol.

    ``gap_detected`` (MD-10) forces ``garch_distorted`` so cheap-vol entries are blocked.
    """
    _assert_weights(gamma, alpha, beta)
    cleaned = [
        float(r)
        for r in log_returns
        if r is not None and not math.isnan(float(r)) and not math.isinf(float(r))
    ]
    n = len(cleaned)

    if gap_detected:
        return GarchForecastResult(
            sigma_daily=None,
            sigma_annual=None,
            vl=None,
            prior_u2=None,
            prior_sigma2=None,
            forecast_sigma2=None,
            garch_distorted=True,
            insufficient_history=False,
            reason="ohlcv_gap",
            observations=n,
        )

    if n < min_observations:
        return GarchForecastResult(
            sigma_daily=None,
            sigma_annual=None,
            vl=None,
            prior_u2=None,
            prior_sigma2=None,
            forecast_sigma2=None,
            garch_distorted=True,
            insufficient_history=True,
            reason="insufficient_history",
            observations=n,
        )

    # Long-run variance VL = sample variance of log returns (H5)
    vl = sum(r * r for r in cleaned) / n
    if vl <= 0:
        return GarchForecastResult(
            sigma_daily=None,
            sigma_annual=None,
            vl=vl,
            prior_u2=None,
            prior_sigma2=None,
            forecast_sigma2=None,
            garch_distorted=True,
            insufficient_history=False,
            reason="zero_sample_variance",
            observations=n,
        )

    # Initialize σ² with VL; iterate so last step is today's forecast (H6–H8)
    sigma2 = vl
    prior_u2 = cleaned[0] ** 2
    for r in cleaned:
        prior_u2 = r * r
        prior_sigma2 = sigma2
        sigma2 = gamma * vl + alpha * prior_u2 + beta * prior_sigma2

    daily = math.sqrt(max(sigma2, 0.0))
    annual = daily * math.sqrt(float(annualization_factor))
    return GarchForecastResult(
        sigma_daily=daily,
        sigma_annual=annual,
        vl=vl,
        prior_u2=prior_u2,
        prior_sigma2=prior_sigma2,
        forecast_sigma2=sigma2,
        garch_distorted=False,
        insufficient_history=False,
        reason=None,
        observations=n,
    )


def detect_price_gaps(
    prices: Sequence[float],
    *,
    max_return_abs: float = 0.25,
) -> bool:
    """Heuristic MD-10: non-positive bars or |log return| > ``max_return_abs`` ⇒ gap/shock."""
    prev: float | None = None
    for p in prices:
        if p is None or float(p) <= 0 or math.isnan(float(p)) or math.isinf(float(p)):
            return True
        px = float(p)
        if prev is not None and prev > 0:
            move = abs(math.log(px / prev))
            if move > max_return_abs:
                return True
        prev = px
    return False


def _assert_weights(gamma: float, alpha: float, beta: float) -> None:
    total = gamma + alpha + beta
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"GARCH weights must sum to 1.0 (H4); got γ+α+β={total}")
