"""Chat service: RAG retrieval + Groq (or extractive fallback) + quality gate."""

from __future__ import annotations

import re
from collections import OrderedDict
from threading import Lock

from backend.knowledge.retrieval.service import build_prompt, get_rag_service
from backend.llm.groq_client import get_groq_client
from backend.models.chat import ChatRequest, ChatResponse
from backend.quality.config import get_thresholds
from backend.quality.latency import get_latency_tracker
from backend.quality.models import CitationRef, ValidationAction, ValidationContext
from backend.quality.pipeline import QualityPipeline
from backend.quality.validators.toxicity import toxicity_raw

_PRIOR_LOCK = Lock()
_PRIOR_ANSWERS: OrderedDict[str, str] = OrderedDict()
_PRIOR_MAX = 256

_SYSTEM = (
    "You are Bhale Bullodu's volatility trading desk assistant. "
    "Ground every factual claim in the provided context. "
    "Refuse to guess when context is insufficient. "
    "Never execute or place trades. Educational answers only."
)


def _prior_key(req: ChatRequest) -> str:
    session = req.session_id or "anon"
    normalized = re.sub(r"\s+", " ", req.message.strip().lower())
    return f"{session}::{normalized}"


def _get_prior(key: str) -> str | None:
    with _PRIOR_LOCK:
        return _PRIOR_ANSWERS.get(key)


def _store_prior(key: str, answer: str) -> None:
    with _PRIOR_LOCK:
        _PRIOR_ANSWERS[key] = answer
        while len(_PRIOR_ANSWERS) > _PRIOR_MAX:
            _PRIOR_ANSWERS.popitem(last=False)


def _extractive_answer(question: str, chunks: list, citations: list[CitationRef]) -> str:
    """Offline / no-Groq fallback: stitch top chunks with required structure."""
    excerpts: list[str] = []
    for chunk in chunks[:3]:
        excerpt = (chunk.text or "").strip()
        if len(excerpt) > 520:
            excerpt = excerpt[:520].rsplit(" ", 1)[0] + "…"
        meta = chunk.metadata
        label = meta.get("chapter") or meta.get("section") or "Context"
        excerpts.append(f"({label}, p.{meta.get('page', '?')}) {excerpt}")
    body = "\n\n".join(excerpts)
    cite = citations[0] if citations else None
    cite_line = ""
    if cite:
        cite_line = (
            f"Source: {cite.document or cite.document_id}"
            f"{f' · {cite.section}' if cite.section else ''}"
            f"{f' · p.{cite.page}' if cite.page is not None else ''}."
        )
    return (
        f"Based on the retrieved Volatility Trading context for "
        f"“{question.strip()}”:\n\n{body}\n\n"
        f"Practical trading implications: treat this as educational desk knowledge; "
        f"validate against live marks and risk gates before any action. "
        f"Risks and assumptions: retrieval may miss nuance; confirm page citations. "
        f"{cite_line}"
    )


def _insufficient() -> tuple[str, list[CitationRef], bool]:
    return (
        (
            "I do not have enough grounded context in the knowledge base for "
            "that question yet. Track B1 currently indexes Volatility Trading.pdf — "
            "try questions about option Greeks, delta hedge, GARCH vs implied "
            "volatility, or volatility trading rules. Risks and assumptions: without "
            "retrieved citations the answer should not gate trades."
        ),
        [],
        False,
    )


def _generate_answer(
    req: ChatRequest,
) -> tuple[str, list[CitationRef], bool, dict]:
    rag = get_rag_service()
    strategy = req.filters.strategy if req.filters else None
    chunks = rag.retrieve(req.message, top_k=5, strategy=strategy)
    if not chunks:
        answer, citations, ok = _insufficient()
        return answer, citations, ok, {"retrieval": "empty"}

    citations = [c.citation() for c in chunks]
    prompt = build_prompt(req.message, chunks)
    groq = get_groq_client()
    meta: dict = {
        "retrieval": "hybrid",
        "chunk_ids": [c.chunk_id for c in chunks],
        "llm": "groq" if groq.available else "extractive",
    }
    if groq.available:
        try:
            answer = groq.complete(system=_SYSTEM, user=prompt)
            if not answer.strip():
                answer = _extractive_answer(req.message, chunks, citations)
                meta["llm"] = "extractive_empty_completion"
        except Exception as exc:
            answer = _extractive_answer(req.message, chunks, citations)
            meta["llm"] = "extractive_groq_error"
            meta["groq_error"] = str(exc)[:200]
    else:
        answer = _extractive_answer(req.message, chunks, citations)

    return answer, citations, True, meta


