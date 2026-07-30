"""Thresholds aligned with architecture §7 Stage 14 and Core Metrics slide."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field


class QualityThresholds(BaseModel):
    # Quality (architecture Stage 14 + Core Metrics)
    relevance_min: float = Field(default=0.80, ge=0.0, le=1.0)
    coherence_min: float = Field(default=0.70, ge=0.0, le=1.0)
    completeness_min: float = Field(default=0.75, ge=0.0, le=1.0)
    conciseness_min: float = Field(default=0.60, ge=0.0, le=1.0)

    # Safety — fail closed on toxicity; bias warns then blocks at low scores
    toxicity_max: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Max allowed toxicity score (lower is safer)",
    )
    bias_max: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Max allowed bias score (lower is safer)",
    )

    # Consistency
    consistency_min: float = Field(default=0.65, ge=0.0, le=1.0)

    # Performance budgets (ms) — chat profile defaults
    latency_p50_ms: float = 2000.0
    latency_p95_ms: float = 5000.0
    latency_p99_ms: float = 8000.0
    ttft_p95_ms: float = 1500.0
    # Single-request soft budget used at validation time
    latency_request_max_ms: float = 8000.0
    ttft_request_max_ms: float = 2500.0

    # Conciseness budgets by profile
    chat_max_words: int = 450
    decision_max_words: int = 220
    chat_min_words: int = 40
    decision_min_words: int = 25

    # Completeness: Stage 13 required facets for chat
    require_citations: bool = True
    require_risks_section: bool = True


@lru_cache(maxsize=1)
def get_thresholds() -> QualityThresholds:
    return QualityThresholds()
