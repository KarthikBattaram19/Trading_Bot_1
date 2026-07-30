"""FastAPI app — paper_sim + ICICI Direct data/A3; Railway never live (Phase 1.10)."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config_env import load_project_env
from backend.integrations.registry import (
    get_integration_health,
    paper_stack_guard_status,
    place_order_enabled,
)
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
    description=(
        "Phase 1.10: paper_sim + ICICI Direct marks (REST + WS) + A3 shadow "
        "dry-run + Market_News + SH-4 + GARCH/IV z + γ–θ re-hedge + BSM/OSS "
        "parity + cost/risk gates; EXECUTION_MODE=paper on Railway — never live"
    ),
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
    """Phase 1 health — paper stack guard; Nixpacks / Railpack remote builder."""
    local_infra = os.getenv("LOCAL_INFRA", "none").strip().lower() or "none"
    guard = paper_stack_guard_status()
    return {
        "status": "ok",
        "execution_mode": guard["execution_mode"],
        "requested_execution_mode": guard["requested_execution_mode"],
        "deploy_stack": guard["deploy_stack"],
        "live_blocked": guard["live_blocked"],
        "phase": "1",
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
