"""Offline golden-set runner for Core Metrics + Stage 14 readiness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.quality.models import CitationRef, ValidationContext
from backend.quality.pipeline import QualityPipeline

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_qa.jsonl"


def load_golden(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or GOLDEN_PATH
    rows: list[dict[str, Any]] = []
    with open(target, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def evaluate_golden(
    path: Path | None = None,
    *,
    pipeline: QualityPipeline | None = None,
) -> dict[str, Any]:
    """Score golden answers with the Core Metrics pipeline.

    Each row may include optional `sample_answer` and `sample_citations` for
    offline validation before the full RAG stack is wired.
    """
    pipe = pipeline or QualityPipeline()
    rows = load_golden(path)
    results: list[dict[str, Any]] = []
    passed = 0

    for row in rows:
        answer = row.get("sample_answer") or row.get("reference_answer") or ""
        citations_raw = row.get("sample_citations") or row.get("expected_citations") or []
        citations = [
            CitationRef(
                document_id=c.get("document_id", ""),
                document=c.get("document"),
                section=c.get("section"),
                page=c.get("page"),
                chunk_id=c.get("chunk_id"),
            )
            for c in citations_raw
            if isinstance(c, dict)
        ]
        expected_chunks = row.get("expected_chunk_ids") or []
        ctx = ValidationContext(
            query=row["question"],
            answer=answer,
            citations=citations,
            retrieved_chunk_ids=list(expected_chunks),
            profile="chat",
            faithfulness_ok=bool(citations),
        )
        report = pipe.evaluate(ctx)
        if report.passed:
            passed += 1
        results.append(
            {
                "id": row.get("id"),
                "question": row["question"],
                "passed": report.passed,
                "action": report.action.value,
                "quality_score": report.quality_score,
                "scores": report.score_map(),
                "blocking_failures": report.blocking_failures,
            }
        )

    total = len(rows) or 1
    return {
        "total": len(rows),
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "results": results,
    }
