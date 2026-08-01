"""Hybrid retrieval + prompt build (architecture.md §7.3)."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from backend.knowledge.ingestion.pipeline import get_ingest_pipeline
from backend.knowledge.vectorstore.bm25_index import BM25Corpus
from backend.knowledge.vectorstore.chroma_store import (
    ChromaKnowledgeStore,
    get_chroma_store,
)
from backend.quality.models import CitationRef

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float

    def citation(self) -> CitationRef:
        meta = self.metadata
        page = meta.get("page")
        # Prefer chapter for citation chips (stable TOC label); fall back to section.
        section = meta.get("chapter") or meta.get("section")
        return CitationRef(
            document_id=str(meta.get("document_id") or ""),
            document=meta.get("document"),
            section=section,
            page=int(page) if page is not None else None,
            chunk_id=self.chunk_id,
        )


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    payload: dict[str, dict[str, Any]] = {}
    for ranked in ranked_lists:
        for rank, row in enumerate(ranked, start=1):
            cid = row["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            payload[cid] = row
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out: list[dict[str, Any]] = []
    for cid, score in ordered:
        row = dict(payload[cid])
        row["rrf_score"] = score
        out.append(row)
    return out


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = ["## Context\n"]
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        blocks.append(f"### Source {i}")
        blocks.append(f"- Document: {meta.get('document', '')}")
        blocks.append(f"- Chapter: {meta.get('chapter', '')}")
        blocks.append(f"- Section: {meta.get('section', '')}")
        blocks.append(f"- Page: {meta.get('page', '')}")
        blocks.append(f"- Chunk ID: {chunk.chunk_id}")
        blocks.append(f"- Content: {chunk.text}\n")
    blocks.append(f"## Question\n{question}\n")
    blocks.append(
        "## Instructions\n"
        "- Answer using retrieved context only\n"
        "- Cite document, chapter/section, and page when available\n"
        "- State clearly if information is unavailable\n"
        "- Explain equations step by step when relevant\n"
        "- Include practical trading implications and risks/assumptions\n"
        "- Never place or recommend live orders; educational only\n"
    )
    return "\n".join(blocks)


class RAGService:
    def __init__(
        self,
        store: ChromaKnowledgeStore | None = None,
        bm25: BM25Corpus | None = None,
    ) -> None:
        self.store = store or get_chroma_store()
        self.bm25 = bm25 if bm25 is not None else BM25Corpus.shared()
        self._ensure_lock = threading.Lock()

    def ensure_ready(self) -> None:
        """Auto-ingest B1 PDF once when collection is empty (paper/dev convenience)."""
        with self._ensure_lock:
            if self.store.count() > 0 and self.bm25.ready:
                return
            if self.store.count() == 0:
                if os.getenv("RAG_AUTO_INGEST", "1").strip().lower() in {
                    "0",
                    "false",
                    "no",
                }:
                    return
                logger.info("Knowledge base empty — running Track B1 ingest")
                get_ingest_pipeline().ingest_b1()
                return
            if not self.bm25.ready:
                active = self.store.list_active_chunks()
                self.bm25.rebuild(active)
                self.bm25.mark_ready()

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        strategy: str | None = None,
        candidate_n: int = 50,
    ) -> list[RetrievedChunk]:
        self.ensure_ready()
        if not self.bm25.ready:
            return []

        where: dict[str, Any] | None = None
        if strategy:
            where = {"strategy": strategy}

        dense = self.store.query_dense(query, n_results=candidate_n, where=where)
        sparse = self.bm25.search(query, top_k=candidate_n)
        if strategy:
            sparse = [
                r
                for r in sparse
                if (r.get("metadata") or {}).get("strategy") == strategy
            ]

        # Hash embeddings are lexical-weak; prefer BM25 for CI / offline backends.
        embedding_backend = os.getenv("EMBEDDING_BACKEND", "default").strip().lower()
        if embedding_backend in {"hash", "test", "ci"} or not dense:
            fused = reciprocal_rank_fusion([sparse, sparse, dense] if dense else [sparse])
        else:
            fused = reciprocal_rank_fusion([dense, sparse])
        # Optional lightweight lexical re-rank among top candidates (B1: skip heavy cross-encoder)
        top = fused[: max(top_k * 4, top_k)]
        q_tokens = set(query.lower().split())
        for row in top:
            text = (row.get("text") or "").lower()
            overlap = len(q_tokens & set(text.split()))
            row["final_score"] = float(row.get("rrf_score", 0)) + 0.01 * overlap
        top.sort(key=lambda r: float(r.get("final_score", 0)), reverse=True)

        results: list[RetrievedChunk] = []
        for row in top[:top_k]:
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    text=row.get("text") or "",
                    metadata=row.get("metadata") or {},
                    score=float(row.get("final_score", row.get("rrf_score", 0))),
                )
            )
        return results

    def status(self) -> dict[str, Any]:
        self.ensure_ready()
        active = self.store.list_active_chunks()
        by_doc: dict[str, int] = {}
        for row in active:
            doc_id = str((row.get("metadata") or {}).get("document_id") or "unknown")
            by_doc[doc_id] = by_doc.get(doc_id, 0) + 1
        meta = self.store.get_ingest_meta()
        return {
            "collection": self.store.collection_name,
            "chunk_count": len(active),
            "chunks_by_document": by_doc,
            "bm25_ready": self.bm25.ready,
            "ingest": meta,
            "track": "B1",
            "active_documents": list(by_doc.keys()),
        }


_RAG: RAGService | None = None


def get_rag_service() -> RAGService:
    global _RAG
    if _RAG is None:
        _RAG = RAGService()
    return _RAG


def reset_rag_service_for_tests() -> None:
    global _RAG
    _RAG = None
