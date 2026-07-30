"""Phase 0 FastAPI scaffold — ICICI Direct data-only, zero place_order."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config_env import load_project_env
from backend.integrations.registry import get_execution_mode, get_integration_health, place_order_enabled
from backend.routers import (
    bot,
    chat,
    decisions,
    integrations,
    learning,
    paper_sim,
    quality,
    recommendations,
)

load_project_env()

app = FastAPI(
    title="Bhale Bullodu 1.0 - Volatility Trading Bot",
    version="1.0.0",
    description="Phase 0: ICICI Direct marks + feed health; paper_sim stub; no place_order",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bot.router)
app.include_router(decisions.router)
app.include_router(recommendations.router)
app.include_router(learning.router)
app.include_router(chat.router)
app.include_router(quality.router)
app.include_router(integrations.router)
app.include_router(paper_sim.router)


@app.get("/health")
async def health():
    """Phase 0 health — native local toolchain; Nixpacks remote builder."""
    local_infra = os.getenv("LOCAL_INFRA", "none").strip().lower() or "none"
    mode = get_execution_mode()
    return {
        "status": "ok",
        "execution_mode": mode.value,
        "phase": "0",
        "place_order_enabled": place_order_enabled(),
        "local_infra": local_infra,
        "database_configured": bool(os.getenv("DATABASE_URL", "").strip()),
        "redis_configured": bool(os.getenv("REDIS_URL", "").strip()),
        "local_containers_required": False,
        "remote_builder": "nixpacks",
    }


@app.get("/health/integrations")
async def health_integrations():
    return await get_integration_health()
