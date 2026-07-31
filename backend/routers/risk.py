"""Risk dashboard API — circuit breakers, Greeks, events (§11.4 / UI_Dashboard)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.risk_snapshot import build_risk_snapshot

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


@router.get("/snapshot")
async def risk_snapshot():
    """Live paper-sim risk dashboard payload (replaces frontend mock constants)."""
    return JSONResponse(content=build_risk_snapshot())
