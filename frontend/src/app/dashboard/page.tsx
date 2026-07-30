import Link from "next/link";

import {
  getApiHealth,
  getBotStatus,
  getFeedStatus,
  getPaperSimHealth,
} from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { FeedStatusPanel } from "@/components/recommendations/feed-status";
import { Badge, Card } from "@/components/ui/primitives";
import type { FeedSource } from "@/types/recommendations";
import { formatCurrency, formatPct } from "@/lib/utils";

/**
 * Phase 0 frontend shell (implementation_plan 0.8 / UI_Dashboard):
 * bot status, API + paper-sim health, feed status, kill-switch placeholder.
 */
export default async function DashboardPage() {
  const [status, apiHealth, paperHealth, feeds] = await Promise.all([
    getBotStatus(),
    getApiHealth(),
    getPaperSimHealth(),
    getFeedStatus(),
  ]);
  const feedSources: FeedSource[] = feeds;

  return (
    <>
      <SituationalBar status={status} />
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-white">Bot overview</h1>
          <p className="mt-1 text-sm text-gray-500">
            Phase 0 shell — ICICI Direct data-only marks · shadow mode · kill-switch
            placeholder · no place_order
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Execution" value={status.execution_mode} />
          <StatCard
            label="Supervision"
            value={status.supervision_mode ?? status.autonomy}
          />
          <StatCard label="Scheduler" value={status.scheduler_mode} />
          <StatCard
            label="Kill switch"
            value={status.kill_switch_armed ? "armed" : "inactive"}
            highlight={Boolean(status.kill_switch_armed)}
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="p-4">
            <div className="text-xs text-gray-500">API health</div>
            <div className="mt-1 flex items-center gap-2">
              <Badge variant={apiHealth.status === "ok" ? "pass" : "fail"}>
                {apiHealth.status}
              </Badge>
              <span className="text-sm text-gray-400">
                mode {apiHealth.execution_mode}
                {apiHealth.place_order_enabled
                  ? " · place_order on"
                  : " · no place_order"}
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-500">
              Phase {apiHealth.phase ?? "0"} · containers not required · Nixpacks
              remote
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-xs text-gray-500">Paper-sim health</div>
            <div className="mt-1 text-sm text-white">
              {String(paperHealth.module ?? "paper_sim")}
              {paperHealth.status ? ` · ${String(paperHealth.status)}` : ""}
            </div>
            <div className="mt-2 text-xs text-gray-500">
              {paperHealth.broker_place_order
                ? "WARNING: place_order coupled"
                : "Separate from ICICI Direct live orders (broker_place_order: false)"}
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-xs text-gray-500">Daily P&L</div>
            <div
              className={`mt-1 text-2xl font-semibold ${
                status.daily_pnl >= 0 ? "text-status-pass" : "text-status-fail"
              }`}
            >
              {formatCurrency(status.daily_pnl)}
            </div>
            <div className="mt-2 text-xs text-gray-500">
              Win rate {formatPct(status.win_rate)} · DD{" "}
              {status.drawdown_pct.toFixed(1)}%
            </div>
          </Card>
        </div>

        <Card className="p-4">
          <div className="mb-3">
            <h2 className="font-medium text-white">Feed status</h2>
            <p className="text-sm text-gray-500">
              ICICI Direct marks + Market_News (MCP registry retired)
            </p>
          </div>
          <FeedStatusPanel sources={feedSources} />
        </Card>

        <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div>
            <h2 className="font-medium text-white">Next surfaces</h2>
            <p className="text-sm text-gray-500">
              Recommendations and supervised cockpit expand after Phase 0 exit
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/recommendations"
              className="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-blue-600"
            >
              Recommendations →
            </Link>
            <Link
              href="/risk"
              className="rounded border border-surface-border px-4 py-2 text-sm text-gray-300 hover:border-accent/50"
            >
              Risk →
            </Link>
          </div>
        </Card>
      </div>
    </>
  );
}

function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={
          highlight
            ? "mt-1 font-medium text-status-pending"
            : "mt-1 font-medium capitalize text-white"
        }
      >
        {value.replace(/_/g, " ")}
      </div>
    </Card>
  );
}
