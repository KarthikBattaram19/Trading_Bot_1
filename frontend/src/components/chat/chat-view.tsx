"use client";

import { useState } from "react";
import { Badge, Button, Card } from "@/components/ui/primitives";

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
      "Against configured limits (Δ 0.15 / Γ 2.0 / ν 1.5 / Θ −500):\n\n• Delta 0.04 → ~27% of limit used\n• Gamma 0.82 → ~41% used\n• Vega 0.35 → ~23% used\n• Theta −120 → ~24% used\n\nNo circuit breakers are active. Daily P&L +$342.50 with drawdown 3.2% (max DD breaker 10%). Headroom is comfortable for one discretionary book under one-trade scope.",
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
    <Card className="flex flex-1 flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-4 py-3">
        <Badge variant="pass">RAG connected (mock)</Badge>
        {decisionId ? (
          <Badge variant="pending">Context: {decisionId}</Badge>
        ) : (
          <Badge variant="default">General desk context</Badge>
        )}
        <span className="text-xs text-gray-500">
          Sample thread — POST /api/v1/chat not required in mock mode
        </span>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.map((m) => (
          <div
            key={m.id}
            className={
              m.role === "user" ? "ml-8 text-right" : "mr-8 text-left"
            }
          >
            <div
              className={
                m.role === "user"
                  ? "inline-block rounded-lg bg-accent/20 px-4 py-3 text-left text-sm text-gray-100"
                  : "inline-block rounded-lg border border-surface-border bg-surface px-4 py-3 text-left text-sm text-gray-200"
              }
            >
              <div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
                {m.role === "user" ? "You" : "Bhale Bullodu"}
              </div>
              <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
              {m.citations && m.citations.length > 0 && (
                <ul className="mt-3 space-y-1 border-t border-surface-border pt-2 text-xs text-gray-500">
                  {m.citations.map((c, i) => (
                    <li key={i}>
                      {c.document}
                      {c.chapter ? ` · ${c.chapter}` : ""}
                      {c.page != null ? ` · p.${c.page}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-surface-border p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setInput(s)}
              className="rounded border border-surface-border px-2 py-1 text-xs text-gray-400 hover:border-accent hover:text-accent"
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about entry rationale, Greeks, or failure memory…"
            className="flex-1 rounded border border-surface-border bg-surface px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-accent focus:outline-none"
          />
          <Button variant="primary" disabled>
            Send
          </Button>
        </div>
      </div>
    </Card>
  );
}
