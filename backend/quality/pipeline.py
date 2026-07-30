"""Orchestrates Quality, Safety & Performance validators into one report."""

from __future__ import annotations

from backend.quality.config import QualityThresholds, get_thresholds
from backend.quality.models import (
    MetricCategory,
    MetricName,
    MetricScore,
    ValidationAction,
    ValidationContext,
    ValidationReport,
)
from backend.quality.validators import (
    score_bias,
    score_coherence,
    score_completeness,
    score_conciseness,
    score_consistency,
    score_relevance,
    score_toxicity,
)


def _score_latency(
    ctx: ValidationContext, thresholds: QualityThresholds
) -> MetricScore:
    evidence: list[str] = []
    score = 1.0

    if ctx.latency_ms is None and ctx.ttft_ms is None:
        return MetricScore(
            name=MetricName.latency,
            category=MetricCategory.performance,
            score=1.0,
            passed=True,
            threshold=0.0,
            detail="Latency not measured for this request",
            evidence=["no latency sample"],
        )

    if ctx.latency_ms is not None:
        evidence.append(f"total_ms={ctx.latency_ms:.1f}")
        if ctx.latency_ms > thresholds.latency_request_max_ms:
            overshoot = ctx.latency_ms / thresholds.latency_request_max_ms
            score = min(score, max(0.0, 2.0 - overshoot))
            evidence.append("exceeded request latency budget")

    if ctx.ttft_ms is not None:
        evidence.append(f"ttft_ms={ctx.ttft_ms:.1f}")
        if ctx.ttft_ms > thresholds.ttft_request_max_ms:
            overshoot = ctx.ttft_ms / thresholds.ttft_request_max_ms
            score = min(score, max(0.0, 2.0 - overshoot))
            evidence.append("exceeded TTFT budget")

    passed = score >= 0.5
    return MetricScore(
        name=MetricName.latency,
        category=MetricCategory.performance,
        score=round(score, 3),
        passed=passed,
        threshold=0.5,
        detail="Within latency / TTFT budget"
        if passed
        else "Latency or TTFT exceeded budget",
        evidence=evidence,
    )


class QualityPipeline:
    """Runs Core Metrics validators and decides pass / warn / block / regenerate."""

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self.thresholds = thresholds or get_thresholds()

    def evaluate(self, ctx: ValidationContext) -> ValidationReport:
        scores = [
            score_relevance(ctx, self.thresholds),
            score_coherence(ctx, self.thresholds),
            score_completeness(ctx, self.thresholds),
            score_conciseness(ctx, self.thresholds),
            score_toxicity(ctx, self.thresholds),
            score_bias(ctx, self.thresholds),
            score_consistency(ctx, self.thresholds),
            _score_latency(ctx, self.thresholds),
        ]

        quality_scores = [s for s in scores if s.category == MetricCategory.quality]
        safety_scores = [s for s in scores if s.category == MetricCategory.safety]
        performance_scores = [
            s for s in scores if s.category == MetricCategory.performance
        ]

        quality_score = (
            sum(s.score for s in quality_scores) / len(quality_scores)
            if quality_scores
            else 0.0
        )
        safety_ok = all(s.passed for s in safety_scores)
        performance_ok = all(s.passed for s in performance_scores)

        blocking: list[str] = []
        warnings: list[str] = []

        for s in safety_scores:
            if not s.passed:
                blocking.append(f"{s.name.value}: {s.detail}")

        for s in quality_scores:
            if not s.passed:
                # Relevance / completeness failures → regenerate; others warn
                if s.name in (MetricName.relevance, MetricName.completeness):
                    blocking.append(f"{s.name.value}: {s.detail}")
                else:
                    warnings.append(f"{s.name.value}: {s.detail}")

        for s in performance_scores:
            if not s.passed:
                if s.name == MetricName.latency:
                    warnings.append(f"{s.name.value}: {s.detail}")
                else:
                    warnings.append(f"{s.name.value}: {s.detail}")

        if any(s.name == MetricName.toxicity and not s.passed for s in safety_scores):
            action = ValidationAction.block
        elif blocking:
            # Prefer regenerate for quality gaps; block for bias
            if any(s.name == MetricName.bias and not s.passed for s in safety_scores):
                action = ValidationAction.block
            else:
                action = ValidationAction.regenerate
        elif warnings:
            action = ValidationAction.warn
        else:
            action = ValidationAction.pass_through

        passed = action in (
            ValidationAction.pass_through,
            ValidationAction.warn,
        )

        return ValidationReport(
            passed=passed,
            action=action,
            scores=scores,
            quality_score=round(quality_score, 3),
            safety_ok=safety_ok,
            performance_ok=performance_ok,
            blocking_failures=blocking,
            warnings=warnings,
        )


def validate_response(
    ctx: ValidationContext,
    thresholds: QualityThresholds | None = None,
) -> ValidationReport:
    return QualityPipeline(thresholds).evaluate(ctx)
