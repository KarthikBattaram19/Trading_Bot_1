"""Phase 1.6 — gamma–theta breakeven / hedge optimizer (no LLM)."""

from __future__ import annotations

from math import sqrt

import pytest

from backend.quant.gamma.hedge_optimizer import (
    expected_gamma_pnl,
    gamma_theta_breakeven_move,
    gamma_theta_breakeven_pct,
    min_rebalance_interval_sec,
    net_hedge_edge,
    should_execute_hedge,
    should_rehedge,
)


def test_breakeven_move_matches_half_gamma_theta_identity():
    # 0.5 * Γ * (ΔS)^2 = |Θ|  →  ΔS = sqrt(2|Θ|/Γ)
    gamma, theta = 2.0, -50.0
    move = gamma_theta_breakeven_move(total_gamma=gamma, total_theta=theta)
    assert move == pytest.approx(sqrt(2.0 * 50.0 / 2.0))
    assert expected_gamma_pnl(total_gamma=gamma, spot_move=move) == pytest.approx(50.0)


def test_breakeven_pct_not_hardcoded():
    # Same Greeks at different spots → different % (VT-5: compute, don't hard-code ~1%)
    pct_a = gamma_theta_breakeven_pct(total_gamma=1.5, total_theta=-80.0, spot=500.0)
    pct_b = gamma_theta_breakeven_pct(total_gamma=1.5, total_theta=-80.0, spot=1000.0)
    assert pct_a > 0
    assert pct_b > 0
    assert pct_a != pytest.approx(pct_b)
    assert pct_a == pytest.approx(pct_b * 2.0, rel=1e-9)


def test_breakeven_zero_when_gamma_non_positive():
    assert gamma_theta_breakeven_move(total_gamma=0.0, total_theta=-10.0) == 0.0
    assert gamma_theta_breakeven_pct(total_gamma=-1.0, total_theta=-10.0, spot=100.0) == 0.0


def test_should_rehedge_at_breakeven_and_half():
    assert should_rehedge(
        spot=101.0, hedge_point_price=100.0, breakeven_pct=1.0, use_half_breakeven=False
    )
    assert not should_rehedge(
        spot=100.4, hedge_point_price=100.0, breakeven_pct=1.0, use_half_breakeven=False
    )
    assert should_rehedge(
        spot=100.5, hedge_point_price=100.0, breakeven_pct=1.0, use_half_breakeven=True
    )


def test_net_hedge_edge_and_execute_gate():
    # Move to breakeven → edge ≈ −transaction_cost when theta fully offset
    gamma, theta, spot, hp = 2.0, -50.0, 100.0, 100.0
    move = gamma_theta_breakeven_move(total_gamma=gamma, total_theta=theta)
    be = gamma_theta_breakeven_pct(total_gamma=gamma, total_theta=theta, spot=spot)
    edge = net_hedge_edge(
        total_gamma=gamma,
        total_theta=theta,
        spot_move=move,
        transaction_cost=5.0,
    )
    assert edge == pytest.approx(-5.0)

    reject = should_execute_hedge(
        spot=hp + move,
        hedge_point_price=hp,
        breakeven_pct=be,
        total_delta=5.0,
        total_gamma=gamma,
        total_theta=theta,
        transaction_cost=5.0,
        min_edge_threshold=0.0,
        delta_threshold=0.1,
    )
    assert reject.should_hedge is False
    assert reject.reason == "net_hedge_edge_non_positive"

    accept = should_execute_hedge(
        spot=hp + move,
        hedge_point_price=hp,
        breakeven_pct=be,
        total_delta=5.0,
        total_gamma=gamma,
        total_theta=theta,
        transaction_cost=0.0,
        min_edge_threshold=0.0,
        delta_threshold=0.1,
    )
    assert accept.should_hedge is True
    assert accept.reason == "breakeven_reached"


def test_delta_below_threshold_skips():
    be = gamma_theta_breakeven_pct(total_gamma=2.0, total_theta=-50.0, spot=100.0)
    move = gamma_theta_breakeven_move(total_gamma=2.0, total_theta=-50.0)
    d = should_execute_hedge(
        spot=100.0 + move,
        hedge_point_price=100.0,
        breakeven_pct=be,
        total_delta=0.01,
        total_gamma=2.0,
        total_theta=-50.0,
        delta_threshold=0.1,
    )
    assert d.should_hedge is False
    assert d.reason == "delta_below_threshold"


def test_min_rebalance_interval_retail_floor():
    # Positive edge → interval between 60s and session
    interval = min_rebalance_interval_sec(
        total_gamma=5.0,
        total_theta=-20.0,
        spot=500.0,
        realized_vol_daily=0.02,
        transaction_cost=1.0,
        min_edge_threshold=0.0,
    )
    assert 60.0 <= interval <= 22_500.0

    # No edge → full session wait
    long = min_rebalance_interval_sec(
        total_gamma=0.01,
        total_theta=-100.0,
        spot=500.0,
        realized_vol_daily=0.001,
        transaction_cost=50.0,
    )
    assert long == pytest.approx(22_500.0)
