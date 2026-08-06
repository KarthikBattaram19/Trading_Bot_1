import { getBotStatus, getRiskSnapshot } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Icon, StatCard, StatusPill } from "@/components/ui/primitives";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { formatCurrency, formatGreek, formatTime } from "@/lib/utils";
import type { BreakerTone, RiskBreaker, RiskSnapshot } from "@/types/risk";

function barColor(pct: number): string {
  if (pct > 80) return "bg-error";
  if (pct >= 50) return "bg-tertiary";
  return "bg-secondary";
}

function greekTextColor(pct: number): string {
  if (pct > 80) return "text-error";
  if (pct >= 50) return "text-tertiary";
  return "text-secondary";
}

function formatBreakerCurrent(b: RiskBreaker): string {
  switch (b.unit) {
    case "pct":
      return `${b.current.toFixed(1)}%`;
    case "inr":
      return formatCurrency(b.current);
    case "sec":
      return b.current < 1
        ? `${(b.current * 1000).toFixed(0)}ms`
        : `${b.current.toFixed(1)}s`;
    case "count":
      return String(Math.round(b.current));
    default:
      return String(b.current);
  }
}

function formatBreakerLimit(b: RiskBreaker): string {
  switch (b.unit) {
    case "pct":
      return `${b.limit.toFixed(1)}%`;
    case "inr":
      return formatCurrency(b.limit);
    case "sec":
      return b.limit < 1
        ? `${(b.limit * 1000).toFixed(0)}ms`
        : `${b.limit.toFixed(0)}s`;
    case "count":
      return String(Math.round(b.limit));
    default:
      return String(b.limit);
  }
}

function toneLabel(tone: BreakerTone): string {
  if (tone === "safe") return "Safe";
  if (tone === "warn") return "Warn";
  return "Breach";
}

function activeBreakersLabel(snap: RiskSnapshot): string {
  if (snap.circuit_breakers_active.length === 0) return "None";
  return snap.circuit_breakers_active
    .map((id) => id.replace(/_/g, " "))
    .join(", ");
}

