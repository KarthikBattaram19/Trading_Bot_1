"use client";

import { useState } from "react";
import { Icon, StatusPill } from "@/components/ui/primitives";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: { document: string; chapter?: string; page?: number }[];
}

const SAMPLE_THREAD: Message[] = [
  {
    id: "m1",
    role: "user",
    content:
      "Why was RELIANCE ranked #2 and opened after TATASTEEL failed? Was vega scalp liquidity the only gate?",
  },
  {
    id: "m2",
    role: "assistant",
    content:
      "Yes — in this cycle rank #1 (TATASTEEL / vega scalping) failed broker-side: insufficient liquidity on the near-week put vertical at session open. The autonomous executor then attempted rank #2 (RELIANCE / simple volatility, cheap-vol mode). All risk gates passed, net edge after costs stayed positive, and the fill was confirmed as order_status=filled.\n\nLiquidity was the hard reject for #1; confidence (0.88) and scenario tag were otherwise fine. Failure memory will store the liquidity reject so similar mid-cap steel IV-flush setups get a confidence penalty next time.",
    citations: [
      { document: "Volatility Trading", chapter: "Chapter 2", page: 31 },
      { document: "System Architecture", chapter: "§12 Continual Learning", page: 12 },
    ],
  },
  {
    id: "m3",
    role: "user",
    content:
      "For the INTC gamma packet (dec_20260705_001), what is the gamma-theta breakeven and when should we flatten?",
  },
  {
    id: "m4",
    role: "assistant",
    content:
      "Entry is earnings-gap mode with IV 35% vs GARCH 38%, vega-neutral at entry, term structure OK. Gamma-theta breakeven is ~0.96% of spot. Plan:\n\n• Stop — re-neutralize or flatten if Greeks drift beyond cost limits (gap rule).\n• Target — close after the earnings gap if breakeven is exceeded.\n• Time exit — D+0 or D+1; do not hold through a quiet post-gap session where theta dominates.\n\nPrimary failure modes: quiet market (theta wins) and post-gap Greek drift losing neutrality.",
    citations: [
      { document: "Gamma Scalping", chapter: "Chapter 5", page: 132 },
      { document: "Volatility Trading", chapter: "Chapter 3", page: 48 },
    ],
  },
  {
    id: "m5",
    role: "user",
    content: "Summarize current portfolio Greek headroom vs limits.",
  },
  {
    id: "m6",
    role: "assistant",
    content:
      "Against configured limits (Δ 0.15 / Γ 2.0 / ν 1.5 / Θ −500):\n\n• Delta 0.04 → ~27% of limit used\n• Gamma 0.82 → ~41% used\n• Vega 0.35 → ~23% used\n• Theta −120 → ~24% used\n\nNo circuit breakers are active. Daily P&L +₹342.50 with drawdown 3.2% (max DD breaker 10%). Headroom is comfortable for one discretionary book under one-trade scope.",
  },
];

const SUGGESTIONS = [
  "Explain the AMZN/META residual z-score stop",
  "What did failure memory learn from TATASTEEL?",
  "List open mechanical hedges on SPY",
];

export function ChatView({ decisionId }: { decisionId?: string }) {
  const [input, setInput] = useState("");
  const [messages] = useState(SAMPLE_THREAD);

  return (
    <div className="flex flex-1 flex-col overflow-hidden rounded-md border border-outline-variant bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-outline-variant bg-surface-container-low px-4 py-3">
        <StatusPill tone="success">
          <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-secondary" />
          RAG Connected
        </StatusPill>
        {decisionId ? (
          <StatusPill tone="info">Context: {decisionId}</StatusPill>
        ) : (
          <StatusPill tone="neutral">General desk context</StatusPill>
        )}
        <span className="text-data-sm text-on-surface-variant">
          Sample thread — POST /api/v1/chat not required in mock mode
        </span>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {messages.map((m) =>
          m.role === "assistant" ? (
            <div key={m.id} className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant bg-surface-container-high text-on-surface-variant">
                <Icon name="smart_toy" className="text-[18px]" />
              </div>
              <div className="max-w-[80%] rounded-md border border-outline-variant bg-surface-container px-4 py-3">
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
                        key={i}
                        className="flex items-center gap-1 rounded border border-outline-variant bg-surface-container-low px-2 py-1 font-mono text-[10px] text-on-surface-variant"
                      >
                        <Icon name="description" className="text-[12px]" />
                        {c.document}
                        {c.chapter ? ` · ${c.chapter}` : ""}
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
      </div>

      <div className="border-t border-outline-variant p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setInput(s)}
              className="flex items-center gap-1 rounded-full border border-outline-variant px-3 py-1.5 text-data-sm text-on-surface-variant transition-colors hover:border-primary hover:text-primary"
            >
              <Icon name="auto_awesome" className="text-[14px]" />
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-full border border-outline-variant bg-surface-container-low px-2 py-1 focus-within:border-primary">
          <Icon name="add" className="ml-1 text-[20px] text-on-surface-variant" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about entry rationale, Greeks, or failure memory…"
            className="flex-1 bg-transparent px-1 py-1.5 text-data-md text-on-surface placeholder:text-outline focus:outline-none"
          />
          <button
            type="button"
            disabled
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-container text-white disabled:opacity-40"
          >
            <Icon name="send" className="text-[16px]" />
          </button>
        </div>
        <p className="mt-2 text-center text-[11px] text-outline">
          AI models may produce inaccurate information — verify against packets.
        </p>
      </div>
    </div>
  );
}
