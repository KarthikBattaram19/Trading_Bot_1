import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Icon, StatCard, StatusPill } from "@/components/ui/primitives";
import { formatCurrency } from "@/lib/utils";

const MOCK_POSITIONS = [
  {
    id: "pos_001",
    symbol: "RELIANCE",
    strategy: "LONG_VEGA",
    type: "mechanical_hedge",
    status: "open" as const,
    delta: 0.02,
    gamma: 0.11,
    vega: 0.42,
    theta: -85,
    pnl: 4200.0,
    opened: "09:48 IST",
    note: "Gamma scaling active. Waiting for VIX confirmation > 15 to unhedge delta.",
    noteTone: "primary" as const,
  },
  {
    id: "pos_002",
    symbol: "BANKNIFTY 28DEC 48000P",
    strategy: "SHORT_STRANGLE",
    type: "core_position",
    status: "open" as const,
    delta: -0.12,
    gamma: -0.05,
    vega: -22.1,
    theta: 18.5,
    pnl: 4250.0,
    opened: "10:15 IST",
    note: "Theta decay collection. Monitoring for tail risk break below 47800.",
    noteTone: "tertiary" as const,
  },
];

const CLOSED_POSITIONS = [
  {
    id: "cls_001",
    symbol: "FINNIFTY 19DEC 21200C",
    strategy: "INTRADAY_MOMENTUM",
    pnl: -1200,
    note: "Hit time exit (15:15)",
  },
  {
    id: "cls_002",
    symbol: "NIFTY 21DEC 21400P",
    strategy: "SHORT_GAMMA",
    pnl: 3400,
    note: "Target profit reached",
  },
];

const HEDGE_LOG = [
  {
    time: "11:02:45 IST",
    action: "DELTA_NEUTRAL_HEDGE",
    symbol: "NIFTY 21DEC 21500C",
    reason: "Delta > 0.3",
    reasonTone: "error" as const,
    pnl: 0,
  },
  {
    time: "10:45:12 IST",
    action: "VEGA_EXPOSURE_REDUCE",
    symbol: "BANKNIFTY 28DEC 48000P",
    reason: "VIX Spike Detected",
    reasonTone: "tertiary" as const,
    pnl: -150,
  },
  {
    time: "09:35:00 IST",
    action: "INITIAL_HEDGE_ENTRY",
    symbol: "NIFTY 21DEC 21500C",
    reason: "Strategy Bootstrap",
    reasonTone: "secondary" as const,
    pnl: 0,
  },
];

function signedInr(v: number): string {
  return v >= 0 ? `+${formatCurrency(v)}` : formatCurrency(v);
}

function greekColor(v: number, invert = false): string {
  if (v === 0) return "text-on-surface";
  const positive = invert ? v < 0 : v > 0;
  return positive ? "text-secondary" : "text-error";
}

