"""Knowledge ingest + status endpoints (architecture.md §7.7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.knowledge.ingestion.pipeline import get_ingest_pipeline
from backend.knowledge.retrieval.service import get_rag_service

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


class IngestRequest(BaseModel):
    track: str = Field(default="B1", description="B1 = Volatility Trading.pdf only")


class IngestResponse(BaseModel):
    document_ids: list[str]
    chunk_count: int
    collection: str
    version: str
    ingested_at: str
    details: list[dict[str, Any]]


@router.post("/ingest", response_model=IngestResponse)
async def ingest_knowledge(body: IngestRequest | None = None) -> IngestResponse:
    """Trigger re-ingestion. Track B1 indexes Volatility Trading.pdf only."""
    track = (body.track if body else "B1").upper()
    if track != "B1":
        raise HTTPException(
            status_code=400,
            detail="Only track=B1 is implemented; remaining PDFs are Track B2",
        )
    result = get_ingest_pipeline().ingest_b1()
    return IngestResponse(
        document_ids=result.document_ids,
        chunk_count=result.chunk_count,
        collection=result.collection,
        version=result.version,
        ingested_at=result.ingested_at,
        details=result.details,
    )


@router.get("/status")
async def knowledge_status() -> dict[str, Any]:
    return get_rag_service().status()
