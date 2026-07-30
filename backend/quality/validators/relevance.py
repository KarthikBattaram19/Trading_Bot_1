"""Relevance: does the answer address the user's query?"""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "for",
        "with",
        "how",
        "what",
        "when",
        "where",
        "why",
        "which",
        "should",
        "i",
        "my",
        "me",
        "do",
        "does",
        "can",
        "could",
        "would",
        "about",
        "from",
        "this",
        "that",
        "it",
        "as",
        "at",
        "by",
        "if",
        "into",
        "than",
        "then",
        "too",
        "very",
    }
)

_DOMAIN_ALIASES: dict[str, set[str]] = {
    "gamma": {"gamma", "hedge", "delta", "scalp", "scalping"},
    "vega": {"vega", "vol", "volatility", "implied"},
    "theta": {"theta", "decay", "time"},
    "rebalance": {"rebalance", "rebalancing", "hedge", "adjust", "threshold"},
    "iv": {"iv", "implied", "volatility", "vol"},
    "retail": {"retail", "capital", "slippage", "spread", "margin"},
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _expand_query_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    for term in terms:
        for key, aliases in _DOMAIN_ALIASES.items():
            if term == key or term in aliases:
                expanded |= aliases
    return expanded


def _soft_coverage(query_terms: set[str], answer_terms: set[str]) -> tuple[float, int]:
    """Count exact and stem-like overlaps (scalp/scalping, vol/volatility)."""
    if not query_terms:
        return 1.0, 0
    hits = 0
    for q in query_terms:
        if q in answer_terms:
            hits += 1
            continue
        for a in answer_terms:
            if len(q) >= 4 and len(a) >= 4 and (a.startswith(q) or q.startswith(a)):
                hits += 1
                break
    return hits / len(query_terms), hits


def score_relevance(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    query_terms = _expand_query_terms(_tokens(ctx.query))
    answer_terms = _tokens(ctx.answer)
    evidence: list[str] = []

    if not query_terms:
        score = 1.0 if len(ctx.answer.strip()) > 20 else 0.0
        evidence.append("empty or stopword-only query")
    else:
        coverage, hit_count = _soft_coverage(query_terms, answer_terms)
        evidence.append(
            f"query-term coverage {coverage:.0%} ({hit_count}/{len(query_terms)})"
        )

        citation_bonus = 0.0
        if ctx.citations:
            citation_bonus = 0.1
            evidence.append(f"{len(ctx.citations)} citation(s) present")
        elif ctx.retrieved_chunk_ids:
            citation_bonus = 0.05

        # Soft penalty when answer ignores the question entirely
        if coverage == 0 and len(ctx.answer) > 40:
            score = 0.15
            evidence.append("no lexical overlap with query terms")
        else:
            # coverage dominates; citations and a base floor keep grounded answers above gate
            score = min(1.0, coverage * 0.85 + citation_bonus + 0.15)

    score = round(max(0.0, min(1.0, score)), 3)
    passed = score >= thresholds.relevance_min
    return MetricScore(
        name=MetricName.relevance,
        category=MetricCategory.quality,
        score=score,
        passed=passed,
        threshold=thresholds.relevance_min,
        detail="Addresses the user's query"
        if passed
        else "Answer does not sufficiently address the query",
        evidence=evidence,
    )
