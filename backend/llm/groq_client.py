"""Groq LLM client wrapper (architecture.md §10)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
        self.model = (model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        self._client: Any = None
        if self.api_key:
            try:
                from groq import Groq

                self._client = Groq(api_key=self.api_key)
            except Exception as exc:  # pragma: no cover - import/env edge
                logger.warning("Groq client unavailable: %s", exc)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete(self, *, system: str, user: str, temperature: float = 0.2) -> str:
        if not self._client:
            raise RuntimeError("GROQ_API_KEY not configured")
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()


_GROQ: GroqClient | None = None


def get_groq_client() -> GroqClient:
    global _GROQ
    if _GROQ is None:
        _GROQ = GroqClient()
    return _GROQ
