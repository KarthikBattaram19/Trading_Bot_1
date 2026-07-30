"""Conciseness: no verbosity — brief and to the point within profile budgets."""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext

_FILLER = re.compile(
    r"\b(as an ai|it is important to note|in conclusion|to summarize|"
    r"needless to say|at the end of the day|in today's market)\b",
    re.IGNORECASE,
)


def score_conciseness(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    words = re.findall(r"\b\w+\b", ctx.answer)
    word_count = len(words)
    evidence: list[str] = [f"word_count={word_count}"]

    if ctx.profile == "decision":
        max_words = thresholds.decision_max_words
        min_words = thresholds.decision_min_words
    else:
        max_words = thresholds.chat_max_words
        min_words = thresholds.chat_min_words

    if word_count == 0:
        score = 0.0
        evidence.append("empty answer")
    elif word_count < min_words:
        # Too terse can hurt completeness; mild penalty only
        score = 0.75
        evidence.append(f"below min budget ({min_words} words)")
    elif word_count <= max_words:
        # Ideal band
        ratio = word_count / max_words
        score = 1.0 - 0.15 * ratio  # slight preference for tighter answers
        evidence.append(f"within budget (max {max_words})")
    else:
        overshoot = (word_count - max_words) / max_words
        # Steep penalty so 1.3× budget fails the default 0.60 gate
        score = max(0.0, 1.0 - overshoot * 1.5)
        evidence.append(f"exceeds budget by {overshoot:.0%}")

    fillers = _FILLER.findall(ctx.answer)
    if fillers:
        score = max(0.0, score - 0.1 * min(len(fillers), 3))
        evidence.append(f"filler phrases: {len(fillers)}")

    score = round(max(0.0, min(1.0, score)), 3)
    passed = score >= thresholds.conciseness_min
    return MetricScore(
        name=MetricName.conciseness,
        category=MetricCategory.quality,
        score=score,
        passed=passed,
        threshold=thresholds.conciseness_min,
        detail="Brief and to the point"
        if passed
        else "Response is overly verbose for the profile",
        evidence=evidence,
    )
