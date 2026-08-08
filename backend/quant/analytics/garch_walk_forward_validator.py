"""Walk-forward evidence: does MLE-fit GARCH(1,1) forecast next-day realized
variance better than the fixed-weight fallback? Pure functions, no I/O.

Improve_Recoemmendation_Engine.md §3.4 / Docs/bot_health/BACKLOG.md P1 — this
is evidence for the forecast itself (not a P&L replay, which needs closed
trades and is a separate, blocked backlog item).

Method: roll a trailing window forward one trading day at a time. At each
step, both the fixed-weight and MLE-fit GARCH(1,1) forecast next-day
variance from the same trailing window; each is scored against the actually
realized next-day squared log return via QLIKE (the standard robust loss for
comparing variance forecasts) and squared error. QLIKE mirrors the shape of
the MLE fit's own likelihood, so a fit that wins on QLIKE is winning on the
terms it was optimized for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from backend.quant.signals.garch import forecast_garch_11


@dataclass(frozen=True, slots=True)
class WalkForwardEvent:
    """One walk-forward step: forecasts made from a trailing window, scored
    against the realized squared return of the day immediately after it."""

    index: int
    realized_r2: float
    fixed_sigma2: float | None
    fixed_qlike: float | None
    fitted_usable: bool
    fitted_reason: str | None
    fitted_sigma2: float | None
    fitted_qlike: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    """Aggregate evidence for one symbol (or a combined pseudo-symbol)."""

    symbol: str
    n_events: int
    n_fit_usable: int
    fit_usable_rate: float | None
    mean_qlike_fixed: float | None
    mean_qlike_fitted: float | None
    mean_mse_fixed: float | None
    mean_mse_fitted: float | None
    fitted_win_rate: float | None
    insufficient_sample: bool


def _qlike(sigma2: float | None, r2: float) -> float | None:
    """QLIKE loss: ln(sigma2) + r2/sigma2. Lower is better. None if sigma2 invalid."""
    if sigma2 is None or sigma2 <= 0 or math.isnan(sigma2) or math.isinf(sigma2):
        return None
    return math.log(sigma2) + r2 / sigma2


def run_walk_forward(
    log_returns: Sequence[float],
    *,
    window: int = 250,
    fit_min_observations: int = 60,
) -> list[WalkForwardEvent]:
    """Roll a `window`-observation trailing window forward one day at a time.

    Each step forecasts the variance of `log_returns[t]` from
    `log_returns[t-window:t]` via both the fixed-weight and MLE-fit GARCH(1,1)
    paths, and records both forecasts' loss against the realized outcome.
    """
    returns = list(log_returns)
    n = len(returns)
    events: list[WalkForwardEvent] = []
    for t in range(window, n):
        trailing = returns[t - window : t]
        realized_r2 = returns[t] ** 2

        fixed = forecast_garch_11(trailing, fit_weights=False)
        fixed_sigma2 = fixed.forecast_sigma2 if fixed.usable else None

        fitted = forecast_garch_11(
            trailing, fit_weights=True, fit_min_observations=fit_min_observations
        )
        fitted_sigma2 = fitted.forecast_sigma2 if fitted.usable else None

        events.append(
            WalkForwardEvent(
                index=t,
                realized_r2=realized_r2,
                fixed_sigma2=fixed_sigma2,
                fixed_qlike=_qlike(fixed_sigma2, realized_r2),
                fitted_usable=fitted.usable,
                fitted_reason=fitted.reason,
                fitted_sigma2=fitted_sigma2,
                fitted_qlike=_qlike(fitted_sigma2, realized_r2),
            )
        )
    return events


def summarize_walk_forward(
    *,
    symbol: str,
    events: Sequence[WalkForwardEvent],
    min_events: int = 100,
) -> WalkForwardSummary:
    """Aggregate one symbol's walk-forward events into headline evidence stats."""
    n = len(events)
    fixed_qlikes = [e.fixed_qlike for e in events if e.fixed_qlike is not None]
    fixed_mses = [
        (e.fixed_sigma2 - e.realized_r2) ** 2 for e in events if e.fixed_sigma2 is not None
    ]

    fit_usable_events = [e for e in events if e.fitted_usable and e.fitted_qlike is not None]
    n_fit_usable = len(fit_usable_events)
    fitted_qlikes = [e.fitted_qlike for e in fit_usable_events]
    fitted_mses = [(e.fitted_sigma2 - e.realized_r2) ** 2 for e in fit_usable_events]

    # Win rate only over events where both forecasts are usable and comparable.
    paired = [e for e in fit_usable_events if e.fixed_qlike is not None]
    wins = sum(1 for e in paired if e.fitted_qlike < e.fixed_qlike)  # type: ignore[operator]

    return WalkForwardSummary(
        symbol=symbol,
        n_events=n,
        n_fit_usable=n_fit_usable,
        fit_usable_rate=(n_fit_usable / n) if n else None,
        mean_qlike_fixed=(sum(fixed_qlikes) / len(fixed_qlikes)) if fixed_qlikes else None,
        mean_qlike_fitted=(sum(fitted_qlikes) / len(fitted_qlikes)) if fitted_qlikes else None,
        mean_mse_fixed=(sum(fixed_mses) / len(fixed_mses)) if fixed_mses else None,
        mean_mse_fitted=(sum(fitted_mses) / len(fitted_mses)) if fitted_mses else None,
        fitted_win_rate=(wins / len(paired)) if paired else None,
        insufficient_sample=n < min_events,
    )


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """OOS walk-forward score for one fixed (gamma, alpha, beta) candidate."""

    gamma: float
    alpha: float
    beta: float
    n_events: int
    mean_qlike: float | None
    win_rate_vs_default: float | None


