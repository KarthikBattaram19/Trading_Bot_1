"""Completeness: Stage 13 facets — answer, implications, risks, citations."""

from __future__ import annotations

import re

from backend.quality.config import QualityThresholds
from backend.quality.models import MetricCategory, MetricName, MetricScore, ValidationContext

_RISK_PATTERNS = re.compile(
    r"\b(risk|risks|assumption|assumptions|caution|drawdown|slippage|"
    r"limitation|limitations|warning|caveat)\b",
    re.IGNORECASE,
)
_IMPLICATION_PATTERNS = re.compile(
    r"\b(implication|implications|practically|in practice|for retail|"
    r"trading implication|means that|therefore)\b",
    re.IGNORECASE,
)
_MATH_PATTERNS = re.compile(
    r"(\$|\\frac|delta|gamma|vega|theta|σ|√|\bBS\b|Black-?Scholes|"
    r"\bequation\b|\bformula\b)",
    re.IGNORECASE,
)


def score_completeness(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    """Score how completely the response covers Stage 13 facets."""
    evidence: list[str] = []
    facets: dict[str, bool] = {}

    has_answer = len(ctx.answer.strip()) >= 40
    facets["direct_answer"] = has_answer
    evidence.append("direct answer present" if has_answer else "answer too short")

    has_implications = bool(_IMPLICATION_PATTERNS.search(ctx.answer))
    facets["practical_implications"] = has_implications
    if has_implications:
        evidence.append("practical implications mentioned")
    else:
        evidence.append("missing practical trading implications")

    has_risks = bool(_RISK_PATTERNS.search(ctx.answer))
    if thresholds.require_risks_section:
        facets["risks_assumptions"] = has_risks
        evidence.append(
            "risks/assumptions present" if has_risks else "missing risks/assumptions"
        )

    has_citations = len(ctx.citations) > 0
    if thresholds.require_citations and ctx.profile == "chat":
        facets["citations"] = has_citations
        evidence.append(
            f"{len(ctx.citations)} citation(s)"
            if has_citations
            else "missing source citations"
        )

    # Math explanation is optional — bonus only when query looks quantitative
    query_wants_math = bool(
        re.search(r"\b(formula|equation|derive|calculate|greek)\b", ctx.query, re.I)
    )
    if query_wants_math:
        has_math = bool(_MATH_PATTERNS.search(ctx.answer))
        facets["math_explanation"] = has_math
        evidence.append(
            "math/Greeks explanation present"
            if has_math
            else "query asked for math but answer lacks it"
        )

    if not facets:
        score = 0.0
    else:
        score = sum(1.0 for ok in facets.values() if ok) / len(facets)

    # Faithfulness flag from RAG post-check
    if ctx.faithfulness_ok is False:
        score = min(score, 0.4)
        evidence.append("faithfulness_ok=false — grounding incomplete")

    passed = score >= thresholds.completeness_min
    return MetricScore(
        name=MetricName.completeness,
        category=MetricCategory.quality,
        score=round(score, 3),
        passed=passed,
        threshold=thresholds.completeness_min,
        detail="All required aspects of the query are addressed"
        if passed
        else "Response is missing required facets (Stage 13)",
        evidence=evidence,
    )
