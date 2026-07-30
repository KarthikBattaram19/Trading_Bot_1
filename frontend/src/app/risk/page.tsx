import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Badge, Card } from "@/components/ui/primitives";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";

const BREAKERS = [
  {
    name: "Max drawdown",
    threshold: "10% equity",
    current: "3.2%",
    status: "ok" as const,
  },
  {
    name: "Max daily loss",
    threshold: "2% equity",
    current: "+0.34% (pnl)",
    status: "ok" as const,
  },
  {
    name: "Max concurrent discretionary",
    threshold: "1",
    current: "1 open",
    status: "ok" as const,
  },
  {
    name: "Consecutive losses",
    threshold: "5",
    current: "2",
    status: "ok" as const,
  },
  {
    name: "Feed staleness",
    threshold: "< 30s L1",
    current: "4s",
    status: "ok" as const,
  },
  {
    name: "Kill switch",
    threshold: "inactive",
    current: "inactive",
    status: "ok" as const,
  },
];

const GREEK_LIMITS = [
  { greek: "Delta", current: 0.04, limit: 0.15, unit: "" },
  { greek: "Gamma", current: 0.82, limit: 2.0, unit: "" },
  { greek: "Vega", current: 0.35, limit: 1.5, unit: "" },
  { greek: "Theta", current: -120, limit: -500, unit: "$/day" },
];

const ALERTS = [
  {
    time: "14:22 IST",
    level: "info" as const,
    text: "Mechanical Δ re-hedge on SPY — within Greek limits",
  },
  {
    time: "09:48 IST",
    level: "warn" as const,
    text: "TATASTEEL rank #1 liquidity reject — fell back to RELIANCE #2",
  },
  {
    time: "Yesterday",
    level: "info" as const,
    text: "AMZN/META packet rejected — high notional margin warn",
  },
  {
    time: "2 days ago",
    level: "fail" as const,
    text: "NIFTY cheap-vol approval window expired — not submitted",
  },
];

const EQUITY = {
  starting: 1_000_000,
  current: 1_003_425,
  peak: 1_036_800,
  reserved_margin: 95_400,
};

export default async function RiskPage() {
  const status = await getBotStatus();
  const utilization =
    ((EQUITY.peak - EQUITY.current) / EQUITY.peak) * 100;

  return (
    <>
      <SituationalBar status={status} />
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-white">Risk dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Circuit breakers, portfolio Greek limits, and recent risk events
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Equity (paper)</div>
            <div className="mt-1 font-mono text-lg text-white">
              ₹{EQUITY.current.toLocaleString("en-IN")}
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Peak / DD used</div>
            <div className="mt-1 font-mono text-lg text-status-warn">
              {utilization.toFixed(1)}% of 10%
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Reserved margin</div>
            <div className="mt-1 font-mono text-lg text-white">
              ₹{EQUITY.reserved_margin.toLocaleString("en-IN")}
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Active breakers</div>
            <div className="mt-1 text-lg font-semibold text-status-pass">
              None
            </div>
          </Card>
        </div>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">
            Circuit breakers
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {BREAKERS.map((b) => (
              <Card
                key={b.name}
                className="flex items-center justify-between px-4 py-3"
              >
                <div>
                  <div className="font-medium text-white">{b.name}</div>
                  <div className="text-xs text-gray-500">
                    Limit: {b.threshold}
                  </div>
                  <div className="mt-1 text-xs text-gray-400">
                    Now: {b.current}
                  </div>
                </div>
                <Badge variant="pass">{b.status}</Badge>
              </Card>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">Greek limits</h2>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs text-gray-500">
                  <th className="px-4 py-3 text-left">Greek</th>
                  <th className="px-4 py-3 text-right">Current</th>
                  <th className="px-4 py-3 text-right">Limit</th>
                  <th className="px-4 py-3 text-right">Utilization</th>
                  <th className="px-4 py-3 text-left">Headroom bar</th>
                </tr>
              </thead>
              <tbody>
                {GREEK_LIMITS.map((row) => {
                  const used =
                    row.greek === "Theta"
                      ? Math.abs(row.current) / Math.abs(row.limit)
                      : Math.abs(row.current) / Math.abs(row.limit);
                  const pct = Math.min(100, used * 100);
                  const tone =
                    pct > 80
                      ? "bg-status-fail"
                      : pct > 50
                        ? "bg-status-warn"
                        : "bg-status-pass";
                  return (
                    <tr
                      key={row.greek}
                      className="border-b border-surface-border/50"
                    >
                      <td className="px-4 py-3">{row.greek}</td>
                      <td className="px-4 py-3 text-right font-mono">
                        {row.current}
                        {row.unit ? (
                          <span className="ml-1 text-xs text-gray-500">
                            {row.unit}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-gray-500">
                        {row.limit}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-status-pass">
                        {pct.toFixed(0)}%
                      </td>
                      <td className="px-4 py-3">
                        <div className="h-2 w-full max-w-[160px] rounded bg-surface-border">
                          <div
                            className={`h-2 rounded ${tone}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">
            Recent risk events
          </h2>
          <Card className="divide-y divide-surface-border">
            {ALERTS.map((a) => (
              <div
                key={a.time + a.text}
                className="flex items-start gap-3 px-4 py-3 text-sm"
              >
                <Badge
                  variant={
                    a.level === "fail"
                      ? "fail"
                      : a.level === "warn"
                        ? "warn"
                        : "pass"
                  }
                >
                  {a.level}
                </Badge>
                <div>
                  <div className="text-gray-200">{a.text}</div>
                  <div className="mt-0.5 text-xs text-gray-500">{a.time}</div>
                </div>
              </div>
            ))}
          </Card>
        </section>

        <SharedKillConditions />
      </div>
    </>
  );
}
