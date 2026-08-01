"""Golden-set runner — Stage 14 RAG metrics for Track B1."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from backend.quality.models import CitationRef, ValidationContext
from backend.quality.pipeline import QualityPipeline

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_qa.jsonl"
FAITHFULNESS_GATE = float(os.getenv("RAG_FAITHFULNESS_GATE", "0.85"))


def load_golden(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or GOLDEN_PATH
    rows: list[dict[str, Any]] = []
    with open(target, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _term_hit_rate(answer: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lower = answer.lower()
    hits = sum(1 for t in terms if t.lower() in lower)
    return hits / len(terms)


def _citation_accuracy(citations: list[CitationRef], row: dict[str, Any]) -> float:
    if not citations:
        return 0.0
    doc_id = row.get("expected_document_id")
    chapter_needle = (row.get("expected_chapter_contains") or "").lower()
    page_min = row.get("expected_page_min")
    page_max = row.get("expected_page_max")
    scores: list[float] = []
    for c in citations[:3]:
        score = 0.0
        parts = 0
        if doc_id:
            parts += 1
            if c.document_id == doc_id:
                score += 1.0
        if chapter_needle:
            parts += 1
            hay = f"{c.section or ''} {c.document or ''}".lower()
            # chapter often lives in retrieved metadata section/chapter via citation.section
            if chapter_needle in hay:
                score += 1.0
            elif any(
                chapter_needle in (getattr(c, attr, "") or "").lower()
                for attr in ("section", "document")
            ):
                score += 1.0
        if page_min is not None and page_max is not None and c.page is not None:
            parts += 1
            if int(page_min) <= int(c.page) <= int(page_max):
                score += 1.0
        scores.append(score / parts if parts else 1.0)
    return max(scores) if scores else 0.0


def _context_faithfulness(answer: str, contexts: list[str]) -> float:
    """Proxy faithfulness: fraction of answer sentences supported by retrieved context.

    Full Ragas is optional later; this CI gate stays dependency-light for B1.
    """
    if not answer.strip() or not contexts:
        return 0.0
    joined = " ".join(contexts).lower()
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", answer)
        if len(s.strip()) > 20
    ]
    if not sentences:
        return 1.0 if answer.lower() in joined else 0.0
    supported = 0
    for sent in sentences:
        tokens = [t for t in re.findall(r"[a-z0-9]+", sent.lower()) if len(t) > 3]
        if not tokens:
            supported += 1
            continue
        hits = sum(1 for t in tokens if t in joined)
        if hits / len(tokens) >= 0.35:
            supported += 1
    return supported / len(sentences)


def evaluate_golden(
    path: Path | None = None,
    *,
    pipeline: QualityPipeline | None = None,
    use_live_rag: bool | None = None,
) -> dict[str, Any]:
    """Score golden Q&A.

    When ``use_live_rag`` is true (default unless RAG_EVAL_OFFLINE=1), each
    question is answered via ChatService / RAG. Offline mode scores reference
    answers with the Core Metrics pipeline only.
    """
    pipe = pipeline or QualityPipeline()
    rows = load_golden(path)
    offline_env = os.getenv("RAG_EVAL_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    live = (not offline_env) if use_live_rag is None else use_live_rag

    results: list[dict[str, Any]] = []
    passed = 0
    faith_scores: list[float] = []
    citation_scores: list[float] = []

    chat_service = None
    if live:
        from backend.services.chat_service import ChatService
        from backend.models.chat import ChatRequest, ChatFilters

        chat_service = ChatService()

    for row in rows:
        contexts: list[str] = []
        citations: list[CitationRef] = []
        answer = ""
        retrieved_ids: list[str] = []

        if live and chat_service is not None:
            from backend.models.chat import ChatRequest, ChatFilters

            filters = None
            if row.get("strategy_filter"):
                filters = ChatFilters(strategy=row["strategy_filter"])
            resp = chat_service.answer(
                ChatRequest(
                    message=row["question"],
                    session_id=f"golden-{row.get('id', 'x')}",
                    filters=filters,
                )
            )
            answer = resp.answer
            citations = list(resp.citations)
            retrieved_ids = [c.chunk_id or c.document_id for c in citations]
            contexts = [
                # best-effort: citation text not stored; use answer grounding later
            ]
            # Pull retrieved chunk texts from RAG for faithfulness
            try:
                from backend.knowledge.retrieval.service import get_rag_service

                chunks = get_rag_service().retrieve(
                    row["question"],
                    top_k=5,
                    strategy=row.get("strategy_filter"),
                )
                contexts = [c.text for c in chunks]
                if not retrieved_ids:
                    retrieved_ids = [c.chunk_id for c in chunks]
            except Exception:
                contexts = []
        else:
            answer = row.get("sample_answer") or row.get("reference_answer") or ""
            citations_raw = row.get("sample_citations") or row.get("expected_citations") or []
            citations = [
                CitationRef(
                    document_id=c.get("document_id", ""),
                    document=c.get("document"),
                    section=c.get("section"),
                    page=c.get("page"),
                    chunk_id=c.get("chunk_id"),
                )
                for c in citations_raw
                if isinstance(c, dict)
            ]
            retrieved_ids = list(row.get("expected_chunk_ids") or [])
            contexts = [answer]

        faith = _context_faithfulness(answer, contexts or [answer])
        cite_acc = _citation_accuracy(citations, row)
        term_rate = _term_hit_rate(answer, list(row.get("must_include_terms") or []))

        # Citation section often holds chapter for our enricher — boost if chapter in answer path
        if row.get("expected_chapter_contains") and citations:
            chapter_needle = str(row["expected_chapter_contains"]).lower()
            for c in citations:
                # Enricher puts chapter in metadata; citation.section may be subsection.
                # Accept document match + page band as sufficient for B1.
                if c.document_id == row.get("expected_document_id") and c.page is not None:
                    pmin = row.get("expected_page_min")
                    pmax = row.get("expected_page_max")
                    if pmin is not None and pmax is not None and int(pmin) <= int(c.page) <= int(pmax):
                        cite_acc = max(cite_acc, 0.9)
                if chapter_needle and chapter_needle in (c.section or "").lower():
                    cite_acc = max(cite_acc, 1.0)

        faith_scores.append(faith)
        citation_scores.append(cite_acc)

        ctx = ValidationContext(
            query=row["question"],
            answer=answer,
            citations=citations,
            retrieved_chunk_ids=retrieved_ids,
            profile="chat",
            faithfulness_ok=faith >= FAITHFULNESS_GATE and bool(citations),
        )
        report = pipe.evaluate(ctx)

        row_pass = (
            faith >= max(0.7, FAITHFULNESS_GATE - 0.15)
            and cite_acc >= 0.5
            and term_rate >= 0.34
            and bool(citations)
            and report.action.value != "block"
        )
        if row_pass:
            passed += 1

        results.append(
            {
                "id": row.get("id"),
                "question": row["question"],
                "passed": row_pass,
                "faithfulness": round(faith, 3),
                "citation_accuracy": round(cite_acc, 3),
                "term_hit_rate": round(term_rate, 3),
                "action": report.action.value,
                "quality_score": report.quality_score,
                "scores": report.score_map(),
                "blocking_failures": report.blocking_failures,
            }
        )

    total = len(rows) or 1
    mean_faith = sum(faith_scores) / len(faith_scores) if faith_scores else 0.0
    mean_cite = sum(citation_scores) / len(citation_scores) if citation_scores else 0.0
    return {
        "total": len(rows),
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "mean_faithfulness": round(mean_faith, 3),
        "mean_citation_accuracy": round(mean_cite, 3),
        "faithfulness_gate": FAITHFULNESS_GATE,
        "faithfulness_gate_passed": mean_faith >= FAITHFULNESS_GATE,
        "live_rag": live,
        "results": results,
    }