class ChatService:
    def __init__(self) -> None:
        self.pipeline = QualityPipeline()
        self.tracker = get_latency_tracker()

    def answer(self, req: ChatRequest) -> ChatResponse:
        with self.tracker.measure("chat") as timed:
            timed.mark_first_token()

            input_tox, _ = toxicity_raw(req.message)
            if input_tox > get_thresholds().toxicity_max:
                answer = (
                    "I cannot process that message because it failed safety "
                    "validation. Please rephrase your question about volatility "
                    "trading concepts. Risks and assumptions: safety filters are "
                    "conservative by design."
                )
                ctx = ValidationContext(
                    query="[redacted unsafe input]",
                    answer=answer,
                    citations=[],
                    profile="chat",
                    session_id=req.session_id,
                    faithfulness_ok=False,
                )
                report = self.pipeline.evaluate(ctx)
                timed.success = False
                total_ms = timed.finish(success=False)
                ctx = ctx.model_copy(
                    update={"latency_ms": total_ms, "ttft_ms": timed.ttft_ms}
                )
                report = self.pipeline.evaluate(ctx)
                return ChatResponse(
                    answer=answer,
                    citations=[],
                    faithfulness_ok=False,
                    quality=report,
                    quality_action=ValidationAction.block,
                    latency_ms=total_ms,
                    ttft_ms=timed.ttft_ms,
                    metadata={"blocked_reason": "input_toxicity"},
                )

            answer, citations, faithfulness_ok, rag_meta = _generate_answer(req)
            key = _prior_key(req)
            prior = _get_prior(key)

            ctx = ValidationContext(
                query=req.message,
                answer=answer,
                citations=citations,
                retrieved_chunk_ids=[c.chunk_id or c.document_id for c in citations],
                profile="chat",
                session_id=req.session_id,
                decision_id=req.decision_id,
                faithfulness_ok=faithfulness_ok,
                prior_answer=prior,
            )
            report = self.pipeline.evaluate(ctx)

            if report.action == ValidationAction.regenerate and faithfulness_ok:
                answer = (
                    f"{answer} "
                    "Additional note: always size positions for retail capital "
                    "limits and treat the above as educational, not an order."
                )
                ctx = ctx.model_copy(update={"answer": answer})
                report = self.pipeline.evaluate(ctx)

            if report.action == ValidationAction.block:
                answer = (
                    "I cannot provide that response because it failed safety "
                    "validation (toxicity or biased/overconfident advice). "
                    "Please rephrase your question about volatility trading "
                    "concepts. Risks and assumptions: safety filters are "
                    "conservative by design."
                )
                citations = []
                faithfulness_ok = False
                ctx = ValidationContext(
                    query=req.message,
                    answer=answer,
                    citations=[],
                    profile="chat",
                    session_id=req.session_id,
                    faithfulness_ok=False,
                    prior_answer=prior,
                )
                report = self.pipeline.evaluate(ctx)

            timed.success = report.action != ValidationAction.block
            total_ms = timed.finish(success=timed.success)
            ctx = ctx.model_copy(
                update={"latency_ms": total_ms, "ttft_ms": timed.ttft_ms}
            )
            report = self.pipeline.evaluate(ctx)

            if report.action != ValidationAction.block:
                _store_prior(key, answer)

            return ChatResponse(
                answer=answer,
                citations=citations,
                faithfulness_ok=faithfulness_ok and report.passed,
                quality=report,
                quality_action=report.action,
                latency_ms=total_ms,
                ttft_ms=timed.ttft_ms,
                metadata={
                    "session_id": req.session_id,
                    "decision_id": req.decision_id,
                    "filters": req.filters.model_dump() if req.filters else None,
                    **rag_meta,
                },
            )


_CHAT_SERVICE: ChatService | None = None


def get_chat_service() -> ChatService:
    global _CHAT_SERVICE
    if _CHAT_SERVICE is None:
        _CHAT_SERVICE = ChatService()
    return _CHAT_SERVICE
