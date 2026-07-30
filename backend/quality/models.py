"""Pydantic models for Quality, Safety & Performance validations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MetricCategory(str, Enum):
    quality = "quality"
    safety = "safety"
    performance = "performance"


class MetricName(str, Enum):
    relevance = "relevance"
    coherence = "coherence"
    completeness = "completeness"
    conciseness = "conciseness"
    toxicity = "toxicity"
    bias = "bias"
    consistency = "consistency"
    latency = "latency"


class ValidationAction(str, Enum):
    """What the pipeline should do after scoring."""

    pass_through = "pass_through"
    warn = "warn"
    regenerate = "regenerate"
    block = "block"


class MetricScore(BaseModel):
    name: MetricName
    category: MetricCategory
    score: float = Field(ge=0.0, le=1.0, description="Normalized 0–1 score")
    passed: bool
    threshold: float
    detail: str
    evidence: list[str] = Field(default_factory=list)


class CitationRef(BaseModel):
    document_id: str
    document: str | None = None
    section: str | None = None
    page: int | None = None
    chunk_id: str | None = None


class ValidationContext(BaseModel):
    """Inputs available to validators for a single bot response."""

    query: str
    answer: str
    citations: list[CitationRef] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    profile: str = Field(
        default="chat",
        description="Prompt profile: chat | decision",
    )
    session_id: str | None = None
    decision_id: str | None = None
    faithfulness_ok: bool | None = None
    latency_ms: float | None = None
    ttft_ms: float | None = None
    prior_answer: str | None = Field(
        default=None,
        description="Previous answer for the same query (consistency check)",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Aggregated Quality / Safety / Performance report for one response."""

    passed: bool
    action: ValidationAction
    scores: list[MetricScore]
    quality_score: float = Field(ge=0.0, le=1.0)
    safety_ok: bool
    performance_ok: bool
    blocking_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def score_map(self) -> dict[str, float]:
        return {s.name.value: s.score for s in self.scores}