@dataclass(frozen=True, slots=True)
class CandidateGrid:
    """All candidates' scores for one symbol, plus the default weights' own score."""

    n_events: int
    default: CandidateScore
    candidates: list[CandidateScore]  # sorted best-first by mean_qlike


def _candidate_qlikes(
    returns: Sequence[float],
    *,
    weights: tuple[float, float, float],
    window: int,
) -> list[float | None]:
    """Per-step OOS QLIKE for one fixed weight set; None where unusable."""
    gamma, alpha, beta = weights
    out: list[float | None] = []
    for t in range(window, len(returns)):
        trailing = returns[t - window : t]
        res = forecast_garch_11(trailing, gamma=gamma, alpha=alpha, beta=beta)
        sigma2 = res.forecast_sigma2 if res.usable else None
        out.append(_qlike(sigma2, returns[t] ** 2))
    return out


def _score_from_qlikes(
    weights: tuple[float, float, float],
    qlikes: Sequence[float | None],
    default_qlikes: Sequence[float | None] | None,
) -> CandidateScore:
    valid = [q for q in qlikes if q is not None]
    win_rate: float | None = None
    if default_qlikes is not None:
        paired = [
            (q, dq) for q, dq in zip(qlikes, default_qlikes) if q is not None and dq is not None
        ]
        if paired:
            win_rate = sum(1 for q, dq in paired if q < dq) / len(paired)
    return CandidateScore(
        gamma=weights[0],
        alpha=weights[1],
        beta=weights[2],
        n_events=len(valid),
        mean_qlike=(sum(valid) / len(valid)) if valid else None,
        win_rate_vs_default=win_rate,
    )


def score_weight_candidates(
    log_returns: Sequence[float],
    *,
    candidates: Sequence[tuple[float, float, float]],
    window: int = 250,
    default_weights: tuple[float, float, float] = (0.05, 0.05, 0.90),
) -> CandidateGrid:
    """Walk-forward score each fixed (gamma, alpha, beta) candidate by OOS QLIKE.

    Same rolling scheme as ``run_walk_forward``; each candidate is compared
    pairwise per step against ``default_weights`` (strict wins only). This is
    the shared scoring path for per-symbol weight calibration
    (backend/scripts/calibrate_garch_weights.py).
    """
    returns = list(log_returns)
    default_qlikes = _candidate_qlikes(returns, weights=default_weights, window=window)
    scored = [
        _score_from_qlikes(
            cand,
            _candidate_qlikes(returns, weights=cand, window=window),
            default_qlikes,
        )
        for cand in candidates
    ]
    scored.sort(key=lambda s: math.inf if s.mean_qlike is None else s.mean_qlike)
    return CandidateGrid(
        n_events=max(len(returns) - window, 0),
        default=_score_from_qlikes(default_weights, default_qlikes, None),
        candidates=scored,
    )


def combine_summaries(summaries: Sequence[WalkForwardSummary]) -> WalkForwardSummary:
    """Pool per-symbol events into one combined-universe summary (symbol='ALL')."""
    n_events = sum(s.n_events for s in summaries)
    n_fit_usable = sum(s.n_fit_usable for s in summaries)

    def _weighted_mean(values_and_weights: list[tuple[float | None, int]]) -> float | None:
        total_weight = sum(w for v, w in values_and_weights if v is not None)
        if total_weight == 0:
            return None
        return sum(v * w for v, w in values_and_weights if v is not None) / total_weight

    mean_qlike_fixed = _weighted_mean([(s.mean_qlike_fixed, s.n_events) for s in summaries])
    mean_qlike_fitted = _weighted_mean([(s.mean_qlike_fitted, s.n_fit_usable) for s in summaries])
    mean_mse_fixed = _weighted_mean([(s.mean_mse_fixed, s.n_events) for s in summaries])
    mean_mse_fitted = _weighted_mean([(s.mean_mse_fitted, s.n_fit_usable) for s in summaries])
    fitted_win_rate = _weighted_mean([(s.fitted_win_rate, s.n_fit_usable) for s in summaries])

    return WalkForwardSummary(
        symbol="ALL",
        n_events=n_events,
        n_fit_usable=n_fit_usable,
        fit_usable_rate=(n_fit_usable / n_events) if n_events else None,
        mean_qlike_fixed=mean_qlike_fixed,
        mean_qlike_fitted=mean_qlike_fitted,
        mean_mse_fixed=mean_mse_fixed,
        mean_mse_fitted=mean_mse_fitted,
        fitted_win_rate=fitted_win_rate,
        insufficient_sample=n_events < 100,
    )
