import Link from "next/link";

import { getBotStatus, getDecisionLog } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { Icon, StatusPill } from "@/components/ui/primitives";
import { STRATEGY_LABELS, type DecisionStatus } from "@/types/decisions";
import { formatPct } from "@/lib/utils";

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

export default async function DecisionsPage() {
  const [status, decisions] = await Promise.all([
    getBotStatus(),
    getDecisionLog(),
  ]);

  const counts: Record<DecisionStatus, number> = {
    approved: decisions.filter((d) => d.status === "approved").length,
    rejected: decisions.filter((d) => d.status === "rejected").length,
    expired: decisions.filter((d) => d.status === "expired").length,
    pending: decisions.filter((d) => d.status === "pending").length,
  };

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-6">
          {status.one_trade_locked && (
            <div className="flex items-start gap-3 rounded-md border border-tertiary/50 bg-tertiary/10 px-4 py-3 text-data-md text-tertiary">
              <Icon name="lock" className="text-[18px]" />
              One-trade scope locked. Further autonomous entries are paused until
              the current position resolves.
            </div>
          )}

          <div>
            <h1 className="text-headline-lg text-on-surface">Decision Log</h1>
            <p className="mt-1 text-body-md text-on-surface-variant">
              Real-time trace of algorithmic reasoning and trade executions
              (read-only audit trail — no approval queue).
            </p>
          </div>

          {/* Summary cards */}
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

          {/* Log table */}
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
                        {new Date(d.created_at).toLocaleString("en-IN", {
                          timeZone: "Asia/Kolkata",
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                      <td className="p-4 text-right">
                        <Link
                          href={`/decisions/${d.decision_id}`}
                          className="inline-flex items-center gap-1 text-data-sm text-primary hover:underline"
                        >
                          Packet
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
    </>
  );
}
