from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.models.recommendations import InstrumentRecommendation, RecommendationResponse
from backend.models.trades import AutonomousExecutionResult
from backend.services.recommendation_engine import generate_recommendations
from backend.services.trade_executor import (
    execute_autonomous_from_recommendations,
    is_one_trade_locked,
)

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


async def _autonomous_execution_for(
    recommendations: list[InstrumentRecommendation],
) -> AutonomousExecutionResult:
    """Run ranked fallback immediately after recommendations are generated —
    only when SUPERVISION_MODE=autonomous. Under the default "supervised"
    mode, a fresh GET never opens a trade; POST /decisions/{id}/approve does."""
    supervision = os.getenv("SUPERVISION_MODE", "supervised").strip().lower()
    if supervision == "supervised":
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


async def _recommendations_with_autonomous_execution(
    *,
    force_refresh: bool = False,
) -> RecommendationResponse:
    """Generate (or reuse cached) recommendations; execute only on a fresh cycle."""
    from backend.services.recommendation_engine import peek_cached_recommendations

    if not force_refresh:
        cached = peek_cached_recommendations()
        if cached is not None:
            return cached

    result = await generate_recommendations(force_refresh=force_refresh)
    autonomous_execution = await _autonomous_execution_for(result.recommendations)
    return result.model_copy(update={"autonomous_execution": autonomous_execution})


@router.get("")
async def get_top_recommendations(refresh: bool = False):
    """
    Analyze live feeds + market news, select strategies per Trading_Strategies.md,
    return top 3 instruments with complete decision logic.

    Opens a trade on the ranked list only when computing a fresh cycle
    (`refresh=true` or cold cache) — not on every page load.
    """
    result = await _recommendations_with_autonomous_execution(force_refresh=refresh)
    return JSONResponse(content=result.model_dump(mode="json", exclude_none=True))


@router.post("/execute-autonomous")
async def execute_autonomous_trade():
    """
    Explicit re-execution against a fresh recommendation set.

    Prefer GET /recommendations?refresh=true for the recommendations screen —
    it regenerates recommendations and executes in one cycle.
    """
    recs = await generate_recommendations(force_refresh=True)
    result = await execute_autonomous_from_recommendations(recs.recommendations)
    return JSONResponse(content=result.model_dump(mode="json"))