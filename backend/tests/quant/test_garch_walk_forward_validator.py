from __future__ import annotations

import math
import random

from backend.quant.analytics.garch_walk_forward_validator import (
    WalkForwardEvent,
    combine_summaries,
    run_walk_forward,
    summarize_walk_forward,
)


def _simulate_garch_returns(
    n: int, *, gamma: float, alpha: float, beta: float, vl: float, seed: int
) -> list[float]:
    rng = random.Random(seed)
    sigma2 = vl
    returns: list[float] = []
    for _ in range(n):
        r = rng.gauss(0.0, math.sqrt(sigma2))
        returns.append(r)
        sigma2 = gamma * vl + alpha * (r * r) + beta * sigma2
    return returns


def test_event_count_matches_window_and_series_length():
    returns = [0.01, -0.008, 0.005, -0.003] * 100  # n=400
    events = run_walk_forward(returns, window=250, fit_min_observations=60)
    assert len(events) == 400 - 250


def test_realized_r2_is_next_day_squared_return():
    returns = [0.01 if i % 2 == 0 else -0.01 for i in range(300)]
    events = run_walk_forward(returns, window=250, fit_min_observations=60)
    # events[0] corresponds to t=250: realized_r2 must be returns[250]**2
    assert events[0].index == 250
    assert events[0].realized_r2 == returns[250] ** 2


def test_fixed_forecast_always_usable_on_well_behaved_series():
    returns = _simulate_garch_returns(300, gamma=0.05, alpha=0.05, beta=0.90, vl=0.0002, seed=3)
    events = run_walk_forward(returns, window=250, fit_min_observations=60)
    assert all(e.fixed_sigma2 is not None for e in events)
    assert all(e.fixed_qlike is not None for e in events)


def test_summarize_insufficient_sample_boundary():
    events_99 = [
        WalkForwardEvent(
            index=i,
            realized_r2=0.0001,
            fixed_sigma2=0.0001,
            fixed_qlike=-9.2,
            fitted_usable=True,
            fitted_reason=None,
            fitted_sigma2=0.0001,
            fitted_qlike=-9.2,
        )
        for i in range(99)
    ]
    events_100 = events_99 + [events_99[0]]
    s99 = summarize_walk_forward(symbol="X", events=events_99, min_events=100)
    s100 = summarize_walk_forward(symbol="X", events=events_100, min_events=100)
    assert s99.insufficient_sample is True
    assert s100.insufficient_sample is False


def test_summarize_computes_exact_qlike_and_mse_for_hand_worked_events():
    # Two events with known sigma2/r2 -- QLIKE = ln(sigma2) + r2/sigma2.
    e1 = WalkForwardEvent(
        index=0,
        realized_r2=0.0004,
        fixed_sigma2=0.0002,
        fixed_qlike=math.log(0.0002) + 0.0004 / 0.0002,
        fitted_usable=True,
        fitted_reason=None,
        fitted_sigma2=0.0004,  # fitted forecast matches realized exactly -> lower QLIKE
        fitted_qlike=math.log(0.0004) + 0.0004 / 0.0004,
    )
    e2 = WalkForwardEvent(
        index=1,
        realized_r2=0.0001,
        fixed_sigma2=0.0002,
        fixed_qlike=math.log(0.0002) + 0.0001 / 0.0002,
        fitted_usable=True,
        fitted_reason=None,
        fitted_sigma2=0.0001,  # fitted also matches exactly here
        fitted_qlike=math.log(0.0001) + 0.0001 / 0.0001,
    )
    summary = summarize_walk_forward(symbol="X", events=[e1, e2], min_events=1)
    assert summary.n_events == 2
    assert summary.n_fit_usable == 2
    assert summary.fit_usable_rate == 1.0
    # Fitted matches realized exactly both times -> fitted should win both, QLIKE lower.
    assert summary.fitted_win_rate == 1.0
    assert summary.mean_qlike_fitted < summary.mean_qlike_fixed
    assert summary.mean_mse_fitted == 0.0
    assert summary.mean_mse_fixed > 0.0


def test_summarize_handles_no_fit_usable_events():
    events = [
        WalkForwardEvent(
            index=0,
            realized_r2=0.0001,
            fixed_sigma2=0.0001,
            fixed_qlike=-9.2,
            fitted_usable=False,
            fitted_reason="garch_fit_failed",
            fitted_sigma2=None,
            fitted_qlike=None,
        )
        for _ in range(150)
    ]
    summary = summarize_walk_forward(symbol="X", events=events, min_events=100)
    assert summary.n_fit_usable == 0
    assert summary.fit_usable_rate == 0.0
    assert summary.mean_qlike_fitted is None
    assert summary.fitted_win_rate is None
    assert summary.insufficient_sample is False  # n_events=150 clears the floor


def test_combine_summaries_pools_weighted_by_event_count():
    s1 = summarize_walk_forward(
        symbol="A",
        events=[
            WalkForwardEvent(0, 0.0001, 0.0001, -9.2, True, None, 0.0001, -9.2)
            for _ in range(100)
        ],
        min_events=100,
    )
    s2 = summarize_walk_forward(
        symbol="B",
        events=[
            WalkForwardEvent(0, 0.0001, 0.0001, -9.2, True, None, 0.0001, -9.2)
            for _ in range(50)
        ],
        min_events=100,
    )
    combined = combine_summaries([s1, s2])
    assert combined.symbol == "ALL"
    assert combined.n_events == 150
    assert combined.insufficient_sample is False
