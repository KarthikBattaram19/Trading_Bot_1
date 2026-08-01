"""ChromaDB knowledge_base store (embedded or HTTP)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

from backend.knowledge.manifest import COLLECTION_KNOWLEDGE


def _persist_dir() -> Path:
    raw = os.getenv("CHROMA_PERSIST_DIRECTORY", "./backend/data/chroma").strip()
    path = Path(raw)
    if not path.is_absolute():
        repo = Path(__file__).resolve().parents[3]  # …/backend/knowledge/vectorstore → repo
        backend = Path(__file__).resolve().parents[2]
        cleaned = raw.replace("\\", "/").lstrip("./")
        if cleaned.startswith("backend/"):
            path = (repo / cleaned).resolve()
        elif cleaned.startswith("data/"):
            path = (backend / cleaned).resolve()
        else:
            path = (repo / cleaned).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


class HashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic embeddings for CI / offline tests (no model download)."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    @staticmethod
    def name() -> str:
        return "hash"

    def __call__(self, input: Documents) -> Embeddings:
        out: Embeddings = []
        for text in input:
            vec: list[float] = []
            for i in range(self.dim):
                h = hashlib.sha256(f"{i}:{text}".encode("utf-8")).digest()
                # map byte to [-1, 1]
                vec.append((h[0] / 127.5) - 1.0)
            # L2 normalize
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


def build_embedding_function() -> EmbeddingFunction[Documents]:
    backend = os.getenv("EMBEDDING_BACKEND", "default").strip().lower()
    if backend in {"hash", "test", "ci"}:
        return HashEmbeddingFunction()
    # Prefer chromadb default (onnx MiniLM) — avoids multi-GB bge-m3 in paper/CI.
    # Production can set EMBEDDING_BACKEND=bge-m3 once sentence-transformers is wired.
    if backend in {"bge-m3", "bge"}:
        try:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            return SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-m3")
        except Exception:
            pass
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()
    except Exception:
        return HashEmbeddingFunction()


class ChromaKnowledgeStore:
    def __init__(
        self,
        *,
        collection_name: str = COLLECTION_KNOWLEDGE,
        embedding_fn: EmbeddingFunction[Documents] | None = None,
    ) -> None:
        self.collection_name = collection_name
        self._embedding_fn = embedding_fn or build_embedding_function()
        self._client = self._make_client()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self._meta_collection = self._client.get_or_create_collection(
            name=f"{collection_name}__meta",
            embedding_function=HashEmbeddingFunction(dim=8),
        )

    def _make_client(self) -> chromadb.ClientAPI:
        host = os.getenv("CHROMA_HOST", "").strip()
        if host:
            port = int(os.getenv("CHROMA_PORT", "8100"))
            return chromadb.HttpClient(host=host, port=port)
        return chromadb.PersistentClient(path=str(_persist_dir()))

    @property
    def collection(self) -> Collection:
        return self._collection

    def count(self) -> int:
        return int(self._collection.count())

    def deprecate_document(self, document_id: str) -> None:
        existing = self._collection.get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
        ids = existing.get("ids") or []
        if not ids:
            return
        metadatas = existing.get("metadatas") or []
        updated = []
        for meta in metadatas:
            m = dict(meta or {})
            m["deprecated"] = True
            updated.append(m)
        self._collection.update(ids=ids, metadatas=updated)

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings_input: list[str] | None = None,
    ) -> None:
        # Chroma embeds `documents` via embedding_function; pass prefixed text as documents
        # for storage fidelity we store raw text but embed prefixed — so embed explicitly.
        texts_for_embed = embeddings_input or documents
        embeddings = self._embedding_fn(texts_for_embed)
        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def list_active_chunks(self) -> list[dict[str, Any]]:
        raw = self._collection.get(include=["documents", "metadatas"])
        rows: list[dict[str, Any]] = []
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []
        for i, chunk_id in enumerate(ids):
            meta = dict(metas[i] or {})
            if meta.get("deprecated") is True:
                continue
            rows.append(
                {
                    "chunk_id": chunk_id,
                    "text": docs[i] or "",
                    "metadata": meta,
                }
            )
        return rows

    def query_dense(
        self,
        query: str,
        *,
        n_results: int = 50,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": max(1, n_results),
            "include": ["documents", "metadatas", "distances"],
        }
        # Always exclude deprecated when possible
        dep_filter: dict[str, Any] = {"deprecated": False}
        if where:
            kwargs["where"] = {"$and": [dep_filter, where]}
        else:
            kwargs["where"] = dep_filter
        try:
            res = self._collection.query(**kwargs)
        except Exception:
            # Older / empty collections may lack deprecated=False rows
            kwargs.pop("where", None)
            if where:
                kwargs["where"] = where
            res = self._collection.query(**kwargs)

        rows: list[dict[str, Any]] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, chunk_id in enumerate(ids):
            meta = dict(metas[i] or {})
            if meta.get("deprecated") is True:
                continue
            dist = float(dists[i]) if i < len(dists) else 1.0
            rows.append(
                {
                    "chunk_id": chunk_id,
                    "text": docs[i] or "",
                    "metadata": meta,
                    "distance": dist,
                    "score": 1.0 / (1.0 + dist),
                }
            )
        return rows

    def set_ingest_meta(self, meta: dict[str, str]) -> None:
        self._meta_collection.upsert(
            ids=["ingest_status"],
            documents=["ingest status"],
            metadatas=[meta],
            embeddings=[[0.0] * 8],
        )

    def get_ingest_meta(self) -> dict[str, Any]:
        try:
            res = self._meta_collection.get(ids=["ingest_status"], include=["metadatas"])
            metas = res.get("metadatas") or []
            if metas and metas[0]:
                return dict(metas[0])
        except Exception:
            pass
        return {}


_STORE: ChromaKnowledgeStore | None = None


def get_chroma_store() -> ChromaKnowledgeStore:
    global _STORE
    if _STORE is None:
        _STORE = ChromaKnowledgeStore()
    return _STORE


def reset_chroma_store_for_tests() -> None:
    global _STORE
    _STORE = None
