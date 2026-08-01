"""Metadata enrichment + ingest orchestration (architecture.md §7.2 Stages 6–9)."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from backend.knowledge.ingestion.chunk import RawChunk, chunk_pages
from backend.knowledge.ingestion.extract import extract_pages
from backend.knowledge.manifest import (
    COLLECTION_KNOWLEDGE,
    DocumentSpec,
    b1_documents,
)
from backend.knowledge.vectorstore.chroma_store import (
    ChromaKnowledgeStore,
    get_chroma_store,
)
from backend.knowledge.vectorstore.bm25_index import BM25Corpus

logger = logging.getLogger(__name__)


@dataclass
class EnrichedChunk:
    chunk_id: str
    document_id: str
    document: str
    version: str
    chapter: str
    section: str
    page: int
    heading_path: str
    topic: str
    difficulty: str
    strategy: str
    concepts: list[str]
    asset_class: str
    math_models: list[str]
    risk_category: list[str]
    content_type: str
    has_table: bool
    has_equation: bool
    text: str
    deprecated: bool = False

    def metadata(self) -> dict[str, Any]:
        meta = asdict(self)
        text = meta.pop("text")
        # Chroma metadata values must be str/int/float/bool
        meta["concepts"] = ",".join(self.concepts)
        meta["math_models"] = ",".join(self.math_models)
        meta["risk_category"] = ",".join(self.risk_category)
        meta["text_preview"] = text[:240]
        return meta


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s[:48] or "section"


def _content_type(chunk: RawChunk) -> str:
    lower = chunk.text.lower()
    if "rule" in lower or re.search(r"(?m)^\d+\)\s", chunk.text):
        return "procedure"
    if chunk.has_equation:
        return "derivation"
    if "example" in lower or "let's say" in lower:
        return "example"
    if "risk" in lower or "limitation" in lower:
        return "risk_note"
    return "definition"


def _difficulty(chunk: RawChunk) -> str:
    if chunk.has_equation or "garch" in chunk.text.lower():
        return "Advanced"
    if chunk.chapter in {"Introduction", "Basics of Derivatives"}:
        return "Beginner"
    return "Intermediate"


def _math_models(text: str) -> list[str]:
    models: list[str] = []
    lower = text.lower()
    if "black-scholes" in lower or "black scholes" in lower:
        models.append("Black-Scholes")
    if "garch" in lower:
        models.append("GARCH")
    return models


def _risk_cats(text: str) -> list[str]:
    lower = text.lower()
    cats: list[str] = []
    if "liquidity" in lower:
        cats.append("Liquidity Risk")
    if "margin" in lower or "retail" in lower:
        cats.append("Execution Risk")
    if "volatility" in lower or "vega" in lower or "gamma" in lower:
        cats.append("Volatility Risk")
    if "model" in lower or "garch" in lower:
        cats.append("Model Risk")
    return cats or ["Volatility Risk"]


def enrich_chunk(raw: RawChunk, spec: DocumentSpec, index: int) -> EnrichedChunk:
    chunk_id = (
        f"{spec.document_id}_{_slug(raw.chapter)}_{_slug(raw.section)}_c{index:03d}"
    )
    # Stable id if slug collision: append short hash
    digest = hashlib.sha1(raw.text.encode("utf-8")).hexdigest()[:6]
    chunk_id = f"{chunk_id}_{digest}"
    return EnrichedChunk(
        chunk_id=chunk_id,
        document_id=spec.document_id,
        document=spec.title,
        version=spec.version,
        chapter=raw.chapter,
        section=raw.section,
        page=raw.page,
        heading_path=raw.heading_path,
        topic=raw.concepts[0] if raw.concepts else raw.chapter,
        difficulty=_difficulty(raw),
        strategy=spec.strategy,
        concepts=raw.concepts,
        asset_class="Equity Options",
        math_models=_math_models(raw.text),
        risk_category=_risk_cats(raw.text),
        content_type=_content_type(raw),
        has_table=False,
        has_equation=raw.has_equation,
        text=raw.text,
    )


@dataclass
class IngestResult:
    document_ids: list[str]
    chunk_count: int
    collection: str
    version: str
    ingested_at: str
    details: list[dict[str, Any]]


class IngestPipeline:
    def __init__(
        self,
        store: ChromaKnowledgeStore | None = None,
        bm25: BM25Corpus | None = None,
    ) -> None:
        self.store = store or get_chroma_store()
        self.bm25 = bm25 if bm25 is not None else BM25Corpus.shared()

    def ingest_document(self, spec: DocumentSpec) -> dict[str, Any]:
        pages = extract_pages(spec.absolute_path)
        raw_chunks = chunk_pages(pages, document_title=spec.title)
        enriched = [enrich_chunk(c, spec, i) for i, c in enumerate(raw_chunks, start=1)]

        # Deprecate prior version chunks for this document_id
        self.store.deprecate_document(spec.document_id)

        ids = [c.chunk_id for c in enriched]
        documents = [c.text for c in enriched]
        metadatas = [c.metadata() for c in enriched]
        # Embedding payload: structural prefix + text (§7.2 Stage 7)
        embed_docs = [f"[{c.heading_path}]\n{c.text}" for c in enriched]
        self.store.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings_input=embed_docs,
        )
        return {
            "document_id": spec.document_id,
            "title": spec.title,
            "version": spec.version,
            "pages": len(pages),
            "chunks": len(enriched),
            "path": str(spec.relative_path),
        }

    def ingest_b1(self) -> IngestResult:
        docs = b1_documents()
        details: list[dict[str, Any]] = []
        total = 0
        for spec in docs:
            detail = self.ingest_document(spec)
            details.append(detail)
            total += int(detail["chunks"])

        # Rebuild BM25 from active chunks only
        active = self.store.list_active_chunks()
        self.bm25.rebuild(active)
        self.bm25.mark_ready()

        now = datetime.now(timezone.utc).isoformat()
        self.store.set_ingest_meta(
            {
                "last_ingest_at": now,
                "last_chunk_count": str(total),
                "track": "B1",
                "documents": ",".join(d.document_id for d in docs),
            }
        )
        logger.info("B1 ingest complete: %s chunks across %s docs", total, len(docs))
        return IngestResult(
            document_ids=[d.document_id for d in docs],
            chunk_count=total,
            collection=COLLECTION_KNOWLEDGE,
            version=docs[0].version if docs else "1.0",
            ingested_at=now,
            details=details,
        )


_PIPELINE: IngestPipeline | None = None


def get_ingest_pipeline() -> IngestPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = IngestPipeline()
    return _PIPELINE
