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

from scipy.optimize import minimize


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
    fitted: bool = False
    gamma_used: float | None = None
    alpha_used: float | None = None
    beta_used: float | None = None

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


def _sigma2_path(
    returns: Sequence[float],
    *,
    vl: float,
    gamma: float,
    alpha: float,
    beta: float,
) -> list[float]:
    """Recursive one-step-ahead variance path.

    ``path[i]`` is the forecast produced after observing ``returns[0..i]`` —
    i.e. it's the variance forecast *for* ``returns[i+1]``. Shared by the
    plain filter and the MLE fit objective so both walk the identical
    recursion.
    """
    sigma2 = vl
    path: list[float] = []
    for r in returns:
        prior_u2 = r * r
        prior_sigma2 = sigma2
        sigma2 = gamma * vl + alpha * prior_u2 + beta * prior_sigma2
        path.append(sigma2)
    return path


@dataclass(frozen=True, slots=True)
class FittedGarchWeights:
    """MLE-fit GARCH(1,1) weights for one symbol's return history."""

    gamma: float
    alpha: float
    beta: float


def _negative_log_likelihood(
    params: Sequence[float], cleaned: Sequence[float], vl: float
) -> float:
    alpha, beta = params
    gamma = 1.0 - alpha - beta
    path = _sigma2_path(cleaned, vl=vl, gamma=gamma, alpha=alpha, beta=beta)
    total = 0.0
    for sigma2_t, r_next in zip(path[:-1], cleaned[1:]):
        if sigma2_t <= 0 or math.isnan(sigma2_t) or math.isinf(sigma2_t):
            return math.inf
        total += math.log(sigma2_t) + (r_next * r_next) / sigma2_t
    return 0.5 * total


def fit_garch_11_mle(
    cleaned_returns: Sequence[float],
    vl: float,
    *,
    initial: tuple[float, float] = (0.05, 0.90),
) -> FittedGarchWeights | None:
    """MLE-fit (gamma, alpha, beta) to ``cleaned_returns`` via Gaussian log-likelihood.

    Returns ``None`` if the optimizer doesn't converge or the fitted weights
    produce a degenerate (non-positive/non-finite) variance path — caller
    decides what "fit failed" means (Task 3: fail-closed to distorted).
    """
    if vl <= 0 or len(cleaned_returns) < 2:
        return None

    eps = 1e-6
    bounds = [(eps, 1.0 - eps), (eps, 1.0 - eps)]
    constraints = [{"type": "ineq", "fun": lambda p: (1.0 - eps) - (p[0] + p[1])}]

    cleaned = list(cleaned_returns)
    result = minimize(
        _negative_log_likelihood,
        x0=list(initial),
        args=(cleaned, vl),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )
    if not result.success:
        return None

    alpha, beta = float(result.x[0]), float(result.x[1])
    gamma = 1.0 - alpha - beta
    if gamma <= 0 or alpha <= 0 or beta <= 0:
        return None

    path = _sigma2_path(cleaned, vl=vl, gamma=gamma, alpha=alpha, beta=beta)
    if any(s <= 0 or math.isnan(s) or math.isinf(s) for s in path):
        return None

    return FittedGarchWeights(gamma=gamma, alpha=alpha, beta=beta)


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
    fit_weights: bool = False,
    fit_min_observations: int = 60,
) -> GarchForecastResult:
    """Walk GARCH(1,1) through a log-return series; return one-step-ahead annualized vol.

    ``gap_detected`` (MD-10) forces ``garch_distorted`` so cheap-vol entries are blocked.

    ``fit_weights``: when True and ``n >= fit_min_observations``, fits
    (gamma, alpha, beta) per this return series via MLE instead of using the
    fixed ``gamma``/``alpha``/``beta`` arguments; a failed/non-converged fit
    forces ``garch_distorted`` (``reason="garch_fit_failed"``). Below
    ``fit_min_observations`` (but at/above ``min_observations``) the fixed
    weights are used, unchanged from today's behavior.
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

    # Long-run variance VL = mean-centered sample variance of log returns (H5)
    mean_r = sum(cleaned) / n
    vl = sum((r - mean_r) ** 2 for r in cleaned) / n
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

    fitted = False
    use_gamma, use_alpha, use_beta = gamma, alpha, beta
    if fit_weights and n >= fit_min_observations:
        fit = fit_garch_11_mle(cleaned, vl)
        if fit is None:
            return GarchForecastResult(
                sigma_daily=None,
                sigma_annual=None,
                vl=vl,
                prior_u2=None,
                prior_sigma2=None,
                forecast_sigma2=None,
                garch_distorted=True,
                insufficient_history=False,
                reason="garch_fit_failed",
                observations=n,
            )
        use_gamma, use_alpha, use_beta = fit.gamma, fit.alpha, fit.beta
        fitted = True

    # Walk the recursive variance path; last entry is today's forecast (H6–H8)
    path = _sigma2_path(cleaned, vl=vl, gamma=use_gamma, alpha=use_alpha, beta=use_beta)
    sigma2 = path[-1]
    prior_u2 = cleaned[-1] ** 2
    prior_sigma2 = path[-2] if len(path) > 1 else vl

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
        fitted=fitted,
        gamma_used=use_gamma,
        alpha_used=use_alpha,
        beta_used=use_beta,
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
