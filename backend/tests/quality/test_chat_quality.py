"""Chat endpoint + golden eval integration tests (Track B1)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("EMBEDDING_BACKEND", "hash")
os.environ.setdefault("GROQ_API_KEY", "")


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    persist = tmp_path / "chroma"
    persist.mkdir()
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(persist))
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RAG_AUTO_INGEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "")

    from backend.knowledge.ingestion import pipeline as ingest_mod
    from backend.knowledge.retrieval import service as rag_mod
    from backend.knowledge.vectorstore import bm25_index, chroma_store
    from backend.services import chat_service
    from backend.quality.latency import get_latency_tracker
    from backend.main import app

    chroma_store.reset_chroma_store_for_tests()
    bm25_index.BM25Corpus.reset_shared()
    rag_mod.reset_rag_service_for_tests()
    ingest_mod._PIPELINE = None  # noqa: SLF001
    chat_service._CHAT_SERVICE = None  # noqa: SLF001
    chat_service._PRIOR_ANSWERS.clear()
    get_latency_tracker().clear()

    # Pre-ingest so chat tests are stable
    pipeline = ingest_mod.get_ingest_pipeline()
    pipeline.ingest_b1()

    yield TestClient(app)

    chroma_store.reset_chroma_store_for_tests()
    bm25_index.BM25Corpus.reset_shared()
    rag_mod.reset_rag_service_for_tests()
    ingest_mod._PIPELINE = None  # noqa: SLF001
    chat_service._CHAT_SERVICE = None  # noqa: SLF001


def test_chat_returns_quality_report(client: TestClient):
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "What is a delta hedge?",
            "session_id": "s1",
            "filters": {"strategy": "Volatility Trading"},
        },
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


def test_chat_consistency_across_repeats(client: TestClient):
    payload = {
        "message": "Explain theta in a long option delta hedge",
        "session_id": "s2",
    }
    first = client.post("/api/v1/chat", json=payload).json()
    second = client.post("/api/v1/chat", json=payload).json()
    consistency = next(
        s for s in second["quality"]["scores"] if s["name"] == "consistency"
    )
    assert consistency["passed"]
    assert consistency["score"] >= 0.65
    assert first["answer"] == second["answer"]


def test_quality_metrics_endpoint(client: TestClient):
    client.post("/api/v1/chat", json={"message": "Explain theta decay for options"})
    res = client.get("/api/v1/quality/metrics")
    assert res.status_code == 200
    body = res.json()
    assert body["framework"].startswith("Core Metrics")
    assert body["latency"]["chat"]["count"] >= 1
    assert "p50_ms" in body["latency"]["chat"]
    assert "ttft_p95_ms" in body["latency"]["chat"]


def test_golden_eval_pass_rate(client: TestClient):
    from backend.knowledge.evaluation.runner import evaluate_golden

    summary = evaluate_golden(use_live_rag=True)
    assert summary["total"] >= 5
    assert summary["mean_faithfulness"] >= 0.85
    assert summary["pass_rate"] >= 0.75


def test_chat_blocks_toxic_input_via_api(client: TestClient):
    res = client.post(
        "/api/v1/chat",
        json={"message": "kill yourself you moron"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["quality_action"] == "block"
    assert body["metadata"].get("blocked_reason") == "input_toxicity"
