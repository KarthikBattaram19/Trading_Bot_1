"""Read-only decision log (Phase 0) — no approve / reject transitions yet."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.decisions import DecisionRecord
from backend.services import decision_log

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.get("")
async def list_decisions() -> list[DecisionRecord]:
    """Audit trail of surfaced and acted-on decisions, newest first."""
    return await decision_log.list_decisions()


@router.get("/pending")
async def list_pending_decisions() -> list[DecisionRecord]:
    """Decisions surfaced this cycle that the bot has not acted on yet."""
    return await decision_log.list_pending_decisions()


@router.get("/{decision_id}")
async def get_decision(decision_id: str) -> DecisionRecord:
    """Pre-approval packet for a single decision."""
    decision = await decision_log.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision with id {decision_id}")
    return decision
