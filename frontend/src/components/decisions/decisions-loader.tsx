"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getDecisionLog } from "@/lib/api";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { Icon, StatusPill } from "@/components/ui/primitives";
import {
  STRATEGY_LABELS,
  type DecisionStatus,
  type PendingDecision,
} from "@/types/decisions";
import { formatDateTime, formatPct } from "@/lib/utils";

const STATUS_TONE: Record<
  DecisionStatus,
  "success" | "danger" | "warning" | "info"
> = {
  approved: "success",
  rejected: "danger",
  expired: "warning",
  pending: "info",
};

const STAT_META: {
  key: DecisionStatus;
  label: string;
  color: string;
  icon: string;
}[] = [
  { key: "approved", label: "Approved", color: "text-secondary", icon: "check_circle" },
  { key: "rejected", label: "Rejected", color: "text-error", icon: "cancel" },
  { key: "expired", label: "Expired", color: "text-tertiary", icon: "schedule" },
  { key: "pending", label: "Pending", color: "text-primary", icon: "hourglass_top" },
];

export function DecisionsLoader({
  oneTradeLocked,
}: {
  oneTradeLocked: boolean;
}) {
  const [decisions, setDecisions] = useState<PendingDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getDecisionLog();
        if (!cancelled) setDecisions(next);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load decisions");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto max-w-container-max rounded-md border border-error/50 bg-error/10 p-4 text-data-md text-error">
          Could not load decision log: {error}
        </div>
      </main>
    );
  }

  if (!decisions) {
    return (
      <main className="flex flex-1 items-center justify-center p-margin-page">
        <div className="flex items-center gap-3 text-body-md text-on-surface-variant">
          <Icon name="progress_activity" className="animate-spin text-[22px]" />
          Loading decision log…
        </div>
      </main>
    );
  }

  const counts: Record<DecisionStatus, number> = {
    approved: decisions.filter((d) => d.status === "approved").length,
    rejected: decisions.filter((d) => d.status === "rejected").length,
    expired: decisions.filter((d) => d.status === "expired").length,
    pending: decisions.filter((d) => d.status === "pending").length,
  };

  return (
    <main className="flex-1 overflow-y-auto p-margin-page">
      <div className="mx-auto flex max-w-container-max flex-col gap-6">
        {oneTradeLocked && (
          <div className="flex items-start gap-3 rounded-md border border-tertiary/50 bg-tertiary/10 px-4 py-3 text-data-md text-tertiary">
            <Icon name="lock" className="text-[18px]" />
            One-trade scope locked. Further autonomous entries are paused until
            the current position resolves.
          </div>
        )}

        <div>
          <h1 className="text-headline-lg text-on-surface">Decision Log</h1>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Real-time trace of algorithmic reasoning and trade executions.
            Open a <span className="font-medium text-on-surface">Pending</span>{" "}
            row&apos;s packet to approve or reject it — approved decisions execute
            through <span className="font-mono">paper_sim</span>.
          </p>
        </div>

        <section className="grid grid-cols-1 gap-gutter sm:grid-cols-2 lg:grid-cols-4">
          {STAT_META.map((s) => (
            <div
              key={s.key}
              className="flex items-center justify-between rounded-md border border-outline-variant bg-surface p-4"
            >
              <div>
                <div className="text-label-caps uppercase text-on-surface-variant">
                  {s.label}
                </div>
                <div className={`mt-1 font-mono text-data-lg ${s.color}`}>
                  {counts[s.key]}
                </div>
              </div>
              <Icon name={s.icon} className={`text-[24px] ${s.color}`} />
            </div>
          ))}
        </section>

        <div className="overflow-hidden rounded-md border border-outline-variant bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
                  <th className="p-4 font-normal">Decision</th>
                  <th className="p-4 font-normal">Symbol</th>
                  <th className="p-4 font-normal">Strategy</th>
                  <th className="p-4 text-right font-normal">Confidence</th>
                  <th className="p-4 font-normal">Regime</th>
                  <th className="p-4 font-normal">Status</th>
                  <th className="p-4 font-normal">Created</th>
                  <th className="p-4 font-normal" />
                </tr>
              </thead>
              <tbody className="text-data-md">
                {decisions.map((d, i) => (
                  <tr
                    key={`${d.decision_id}:${d.status}:${d.created_at}:${i}`}
                    className="border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high"
                  >
                    <td className="p-4 font-mono text-data-sm text-on-surface-variant">
                      {d.decision_id}
                    </td>
                    <td className="p-4 font-medium text-on-surface">
                      {d.underlying_symbol}
                    </td>
                    <td className="p-4 text-on-surface-variant">
                      {STRATEGY_LABELS[d.module]}
                    </td>
                    <td className="p-4 text-right font-mono text-on-surface">
                      {formatPct(d.confidence)}
                    </td>
                    <td className="p-4 text-on-surface-variant">
                      {d.regime.replace(/_/g, " ")}
                    </td>
                    <td className="p-4">
                      <StatusPill tone={STATUS_TONE[d.status]}>
                        {d.status}
                      </StatusPill>
                    </td>
                    <td className="p-4 font-mono text-data-sm text-on-surface-variant">
                      {formatDateTime(d.created_at)}
                    </td>
                    <td className="p-4 text-right">
                      <Link
                        href={`/decisions/${d.decision_id}`}
                        className={
                          d.status === "pending"
                            ? "inline-flex items-center gap-1 text-data-sm font-medium text-primary hover:underline"
                            : "inline-flex items-center gap-1 text-data-sm text-primary hover:underline"
                        }
                      >
                        {d.status === "pending" ? "Review & approve" : "Packet"}
                        <Icon name="arrow_forward" className="text-[14px]" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <SharedKillConditions />
      </div>
    </main>
  );
}
