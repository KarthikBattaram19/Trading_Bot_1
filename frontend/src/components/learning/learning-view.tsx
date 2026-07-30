"use client";

import { useCallback, useState } from "react";
import { getLearningDashboard, recordTradeOutcome } from "@/lib/api";
import type { LearningDashboard, TradeOutcomeLabel } from "@/types/learning";
import { STRATEGY_LABELS } from "@/types/learning";
import { Button, Icon, Panel, StatusPill } from "@/components/ui/primitives";
import { formatDateTime, formatPct } from "@/lib/utils";

function formatInr(value: number): string {
  const s = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Math.abs(value));
  return value < 0 ? `-${s}` : s;
}

const LOOP_STEPS = [
  {
    title: "Execute",
    detail: "Rank top-3 with P1 insight packets, then open via ranked fallback.",
  },
  {
    title: "Record",
    detail: "Store recommendation snapshot for attribution on open.",
  },
  {
    title: "Retrieve",
    detail: "Pre-trade: match similar losses → confidence −0.10 if hit.",
  },
  {
    title: "Adjust",
    detail: "Close win/loss/scratch → update module weights; losses write memory.",
  },
];

export function LearningView({ initial }: { initial: LearningDashboard }) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getLearningDashboard());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setLoading(false);
    }
  }, []);

  const closeTrade = useCallback(
    async (
      tradeId: string,
      outcome: TradeOutcomeLabel,
      pnl: number,
      reason: string,
    ) => {
      setClosingId(tradeId);
      setError(null);
      try {
        await recordTradeOutcome({
          trade_id: tradeId,
          outcome,
          realized_pnl_inr: pnl,
          exit_reason: reason,
        });
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Close failed");
      } finally {
        setClosingId(null);
      }
    },
    [refresh],
  );

  return (
    <main className="flex-1 overflow-y-auto p-margin-page">
      <div className="mx-auto flex max-w-container-max flex-col gap-6">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-outline-variant pb-6">
          <div>
            <h1 className="text-headline-lg text-on-surface">Continual Loop</h1>
            <p className="mt-1 max-w-2xl text-body-md text-on-surface-variant">
              Trade outcomes feed failure memory, module attribution, and
              adaptation — then reshape the next top-3 recommendations (§12).
            </p>
            <p className="mt-1 font-mono text-data-sm text-on-surface-variant opacity-80">
              As of {formatDateTime(data.as_of)}
            </p>
          </div>
          <Button variant="primary" disabled={loading} onClick={refresh}>
            <Icon name="refresh" className="text-[18px]" />
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        </header>

        {error && (
          <div className="rounded-md border border-error/50 bg-error/10 p-3 text-data-md text-error">
            {error}
          </div>
        )}

        {data.adaptation_frozen && (
          <div className="rounded-md border border-tertiary/50 bg-tertiary/10 p-3 text-data-md text-tertiary">
            Adaptation frozen: {data.freeze_reason}
          </div>
        )}

        {/* KPIs */}
        <section className="grid grid-cols-2 gap-gutter lg:grid-cols-5">
          <Stat label="Closed Trades" value={String(data.closed_trade_count)} />
          <Stat label="Open Trades" value={String(data.open_trade_count)} />
          <Stat
            label="Win Rate"
            value={data.win_rate != null ? formatPct(data.win_rate, 0) : "—"}
            tone="pass"
          />
          <Stat
            label="Total P&L"
            value={formatInr(data.total_pnl_inr)}
            tone={data.total_pnl_inr >= 0 ? "pass" : "fail"}
          />
          <Stat label="Failure Memory" value={String(data.failure_memory_count)} />
        </section>

        {/* How the loop works */}
        <Panel
          title={
            <h3 className="text-label-caps uppercase text-on-surface">
              How the Loop Works
            </h3>
          }
        >
          <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {LOOP_STEPS.map((s, i) => (
              <li
                key={s.title}
                className="rounded-md border border-outline-variant bg-surface-container-low p-4"
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 font-mono text-data-sm font-bold text-primary">
                    {i + 1}
                  </span>
                  <span className="font-semibold text-on-surface">{s.title}</span>
                </div>
                <p className="mt-2 text-data-sm text-on-surface-variant">
                  {s.detail}
                </p>
              </li>
            ))}
          </ol>
          {data.learning_loop_notes.length > 0 && (
            <ul className="mt-4 space-y-1 border-t border-outline-variant pt-3">
              {data.learning_loop_notes.map((n) => (
                <li key={n} className="text-data-sm text-on-surface-variant">
                  {n}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Open trades */}
        <section className="space-y-3">
          <div>
            <h2 className="text-headline-md text-on-surface">
              Open Trades — record outcome
            </h2>
            <p className="mt-1 text-data-md text-on-surface-variant">
              Closing a trade writes the result into learning. Losses become
              failure-memory lessons that penalize similar future setups.
            </p>
          </div>
          {data.open_trades.length === 0 ? (
            <div className="rounded-md border border-outline-variant bg-surface p-6 text-center text-data-md text-on-surface-variant">
              No open trades. Refresh recommendations to open one via ranked
              fallback, then return here to close it.
            </div>
          ) : (
            data.open_trades.map((t) => (
              <div
                key={t.trade_id}
                className="rounded-md border border-outline-variant bg-surface p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-data-md text-primary">
                        #{t.rank}
                      </span>
                      <span className="text-lg font-semibold text-on-surface">
                        {t.underlying_symbol}
                      </span>
                      <StatusPill tone="info">
                        {STRATEGY_LABELS[t.strategy] ?? t.strategy}
                      </StatusPill>
                    </div>
                    <p className="mt-1 font-mono text-data-sm text-on-surface-variant">
                      {t.trade_id}
                    </p>
                    <p className="mt-2 text-data-md text-on-surface-variant">
                      {t.primary_signal}
                    </p>
                    <p className="mt-1 text-data-sm text-on-surface-variant opacity-80">
                      Score {t.score.toFixed(2)} · confidence{" "}
                      {formatPct(t.confidence, 0)} · opened{" "}
                      {formatDateTime(t.opened_at)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={closingId === t.trade_id}
                      onClick={() =>
                        closeTrade(
                          t.trade_id,
                          "win",
                          2500,
                          "Target hit — IV mean reversion",
                        )
                      }
                    >
                      Mark win (+₹2,500)
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={closingId === t.trade_id}
                      onClick={() =>
                        closeTrade(
                          t.trade_id,
                          "loss",
                          -3200,
                          "Stop hit — adverse IV path",
                        )
                      }
                    >
                      Mark loss (−₹3,200)
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={closingId === t.trade_id}
                      onClick={() =>
                        closeTrade(
                          t.trade_id,
                          "scratch",
                          -150,
                          "Flattened near flat — costs only",
                        )
                      }
                    >
                      Scratch
                    </Button>
                  </div>
                </div>
              </div>
            ))
          )}
        </section>

        {/* Module attribution */}
        <section className="space-y-3">
          <h2 className="text-headline-md text-on-surface">Module Attribution</h2>
          <div className="overflow-x-auto rounded-md border border-outline-variant">
            <table className="w-full min-w-[640px] border-collapse text-left text-data-md">
              <thead className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
                <tr>
                  <th className="px-3 py-2 font-normal">Strategy</th>
                  <th className="px-3 py-2 text-right font-normal">Trades</th>
                  <th className="px-3 py-2 text-right font-normal">W / L / S</th>
                  <th className="px-3 py-2 text-right font-normal">Win rate</th>
                  <th className="px-3 py-2 text-right font-normal">P&L</th>
                  <th className="px-3 py-2 text-right font-normal">Expectancy</th>
                  <th className="px-3 py-2 text-right font-normal">Weight</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {data.module_attribution.map((m) => (
                  <tr
                    key={m.strategy}
                    className="border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high"
                  >
                    <td className="px-3 py-2 font-sans text-on-surface">
                      {STRATEGY_LABELS[m.strategy] ?? m.strategy}
                    </td>
                    <td className="px-3 py-2 text-right text-on-surface-variant">
                      {m.trade_count}
                    </td>
                    <td className="px-3 py-2 text-right text-on-surface-variant">
                      {m.wins}/{m.losses}/{m.scratches}
                    </td>
                    <td className="px-3 py-2 text-right text-on-surface">
                      {m.trade_count ? formatPct(m.win_rate, 0) : "—"}
                    </td>
                    <td
                      className={`px-3 py-2 text-right ${
                        m.total_pnl_inr >= 0 ? "text-secondary" : "text-error"
                      }`}
                    >
                      {formatInr(m.total_pnl_inr)}
                    </td>
                    <td className="px-3 py-2 text-right text-on-surface-variant">
                      {formatInr(m.expectancy_inr)}
                    </td>
                    <td className="px-3 py-2 text-right text-primary">
                      ×{m.weight.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Failure memory */}
        <section className="space-y-3">
          <h2 className="text-headline-md text-on-surface">Failure Memory</h2>
          <p className="text-data-md text-on-surface-variant">
            Losing contexts retrieved before the next ranking cycle. Matching
            setups get a −0.10 confidence penalty on Recommendations.
          </p>
          <div className="space-y-3">
            {data.failure_memories.map((fm) => (
              <div
                key={fm.failure_id}
                className="rounded-md border border-l-4 border-outline-variant border-l-error bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-on-surface">
                    {fm.underlying_symbol}
                  </span>
                  <StatusPill tone="danger">
                    {STRATEGY_LABELS[fm.strategy] ?? fm.strategy}
                  </StatusPill>
                  <span className="font-mono text-data-sm text-error">
                    {formatInr(fm.loss_pnl_inr)}
                  </span>
                </div>
                <p className="mt-2 text-data-md text-on-surface-variant">
                  {fm.market_summary}
                </p>
                <p className="mt-2 text-data-md text-tertiary">
                  Lesson: {fm.lesson}
                </p>
                <p className="mt-1 text-data-sm text-on-surface-variant opacity-80">
                  Exit: {fm.exit_reason} · {fm.primary_signal}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Recent outcomes */}
        <section className="space-y-3">
          <h2 className="text-headline-md text-on-surface">Recent Outcomes</h2>
          {data.recent_outcomes.length === 0 ? (
            <div className="rounded-md border border-outline-variant bg-surface p-6 text-center text-data-md text-on-surface-variant">
              No closed outcomes yet.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border border-outline-variant">
              <table className="w-full min-w-[720px] border-collapse text-left text-data-md">
                <thead className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
                  <tr>
                    <th className="px-3 py-2 font-normal">Symbol</th>
                    <th className="px-3 py-2 font-normal">Strategy</th>
                    <th className="px-3 py-2 font-normal">Outcome</th>
                    <th className="px-3 py-2 text-right font-normal">P&L</th>
                    <th className="px-3 py-2 font-normal">Exit</th>
                    <th className="px-3 py-2 font-normal">Signal at entry</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_outcomes.map((o) => (
                    <tr
                      key={o.outcome_id}
                      className="border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high"
                    >
                      <td className="px-3 py-2 text-on-surface">
                        {o.underlying_symbol}
                      </td>
                      <td className="px-3 py-2 text-on-surface-variant">
                        {STRATEGY_LABELS[o.strategy] ?? o.strategy}
                      </td>
                      <td className="px-3 py-2">
                        <StatusPill
                          tone={
                            o.outcome === "win"
                              ? "success"
                              : o.outcome === "loss"
                                ? "danger"
                                : "neutral"
                          }
                        >
                          {o.outcome}
                        </StatusPill>
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono ${
                          o.realized_pnl_inr >= 0
                            ? "text-secondary"
                            : "text-error"
                        }`}
                      >
                        {formatInr(o.realized_pnl_inr)}
                      </td>
                      <td className="px-3 py-2 text-on-surface-variant">
                        {o.exit_reason}
                      </td>
                      <td className="max-w-xs truncate px-3 py-2 font-mono text-data-sm text-on-surface-variant opacity-80">
                        {o.primary_signal}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Adaptation history */}
        <section className="space-y-3">
          <h2 className="text-headline-md text-on-surface">Adaptation History</h2>
          {data.adaptation_history.length === 0 ? (
            <div className="rounded-md border border-outline-variant bg-surface p-6 text-center text-data-md text-on-surface-variant">
              No adaptation cycles yet. Triggers fire after enough closed trades
              with win rate &lt; 60% (under §12.5 guards).
            </div>
          ) : (
            data.adaptation_history.map((a) => (
              <div
                key={a.adaptation_id}
                className="rounded-md border border-outline-variant bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill tone={a.deployed ? "success" : "warning"}>
                    {a.deployed ? "Deployed" : "Held"}
                  </StatusPill>
                  <span className="text-data-md text-on-surface">{a.action}</span>
                  <span className="font-mono text-data-sm text-on-surface-variant">
                    {formatDateTime(a.triggered_at)}
                  </span>
                </div>
                <p className="mt-2 text-data-md text-on-surface-variant">
                  Trigger: {a.trigger}
                </p>
                <p className="mt-1 text-data-sm text-on-surface-variant opacity-80">
                  {a.detail}
                </p>
              </div>
            ))
          )}
        </section>
      </div>
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pass" | "fail";
}) {
  return (
    <div className="rounded-md border border-outline-variant bg-surface p-4">
      <div className="text-label-caps uppercase text-on-surface-variant">
        {label}
      </div>
      <div
        className={
          tone === "pass"
            ? "mt-1 font-mono text-data-lg text-secondary"
            : tone === "fail"
              ? "mt-1 font-mono text-data-lg text-error"
              : "mt-1 font-mono text-data-lg text-on-surface"
        }
      >
        {value}
      </div>
    </div>
  );
}
