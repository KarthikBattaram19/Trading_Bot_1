"""Decision log + approve/reject — writes go through paper_sim (Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.decisions import DecisionRecord, DecisionStatus
from backend.services import decision_log
from backend.services.decision_state import DecisionState, get_decision_state_store
from backend.services.recommendation_engine import peek_cached_recommendations
from backend.services.trade_executor import execute_autonomous_from_recommendations

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


class RejectRequest(BaseModel):
    reason: str | None = None


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


async def _get_pending_decision(decision_id: str) -> DecisionRecord:
    decision = await decision_log.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision with id {decision_id}")
    if decision.status != DecisionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Decision {decision_id} is already {decision.status.value}, not pending",
        )
    return decision


@router.post("/{decision_id}/approve")
async def approve_decision(decision_id: str) -> dict:
    """Approve a pending decision — executes it through paper_sim (single candidate)."""
    decision = await _get_pending_decision(decision_id)

    cached = peek_cached_recommendations()
    rec = None
    if cached is not None:
        rec = next(
            (
                r
                for r in cached.recommendations
                if f"dec_{r.underlying_symbol.lower()}_{cached.generated_at.strftime('%Y%m%d')}" == decision_id
            ),
            None,
        )
        if rec is None:
            # Fall back to matching by underlying_symbol against the already-fetched
            # decision (per Docs/superpowers/specs/2026-08-04-wire-trade-executor-paper-sim-design.md
            # §5) — covers decision_ids that don't follow the live dec_{symbol}_{date} pattern
            # (e.g. acted-on decisions keyed off a trade_id).
            rec = next(
                (r for r in cached.recommendations if r.underlying_symbol == decision.underlying_symbol),
                None,
            )
    if rec is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Decision {decision_id} is no longer in the live recommendation cache — "
                "re-fetch GET /decisions/pending and retry"
            ),
        )

    result = await execute_autonomous_from_recommendations([rec])

    store = get_decision_state_store()
    if result.executed:
        store.set(
            decision_id,
            DecisionState(
                status="approved",
                trade_id=result.trade_id,
                acted_at=datetime.now(timezone.utc),
            ),
        )
        updated = decision.model_copy(update={"status": DecisionStatus.approved})
        return {"decision": updated, "execution": result}

    # paper_sim rejected it — leave the decision pending so the operator can retry/reject.
    return {"decision": decision, "execution": result}


@router.post("/{decision_id}/reject")
async def reject_decision(decision_id: str, body: RejectRequest | None = None) -> DecisionRecord:
    """Reject a pending decision — persisted, no execution."""
    decision = await _get_pending_decision(decision_id)

    store = get_decision_state_store()
    store.set(
        decision_id,
        DecisionState(
            status="rejected",
            reason=body.reason if body else None,
            acted_at=datetime.now(timezone.utc),
        ),
    )
    return decision.model_copy(update={"status": DecisionStatus.rejected})
