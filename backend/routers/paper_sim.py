"""HTTP API for the in-house paper simulator (separate from ICICI Direct live orders)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.paper_sim.ledger import PaperLedgerError
from backend.paper_sim.models import PaperOrderRequest
from backend.paper_sim.service import get_paper_engine

router = APIRouter(prefix="/api/v1/paper-sim", tags=["paper-sim"])


class ResetRequest(BaseModel):
    starting_capital_inr: float | None = Field(
        default=None, description="Optional virtual cash reset; defaults to config"
    )


@router.get("/health")
async def paper_sim_health():
    return get_paper_engine().health()


@router.get("/account")
async def paper_account():
    return get_paper_engine().account().model_dump(mode="json")


@router.post("/reset")
async def paper_reset(body: ResetRequest | None = None):
    engine = get_paper_engine()
    capital = body.starting_capital_inr if body else None
    return engine.reset(capital).model_dump(mode="json")


@router.get("/positions")
async def paper_positions(status: str | None = Query(default="open")):
    return {
        "positions": [
            p.model_dump(mode="json") for p in get_paper_engine().positions(status=status)
        ]
    }


@router.get("/fills")
async def paper_fills(limit: int = Query(default=100, ge=1, le=500)):
    return {
        "fills": [f.model_dump(mode="json") for f in get_paper_engine().fills(limit=limit)]
    }


@router.post("/orders")
async def paper_submit_order(request: PaperOrderRequest):
    """Simulate a multi-leg fill locally. Does not call ICICI Direct place_order."""
    try:
        return await get_paper_engine().submit_order(request)
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface feed/auth failures clearly
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.post("/positions/{position_id}/close")
async def paper_close_position(position_id: str):
    try:
        return await get_paper_engine().close_position(position_id)
    except PaperLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.post("/marks/refresh")
async def paper_refresh_marks():
    try:
        return await get_paper_engine().refresh_marks()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper mark feed error: {exc}") from exc


@router.get("/chain")
async def paper_option_chain(
    underlying: str = Query(..., description="e.g. NIFTY, SBIN"),
    expiry: str | None = Query(default=None),
    include_ltp: bool = Query(default=False),
    max_contracts: int = Query(default=80, ge=1, le=300),
):
    try:
        return await get_paper_engine().option_chain(
            underlying=underlying,
            expiry=expiry,
            include_ltp=include_ltp,
            max_contracts=max_contracts,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"paper chain feed error: {exc}") from exc
