"use client";

import { useState } from "react";
import Link from "next/link";
import { approveDecision, rejectDecision } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { PendingDecision } from "@/types/decisions";
import {
  ENTRY_MODE_LABELS,
  STRATEGY_LABELS,
} from "@/types/decisions";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { CountdownTimer } from "@/components/dashboard/situational-bar";
import { OssLegTable } from "@/components/dashboard/oss-leg-table";
import {
  RiskGateChecklist,
  gatesAllowApprove,
} from "@/components/dashboard/risk-gate-checklist";
import { KillConditions } from "@/components/dashboard/kill-conditions";
import {
  StatArbPanel,
  VolatilityPanel,
  GammaPanel,
  VegaPanel,
} from "@/components/dashboard/strategy-panels";

interface ApprovalCardProps {
  decision: PendingDecision;
  expanded?: boolean;
  onAction?: () => void;
}

export function ApprovalCard({
  decision,
  expanded = false,
  onAction,
}: ApprovalCardProps) {
  const [loading, setLoading] = useState<"approve" | "reject" | null>(null);
  const canApprove = gatesAllowApprove(decision.risk_gates);

  async function handleApprove() {
    setLoading("approve");
    try {
      await approveDecision(decision.decision_id);
      onAction?.();
    } finally {
      setLoading(null);
    }
  }

  async function handleReject() {
    setLoading("reject");
    try {
      await rejectDecision(decision.decision_id);
      onAction?.();
    } finally {
      setLoading(null);
    }
  }

  const entryMode = decision.strategy_context.entry_mode;

  return (
    <Card className="overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="pending">PENDING</Badge>
          <Badge variant="default">{STRATEGY_LABELS[decision.module]}</Badge>
          {entryMode && entryMode !== "standard" && (
            <Badge variant="default">{ENTRY_MODE_LABELS[entryMode]}</Badge>
          )}
          <CountdownTimer expiresAt={decision.expires_at} />
        </div>
        {!expanded && (
          <Link
            href={`/decisions/${decision.decision_id}`}
            className="text-xs text-accent hover:underline"
          >
            Full detail →
          </Link>
        )}
      </div>

      {/* Summary */}
      <div className="space-y-4 px-4 py-4">
        <div>
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="text-lg font-semibold text-white">
              {decision.underlying_symbol}
            </h2>
            <span className="font-mono text-sm text-gray-400">
              Confidence {(decision.confidence * 100).toFixed(0)}%
            </span>
            <span className="text-sm text-gray-500">Regime: {decision.regime}</span>
          </div>
          <p className="mt-2 text-sm text-gray-300">{decision.rationale}</p>
          {decision.scenario_tag && (
            <p className="mt-1 text-xs text-accent">{decision.scenario_tag}</p>
          )}
        </div>

        <StrategyPanel decision={decision} />

        {(expanded || decision.legs.length > 0) && (
          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-400">Structure (OSS)</h3>
            <OssLegTable legs={decision.legs} totals={decision.totals} />
          </div>
        )}

        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <PlanBlock
            label="Edge after costs"
            value={formatCurrency(decision.economics.net_edge_after_costs)}
            positive={decision.economics.net_edge_after_costs > 0}
          />
          <PlanBlock
            label="Margin estimate"
            value={formatCurrency(decision.economics.margin_estimate)}
          />
          <PlanBlock label="Stop" value={decision.plan.stop} small />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <PlanBlock label="Target" value={decision.plan.target} small />
          <PlanBlock label="Time exit" value={decision.plan.time_exit} small />
        </div>

        {decision.event_risks.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase text-gray-500">
              Event risks
            </h3>
            <ul className="list-inside list-disc text-sm text-status-warn">
              {decision.event_risks.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        {expanded && (
          <>
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase text-gray-500">
                LLM explanation
              </h3>
              <p className="text-sm text-gray-300">{decision.explanation}</p>
            </div>

            {decision.rag_citations.length > 0 && (
              <div>
                <h3 className="mb-1 text-xs font-medium uppercase text-gray-500">
                  RAG citations
                </h3>
                <ul className="space-y-1 text-sm text-gray-400">
                  {decision.rag_citations.map((c, i) => (
                    <li key={i}>
                      {c.document}
                      {c.chapter && ` · ${c.chapter}`}
                      {c.page != null && ` · p.${c.page}`}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {decision.failure_modes.length > 0 && (
              <KillConditions conditions={decision.failure_modes} />
            )}

            {decision.alternative_strategies && (
              <div className="text-xs text-gray-500">
                Alternatives considered: {decision.alternative_strategies.join("; ")}
              </div>
            )}

            <RiskGateChecklist gates={decision.risk_gates} />
          </>
        )}

        {!expanded && (
          <p className="text-xs text-gray-500">
            Gates: {decision.risk_gates.filter((g) => g.status === "pass").length}/
            {decision.risk_gates.length} pass
            {decision.rag_citations[0] && (
              <> · RAG: {decision.rag_citations[0].document}</>
            )}
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-surface-border bg-surface px-4 py-3">
        <Button
          variant="danger"
          disabled={loading !== null}
          onClick={handleReject}
        >
          {loading === "reject" ? "Rejecting…" : "Reject"}
        </Button>
        <Link href={`/chat?decision=${decision.decision_id}`}>
          <Button variant="ghost">Ask AI</Button>
        </Link>
        <Button
          variant="primary"
          disabled={!canApprove || loading !== null}
          onClick={handleApprove}
        >
          {loading === "approve" ? "Approving…" : "Approve ✓"}
        </Button>
      </div>
    </Card>
  );
}

function StrategyPanel({ decision }: { decision: PendingDecision }) {
  const ctx = decision.strategy_context;
  switch (decision.module) {
    case "stat_arb":
      return <StatArbPanel ctx={ctx} />;
    case "volatility":
      return <VolatilityPanel ctx={ctx} />;
    case "gamma_scalping":
      return <GammaPanel ctx={ctx} />;
    case "vega_scalping":
      return <VegaPanel ctx={ctx} />;
    default:
      return null;
  }
}

function PlanBlock({
  label,
  value,
  positive,
  small,
}: {
  label: string;
  value: string;
  positive?: boolean;
  small?: boolean;
}) {
  return (
    <div className="rounded border border-surface-border/50 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={
          small
            ? "mt-0.5 text-xs text-gray-300"
            : positive
              ? "mt-0.5 font-mono text-status-pass"
              : "mt-0.5 font-mono text-white"
        }
      >
        {value}
      </div>
    </div>
  );
}
