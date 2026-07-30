"""Unit tests for Core Metrics validators."""

from __future__ import annotations

from backend.quality.config import QualityThresholds
from backend.quality.models import CitationRef, ValidationContext
from backend.quality.validators import (
    score_bias,
    score_coherence,
    score_completeness,
    score_conciseness,
    score_consistency,
    score_relevance,
    score_toxicity,
)

THRESHOLDS = QualityThresholds()


def _ctx(**kwargs: object) -> ValidationContext:
    base = {
        "query": "When should I rebalance a gamma scalp?",
        "answer": (
            "Rebalance a gamma scalp when delta drifts past your hedge threshold. "
            "In practice retail traders widen bands for slippage. "
            "Risks and assumptions: costs can erase edge."
        ),
        "citations": [
            CitationRef(
                document_id="doc-gamma",
                document="Gamma Scalping",
                section="Dynamic Hedging",
                page=132,
                chunk_id="doc-gamma_c003",
            )
        ],
        "profile": "chat",
        "faithfulness_ok": True,
    }
    base.update(kwargs)
    return ValidationContext(**base)  # type: ignore[arg-type]


def test_relevance_passes_for_on_topic_answer():
    score = score_relevance(_ctx(), THRESHOLDS)
    assert score.passed
    assert score.score >= THRESHOLDS.relevance_min


def test_relevance_fails_for_off_topic_answer():
    score = score_relevance(
        _ctx(answer="The weather in Paris is lovely today with sunny skies."),
        THRESHOLDS,
    )
    assert not score.passed


def test_coherence_flags_same_sentence_contradiction():
    score = score_coherence(
        _ctx(answer="You should always buy and never buy the same hedge."),
        THRESHOLDS,
    )
    assert score.score < 1.0


def test_completeness_requires_citations_and_risks():
    score = score_completeness(
        _ctx(answer="Just rebalance sometimes.", citations=[]),
        THRESHOLDS,
    )
    assert not score.passed


def test_conciseness_penalizes_verbosity():
    long_answer = " ".join(["word"] * 900) + " Risks and assumptions apply."
    score = score_conciseness(_ctx(answer=long_answer), THRESHOLDS)
    assert not score.passed


def test_toxicity_blocks_harmful_content():
    score = score_toxicity(
        _ctx(answer="You are an idiot and should kill yourself."),
        THRESHOLDS,
    )
    assert not score.passed
    assert score.score < 0.5


def test_chat_service_blocks_toxic_user_query():
    from backend.models.chat import ChatRequest
    from backend.services.chat_service import ChatService

    svc = ChatService()
    resp = svc.answer(
        ChatRequest(message="kill yourself you idiot — also explain gamma?")
    )
    assert resp.quality_action is not None
    assert resp.quality_action.value == "block"
    assert resp.metadata.get("blocked_reason") == "input_toxicity"


def test_bias_blocks_guaranteed_profit_language():
    score = score_bias(
        _ctx(answer="This strategy is guaranteed risk-free and a sure thing."),
        THRESHOLDS,
    )
    assert not score.passed


def test_consistency_compares_prior_answer():
    prior = _ctx().answer
    score = score_consistency(_ctx(prior_answer=prior), THRESHOLDS)
    assert score.passed
    assert score.score >= 0.9

    score_divergent = score_consistency(
        _ctx(prior_answer="Completely unrelated prior text about bananas."),
        THRESHOLDS,
    )
    assert score_divergent.score < score.score
