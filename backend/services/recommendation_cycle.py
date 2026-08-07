"""Supervision-gated recommendation cycle, callable outside the router.

Extracted from backend/routers/recommendations.py so the trading scheduler
can run cycles without importing a router. Behavior is identical: a fresh
cycle executes the ranked list only when SUPERVISION_MODE=fully_autonomous;
every other value (supervised / semi_autonomous / blank / typo) fails closed
to "approval required".
"""

from __future__ import annotations

from backend.models.recommendations import InstrumentRecommendation, RecommendationResponse
from backend.models.trades import AutonomousExecutionResult
from backend.services.recommendation_engine import (
    generate_recommendations,
    peek_cached_recommendations,
)
from backend.services.supervision_mode import get_supervision_mode
from backend.services.trade_executor import (
    execute_autonomous_from_recommendations,
    is_one_trade_locked,
)


async def autonomous_execution_for(
    recommendations: list[InstrumentRecommendation],
) -> AutonomousExecutionResult:
    """Run ranked fallback immediately after recommendations are generated —
    only when SUPERVISION_MODE=fully_autonomous. Under "supervised" or
    "semi_autonomous" (and any blank/unset/typo value), a fresh cycle never
    opens a trade; POST /decisions/{id}/approve does."""
    supervision = get_supervision_mode()
    if supervision != "fully_autonomous":
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message=(
                "Supervision mode requires explicit approval — "
                "see POST /api/v1/decisions/{id}/approve"
            ),
        )

    if is_one_trade_locked():
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message="One-trade scope locked — close the active trade before opening another.",
        )

    if not recommendations:
        return AutonomousExecutionResult(
            executed=False,
            attempts=[],
            message="No recommendations available to execute",
        )

    return await execute_autonomous_from_recommendations(recommendations)


async def run_recommendation_cycle(
    *,
    force_refresh: bool = False,
) -> RecommendationResponse:
    """Generate (or reuse cached) recommendations; execute only on a fresh cycle."""
    if not force_refresh:
        cached = peek_cached_recommendations()
        if cached is not None:
            return cached

    result = await generate_recommendations(force_refresh=force_refresh)
    autonomous_execution = await autonomous_execution_for(result.recommendations)
    return result.model_copy(update={"autonomous_execution": autonomous_execution})
