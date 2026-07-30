"""Continual learning API — architecture §12."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.models.learning import CloseTradeRequest
from backend.services.learning_service import get_learning_service
from backend.services.trade_executor import get_active_trade_id, unlock_trade

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])


@router.get("/dashboard")
async def learning_dashboard():
    """Operator view: outcomes, failure memory, module attribution, adaptations."""
    dash = get_learning_service().dashboard()
    return JSONResponse(content=dash.model_dump(mode="json"))


@router.get("/history")
async def learning_history():
    """Adaptation cycle history (§12 / config versioning)."""
    dash = get_learning_service().dashboard()
    return JSONResponse(
        content={
            "adaptation_history": [
                a.model_dump(mode="json") for a in dash.adaptation_history
            ],
            "adaptation_frozen": dash.adaptation_frozen,
            "freeze_reason": dash.freeze_reason,
        }
    )


@router.get("/open-trades")
async def list_open_trades():
    trades = get_learning_service().list_open_trades()
    return JSONResponse(
        content={"open_trades": [t.model_dump(mode="json") for t in trades]}
    )


@router.post("/outcomes")
async def record_trade_outcome(body: CloseTradeRequest):
    """
    Close a trade and feed the continual learning loop.

    On loss: writes failure_memory. Always updates module attribution.
    May queue an adaptation event when triggers fire under §12.5 guards.
    """
    learning = get_learning_service()
    try:
        outcome = learning.record_outcome(body)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Release one-trade lock if this was the active discretionary entry
    if get_active_trade_id() == body.trade_id:
        unlock_trade()

    return JSONResponse(content=outcome.model_dump(mode="json"))
