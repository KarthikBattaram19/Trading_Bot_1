"""Ops surface for the background trading scheduler."""

from __future__ import annotations

from fastapi import APIRouter

from backend.services.trading_scheduler import get_trading_scheduler

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status():
    return get_trading_scheduler().status()


@router.post("/start")
async def scheduler_start():
    return await get_trading_scheduler().start()


@router.post("/stop")
async def scheduler_stop():
    return await get_trading_scheduler().stop()


@router.post("/tick")
async def scheduler_tick():
    """Run one scheduler cycle immediately (ops/tests)."""
    scheduler = get_trading_scheduler()
    result = await scheduler.tick()
    return {"tick": result, "status": scheduler.status()}
