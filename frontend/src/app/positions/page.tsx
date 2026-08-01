import {
  getBotStatus,
  getPaperAccount,
  getPaperAutomationStatus,
  getPaperPositions,
} from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { Icon, StatCard, StatusPill } from "@/components/ui/primitives";
import {
  formatCurrency,
  formatGreek,
  formatTime,
} from "@/lib/utils";
import type {
  PaperAutomationAction,
  PaperPosition,
} from "@/types/paper-sim";

function signedInr(v: number): string {
  return v >= 0 ? `+${formatCurrency(v)}` : formatCurrency(v);
}

function greekColor(v: number, invert = false): string {
  if (v === 0) return "text-on-surface";
  const positive = invert ? v < 0 : v > 0;
  return positive ? "text-secondary" : "text-error";
}

function istYmd(value: string | Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function isTodayIst(iso: string | null | undefined): boolean {
  if (!iso) return false;
  return istYmd(iso) === istYmd(new Date());
}

function positionSymbol(p: PaperPosition): string {
  if (p.legs.length === 1) return p.legs[0].symbol;
  if (p.legs.length > 1) {
    const labels = p.legs.map((l) => l.symbol);
    if (labels.every((s) => s === labels[0])) return labels[0];
    return p.underlying
      ? `${p.underlying} (${p.legs.length} legs)`
      : labels.slice(0, 2).join(" / ");
  }
  return p.underlying ?? p.position_id;
}

function positionType(p: PaperPosition): "mechanical_hedge" | "core_position" {
  const tag = (p.strategy_tag ?? "").toLowerCase();
  if (tag.includes("hedge") || tag.includes("rehedge")) return "mechanical_hedge";
  return "core_position";
}

function phaseNote(p: PaperPosition): { text: string; tone: "primary" | "tertiary" } {
  if (p.note?.trim()) {
    return {
      text: p.note.trim(),
      tone: positionType(p) === "mechanical_hedge" ? "primary" : "tertiary",
    };
  }
  if (!p.structure_complete) {
    return {
      text: "Opening multi-leg structure incomplete — auto-completion pending under capital / freshness / lot gates.",
      tone: "primary",
    };
  }
  if (p.last_rehedge_at) {
    return {
      text: `γ–θ monitoring. Breakeven paid ${p.breakeven_paid_count ?? 0}. Last re-hedge ${formatTime(p.last_rehedge_at)}.`,
      tone: "tertiary",
    };
  }
  return {
    text: "Open paper position. Marks from ICICI Direct LTP.",
    tone: "tertiary",
  };
}

const HEDGE_ACTIONS = new Set([
  "rehedge",
  "flatten",
  "flatten_failed",
  "multi_leg_auto_complete",
  "multi_leg_auto_complete_failed",
]);

function hedgeLogRows(actions: PaperAutomationAction[] | undefined) {
  const rows = (actions ?? [])
    .filter((a) => HEDGE_ACTIONS.has(String(a.action ?? "")))
    .filter((a) => !a.at || isTodayIst(a.at))
    .slice()
    .reverse();

  return rows.map((a, i) => {
    const actionLabel = String(a.note ?? a.method ?? a.action ?? "ACTION")
      .toString()
      .toUpperCase()
      .replace(/\s+/g, "_");
    const symbol =
      (typeof a.underlying === "string" && a.underlying) ||
      (typeof a.position_id === "string" && a.position_id) ||
      "—";
    const reasonRaw = a.reason ?? a.note ?? a.detail ?? "—";
    const reason =
      typeof reasonRaw === "string"
        ? reasonRaw
        : JSON.stringify(reasonRaw);
    const pnl =
      typeof a.realized_pnl === "number"
        ? a.realized_pnl
        : typeof a.pnl === "number"
          ? Number(a.pnl)
          : 0;
    const reasonTone =
      String(a.action).includes("fail") || /stale|kill|spike|error/i.test(reason)
        ? ("error" as const)
        : String(a.action) === "rehedge"
          ? ("tertiary" as const)
          : ("secondary" as const);

    return {
      key: `${a.at ?? i}-${actionLabel}-${symbol}`,
      time: a.at ? formatTime(a.at) : "—",
      action: actionLabel,
      symbol,
      reason,
      reasonTone,
      pnl,
    };
  });
}

async function loadPositionsPageData() {
  const status = await getBotStatus();
  try {
    const [open, closed, account, automation] = await Promise.all([
      getPaperPositions("open"),
      getPaperPositions("closed"),
      getPaperAccount(),
      getPaperAutomationStatus(),
    ]);
    return { status, open, closed, account, automation, error: null as string | null };
  } catch (err) {
    return {
      status,
      open: [] as PaperPosition[],
      closed: [] as PaperPosition[],
      account: null,
      automation: null,
      error: err instanceof Error ? err.message : "Failed to load paper positions",
    };
  }
}

export default async function PositionsPage() {
  const { status, open, closed, account, automation, error } =
    await loadPositionsPageData();

  const openPnl =
    account?.unrealized_pnl ??
    open.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
  const closedToday = closed.filter((p) => isTodayIst(p.closed_at));
  const hedgeLog = hedgeLogRows(automation?.last_actions);

  return (
    <>
      <SituationalBar status={status} />
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-container-max flex-col gap-6">
          <div>
            <h1 className="text-headline-lg text-on-surface">Positions</h1>
            <p className="mt-1 text-body-md text-on-surface-variant">
              Paper-sim ledger · ICICI Direct marks
              {automation?.state ? ` · automation ${automation.state}` : ""}
            </p>
          </div>

          {error ? (
            <div className="rounded-lg border border-error/40 bg-error/10 px-4 py-3 text-body-md text-error">
              Could not load positions from paper-sim: {error}
            </div>
          ) : null}

          <section className="grid grid-cols-1 gap-gutter md:grid-cols-3">
            <StatCard label="Open Positions" value={String(open.length)} />
            <StatCard
              label="Open MTM P&L"
              value={signedInr(openPnl)}
              tone={openPnl >= 0 ? "success" : "danger"}
            />
            <StatCard
              label="Recently Closed (Today)"
              value={String(closedToday.length)}
            />
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="flex flex-col gap-6 lg:col-span-8">
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
                          <th className="p-4 text-right font-normal">
                            Greeks (Δ Γ ν Θ)
                          </th>
                          <th className="p-4 text-right font-normal">P&L</th>
                          <th className="p-4 text-right font-normal">Opened</th>
                        </tr>
                      </thead>
                      <tbody className="font-mono text-data-md text-on-surface">
                        {open.length === 0 ? (
                          <tr>
                            <td
                              colSpan={5}
                              className="p-6 text-center text-body-md text-on-surface-variant"
                            >
                              No open paper positions.
                            </td>
                          </tr>
                        ) : (
                          open.map((p) => <RowGroup key={p.position_id} p={p} />)
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>

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
                        {closedToday.length === 0 ? (
                          <tr>
                            <td
                              colSpan={4}
                              className="p-6 text-center text-body-md text-on-surface-variant"
                            >
                              No positions closed today.
                            </td>
                          </tr>
                        ) : (
                          closedToday.map((p) => (
                            <tr
                              key={p.position_id}
                              className="border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high"
                            >
                              <td className="whitespace-nowrap p-4 text-on-surface-variant">
                                {positionSymbol(p)}
                              </td>
                              <td className="p-4 text-on-surface-variant">
                                {p.strategy_tag ?? "—"}
                              </td>
                              <td
                                className={`p-4 text-right ${
                                  p.realized_pnl >= 0
                                    ? "text-secondary"
                                    : "text-error"
                                }`}
                              >
                                {signedInr(p.realized_pnl)}
                              </td>
                              <td className="p-4 text-data-sm text-on-surface-variant">
                                {p.note?.trim() ||
                                  (p.closed_at
                                    ? `Closed ${formatTime(p.closed_at)}`
                                    : "—")}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            </div>

            <div className="lg:col-span-4">
              <section className="flex h-full flex-col rounded-lg border border-outline-variant bg-surface-container p-5">
                <h2 className="mb-4 flex items-center gap-2 text-[18px] font-semibold text-on-surface">
                  <Icon name="memory" className="text-tertiary" />
                  Mechanical Hedge Log (Today)
                </h2>
                <div className="flex-1 overflow-y-auto pr-2">
                  {hedgeLog.length === 0 ? (
                    <p className="text-body-md text-on-surface-variant">
                      No mechanical hedge / flatten actions recorded today.
                    </p>
                  ) : (
                    <div className="relative ml-3 space-y-6 border-l border-outline-variant pb-4">
                      {hedgeLog.map((h) => (
                        <div key={h.key} className="relative pl-6">
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
                  )}
                </div>
              </section>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function RowGroup({ p }: { p: PaperPosition }) {
  const type = positionType(p);
  const note = phaseNote(p);
  const delta = p.total_delta ?? 0;
  const gamma = p.total_gamma ?? 0;
  const vega = p.total_vega ?? 0;
  const theta = p.total_theta ?? 0;
  const pnl = p.unrealized_pnl ?? 0;

  return (
    <>
      <tr className="border-b border-outline-variant transition-colors hover:bg-surface-container-high">
        <td className="whitespace-nowrap p-4">{positionSymbol(p)}</td>
        <td className="p-4">
          <div className="flex flex-col items-start gap-1">
            <span>{p.strategy_tag ?? "—"}</span>
            <StatusPill tone={type === "core_position" ? "warning" : "success"}>
              {type.replace(/_/g, " ")}
            </StatusPill>
          </div>
        </td>
        <td className="whitespace-nowrap p-4 text-right font-mono text-data-sm text-on-surface-variant">
          <span className={`inline-block w-10 ${greekColor(delta)}`}>
            {formatGreek(delta)}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-10 ${greekColor(gamma)}`}>
            {formatGreek(gamma)}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-12 ${greekColor(vega)}`}>
            {formatGreek(vega)}
          </span>{" "}
          |{" "}
          <span className={`inline-block w-10 ${greekColor(theta, true)}`}>
            {formatGreek(theta)}
          </span>
        </td>
        <td
          className={`p-4 text-right ${pnl >= 0 ? "text-secondary" : "text-error"}`}
        >
          {signedInr(pnl)}
        </td>
        <td className="p-4 text-right text-on-surface-variant">
          {formatTime(p.opened_at)}
        </td>
      </tr>
      <tr className="border-b border-outline-variant bg-surface-container-lowest">
        <td
          colSpan={5}
          className={`border-l-2 p-3 pl-8 font-mono text-data-sm text-on-surface-variant ${
            note.tone === "primary" ? "border-primary" : "border-tertiary"
          }`}
        >
          <span
            className={`mr-2 font-bold ${
              note.tone === "primary" ? "text-primary" : "text-tertiary"
            }`}
          >
            PHASE:
          </span>
          {note.text}
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
    <div className="mb-1 flex items-center justify-between gap-3 font-mono text-data-sm text-on-surface-variant last:mb-0">
      <span>{label}:</span>
      <span className={`max-w-[70%] truncate text-right ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}
