"""Application-layer BM25 index over active knowledge chunks."""

from __future__ import annotations

import re
import threading
from typing import Any

from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class BM25Corpus:
    _shared: BM25Corpus | None = None
    _shared_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ready = False
        self._chunks: list[dict[str, Any]] = []
        self._bm25: BM25Okapi | None = None

    @classmethod
    def shared(cls) -> BM25Corpus:
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = BM25Corpus()
            return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        with cls._shared_lock:
            cls._shared = None

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready

    def rebuild(self, chunks: list[dict[str, Any]]) -> None:
        with self._lock:
            self._chunks = list(chunks)
            corpus = [tokenize(c.get("text") or "") for c in self._chunks]
            self._bm25 = BM25Okapi(corpus) if corpus else None
            self._ready = False

    def mark_ready(self) -> None:
        with self._lock:
            self._ready = True

    def search(self, query: str, *, top_k: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if not self._ready or self._bm25 is None or not self._chunks:
                return []
            scores = self._bm25.get_scores(tokenize(query))
            ranked = sorted(
                enumerate(scores),
                key=lambda x: float(x[1]),
                reverse=True,
            )[:top_k]
            rows: list[dict[str, Any]] = []
            for idx, score in ranked:
                if float(score) <= 0:
                    continue
                chunk = self._chunks[idx]
                rows.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "text": chunk.get("text") or "",
                        "metadata": chunk.get("metadata") or {},
                        "score": float(score),
                    }
                )
            return rows
