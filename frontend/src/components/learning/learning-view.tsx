"use client";

import { useCallback, useState } from "react";
import { getLearningDashboard, recordTradeOutcome } from "@/lib/api";
import type {
  LearningDashboard,
  TradeOutcomeLabel,
} from "@/types/learning";
import { STRATEGY_LABELS } from "@/types/learning";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { formatDateTime, formatPct } from "@/lib/utils";

function formatInr(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

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
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white">
            Continual learning loop
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Trade outcomes feed failure memory, module attribution, and
            adaptation — then reshape the next top-3 recommendations (§12)
          </p>
          <p className="mt-1 font-mono text-xs text-gray-600">
            As of {formatDateTime(data.as_of)}
          </p>
        </div>
        <Button variant="primary" disabled={loading} onClick={refresh}>
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </header>

      {error && (
        <Card className="border-status-fail/50 bg-status-fail/10 p-3 text-sm text-status-fail">
          {error}
        </Card>
      )}

      {data.adaptation_frozen && (
        <Card className="border-status-warn/50 bg-status-warn/10 p-3 text-sm text-status-warn">
          Adaptation frozen: {data.freeze_reason}
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Closed trades" value={String(data.closed_trade_count)} />
        <Stat label="Open trades" value={String(data.open_trade_count)} />
        <Stat
          label="Win rate"
          value={data.win_rate != null ? formatPct(data.win_rate, 0) : "—"}
        />
        <Stat
          label="Total P&L"
          value={formatInr(data.total_pnl_inr)}
          tone={data.total_pnl_inr >= 0 ? "pass" : "fail"}
        />
        <Stat
          label="Failure memory"
          value={String(data.failure_memory_count)}
        />
      </div>

      {data.learning_loop_notes.length > 0 && (
        <Card className="p-4">
          <h2 className="text-xs font-medium uppercase tracking-wide text-gray-500">
            How the loop works
          </h2>
          <ol className="mt-3 space-y-2 text-sm text-gray-400">
            <li>
              1. Rank top-3 with P1 insight packets (strategy, score, gates,
              logic).
            </li>
            <li>
              2. Pre-trade: retrieve similar losses from failure memory →
              confidence −0.10 if matched.
            </li>
            <li>
              3. Open trade → store recommendation snapshot for attribution.
            </li>
            <li>
              4. Close with win/loss/scratch + P&L → update module weights;
              losses write failure memory.
            </li>
            <li>
              5. Adaptation triggers (win rate, drawdown) under §12.5 guards
              reshape future rankings.
            </li>
          </ol>
          <ul className="mt-3 space-y-1">
            {data.learning_loop_notes.map((n) => (
              <li key={n} className="text-xs text-gray-600">
                {n}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium text-white">
          Open trades — record outcome
        </h2>
        <p className="text-sm text-gray-500">
          Closing a trade writes the result into learning. Losses become
          failure-memory lessons that penalize similar future setups.
        </p>
        {data.open_trades.length === 0 ? (
          <Card className="p-6 text-center text-sm text-gray-500">
            No open trades. Refresh recommendations to open one via ranked
            fallback, then return here to close it.
          </Card>
        ) : (
          data.open_trades.map((t) => (
            <Card key={t.trade_id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm text-accent">
                      #{t.rank}
                    </span>
                    <span className="text-lg font-semibold text-white">
                      {t.underlying_symbol}
                    </span>
                    <Badge variant="pending">
                      {STRATEGY_LABELS[t.strategy] ?? t.strategy}
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-xs text-gray-500">
                    {t.trade_id}
                  </p>
                  <p className="mt-2 text-sm text-gray-400">{t.primary_signal}</p>
                  <p className="mt-1 text-xs text-gray-600">
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
            </Card>
          ))
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium text-white">Module attribution</h2>
        <div className="overflow-x-auto rounded-lg border border-surface-border">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-surface-border bg-surface-raised text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Trades</th>
                <th className="px-3 py-2">W / L / S</th>
                <th className="px-3 py-2">Win rate</th>
                <th className="px-3 py-2">P&L</th>
                <th className="px-3 py-2">Expectancy</th>
                <th className="px-3 py-2">Weight</th>
              </tr>
            </thead>
            <tbody>
              {data.module_attribution.map((m) => (
                <tr
                  key={m.strategy}
                  className="border-b border-surface-border/50"
                >
                  <td className="px-3 py-2 text-gray-200">
                    {STRATEGY_LABELS[m.strategy] ?? m.strategy}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-400">
                    {m.trade_count}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-400">
                    {m.wins}/{m.losses}/{m.scratches}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-300">
                    {m.trade_count ? formatPct(m.win_rate, 0) : "—"}
                  </td>
                  <td
                    className={`px-3 py-2 font-mono ${
                      m.total_pnl_inr >= 0
                        ? "text-status-pass"
                        : "text-status-fail"
                    }`}
                  >
                    {formatInr(m.total_pnl_inr)}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-400">
                    {formatInr(m.expectancy_inr)}
                  </td>
                  <td className="px-3 py-2 font-mono text-accent">
                    ×{m.weight.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium text-white">Failure memory</h2>
        <p className="text-sm text-gray-500">
          Losing contexts retrieved before the next ranking cycle. Matching
          setups get a −0.10 confidence penalty on Recommendations.
        </p>
        <div className="space-y-3">
          {data.failure_memories.map((fm) => (
            <Card
              key={fm.failure_id}
              className="border-l-4 border-status-fail p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-white">
                  {fm.underlying_symbol}
                </span>
                <Badge variant="fail">
                  {STRATEGY_LABELS[fm.strategy] ?? fm.strategy}
                </Badge>
                <span className="font-mono text-xs text-status-fail">
                  {formatInr(fm.loss_pnl_inr)}
                </span>
              </div>
              <p className="mt-2 text-sm text-gray-400">{fm.market_summary}</p>
              <p className="mt-2 text-sm text-status-warn">
                Lesson: {fm.lesson}
              </p>
              <p className="mt-1 text-xs text-gray-600">
                Exit: {fm.exit_reason} · {fm.primary_signal}
              </p>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium text-white">Recent outcomes</h2>
        {data.recent_outcomes.length === 0 ? (
          <Card className="p-6 text-center text-sm text-gray-500">
            No closed outcomes yet.
          </Card>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-surface-border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-surface-border bg-surface-raised text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2">Outcome</th>
                  <th className="px-3 py-2">P&L</th>
                  <th className="px-3 py-2">Exit</th>
                  <th className="px-3 py-2">Signal at entry</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_outcomes.map((o) => (
                  <tr
                    key={o.outcome_id}
                    className="border-b border-surface-border/50"
                  >
                    <td className="px-3 py-2 text-white">
                      {o.underlying_symbol}
                    </td>
                    <td className="px-3 py-2 text-gray-400">
                      {STRATEGY_LABELS[o.strategy] ?? o.strategy}
                    </td>
                    <td className="px-3 py-2">
                      <Badge
                        variant={
                          o.outcome === "win"
                            ? "pass"
                            : o.outcome === "loss"
                              ? "fail"
                              : "default"
                        }
                      >
                        {o.outcome}
                      </Badge>
                    </td>
                    <td
                      className={`px-3 py-2 font-mono ${
                        o.realized_pnl_inr >= 0
                          ? "text-status-pass"
                          : "text-status-fail"
                      }`}
                    >
                      {formatInr(o.realized_pnl_inr)}
                    </td>
                    <td className="px-3 py-2 text-gray-500">{o.exit_reason}</td>
                    <td className="max-w-xs truncate px-3 py-2 font-mono text-xs text-gray-600">
                      {o.primary_signal}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium text-white">
          Adaptation history
        </h2>
        {data.adaptation_history.length === 0 ? (
          <Card className="p-6 text-center text-sm text-gray-500">
            No adaptation cycles yet. Triggers fire after enough closed trades
            with win rate &lt; 60% (under §12.5 guards).
          </Card>
        ) : (
          data.adaptation_history.map((a) => (
            <Card key={a.adaptation_id} className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={a.deployed ? "pass" : "warn"}>
                  {a.deployed ? "Deployed" : "Held"}
                </Badge>
                <span className="text-sm text-white">{a.action}</span>
                <span className="font-mono text-xs text-gray-600">
                  {formatDateTime(a.triggered_at)}
                </span>
              </div>
              <p className="mt-2 text-sm text-gray-400">
                Trigger: {a.trigger}
              </p>
              <p className="mt-1 text-xs text-gray-500">{a.detail}</p>
            </Card>
          ))
        )}
      </section>
    </div>
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
    <Card className="p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={
          tone === "pass"
            ? "mt-1 font-mono text-lg text-status-pass"
            : tone === "fail"
              ? "mt-1 font-mono text-lg text-status-fail"
              : "mt-1 font-mono text-lg text-white"
        }
      >
        {value}
      </div>
    </Card>
  );
}
