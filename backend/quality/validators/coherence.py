"""Coherence: logical flow without contradictions or fragmentation."""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext

_CONTRADICTION_PAIRS = (
    (r"\balways\b", r"\bnever\b"),
    (r"\bincrease[sd]?\b", r"\bdecrease[sd]?\b"),
    (r"\blong\b", r"\bshort\b"),
    (r"\bbuy\b", r"\bsell\b"),
)


def score_coherence(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    answer = ctx.answer.strip()
    evidence: list[str] = []
    score = 1.0

    if not answer:
        return MetricScore(
            name=MetricName.coherence,
            category=MetricCategory.quality,
            score=0.0,
            passed=False,
            threshold=thresholds.coherence_min,
            detail="Empty answer has no coherent flow",
            evidence=["empty answer"],
        )

    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip()]
    if len(sentences) < 2 and len(answer.split()) > 80:
        score -= 0.15
        evidence.append("long answer with weak sentence structure")

    # Abrupt fragmentation: many very short sentences
    short = sum(1 for s in sentences if len(s.split()) <= 3)
    if sentences and short / len(sentences) > 0.5 and len(sentences) >= 4:
        score -= 0.2
        evidence.append("fragmented short-sentence pattern")

    # Same-sentence contradiction heuristics
    lower = answer.lower()
    for pos_pat, neg_pat in _CONTRADICTION_PAIRS:
        if re.search(pos_pat, lower) and re.search(neg_pat, lower):
            # Only penalize if both appear in a tight window (same sentence)
            for sentence in sentences:
                s_lower = sentence.lower()
                if re.search(pos_pat, s_lower) and re.search(neg_pat, s_lower):
                    score -= 0.25
                    evidence.append(
                        f"possible contradiction in sentence: '{sentence[:80]}'"
                    )
                    break

    # Repeated identical sentences
    if len(sentences) >= 3:
        unique_ratio = len(set(s.lower() for s in sentences)) / len(sentences)
        if unique_ratio < 0.6:
            score -= 0.2
            evidence.append("high sentence repetition")

    score = max(0.0, min(1.0, score))
    if not evidence:
        evidence.append("logical flow looks intact")

    passed = score >= thresholds.coherence_min
    return MetricScore(
        name=MetricName.coherence,
        category=MetricCategory.quality,
        score=round(score, 3),
        passed=passed,
        threshold=thresholds.coherence_min,
        detail="Logical flow of information"
        if passed
        else "Answer flow is fragmented or contradictory",
        evidence=evidence,
    )
