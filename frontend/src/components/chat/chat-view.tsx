"use client";

import { useEffect, useId, useRef, useState } from "react";
import { postChat } from "@/lib/api";
import type { ChatCitation } from "@/types/chat";
import { Icon, StatusPill } from "@/components/ui/primitives";
import { useMockData } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: ChatCitation[];
  error?: boolean;
}

const SUGGESTIONS = [
  "What is a delta hedge in volatility trading?",
  "When does GARCH beat implied volatility for entry?",
  "Explain theta risk on a long-premium hedge",
];

function newId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function ChatView({ decisionId }: { decisionId?: string }) {
  const mock = useMockData();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const formId = useId();
  const [sessionId] = useState(() => newId("sess"));
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function sendMessage(raw: string) {
    const text = raw.trim();
    if (!text || sending) return;

    const userMsg: Message = { id: newId("u"), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setError(null);
    setSending(true);

    try {
      const res = await postChat({
        message: text,
        session_id: sessionId,
        decision_id: decisionId ?? null,
      });
      setMessages((prev) => [
        ...prev,
        {
          id: newId("a"),
          role: "assistant",
          content: res.answer,
          citations: res.citations,
        },
      ]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Chat request failed";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        {
          id: newId("e"),
          role: "assistant",
          content: `Could not reach the chat API. ${msg}`,
          error: true,
        },
      ]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden rounded-md border border-outline-variant bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-outline-variant bg-surface-container-low px-4 py-3">
        {mock ? (
          <StatusPill tone="neutral">
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-outline" />
            Mock answers
          </StatusPill>
        ) : (
          <StatusPill tone="success">
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-secondary" />
            Live API
          </StatusPill>
        )}
        {decisionId ? (
          <StatusPill tone="info">Context: {decisionId}</StatusPill>
        ) : (
          <StatusPill tone="neutral">General desk context</StatusPill>
        )}
        <span className="text-data-sm text-on-surface-variant">
          POST /api/v1/chat · educational only — never places orders
        </span>
      </div>

      <div ref={listRef} className="flex-1 space-y-5 overflow-y-auto p-4">
        {messages.length === 0 && !sending && (
          <div className="flex h-full min-h-[12rem] flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
            <Icon name="smart_toy" className="text-[28px]" />
            <p className="text-data-md">
              Ask about Volatility Trading Greeks, delta hedges, GARCH entry rules,
              or a decision packet.
            </p>
            <p className="text-[11px] text-outline">
              Answers include citations when retrieval finds grounded context.
            </p>
          </div>
        )}

        {messages.map((m) =>
          m.role === "assistant" ? (
            <div key={m.id} className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant bg-surface-container-high text-on-surface-variant">
                <Icon name="smart_toy" className="text-[18px]" />
              </div>
              <div
                className={`max-w-[80%] rounded-md border px-4 py-3 ${
                  m.error
                    ? "border-error/40 bg-error-container/20"
                    : "border-outline-variant bg-surface-container"
                }`}
              >
                <div className="mb-1 text-[10px] uppercase tracking-wider text-on-surface-variant">
                  Bhale Bullodu
                </div>
                <p className="whitespace-pre-wrap text-data-md leading-relaxed text-on-surface">
                  {m.content}
                </p>
                {m.citations && m.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-outline-variant pt-2">
                    {m.citations.map((c, i) => (
                      <span
                        key={`${c.document_id}-${c.chunk_id ?? i}`}
                        className="flex items-center gap-1 rounded border border-outline-variant bg-surface-container-low px-2 py-1 font-mono text-[10px] text-on-surface-variant"
                      >
                        <Icon name="description" className="text-[12px]" />
                        {c.document ?? c.document_id}
                        {c.section ? ` · ${c.section}` : ""}
                        {c.page != null ? ` · p.${c.page}` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-md border border-primary-container/50 bg-primary-container/20 px-4 py-3">
                <div className="mb-1 text-right text-[10px] uppercase tracking-wider text-primary">
                  You
                </div>
                <p className="whitespace-pre-wrap text-data-md leading-relaxed text-on-surface">
                  {m.content}
                </p>
              </div>
            </div>
          ),
        )}

        {sending && (
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant bg-surface-container-high text-on-surface-variant">
              <Icon name="smart_toy" className="text-[18px]" />
            </div>
            <div className="rounded-md border border-outline-variant bg-surface-container px-4 py-3 text-data-sm text-on-surface-variant">
              Thinking…
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-outline-variant p-4">
        {error && (
          <p className="mb-2 text-center text-[11px] text-error" role="alert">
            {error}
          </p>
        )}
        <div className="mb-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              disabled={sending}
              onClick={() => void sendMessage(s)}
              className="flex items-center gap-1 rounded-full border border-outline-variant px-3 py-1.5 text-data-sm text-on-surface-variant transition-colors hover:border-primary hover:text-primary disabled:opacity-40"
            >
              <Icon name="auto_awesome" className="text-[14px]" />
              {s}
            </button>
          ))}
        </div>
        <form
          id={formId}
          className="flex items-center gap-2 rounded-full border border-outline-variant bg-surface-container-low px-2 py-1 focus-within:border-primary"
          onSubmit={(e) => {
            e.preventDefault();
            void sendMessage(input);
          }}
        >
          <Icon name="add" className="ml-1 text-[20px] text-on-surface-variant" />
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about entry rationale, Greeks, or failure memory…"
            disabled={sending}
            className="flex-1 bg-transparent px-1 py-1.5 text-data-md text-on-surface placeholder:text-outline focus:outline-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            aria-label="Send message"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-container text-white disabled:opacity-40"
          >
            <Icon name="send" className="text-[16px]" />
          </button>
        </form>
        <p className="mt-2 text-center text-[11px] text-outline">
          AI models may produce inaccurate information — verify against packets.
        </p>
      </div>
    </div>
  );
}
