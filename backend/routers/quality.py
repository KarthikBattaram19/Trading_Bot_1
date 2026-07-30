"""Quality metrics API — Core Metrics dashboards and latency percentiles."""

from __future__ import annotations

from fastapi import APIRouter

from backend.quality.config import get_thresholds
from backend.quality.latency import get_latency_tracker

router = APIRouter(prefix="/api/v1", tags=["quality"])


@router.get("/quality/metrics")
async def quality_metrics():
    """Expose Quality / Safety / Performance budgets and live latency percentiles."""
    tracker = get_latency_tracker()
    thresholds = get_thresholds()
    chat_snap = tracker.snapshot("chat")
    all_snap = tracker.snapshot()

    return {
        "framework": "Core Metrics: Quality, Safety & Performance",
        "dimensions": {
            "quality": ["relevance", "coherence", "completeness", "conciseness"],
            "safety": ["toxicity", "bias"],
            "performance": ["latency_p50_p95_p99", "ttft", "consistency"],
        },
        "thresholds": thresholds.model_dump(),
        "latency": {
            "chat": {
                "count": chat_snap.count,
                "p50_ms": chat_snap.p50_ms,
                "p95_ms": chat_snap.p95_ms,
                "p99_ms": chat_snap.p99_ms,
                "ttft_p50_ms": chat_snap.ttft_p50_ms,
                "ttft_p95_ms": chat_snap.ttft_p95_ms,
                "ttft_p99_ms": chat_snap.ttft_p99_ms,
                "mean_ms": chat_snap.mean_ms,
                "within_budget": chat_snap.within_budget,
                "budget_detail": chat_snap.budget_detail,
            },
            "all": {
                "count": all_snap.count,
                "p50_ms": all_snap.p50_ms,
                "p95_ms": all_snap.p95_ms,
                "p99_ms": all_snap.p99_ms,
                "ttft_p50_ms": all_snap.ttft_p50_ms,
                "ttft_p95_ms": all_snap.ttft_p95_ms,
                "ttft_p99_ms": all_snap.ttft_p99_ms,
                "mean_ms": all_snap.mean_ms,
                "within_budget": all_snap.within_budget,
                "budget_detail": all_snap.budget_detail,
            },
        },
    }
