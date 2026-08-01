import Link from "next/link";

import {
  getApiHealth,
  getBotStatus,
  getFeedStatus,
  getPaperSimHealth,
} from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { FeedStatusPanel } from "@/components/recommendations/feed-status";
import { Icon, Panel, StatCard, StatusPill } from "@/components/ui/primitives";
import type { FeedSource } from "@/types/recommendations";
import { formatCurrency, formatPct } from "@/lib/utils";

/**
 * Phase 0 overview (implementation_plan 0.8 / UI_Dashboard) — restyled to the
 * Bhale Bullodu "Command Center" design system (Stitch export).
 */
export default async function DashboardPage() {
  const [status, apiHealth, paperHealth, feeds] = await Promise.all([
    getBotStatus(),
    getApiHealth(),
    getPaperSimHealth(),
    getFeedStatus(),
  ]);
  const feedSources: FeedSource[] = feeds;
  const supervision = status.supervision_mode ?? status.autonomy;
  const paperPass = String(paperHealth.status ?? "").toLowerCase() === "ready";
  const mode = status.execution_mode.toLowerCase();
  const executionPill =
    mode === "paper"
      ? { tone: "success" as const, text: "ACTIVE" }
      : mode === "live"
        ? { tone: "danger" as const, text: "LIVE" }
        : { tone: "warning" as const, text: "SIM" };
  const killArmed = Boolean(status.kill_switch_armed);

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-gutter">
          <div>
            <h1 className="text-headline-lg font-semibold text-on-surface">
              Bot Overview
            </h1>
            <p className="mt-1 text-body-md text-on-surface-variant">
              Phase {apiHealth.phase ?? "—"} · {status.execution_mode} · ICICI
              Direct data-only marks ·{" "}
              {apiHealth.place_order_enabled
                ? "place_order enabled"
                : "no place_order"}
            </p>
          </div>

          {/* KPI stat cards */}
          <section className="grid grid-cols-1 gap-gutter md:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Execution Mode"
              value={status.execution_mode.toUpperCase()}
              tone={mode === "paper" ? "success" : mode === "live" ? "danger" : "warning"}
              pill={executionPill}
            />
            <StatCard
              label="Supervision"
              value={supervision.toUpperCase()}
              pill={{ tone: "warning", text: "MANUAL" }}
            />
            <StatCard
              label="Scheduler"
              value={status.scheduler_mode.toUpperCase()}
              pill={{
                tone: status.scheduler_mode === "paused" ? "warning" : "success",
                text: status.scheduler_mode === "paused" ? "PAUSED" : "ACTIVE",
              }}
            />
            <StatCard
              label="Kill Switch Status"
              value={killArmed ? "ARMED" : "STANDBY"}
              tone={killArmed ? "danger" : "default"}
              icon={killArmed ? "warning" : undefined}
            />
          </section>

          {/* Health & P&L */}
          <section className="grid grid-cols-1 gap-gutter lg:grid-cols-3">
            <Panel title="API Health">
              <div className="flex items-center gap-3">
                <StatusPill tone={apiHealth.status === "ok" ? "success" : "danger"}>
                  {apiHealth.status === "ok" ? "ACTIVE" : apiHealth.status}
                </StatusPill>
                <StatusPill
                  tone={
                    String(apiHealth.execution_mode).toLowerCase() === "paper"
                      ? "success"
                      : "neutral"
                  }
                >
                  {apiHealth.execution_mode} mode
                </StatusPill>
              </div>
              <div className="mt-4 flex items-center gap-2 text-body-md text-on-surface">
                <Icon
                  name="check_circle"
                  className="text-[16px] text-secondary"
                  filled
                />
                ICICI Direct{" "}
                {apiHealth.place_order_enabled
                  ? "· place_order ON"
                  : "stable · no place_order"}
              </div>
              <p className="mt-2 text-data-sm text-on-surface-variant">
                Phase {apiHealth.phase ?? "0"} · containers not required ·
                Nixpacks remote
              </p>
            </Panel>

            <Panel title="Paper-Sim Health">
              <div className="flex items-center gap-3">
                <StatusPill tone={paperPass ? "success" : "warning"}>
                  {paperPass ? "PASS" : String(paperHealth.status ?? "…")}
                </StatusPill>
                <StatusPill tone="neutral">
                  {String(paperHealth.module ?? "paper_sim")}
                </StatusPill>
              </div>
              <div className="mt-4 flex items-center gap-2 text-body-md text-on-surface">
                <Icon name="science" className="text-[16px] text-primary" />
                Simulating NFO trades
              </div>
              <p className="mt-2 text-data-sm text-on-surface-variant">
                {paperHealth.broker_place_order
                  ? "WARNING: place_order coupled"
                  : "Separate from ICICI Direct live orders (broker_place_order: false)"}
              </p>
            </Panel>

            <Panel
              title="Daily P&L"
              bodyClassName="relative overflow-hidden"
            >
              <Icon
                name="monitoring"
                className="pointer-events-none absolute right-2 top-2 text-6xl text-on-surface/5"
              />
              <div
                className={`font-mono text-[36px] leading-[44px] font-bold ${
                  status.daily_pnl >= 0 ? "text-secondary" : "text-error"
                }`}
              >
                {formatCurrency(status.daily_pnl)}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-4 border-t border-outline-variant pt-4">
                <div>
                  <span className="mb-1 block text-[10px] uppercase tracking-wider text-on-surface-variant">
                    Win Rate
                  </span>
                  <span className="font-mono text-data-md text-on-surface">
                    {formatPct(status.win_rate)}
                  </span>
                </div>
                <div>
                  <span className="mb-1 block text-[10px] uppercase tracking-wider text-on-surface-variant">
                    Drawdown
                  </span>
                  <span
                    className={`font-mono text-data-md ${
                      status.drawdown_pct > 5 ? "text-error" : "text-on-surface"
                    }`}
                  >
                    {status.drawdown_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
            </Panel>
          </section>

          {/* Feed status */}
          <Panel
            title="Feed Status"
            action={
              <span className="text-data-sm text-on-surface-variant">
                ICICI Direct marks + Market_News · MCP registry retired
              </span>
            }
          >
            <FeedStatusPanel sources={feedSources} />
          </Panel>

          {/* Next surfaces */}
          <footer className="mt-2 flex flex-col gap-4 sm:flex-row">
            <NavCard
              href="/recommendations"
              icon="auto_graph"
              label="Recommendations"
              tone="primary"
            />
            <NavCard href="/risk" icon="security" label="Risk Management" tone="error" />
          </footer>
        </div>
      </main>
    </>
  );
}

function NavCard({
  href,
  icon,
  label,
  tone,
}: {
  href: string;
  icon: string;
  label: string;
  tone: "primary" | "error";
}) {
  return (
    <Link
      href={href}
      className="group flex flex-1 items-center justify-between rounded-md border border-outline-variant bg-surface-container p-4 transition-colors hover:bg-surface-container-high"
    >
      <div className="flex items-center gap-3">
        <div
          className={
            tone === "primary"
              ? "rounded bg-primary-container/20 p-2"
              : "rounded bg-error-container/20 p-2"
          }
        >
          <Icon
            name={icon}
            className={tone === "primary" ? "text-primary" : "text-error"}
          />
        </div>
        <span
          className={
            tone === "primary"
              ? "text-sm font-bold text-on-surface transition-colors group-hover:text-primary"
              : "text-sm font-bold text-on-surface transition-colors group-hover:text-error"
          }
        >
          {label}
        </span>
      </div>
      <Icon name="arrow_forward" className="text-on-surface-variant" />
    </Link>
  );
}
