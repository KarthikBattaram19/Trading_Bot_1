"""Conservative fill pricing for paper trades (independent of broker)."""

from __future__ import annotations

from backend.paper_sim.models import PaperSide


def compute_fill_price(
    mark_ltp: float,
    side: PaperSide,
    slippage_bps: float,
) -> float:
    """Buy pays above LTP; sell receives below LTP."""
    if mark_ltp <= 0:
        raise ValueError("mark_ltp must be positive")
    slip = max(slippage_bps, 0.0) / 10_000.0
    if side == PaperSide.buy:
        return round(mark_ltp * (1.0 + slip), 4)
    return round(mark_ltp * (1.0 - slip), 4)


def leg_notional(fill_price: float, quantity: int) -> float:
    return abs(fill_price * quantity)
