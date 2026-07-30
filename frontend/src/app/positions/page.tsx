import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Badge, Card } from "@/components/ui/primitives";

const MOCK_POSITIONS = [
  {
    id: "pos_001",
    symbol: "RELIANCE",
    strategy: "Simple Volatility",
    type: "discretionary",
    status: "open" as const,
    entry: "cheap_vol_mode",
    delta: 0.02,
    gamma: 0.11,
    vega: 0.42,
    theta: -85,
    pnl: 1840.0,
    opened: "2026-07-15 09:48 IST",
    note: "Rank #2 after TATASTEEL liquidity reject — calendar + stock hedge",
  },
  {
    id: "pos_002",
    symbol: "SPY",
    strategy: "Simple Volatility",
    type: "mechanical_hedge",
    status: "open" as const,
    entry: "delta_rehedge",
    delta: 0.01,
    gamma: 0.0,
    vega: 0.0,
    theta: 0,
    pnl: 12.39,
    opened: "2026-07-15 14:22 IST",
    note: "Delta re-hedge at gamma-theta breakeven — auto-executed",
  },
  {
    id: "pos_003",
    symbol: "NIFTY",
    strategy: "Gamma Scalping",
    type: "mechanical_hedge",
    status: "open" as const,
    entry: "intraday_rehedge",
    delta: -0.03,
    gamma: 0.0,
    vega: 0.0,
    theta: 0,
    pnl: -48.2,
    opened: "2026-07-15 11:05 IST",
    note: "Index futures overlay to keep book Δ within ±0.05",
  },
  {
    id: "pos_004",
    symbol: "INTC",
    strategy: "Gamma Scalping",
    type: "discretionary",
    status: "closed" as const,
    entry: "earnings_gap_mode",
    delta: 0,
    gamma: 0,
    vega: 0,
    theta: 0,
    pnl: 625.4,
    opened: "2026-07-14 15:40 IST",
    note: "Closed D+0 after gap exceeded gamma-theta breakeven",
  },
  {
    id: "pos_005",
    symbol: "TATASTEEL",
    strategy: "Vega Scalping",
    type: "discretionary",
    status: "closed" as const,
    entry: "iv_flush",
    delta: 0,
    gamma: 0,
    vega: 0,
    theta: 0,
    pnl: -4200.0,
    opened: "2026-07-13 10:12 IST",
    note: "IV stop −3σ (N6.1) — written to failure memory",
  },
];

const HEDGE_LOG = [
  {
    time: "14:22:08",
    symbol: "SPY",
    action: "BUY 12 shares",
    reason: "Δ drifted +0.06 → re-neutralize",
    pnl: 12.39,
  },
  {
    time: "11:05:41",
    symbol: "NIFTY",
    action: "SELL 1 Jul futur",
    reason: "Portfolio Δ +0.08 after RELIANCE fill",
    pnl: -48.2,
  },
  {
    time: "09:51:02",
    symbol: "RELIANCE",
    action: "SELL 40 shares",
    reason: "Entry stock hedge for cheap-vol calendar",
    pnl: 0,
  },
];

export default async function PositionsPage() {
  const status = await getBotStatus();
  const open = MOCK_POSITIONS.filter((p) => p.status === "open");
  const closed = MOCK_POSITIONS.filter((p) => p.status === "closed");
  const openPnl = open.reduce((s, p) => s + p.pnl, 0);

  return (
    <>
      <SituationalBar status={status} />
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-white">Positions</h1>
          <p className="mt-1 text-sm text-gray-500">
            Open trades and mechanical hedge activity (not in approval queue)
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Open positions</div>
            <div className="mt-1 text-2xl font-semibold text-white">
              {open.length}
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Open mark-to-market</div>
            <div
              className={`mt-1 text-2xl font-semibold ${
                openPnl >= 0 ? "text-status-pass" : "text-status-fail"
              }`}
            >
              {openPnl >= 0 ? "+" : ""}${openPnl.toFixed(2)}
            </div>
          </Card>
          <Card className="px-4 py-3">
            <div className="text-xs text-gray-500">Closed (sample window)</div>
            <div className="mt-1 text-2xl font-semibold text-white">
              {closed.length}
            </div>
          </Card>
        </div>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">Open book</h2>
          <Card className="overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs text-gray-500">
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Entry</th>
                  <th className="px-4 py-3">Δ</th>
                  <th className="px-4 py-3">Γ</th>
                  <th className="px-4 py-3">ν</th>
                  <th className="px-4 py-3">Θ</th>
                  <th className="px-4 py-3">P&L</th>
                  <th className="px-4 py-3">Opened</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr key={p.id} className="border-b border-surface-border/50">
                    <td className="px-4 py-3 font-medium text-white">{p.symbol}</td>
                    <td className="px-4 py-3">{p.strategy}</td>
                    <td className="px-4 py-3">
                      <Badge
                        variant={
                          p.type === "discretionary" ? "pending" : "default"
                        }
                      >
                        {p.type}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-gray-400">{p.entry}</td>
                    <td className="px-4 py-3 font-mono">{p.delta}</td>
                    <td className="px-4 py-3 font-mono">{p.gamma}</td>
                    <td className="px-4 py-3 font-mono">{p.vega}</td>
                    <td className="px-4 py-3 font-mono">{p.theta}</td>
                    <td
                      className={`px-4 py-3 font-mono ${
                        p.pnl >= 0 ? "text-status-pass" : "text-status-fail"
                      }`}
                    >
                      {p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{p.opened}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="space-y-1 border-t border-surface-border px-4 py-3 text-xs text-gray-500">
              {open.map((p) => (
                <p key={`${p.id}-note`}>
                  <span className="text-gray-400">{p.symbol}:</span> {p.note}
                </p>
              ))}
            </div>
          </Card>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">
            Recently closed
          </h2>
          <Card className="overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs text-gray-500">
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Strategy</th>
                  <th className="px-4 py-3">P&L</th>
                  <th className="px-4 py-3">Note</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((p) => (
                  <tr key={p.id} className="border-b border-surface-border/50">
                    <td className="px-4 py-3 font-medium">{p.symbol}</td>
                    <td className="px-4 py-3">{p.strategy}</td>
                    <td
                      className={`px-4 py-3 font-mono ${
                        p.pnl >= 0 ? "text-status-pass" : "text-status-fail"
                      }`}
                    >
                      {p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{p.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-medium text-gray-400">
            Mechanical hedge log (today)
          </h2>
          <Card className="overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border text-xs text-gray-500">
                  <th className="px-4 py-3">Time IST</th>
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Reason</th>
                  <th className="px-4 py-3">P&L</th>
                </tr>
              </thead>
              <tbody>
                {HEDGE_LOG.map((h) => (
                  <tr key={h.time + h.symbol} className="border-b border-surface-border/50">
                    <td className="px-4 py-3 font-mono text-xs">{h.time}</td>
                    <td className="px-4 py-3 font-medium">{h.symbol}</td>
                    <td className="px-4 py-3">{h.action}</td>
                    <td className="px-4 py-3 text-gray-400">{h.reason}</td>
                    <td
                      className={`px-4 py-3 font-mono ${
                        h.pnl >= 0 ? "text-status-pass" : "text-status-fail"
                      }`}
                    >
                      {h.pnl >= 0 ? "+" : ""}${h.pnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      </div>
    </>
  );
}
