"""Consistency: variance in response quality/content for the same query."""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_consistency(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    """Compare current answer to a prior answer for the same query when available."""
    evidence: list[str] = []

    if not ctx.prior_answer:
        # No baseline — treat as pass with neutral score (insufficient data)
        return MetricScore(
            name=MetricName.consistency,
            category=MetricCategory.performance,
            score=1.0,
            passed=True,
            threshold=thresholds.consistency_min,
            detail="No prior answer to compare — consistency deferred",
            evidence=["prior_answer absent"],
        )

    similarity = _jaccard(_token_set(ctx.answer), _token_set(ctx.prior_answer))
    evidence.append(f"jaccard_similarity={similarity:.2f}")

    # Also check citation set stability when both have citations
    if ctx.citations and ctx.metadata.get("prior_citation_ids"):
        prior_ids = set(ctx.metadata["prior_citation_ids"])
        current_ids = {c.chunk_id or c.document_id for c in ctx.citations}
        cite_sim = _jaccard(current_ids, prior_ids)
        similarity = 0.7 * similarity + 0.3 * cite_sim
        evidence.append(f"citation_jaccard={cite_sim:.2f}")

    score = similarity
    passed = score >= thresholds.consistency_min
    return MetricScore(
        name=MetricName.consistency,
        category=MetricCategory.performance,
        score=round(score, 3),
        passed=passed,
        threshold=thresholds.consistency_min,
        detail="Response consistent with prior answer for this query"
        if passed
        else "High variance vs prior answer for the same query",
        evidence=evidence,
    )
