"""Document registry for RAG corpus (architecture.md §3.2 / §7.2 Stage 1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Repo root: backend/knowledge/manifest.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DocumentSpec:
    document_id: str
    title: str
    relative_path: str
    version: str
    strategy: str
    # Track B1: only Volatility Trading is active; others land in B2.
    active_for_b1: bool = False

    @property
    def absolute_path(self) -> Path:
        return _REPO_ROOT / self.relative_path


DOCUMENTS: dict[str, DocumentSpec] = {
    "doc-vol-trading": DocumentSpec(
        document_id="doc-vol-trading",
        title="Volatility Trading",
        relative_path="Docs/Volatility Trading.pdf",
        version="1.0",
        strategy="Volatility Trading",
        active_for_b1=True,
    ),
    "doc-gamma": DocumentSpec(
        document_id="doc-gamma",
        title="Gamma Scalping",
        relative_path="Docs/Gamma Scalping.pdf",
        version="1.0",
        strategy="Gamma Scalping",
    ),
    "doc-vega": DocumentSpec(
        document_id="doc-vega",
        title="Vega Scalping",
        relative_path="Docs/Vega Scalping.pdf",
        version="1.0",
        strategy="Vega Scalping",
    ),
    "doc-trading-strategies": DocumentSpec(
        document_id="doc-trading-strategies",
        title="Trading Strategies",
        relative_path="Docs/Trading_Strategies.pdf",
        version="1.0",
        strategy="Trading Strategies",
    ),
}

COLLECTION_KNOWLEDGE = "knowledge_base"


def b1_documents() -> list[DocumentSpec]:
    return [d for d in DOCUMENTS.values() if d.active_for_b1]


def resolve_docs_root() -> Path:
    return _REPO_ROOT / "Docs"
