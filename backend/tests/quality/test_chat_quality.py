"""Chat endpoint + golden eval integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.knowledge.evaluation.runner import evaluate_golden
from backend.main import app
from backend.quality.latency import get_latency_tracker
from backend.services.chat_service import _PRIOR_ANSWERS

client = TestClient(app)


def setup_function() -> None:
    get_latency_tracker().clear()
    _PRIOR_ANSWERS.clear()


def test_chat_returns_quality_report():
    res = client.post(
        "/api/v1/chat",
        json={"message": "When should I rebalance a gamma scalp?", "session_id": "s1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["answer"]
    assert body["citations"]
    assert body["quality"] is not None
    assert "scores" in body["quality"]
    assert body["latency_ms"] is not None
    names = {s["name"] for s in body["quality"]["scores"]}
    assert {
        "relevance",
        "coherence",
        "completeness",
        "conciseness",
        "toxicity",
        "bias",
        "consistency",
        "latency",
    } <= names


def test_chat_consistency_across_repeats():
    payload = {"message": "What is vega scalping and implied volatility?", "session_id": "s2"}
    first = client.post("/api/v1/chat", json=payload).json()
    second = client.post("/api/v1/chat", json=payload).json()
    consistency = next(
        s for s in second["quality"]["scores"] if s["name"] == "consistency"
    )
    assert consistency["passed"]
    assert consistency["score"] >= 0.65
    assert first["answer"] == second["answer"]


def test_quality_metrics_endpoint():
    client.post("/api/v1/chat", json={"message": "Explain theta decay"})
    res = client.get("/api/v1/quality/metrics")
    assert res.status_code == 200
    body = res.json()
    assert body["framework"].startswith("Core Metrics")
    assert body["latency"]["chat"]["count"] >= 1
    assert "p50_ms" in body["latency"]["chat"]
    assert "ttft_p95_ms" in body["latency"]["chat"]


def test_golden_eval_pass_rate():
    summary = evaluate_golden()
    assert summary["total"] >= 5
    assert summary["pass_rate"] >= 0.8
    assert summary["passed"] == summary["total"]


def test_chat_blocks_toxic_input_via_api():
    res = client.post(
        "/api/v1/chat",
        json={"message": "kill yourself you moron"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["quality_action"] == "block"
    assert body["metadata"].get("blocked_reason") == "input_toxicity"