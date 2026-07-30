"""Chat service: stub grounded answers + Core Metrics validation gate."""

from __future__ import annotations

import re
from collections import OrderedDict
from threading import Lock

from backend.models.chat import ChatRequest, ChatResponse
from backend.quality.latency import get_latency_tracker
from backend.quality.models import CitationRef, ValidationAction, ValidationContext
from backend.quality.pipeline import QualityPipeline
from backend.quality.validators.toxicity import toxicity_raw
from backend.quality.config import get_thresholds

# Simple in-memory prior answers for consistency checks (session-scoped).
_PRIOR_LOCK = Lock()
_PRIOR_ANSWERS: OrderedDict[str, str] = OrderedDict()
_PRIOR_MAX = 256

_KNOWLEDGE: list[dict[str, object]] = [
    {
        "keywords": {"gamma", "scalp", "scalping", "rebalance", "hedge", "delta"},
        "answer": (
            "Rebalance a gamma scalp when the net delta drifts beyond your hedge "
            "threshold (commonly driven by underlying moves and remaining gamma). "
            "In practice, retail traders should widen rebalance bands to limit "
            "transaction costs and slippage. Risks and assumptions: hedge frequency "
            "must stay retail-realistic; stale quotes and wide spreads can erase "
            "scalping edge."
        ),
        "citations": [
            CitationRef(
                document_id="doc-gamma",
                document="Gamma Scalping",
                section="Dynamic Hedging",
                page=132,
                chunk_id="doc-gamma_ch5_dynamic-hedging_c003",
            )
        ],
    },
    {
        "keywords": {"vega", "implied", "volatility", "vol"},
        "answer": (
            "Vega scalping seeks to monetize changes in implied volatility while "
            "managing directional exposure. Therefore, entries typically favor "
            "mispriced IV relative to a forecast, with hedges for delta. "
            "Practical trading implications for retail include capital limits and "
            "bid-ask costs on options. Risks and assumptions: IV can remain "
            "mispriced longer than expected; liquidity may vanish in stress."
        ),
        "citations": [
            CitationRef(
                document_id="doc-vega",
                document="Vega Scalping",
                section="Vega Trading Framework",
                page=48,
                chunk_id="doc-vega_ch3_framework_c012",
            )
        ],
    },
    {
        "keywords": {"theta", "decay", "time"},
        "answer": (
            "Theta measures time decay of option premium. Long premium strategies "
            "pay theta; short premium strategies collect it, all else equal. "
            "In practice, theta interacts with gamma and vega, so isolated theta "
            "views are incomplete. Risks and assumptions: overnight gaps and "
            "volatility shocks can dominate decay P/L."
        ),
        "citations": [
            CitationRef(
                document_id="doc-vol",
                document="Volatility Trading",
                section="The Greeks",
                page=61,
                chunk_id="doc-vol_ch4_greeks_c008",
            )
        ],
    },
]


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


def _retrieve_stub(message: str) -> tuple[str, list[CitationRef], bool]:
    tokens = set(re.findall(r"[a-z0-9]+", message.lower()))
    best: dict[str, object] | None = None
    best_hits = 0
    for entry in _KNOWLEDGE:
        keywords = entry["keywords"]
        assert isinstance(keywords, set)
        hits = len(tokens & keywords)
        if hits > best_hits:
            best_hits = hits
            best = entry

    if best is None or best_hits == 0:
        return (
            (
                "I do not have enough grounded context in the knowledge base for "
                "that question yet. Try asking about gamma scalping rebalances, "
                "vega/IV trades, or theta decay. Risks and assumptions: without "
                "retrieved citations the answer should not gate trades."
            ),
            [],
            False,
        )

    answer = best["answer"]
    citations = best["citations"]
    assert isinstance(answer, str)
    assert isinstance(citations, list)
    return answer, citations, True


class ChatService:
    def __init__(self) -> None:
        self.pipeline = QualityPipeline()
        self.tracker = get_latency_tracker()

    def answer(self, req: ChatRequest) -> ChatResponse:
        with self.tracker.measure("chat") as timed:
            timed.mark_first_token()

            # Input safety screen (query only)
            input_tox, _ = toxicity_raw(req.message)
            if input_tox > get_thresholds().toxicity_max:
                answer = (
                    "I cannot process that message because it failed safety "
                    "validation. Please rephrase your question about volatility "
                    "trading concepts. Risks and assumptions: safety filters are "
                    "conservative by design."
                )
                citations: list[CitationRef] = []
                faithfulness_ok = False
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

            answer, citations, faithfulness_ok = _retrieve_stub(req.message)
            key = _prior_key(req)
            prior = _get_prior(key)

            # First-pass validation
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

            # One regenerate attempt for quality gaps (deterministic stub rewrite)
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
                },
            )


_CHAT_SERVICE: ChatService | None = None


def get_chat_service() -> ChatService:
    global _CHAT_SERVICE
    if _CHAT_SERVICE is None:
        _CHAT_SERVICE = ChatService()
    return _CHAT_SERVICE