export default async function RiskPage() {
  const [status, risk] = await Promise.all([getBotStatus(), getRiskSnapshot()]);
  const drawdownLimit = risk.limits.max_drawdown_pct;
  const activeTone =
    risk.circuit_breakers_active.length === 0
      ? "success"
      : risk.circuit_breakers.some((b) => b.tone === "danger")
        ? "danger"
        : "warning";

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-6">
          <div>
            <h1 className="text-headline-lg text-on-surface">Risk Dashboard</h1>
            <p className="mt-1 text-body-md text-on-surface-variant">
              Circuit breakers, portfolio Greek limits, and recent risk events
              from paper-sim.
            </p>
          </div>

          <section className="grid grid-cols-1 gap-gutter md:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Equity" value={formatCurrency(risk.equity_inr)} />
            <StatCard
              label="Drawdown"
              value={`${risk.drawdown_pct.toFixed(1)}%`}
              tone={
                risk.drawdown_pct >= drawdownLimit
                  ? "danger"
                  : risk.drawdown_pct >= drawdownLimit * 0.5
                    ? "warning"
                    : "default"
              }
              change={{
                text: `of ${drawdownLimit.toFixed(0)}% limit`,
                positive: false,
              }}
            />
            <StatCard
              label="Reserved Margin"
              value={formatCurrency(risk.reserved_margin_inr)}
            />
            <StatCard
              label="Active Breakers"
              value={activeBreakersLabel(risk)}
              tone={activeTone}
              icon={
                risk.circuit_breakers_active.length === 0
                  ? "check_circle"
                  : "warning"
              }
            />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="flex flex-col gap-6 lg:col-span-8">
              <section className="rounded-lg border border-outline-variant bg-surface-container p-6">
                <h2 className="mb-4 text-headline-md text-on-surface">
                  Circuit Breakers
                </h2>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {risk.circuit_breakers.map((b) => (
                    <div
                      key={b.id}
                      className="rounded-md border border-outline-variant bg-surface-dim p-4"
                    >
                      <div className="mb-4 flex items-start justify-between">
                        <h3 className="font-mono text-data-md text-on-surface">
                          {b.name}
                        </h3>
                        <StatusPill
                          tone={
                            b.tone === "safe"
                              ? "success"
                              : b.tone === "warn"
                                ? "warning"
                                : "danger"
                          }
                        >
                          {toneLabel(b.tone)}
                        </StatusPill>
                      </div>
                      <div className="space-y-2 font-mono text-data-sm">
                        <div className="flex justify-between">
                          <span className="text-on-surface-variant">Current</span>
                          <span className="text-on-surface">
                            {formatBreakerCurrent(b)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-on-surface-variant">Limit</span>
                          <span className="text-on-surface">
                            {formatBreakerLimit(b)}
                          </span>
                        </div>
                        <div className="mt-2 h-1.5 w-full rounded-full bg-surface-container-high">
                          <div
                            className={`h-1.5 rounded-full ${barColor(b.pct)}`}
                            style={{ width: `${Math.min(100, b.pct)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="flex-1 rounded-lg border border-outline-variant bg-surface-container p-6">
                <h2 className="mb-4 text-headline-md text-on-surface">
                  Recent Risk Events
                </h2>
                <div className="space-y-3">
                  {risk.events.length === 0 ? (
                    <p className="text-data-md text-on-surface-variant">
                      No risk events recorded.
                    </p>
                  ) : (
                    risk.events.map((a) => (
                      <div
                        key={`${a.ts}-${a.text}`}
                        className="flex items-start gap-4 rounded-md border border-transparent p-3 transition-colors hover:border-outline-variant hover:bg-surface-container-high"
                      >
                        <StatusPill
                          tone={
                            a.level === "warn"
                              ? "warning"
                              : a.level === "info"
                                ? "info"
                                : "danger"
                          }
                          className="mt-0.5"
                        >
                          {a.level}
                        </StatusPill>
                        <p className="flex-1 text-data-md text-on-surface">
                          {a.text}
                        </p>
                        <span className="whitespace-nowrap font-mono text-data-sm text-on-surface-variant">
                          {formatTime(a.ts)}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>

            <div className="flex flex-col gap-6 lg:col-span-4">
              <section className="flex-1 rounded-lg border border-outline-variant bg-surface-container p-6">
                <h2 className="mb-4 text-headline-md text-on-surface">
                  Greek Limits
                </h2>
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-outline-variant">
                      <th className="py-3 pr-4 text-label-caps uppercase text-on-surface-variant">
                        Greek
                      </th>
                      <th className="py-3 px-4 text-right text-label-caps uppercase text-on-surface-variant">
                        Current
                      </th>
                      <th className="py-3 pl-4 text-right text-label-caps uppercase text-on-surface-variant">
                        Util %
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {risk.greek_limits.map((row, i) => (
                      <tr
                        key={row.greek}
                        className={`transition-colors hover:bg-surface-container-high ${
                          i < risk.greek_limits.length - 1
                            ? "border-b border-outline-variant"
                            : ""
                        }`}
                      >
                        <td className="py-4 pr-4 font-mono text-data-md text-on-surface">
                          {row.greek}
                        </td>
                        <td className="py-4 px-4 text-right font-mono text-data-md text-on-surface">
                          {formatGreek(row.current)}
                        </td>
                        <td className="py-4 pl-4 text-right font-mono text-data-md">
                          <div className="flex items-center justify-end gap-2">
                            <span className={greekTextColor(row.pct)}>
                              {row.pct.toFixed(0)}%
                            </span>
                            <div className="h-1 w-12 rounded-full bg-surface-container-high">
                              <div
                                className={`h-1 rounded-full ${barColor(row.pct)}`}
                                style={{
                                  width: `${Math.min(100, row.pct)}%`,
                                }}
                              />
                            </div>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          </div>

          <SharedKillConditions conditions={risk.shared_kill_conditions} />

          <div className="flex items-center justify-end gap-2 py-2 text-data-sm text-on-surface-variant">
            <Icon
              name="shield"
              className={`text-[16px] ${
                risk.greeks_within_limits ? "text-secondary" : "text-error"
              }`}
              filled
            />
            {risk.greeks_within_limits
              ? "All portfolio Greeks within configured limits"
              : `Greek limit breach: ${risk.greeks_failures.join(", ") || "check limits"}`}
          </div>
        </div>
      </main>
    </>
  );
}
