"""RAG user chatbot endpoint with Core Metrics validation."""

from __future__ import annotations

from fastapi import APIRouter

from backend.models.chat import ChatRequest, ChatResponse
from backend.services.chat_service import get_chat_service

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Grounded Q&A with Quality / Safety / Performance validation."""
    return get_chat_service().answer(request)
