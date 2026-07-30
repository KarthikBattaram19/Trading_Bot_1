"""Chat request/response contracts with quality validation fields."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quality.models import CitationRef, ValidationAction, ValidationReport


class ChatFilters(BaseModel):
    strategy: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    filters: ChatFilters | None = None
    decision_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationRef] = Field(default_factory=list)
    faithfulness_ok: bool = True
    quality: ValidationReport | None = None
    quality_action: ValidationAction | None = None
    latency_ms: float | None = None
    ttft_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
