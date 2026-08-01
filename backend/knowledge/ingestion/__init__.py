"""Ingestion package — PDF → chunks → Chroma."""

from backend.knowledge.ingestion.pipeline import IngestPipeline, get_ingest_pipeline

__all__ = ["IngestPipeline", "get_ingest_pipeline"]
