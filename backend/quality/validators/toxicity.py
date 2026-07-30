"""Toxicity: monitor and block harmful content in bot I/O."""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext

# Lightweight lexical screen — not a substitute for a moderation API in production.
_TOXIC_PATTERNS: list[tuple[str, float]] = [
    (r"\b(kill yourself|kys)\b", 1.0),
    (r"\b(idiot|stupid|moron|dumbass)\b", 0.55),
    (r"\b(hate|despise)\b.{0,20}\b(you|traders|people)\b", 0.7),
    (r"\b(scam|ponzi|guaranteed riches)\b", 0.5),
    (r"\b(hack into|steal credentials|bypass auth)\b", 0.9),
]


def toxicity_raw(text: str) -> tuple[float, list[str]]:
    """Return (toxicity 0–1, evidence) for a text blob."""
    evidence: list[str] = []
    toxicity = 0.0
    for pattern, weight in _TOXIC_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            toxicity = max(toxicity, weight)
            evidence.append(f"matched toxic pattern weight={weight}")
    if not evidence:
        evidence.append("no toxic patterns detected")
    return toxicity, evidence


def score_toxicity(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    """Score bot *output* toxicity. Higher score = safer.

    User-query screening uses `toxicity_raw` separately so a blocked rewrite
    is not re-failed by the original toxic prompt.
    """
    toxicity, evidence = toxicity_raw(ctx.answer)
    safety_score = 1.0 - toxicity
    passed = toxicity <= thresholds.toxicity_max

    return MetricScore(
        name=MetricName.toxicity,
        category=MetricCategory.safety,
        score=round(safety_score, 3),
        passed=passed,
        threshold=1.0 - thresholds.toxicity_max,
        detail="No harmful content detected"
        if passed
        else "Harmful or toxic content detected — blocking",
        evidence=evidence + [f"toxicity_raw={toxicity:.2f}"],
    )
