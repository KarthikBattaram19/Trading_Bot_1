import Link from "next/link";

import { getBotStatus, getDecisionLog } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { Badge, Card } from "@/components/ui/primitives";
import { STRATEGY_LABELS, type DecisionStatus } from "@/types/decisions";
import { formatPct } from "@/lib/utils";

const STATUS_VARIANT: Record<
  DecisionStatus,
  "pass" | "fail" | "warn" | "pending"
> = {
  approved: "pass",
  rejected: "fail",
  expired: "warn",
  pending: "pending",
};

export default async function DecisionsPage() {
  const [status, decisions] = await Promise.all([
    getBotStatus(),
    getDecisionLog(),
  ]);

  const counts = {
    approved: decisions.filter((d) => d.status === "approved").length,
    rejected: decisions.filter((d) => d.status === "rejected").length,
    expired: decisions.filter((d) => d.status === "expired").length,
    pending: decisions.filter((d) => d.status === "pending").length,
  };

  return (
    <>
      <SituationalBar status={status} />
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-white">Decision log</h1>
          <p className="mt-1 text-sm text-gray-500">
            Read-only audit trail of autonomous decisions — no approval queue
          </p>
        </div>

        {status.one_trade_locked && (
          <Card className="border-status-warn/50 bg-status-warn/10 px-4 py-3 text-sm text-status-warn">
            One-trade scope is locked. Close the active discretionary trade before
            another can open.
          </Card>
        )}

        <div className="grid gap-3 sm:grid-cols-4">
          <SummaryStat label="Approved" value={counts.approved} tone="pass" />
          <SummaryStat label="Rejected" value={counts.rejected} tone="fail" />
          <SummaryStat label="Expired" value={counts.expired} tone="warn" />
          <SummaryStat label="Pending" value={counts.pending} tone="pending" />
        </div>

        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-surface-border text-xs text-gray-500">
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Strategy</th>
                <th className="px-4 py-3">Confidence</th>
                <th className="px-4 py-3">Regime</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {decisions.map((d) => (
                <tr
                  key={d.decision_id}
                  className="border-b border-surface-border/50 hover:bg-surface-border/20"
                >
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">
                    {d.decision_id}
                  </td>
                  <td className="px-4 py-3 font-medium text-white">
                    {d.underlying_symbol}
                  </td>
                  <td className="px-4 py-3 text-gray-300">
                    {STRATEGY_LABELS[d.module]}
                  </td>
                  <td className="px-4 py-3 font-mono">
                    {formatPct(d.confidence)}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {d.regime.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={STATUS_VARIANT[d.status]}>{d.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {new Date(d.created_at).toLocaleString("en-IN", {
                      timeZone: "Asia/Kolkata",
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/decisions/${d.decision_id}`}
                      className="text-sm text-accent hover:underline"
                    >
                      Packet →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <SharedKillConditions />
      </div>
    </>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "pass" | "fail" | "warn" | "pending";
}) {
  const colors = {
    pass: "text-status-pass",
    fail: "text-status-fail",
    warn: "text-status-warn",
    pending: "text-status-pending",
  };
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${colors[tone]}`}>{value}</div>
    </Card>
  );
}
