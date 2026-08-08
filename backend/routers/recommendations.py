from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.recommendation_cycle import autonomous_execution_for, run_recommendation_cycle
from backend.services.recommendation_engine import generate_recommendations

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


@router.get("")
async def get_top_recommendations(refresh: bool = False):
    """
    Analyze live feeds + market news, select strategies per Trading_Strategies.md,
    return top 3 instruments with complete decision logic.

    Opens a trade on the ranked list only when computing a fresh cycle
    (`refresh=true` or cold cache) — not on every page load. The cycle logic
    lives in backend/services/recommendation_cycle.py (shared with the
    trading scheduler).
    """
    result = await run_recommendation_cycle(force_refresh=refresh)
    return JSONResponse(content=result.model_dump(mode="json", exclude_none=True))


@router.post("/execute-autonomous")
async def execute_autonomous_trade():
    """
    Explicit re-execution against a fresh recommendation set.

    Prefer GET /recommendations?refresh=true for the recommendations screen —
    it regenerates recommendations and executes in one cycle.

    Routed through `autonomous_execution_for` (same gate as a fresh
    GET /recommendations?refresh=true cycle) so this endpoint can't open a
    trade when SUPERVISION_MODE isn't "fully_autonomous" — including blank,
    unset, or a typo, which fail closed to "approval required" rather than
    executing. Mirrors that function's own contract: a normal 200 result
    with `executed: false`, not an HTTP error.
    """
    recs = await generate_recommendations(force_refresh=True)
    result = await autonomous_execution_for(recs.recommendations)
    return JSONResponse(content=result.model_dump(mode="json"))
