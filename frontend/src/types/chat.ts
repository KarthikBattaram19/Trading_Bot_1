export interface ChatCitation {
  document_id: string;
  document?: string | null;
  section?: string | null;
  page?: number | null;
  chunk_id?: string | null;
}

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  filters?: { strategy?: string | null } | null;
  decision_id?: string | null;
}

export interface ChatResponse {
  answer: string;
  citations: ChatCitation[];
  faithfulness_ok: boolean;
  quality_action?: string | null;
  latency_ms?: number | null;
  ttft_ms?: number | null;
  metadata?: Record<string, unknown>;
}
