"""Pipeline and latency tracker tests."""

from __future__ import annotations

import time

from backend.quality.config import QualityThresholds
from backend.quality.latency import LatencyTracker
from backend.quality.models import CitationRef, ValidationAction, ValidationContext
from backend.quality.pipeline import QualityPipeline, validate_response


def _good_ctx(**kwargs: object) -> ValidationContext:
    base = {
        "query": "When should I rebalance a gamma scalp?",
        "answer": (
            "Rebalance a gamma scalp when net delta drifts beyond your hedge "
            "threshold as the underlying moves. In practice, retail traders "
            "should widen rebalance bands to limit transaction costs and slippage. "
            "Risks and assumptions: hedge frequency must stay retail-realistic."
        ),
        "citations": [
            CitationRef(
                document_id="doc-gamma",
                document="Gamma Scalping",
                chunk_id="doc-gamma_c003",
            )
        ],
        "profile": "chat",
        "faithfulness_ok": True,
    }
    base.update(kwargs)
    return ValidationContext(**base)  # type: ignore[arg-type]


def test_pipeline_passes_good_response():
    report = validate_response(_good_ctx())
    assert report.passed
    assert report.action in (ValidationAction.pass_through, ValidationAction.warn)
    assert report.safety_ok
    assert report.quality_score >= 0.7


def test_pipeline_blocks_toxicity():
    report = QualityPipeline().evaluate(
        _good_ctx(answer="Kill yourself you moron. " + _good_ctx().answer)
    )
    assert report.action == ValidationAction.block
    assert not report.safety_ok


def test_pipeline_regenerates_on_low_relevance():
    report = validate_response(
        _good_ctx(
            answer=(
                "Bananas are a yellow fruit often eaten at breakfast. "
                "Risks and assumptions: none related to trading."
            ),
            citations=[],
            faithfulness_ok=False,
        )
    )
    assert report.action in (ValidationAction.regenerate, ValidationAction.block)
    assert not report.passed or report.action == ValidationAction.regenerate


def test_latency_percentiles_and_ttft():
    tracker = LatencyTracker(max_samples=100)
    for i in range(20):
        tracker.record("chat", total_ms=100 + i * 10, ttft_ms=20 + i)

    snap = tracker.snapshot("chat")
    assert snap.count == 20
    assert snap.p50_ms is not None
    assert snap.p95_ms is not None
    assert snap.p99_ms is not None
    assert snap.ttft_p95_ms is not None
    assert snap.p50_ms <= snap.p95_ms <= snap.p99_ms


def test_latency_measure_context_records_ttft():
    tracker = LatencyTracker()
    with tracker.measure("chat") as timed:
        time.sleep(0.01)
        timed.mark_first_token()
        time.sleep(0.01)

    snap = tracker.snapshot("chat")
    assert snap.count == 1
    assert snap.ttft_p50_ms is not None
    assert snap.p50_ms is not None
    assert snap.ttft_p50_ms <= snap.p50_ms


def test_custom_thresholds():
    strict = QualityThresholds(relevance_min=0.99)
    report = QualityPipeline(strict).evaluate(_good_ctx())
    # May still pass due to strong overlap; ensure threshold is applied on score object
    relevance = next(s for s in report.scores if s.name.value == "relevance")
    assert relevance.threshold == 0.99
