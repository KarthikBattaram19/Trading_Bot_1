import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Icon, StatCard, StatusPill } from "@/components/ui/primitives";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { formatCurrency } from "@/lib/utils";

type BreakerTone = "safe" | "warn" | "danger";

const BREAKERS: {
  name: string;
  current: string;
  limit: string;
  pct: number;
  tone: BreakerTone;
}[] = [
  { name: "Max Drawdown", current: "2.4%", limit: "10.0%", pct: 24, tone: "safe" },
  { name: "Max Daily Loss", current: "₹45,000", limit: "₹50,000", pct: 90, tone: "warn" },
  { name: "Consecutive Losses", current: "1", limit: "3", pct: 33, tone: "safe" },
  { name: "Feed Staleness", current: "12ms", limit: "500ms", pct: 2, tone: "safe" },
];

const GREEK_LIMITS = [
  { greek: "Delta", current: "150", pct: 30 },
  { greek: "Gamma", current: "-45", pct: 45 },
  { greek: "Vega", current: "1,200", pct: 80 },
  { greek: "Theta", current: "500", pct: 25 },
];

const ALERTS = [
  {
    time: "10:42:15 AM",
    level: "info" as const,
    text: "Volatility spike detected in underlying NIFTY. Margins dynamically adjusted.",
  },
  {
    time: "10:15:02 AM",
    level: "warn" as const,
    text: "Daily loss limit approaching 90% threshold.",
  },
  {
    time: "09:15:00 AM",
    level: "info" as const,
    text: "Session started. Initializing margin checks.",
  },
];

const EQUITY = { current: 1_000_000, reserved_margin: 240_000 };

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

export default async function RiskPage() {
  const status = await getBotStatus();

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-6">
          <div>
            <h1 className="text-headline-lg text-on-surface">Risk Dashboard</h1>
            <p className="mt-1 text-body-md text-on-surface-variant">
              Circuit breakers, portfolio Greek limits, and recent risk events.
            </p>
          </div>

          {/* KPI row */}
          <section className="grid grid-cols-1 gap-gutter md:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Equity" value={formatCurrency(EQUITY.current)} />
            <StatCard
              label="Drawdown"
              value="2.4%"
              tone="warning"
              change={{ text: "of 10% limit", positive: false }}
            />
            <StatCard
              label="Reserved Margin"
              value={formatCurrency(EQUITY.reserved_margin)}
            />
            <StatCard
              label="Active Breakers"
              value="None"
              tone="success"
              icon="check_circle"
            />
          </section>

          {/* Bento */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Left */}
            <div className="flex flex-col gap-6 lg:col-span-8">
              <section className="rounded-lg border border-outline-variant bg-surface-container p-6">
                <h2 className="mb-4 text-headline-md text-on-surface">
                  Circuit Breakers
                </h2>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {BREAKERS.map((b) => (
                    <div
                      key={b.name}
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
                          {b.tone === "safe" ? "Safe" : b.tone === "warn" ? "Warn" : "Breach"}
                        </StatusPill>
                      </div>
                      <div className="space-y-2 font-mono text-data-sm">
                        <div className="flex justify-between">
                          <span className="text-on-surface-variant">Current</span>
                          <span className="text-on-surface">{b.current}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-on-surface-variant">Limit</span>
                          <span className="text-on-surface">{b.limit}</span>
                        </div>
                        <div className="mt-2 h-1.5 w-full rounded-full bg-surface-container-high">
                          <div
                            className={`h-1.5 rounded-full ${barColor(b.pct)}`}
                            style={{ width: `${b.pct}%` }}
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
                  {ALERTS.map((a) => (
                    <div
                      key={a.time + a.text}
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
                      <p className="flex-1 text-data-md text-on-surface">{a.text}</p>
                      <span className="whitespace-nowrap font-mono text-data-sm text-on-surface-variant">
                        {a.time}
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            {/* Right */}
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
                    {GREEK_LIMITS.map((row, i) => (
                      <tr
                        key={row.greek}
                        className={`transition-colors hover:bg-surface-container-high ${
                          i < GREEK_LIMITS.length - 1
                            ? "border-b border-outline-variant"
                            : ""
                        }`}
                      >
                        <td className="py-4 pr-4 font-mono text-data-md text-on-surface">
                          {row.greek}
                        </td>
                        <td className="py-4 px-4 text-right font-mono text-data-md text-on-surface">
                          {row.current}
                        </td>
                        <td className="py-4 pl-4 text-right font-mono text-data-md">
                          <div className="flex items-center justify-end gap-2">
                            <span className={greekTextColor(row.pct)}>
                              {row.pct}%
                            </span>
                            <div className="h-1 w-12 rounded-full bg-surface-container-high">
                              <div
                                className={`h-1 rounded-full ${barColor(row.pct)}`}
                                style={{ width: `${row.pct}%` }}
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

          <SharedKillConditions />

          <div className="flex items-center justify-end gap-2 py-2 text-data-sm text-on-surface-variant">
            <Icon name="shield" className="text-[16px] text-secondary" filled />
            All portfolio Greeks within configured limits
          </div>
        </div>
      </main>
    </>
  );
}
