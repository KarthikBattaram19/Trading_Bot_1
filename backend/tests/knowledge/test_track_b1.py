"""Track B1 — PDF ingest, hybrid retrieval, chat, golden eval."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Force deterministic, download-free embeddings for CI
os.environ.setdefault("EMBEDDING_BACKEND", "hash")
os.environ.setdefault("RAG_AUTO_INGEST", "1")
os.environ.setdefault("GROQ_API_KEY", "")  # extractive path in CI


@pytest.fixture()
def chroma_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    chroma_store.reset_chroma_store_for_tests()
    bm25_index.BM25Corpus.reset_shared()
    rag_mod.reset_rag_service_for_tests()
    ingest_mod._PIPELINE = None  # noqa: SLF001
    chat_service._CHAT_SERVICE = None  # noqa: SLF001
    chat_service._PRIOR_ANSWERS.clear()

    yield persist

    chroma_store.reset_chroma_store_for_tests()
    bm25_index.BM25Corpus.reset_shared()
    rag_mod.reset_rag_service_for_tests()
    ingest_mod._PIPELINE = None  # noqa: SLF001
    chat_service._CHAT_SERVICE = None  # noqa: SLF001


def test_b1_ingest_volatility_trading(chroma_tmpdir: Path):
    from backend.knowledge.ingestion.pipeline import get_ingest_pipeline

    result = get_ingest_pipeline().ingest_b1()
    assert result.document_ids == ["doc-vol-trading"]
    assert result.chunk_count >= 8
    assert (chroma_tmpdir).exists()


def test_hybrid_retrieve_greeks(chroma_tmpdir: Path):
    from backend.knowledge.ingestion.pipeline import get_ingest_pipeline
    from backend.knowledge.retrieval.service import get_rag_service

    get_ingest_pipeline().ingest_b1()
    chunks = get_rag_service().retrieve(
        "What is a delta hedge and positive gamma?",
        top_k=5,
        strategy="Volatility Trading",
    )
    assert chunks
    assert any(c.metadata.get("document_id") == "doc-vol-trading" for c in chunks)
    joined = " ".join(c.text.lower() for c in chunks)
    assert "delta" in joined


def test_chat_endpoint_grounded(chroma_tmpdir: Path):
    from backend.main import app
    from backend.knowledge.ingestion.pipeline import get_ingest_pipeline
    from backend.quality.latency import get_latency_tracker
    from backend.services.chat_service import _PRIOR_ANSWERS

    get_ingest_pipeline().ingest_b1()
    get_latency_tracker().clear()
    _PRIOR_ANSWERS.clear()

    client = TestClient(app)
    res = client.post(
        "/api/v1/chat",
        json={
            "message": "What is a delta hedge in volatility trading?",
            "session_id": "b1-s1",
            "filters": {"strategy": "Volatility Trading"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["answer"]
    assert body["citations"]
    assert body["citations"][0]["document_id"] == "doc-vol-trading"
    assert body["quality"] is not None
    assert body["latency_ms"] is not None


def test_knowledge_status_and_ingest_api(chroma_tmpdir: Path):
    from backend.main import app

    client = TestClient(app)
    ingest = client.post("/api/v1/knowledge/ingest", json={"track": "B1"})
    assert ingest.status_code == 200
    body = ingest.json()
    assert body["chunk_count"] >= 8
    assert "doc-vol-trading" in body["document_ids"]

    status = client.get("/api/v1/knowledge/status")
    assert status.status_code == 200
    st = status.json()
    assert st["chunk_count"] >= 8
    assert st["bm25_ready"] is True


def test_golden_eval_faithfulness_gate(chroma_tmpdir: Path):
    from backend.knowledge.ingestion.pipeline import get_ingest_pipeline
    from backend.knowledge.evaluation.runner import evaluate_golden

    get_ingest_pipeline().ingest_b1()
    summary = evaluate_golden(use_live_rag=True)
    assert summary["total"] >= 5
    assert summary["mean_faithfulness"] >= summary["faithfulness_gate"]
    assert summary["faithfulness_gate_passed"]
    # Allow a couple of soft misses on citation band; overall pass_rate should be strong
    assert summary["pass_rate"] >= 0.75


def test_chunk_regression_no_empty_and_has_greeks(chroma_tmpdir: Path):
    from backend.knowledge.ingestion.extract import extract_pages
    from backend.knowledge.ingestion.chunk import chunk_pages
    from backend.knowledge.manifest import DOCUMENTS

    spec = DOCUMENTS["doc-vol-trading"]
    pages = extract_pages(spec.absolute_path)
    chunks = chunk_pages(pages, document_title=spec.title)
    assert len(chunks) >= 8
    assert all(len(c.text) > 80 for c in chunks)
    greeks = [c for c in chunks if c.chapter == "Option Greeks"]
    assert greeks
    assert any("delta" in c.text.lower() for c in greeks)
