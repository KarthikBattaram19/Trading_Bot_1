"""Gamma–theta breakeven and hedge frequency (mechanical; no LLM).

Playbook authority: ``Trading_Strategies.md`` VT-5 / GS-6 and ``Trading_Parameters.md`` Part J.

Breakeven move: distance from the last hedge point where expected one-day
gamma P&L offsets one day of theta decay:

    0.5 · Γ · (ΔS)²  =  |Θ|
    |ΔS|  =  sqrt(2 · |Θ| / Γ)     (Γ > 0)
    pct   =  (|ΔS| / S) · 100

Re-hedge when spot has moved ≥ that distance from ``hedge_point_price``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Literal

RehedgeMethod = Literal["increase_hedge", "reduce_options", "adjust_call_put_mix"]


@dataclass(frozen=True, slots=True)
class HedgeDecision:
    """Rule-fast-path outcome for a mechanical re-hedge check."""

    should_hedge: bool
    reason: str
    spot: float
    hedge_point_price: float
    move_pct: float
    trigger_pct: float
    breakeven_pct: float
    net_hedge_edge: float
    total_delta: float
    method: RehedgeMethod


def gamma_theta_breakeven_move(*, total_gamma: float, total_theta: float) -> float:
    """Absolute underlying move |ΔS| where ½Γ(ΔS)² offsets one day of |Θ|.

    Returns 0 when gamma is non-positive or inputs are non-finite (cannot
    define a long-gamma breakeven). Theta may be negative (long options) or
    positive; magnitude is used.
    """
    gamma = float(total_gamma)
    theta_abs = abs(float(total_theta))
    if not isfinite(gamma) or not isfinite(theta_abs) or gamma <= 0:
        return 0.0
    if theta_abs <= 0:
        return 0.0
    return sqrt(2.0 * theta_abs / gamma)


def gamma_theta_breakeven_pct(
    *,
    total_gamma: float,
    total_theta: float,
    spot: float,
) -> float:
    """Breakeven as percent of spot (do not hard-code ~1%)."""
    s = float(spot)
    if not isfinite(s) or s <= 0:
        return 0.0
    move = gamma_theta_breakeven_move(total_gamma=total_gamma, total_theta=total_theta)
    if move <= 0:
        return 0.0
    return (move / s) * 100.0


def expected_gamma_pnl(*, total_gamma: float, spot_move: float) -> float:
    """½ Γ (ΔS)² for a realized absolute spot move."""
    return 0.5 * float(total_gamma) * float(spot_move) ** 2


def expected_theta_loss(*, total_theta: float) -> float:
    """One-day theta carry cost as a positive number when theta is negative."""
    return abs(float(total_theta))


def net_hedge_edge(
    *,
    total_gamma: float,
    total_theta: float,
    spot_move: float,
    transaction_cost: float = 0.0,
) -> float:
    """Architecture §9.4: expected_gamma_pnl − expected_theta_loss − costs."""
    return (
        expected_gamma_pnl(total_gamma=total_gamma, spot_move=spot_move)
        - expected_theta_loss(total_theta=total_theta)
        - float(transaction_cost)
    )


def min_rebalance_interval_sec(
    *,
    total_gamma: float,
    total_theta: float,
    spot: float,
    realized_vol_daily: float,
    transaction_cost: float = 0.0,
    min_edge_threshold: float = 0.0,
    session_seconds: float = 22_500.0,
) -> float:
    """Minimum seconds between rebalances where expected gamma edge clears costs.

    Uses a one-day vol scale: expected |ΔS| ≈ spot · σ_daily. If edge at that
    move is ≤ threshold, recommend waiting a full session (no HFT rebalance).
    Otherwise scale interval down with edge / cost ratio (retail-friendly).
    """
    s = float(spot)
    sigma = max(float(realized_vol_daily), 1e-8)
    if not isfinite(s) or s <= 0 or float(total_gamma) <= 0:
        return float(session_seconds)

    typical_move = s * sigma
    edge = net_hedge_edge(
        total_gamma=total_gamma,
        total_theta=total_theta,
        spot_move=typical_move,
        transaction_cost=transaction_cost,
    )
    if edge <= float(min_edge_threshold):
        return float(session_seconds)

    # More edge → shorter interval; floor at 60s for retail / API latency.
    cost = max(float(transaction_cost), 1e-6)
    ratio = edge / cost
    interval = float(session_seconds) / max(ratio, 1.0)
    return max(60.0, min(float(session_seconds), interval))


def should_rehedge(
    *,
    spot: float,
    hedge_point_price: float,
    breakeven_pct: float,
    use_half_breakeven: bool = False,
) -> bool:
    """True when |spot − hedge_point| / hedge_point ≥ trigger (Part J / VT-5)."""
    hp = float(hedge_point_price)
    s = float(spot)
    be = float(breakeven_pct)
    if not isfinite(hp) or not isfinite(s) or hp <= 0 or s <= 0 or be <= 0:
        return False
    trigger = be * 0.5 if use_half_breakeven else be
    move_pct = abs(s - hp) / hp * 100.0
    return move_pct >= trigger


def should_execute_hedge(
    *,
    spot: float,
    hedge_point_price: float,
    breakeven_pct: float,
    total_delta: float,
    total_gamma: float,
    total_theta: float,
    transaction_cost: float = 0.0,
    min_edge_threshold: float = 0.0,
    delta_threshold: float = 0.0,
    use_half_breakeven: bool = False,
    method: RehedgeMethod = "increase_hedge",
    force: bool = False,
) -> HedgeDecision:
    """Combine breakeven distance + §9.4 edge + optional |Δ| gate (no LLM)."""
    hp = float(hedge_point_price)
    s = float(spot)
    move_pct = abs(s - hp) / hp * 100.0 if hp > 0 else 0.0
    trigger = float(breakeven_pct) * (0.5 if use_half_breakeven else 1.0)
    spot_move = abs(s - hp)
    edge = net_hedge_edge(
        total_gamma=total_gamma,
        total_theta=total_theta,
        spot_move=spot_move,
        transaction_cost=transaction_cost,
    )
    delta = float(total_delta)

    if force:
        return HedgeDecision(
            should_hedge=True,
            reason="forced_rehedge",
            spot=s,
            hedge_point_price=hp,
            move_pct=move_pct,
            trigger_pct=trigger,
            breakeven_pct=float(breakeven_pct),
            net_hedge_edge=edge,
            total_delta=delta,
            method=method,
        )

    if not should_rehedge(
        spot=s,
        hedge_point_price=hp,
        breakeven_pct=breakeven_pct,
        use_half_breakeven=use_half_breakeven,
    ):
        return HedgeDecision(
            should_hedge=False,
            reason="below_breakeven",
            spot=s,
            hedge_point_price=hp,
            move_pct=move_pct,
            trigger_pct=trigger,
            breakeven_pct=float(breakeven_pct),
            net_hedge_edge=edge,
            total_delta=delta,
            method=method,
        )

    if abs(delta) < float(delta_threshold):
        return HedgeDecision(
            should_hedge=False,
            reason="delta_below_threshold",
            spot=s,
            hedge_point_price=hp,
            move_pct=move_pct,
            trigger_pct=trigger,
            breakeven_pct=float(breakeven_pct),
            net_hedge_edge=edge,
            total_delta=delta,
            method=method,
        )

    if edge <= float(min_edge_threshold):
        return HedgeDecision(
            should_hedge=False,
            reason="net_hedge_edge_non_positive",
            spot=s,
            hedge_point_price=hp,
            move_pct=move_pct,
            trigger_pct=trigger,
            breakeven_pct=float(breakeven_pct),
            net_hedge_edge=edge,
            total_delta=delta,
            method=method,
        )

    return HedgeDecision(
        should_hedge=True,
        reason="breakeven_reached",
        spot=s,
        hedge_point_price=hp,
        move_pct=move_pct,
        trigger_pct=trigger,
        breakeven_pct=float(breakeven_pct),
        net_hedge_edge=edge,
        total_delta=delta,
        method=method,
    )