export default async function PositionsPage() {
  const status = await getBotStatus();
  const openPnl = MOCK_POSITIONS.reduce((s, p) => s + p.pnl, 0);

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-6">
          <h1 className="text-headline-lg text-on-surface">Positions</h1>

          {/* KPIs */}
          <section className="grid grid-cols-1 gap-gutter md:grid-cols-3">
            <StatCard label="Open Positions" value={String(MOCK_POSITIONS.length)} />
            <StatCard
              label="Open MTM P&L"
              value={signedInr(openPnl)}
              tone={openPnl >= 0 ? "success" : "danger"}
            />
            <StatCard label="Recently Closed (Today)" value="5" />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Main tables */}
            <div className="flex flex-col gap-6 lg:col-span-8">
              {/* Open Book */}
              <section>
                <h2 className="mb-4 flex items-center gap-2 text-[18px] font-semibold text-on-surface">
                  <Icon name="book" className="text-primary" />
                  Open Book
                </h2>
                <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container">
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left">
                      <thead>
                        <tr className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
                          <th className="p-4 font-normal">Symbol</th>
                          <th className="p-4 font-normal">Strategy / Type</th>
                          <th className="p-4 text-right font-normal">Greeks (Δ Γ ν Θ)</th>
                          <th className="p-4 text-right font-normal">P&L</th>
                          <th className="p-4 text-right font-normal">Opened</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono text-data-md text-on-surface">
                        {MOCK_POSITIONS.map((p) => (
                          <RowGroup key={p.id} p={p} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>

              {/* Recently Closed */}
              <section>
                <h2 className="mb-4 flex items-center gap-2 text-[18px] font-semibold text-on-surface">
                  <Icon name="history" className="text-outline" />
                  Recently Closed
                </h2>
                <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container">
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left">
                      <thead>
                        <tr className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
                          <th className="p-4 font-normal">Symbol</th>
                          <th className="p-4 font-normal">Strategy</th>
                          <th className="p-4 text-right font-normal">P&L</th>
                          <th className="p-4 font-normal">Note</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono text-data-md">
                        {CLOSED_POSITIONS.map((p) => (
                          <tr
                            key={p.id}
                            className="border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high"
                          >
                            <td className="whitespace-nowrap p-4 text-on-surface-variant">
                              {p.symbol}
                            </td>
                            <td className="p-4 text-on-surface-variant">
                              {p.strategy}
                            </td>
                            <td
                              className={`p-4 text-right ${p.pnl >= 0 ? "text-secondary" : "text-error"}`}
                            >
                              {signedInr(p.pnl)}
                            </td>
                            <td className="p-4 text-data-sm text-on-surface-variant">
                              {p.note}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            </div>

            {/* Hedge Log timeline */}
            <div className="lg:col-span-4">
              <section className="flex h-full flex-col rounded-lg border border-outline-variant bg-surface-container p-5">
                <h2 className="mb-4 flex items-center gap-2 text-[18px] font-semibold text-on-surface">
                  <Icon name="memory" className="text-tertiary" />
                  Mechanical Hedge Log (Today)
                </h2>
                <div className="flex-1 overflow-y-auto pr-2">
                  <div className="relative ml-3 space-y-6 border-l border-outline-variant pb-4">
                    {HEDGE_LOG.map((h) => (
                      <div key={h.time + h.action} className="relative pl-6">
                        <div className="absolute left-[-5px] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface-container bg-outline-variant" />
                        <div className="mb-1 font-mono text-data-sm text-on-surface-variant">
                          {h.time}
                        </div>
                        <div className="rounded-md border border-outline-variant bg-surface-container-high p-3">
                          <div className="mb-2 font-mono text-data-md text-on-surface">
                            {h.action}
                          </div>
                          <LogRow label="Symbol" value={h.symbol} />
                          <LogRow
                            label="Reason"
                            value={h.reason}
                            valueClass={
                              h.reasonTone === "error"
                                ? "text-error"
                                : h.reasonTone === "tertiary"
                                  ? "text-tertiary"
                                  : "text-secondary"
                            }
                          />
                          <LogRow
                            label="P&L Impact"
                            value={signedInr(h.pnl)}
                            valueClass={
                              h.pnl < 0 ? "text-error" : "text-on-surface"
                            }
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function RowGroup({ p }: { p: (typeof MOCK_POSITIONS)[number] }) {
  return (
    <>
      <tr className="border-b border-outline-variant transition-colors hover:bg-surface-container-high">
        <td className="whitespace-nowrap p-4">{p.symbol}</td>
        <td className="p-4">
          <div className="flex flex-col items-start gap-1">
            <span>{p.strategy}</span>
            <StatusPill tone={p.type === "core_position" ? "warning" : "success"}>
              {p.type.replace(/_/g, " ")}
            </StatusPill>
          </div>
        </td>
        <td className="whitespace-nowrap p-4 text-right font-mono text-data-sm text-on-surface-variant">
          <span className={`inline-block w-10 ${greekColor(p.delta)}`}>
            {p.delta}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-10 ${greekColor(p.gamma)}`}>
            {p.gamma}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-12 ${greekColor(p.vega)}`}>
            {p.vega}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-10 ${greekColor(p.theta, true)}`}>
            {p.theta}
          </span>
        </td>
        <td
          className={`p-4 text-right ${p.pnl >= 0 ? "text-secondary" : "text-error"}`}
        >
          {signedInr(p.pnl)}
        </td>
        <td className="p-4 text-right text-on-surface-variant">{p.opened}</td>
      </tr>
      <tr className="border-b border-outline-variant bg-surface-container-lowest">
        <td
          colSpan={5}
          className={`border-l-2 p-3 pl-8 font-mono text-data-sm text-on-surface-variant ${
            p.noteTone === "primary" ? "border-primary" : "border-tertiary"
          }`}
        >
          <span
            className={`mr-2 font-bold ${p.noteTone === "primary" ? "text-primary" : "text-tertiary"}`}
          >
            PHASE:
          </span>
          {p.note}
        </td>
      </tr>
    </>
  );
}

function LogRow({
  label,
  value,
  valueClass = "text-on-surface",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="mb-1 flex items-center justify-between font-mono text-data-sm text-on-surface-variant last:mb-0">
      <span>{label}:</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}
