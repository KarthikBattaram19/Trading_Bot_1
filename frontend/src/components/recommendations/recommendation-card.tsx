"use client";

import { useState } from "react";
import type { InstrumentRecommendation } from "@/types/recommendations";
import type { AutonomousExecutionResult } from "@/types/trades";
import { rankStatusFromResult } from "@/types/trades";
import {
  ENTRY_MODE_LABELS,
  STRATEGY_TYPE_LABELS,
} from "@/types/recommendations";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { formatPct } from "@/lib/utils";
import { StrategyInsightPanel } from "@/components/recommendations/strategy-insight-panel";

const RANK_STYLES = ["border-accent", "border-status-pass/60", "border-gray-600"];

const EXECUTION_BADGE: Record<
  ReturnType<typeof rankStatusFromResult>,
  { label: string; variant: "pass" | "fail" | "pending" | "default" | "warn" }
> = {
  pending: { label: "Not executed", variant: "default" },
  attempting: { label: "Attempting…", variant: "pending" },
  succeeded: { label: "Trade opened", variant: "pass" },
  failed: { label: "Open failed — trying next rank", variant: "fail" },
  skipped: { label: "Skipped (earlier rank succeeded)", variant: "default" },
};

type InsightTab =
  | "overview"
  | "score"
  | "gates"
  | "logic"
  | "plan"
  | "learning"
  | "checklist";

const TABS: { id: InsightTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "score", label: "Score" },
  { id: "gates", label: "Gates" },
  { id: "logic", label: "Logic trail" },
  { id: "plan", label: "Plan & risks" },
  { id: "learning", label: "Learning" },
  { id: "checklist", label: "P1 checklist" },
];

function formatInr(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

/** Complete insight packet for one ranked recommendation (Trading_Parameters P1). */
export function RecommendationCard({
  rec,
  executionResult = null,
}: {
  rec: InstrumentRecommendation;
  executionResult?: AutonomousExecutionResult | null;
}) {
  const [tab, setTab] = useState<InsightTab>("overview");
  const rankStyle = RANK_STYLES[rec.rank - 1] ?? "border-surface-border";
  const strategyLabel = STRATEGY_TYPE_LABELS[rec.strategy.selected_strategy];
  const entryLabel = rec.strategy.entry_mode
    ? ENTRY_MODE_LABELS[rec.strategy.entry_mode] ?? rec.strategy.entry_mode
    : null;

  const gatesPassed = rec.parameter_gates.filter((g) => g.passed).length;
  const gatesTotal = rec.parameter_gates.length;

  const execStatus = rankStatusFromResult(rec.rank, executionResult, false);
  const execBadge = EXECUTION_BADGE[execStatus];
  const attempt = executionResult?.attempts.find((a) => a.rank === rec.rank);

  const cheap =
    rec.parameters.iv_annualized < rec.parameters.garch_forecast;

  return (
    <Card className={`border-l-4 ${rankStyle}`}>
      {/* Header */}
      <div className="border-b border-surface-border px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/20 font-mono text-sm font-bold text-accent">
              #{rec.rank}
            </span>
            <div>
              <h3 className="text-lg font-semibold text-white">
                {rec.underlying_symbol}
              </h3>
              <div className="mt-1 flex flex-wrap gap-2">
                <Badge variant="pass">{strategyLabel}</Badge>
                {entryLabel && <Badge variant="pending">{entryLabel}</Badge>}
                <Badge variant="default">{rec.strategy.scenario_tag}</Badge>
                {executionResult && (
                  <Badge variant={execBadge.variant}>{execBadge.label}</Badge>
                )}
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-500">Confidence</div>
            <div className="font-mono text-lg text-status-pass">
              {formatPct(rec.confidence, 0)}
            </div>
            <div className="text-xs text-gray-600">
              score {rec.score.toFixed(2)} · gates {gatesPassed}/{gatesTotal}
            </div>
          </div>
        </div>
        <p className="mt-3 text-sm text-gray-300">{rec.entry_rationale}</p>
        <p className="mt-2 text-xs text-accent">{rec.why_this_rank}</p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 border-b border-surface-border px-3 py-2">
        {TABS.map((t) => (
          <Button
            key={t.id}
            size="sm"
            variant={tab === t.id ? "primary" : "ghost"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      <div className="space-y-5 p-5">
        {tab === "overview" && (
          <>
            <section>
              <SectionTitle>Market condition (P1.3)</SectionTitle>
              <p className="mt-2 text-sm text-gray-300">{rec.market_summary}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric
                  label="Spot (A4)"
                  value={`₹${rec.parameters.und_price.toFixed(2)}`}
                />
                <Metric
                  label="IV (G4)"
                  value={formatPct(rec.parameters.iv_annualized)}
                  tone={cheap ? "pass" : "warn"}
                />
                <Metric
                  label="GARCH (H10)"
                  value={formatPct(rec.parameters.garch_forecast)}
                />
                <Metric
                  label="IV z-score (N4)"
                  value={
                    rec.parameters.iv_z_score != null
                      ? rec.parameters.iv_z_score.toFixed(2)
                      : "—"
                  }
                />
                <Metric
                  label="ATM premium"
                  value={`₹${rec.parameters.atm_premium_inr}`}
                />
                <Metric label="DTE" value={`${rec.parameters.dte}d`} />
                <Metric
                  label="Volume / OI"
                  value={`${rec.parameters.volume.toLocaleString()} / ${rec.parameters.open_interest.toLocaleString()}`}
                />
                <Metric
                  label="Spread"
                  value={`${rec.parameters.spread_pct}%`}
                />
              </div>
            </section>

            <section>
              <SectionTitle>Strategy fit (Table SH-4)</SectionTitle>
              <div className="mt-2">
                <StrategyInsightPanel rec={rec} />
              </div>
              <p className="mt-3 text-xs text-gray-500">
                Matrix: {rec.strategy.cross_strategy_matrix_ref}
              </p>
              {rec.strategy.news_impact && (
                <p className="mt-1 text-xs text-status-pending">
                  News: {rec.strategy.news_impact}
                </p>
              )}
            </section>

            <section className="grid gap-4 sm:grid-cols-2">
              <div>
                <SectionTitle>Hedge construction (P1.5)</SectionTitle>
                <dl className="mt-2 space-y-1 text-sm">
                  <Row label="Method" value={rec.hedge.method} />
                  <Row label="Greek targets" value={rec.hedge.greek_targets} />
                  <Row label="Structure" value={rec.hedge.structure_note} />
                </dl>
              </div>
              <div>
                <SectionTitle>Economics (P1.6)</SectionTitle>
                <dl className="mt-2 space-y-1 text-sm">
                  <Row
                    label="Margin est."
                    value={formatInr(rec.economics.margin_estimate_inr)}
                  />
                  <Row
                    label="Budget cap"
                    value={formatInr(rec.economics.max_trade_budget_inr)}
                  />
                  <Row
                    label="ATM premium"
                    value={formatInr(rec.economics.atm_premium_inr)}
                  />
                  <Row
                    label="Est. slippage"
                    value={`${rec.economics.estimated_slippage_pct}%`}
                  />
                </dl>
                <p className="mt-2 text-xs text-gray-500">
                  {rec.economics.net_edge_note}
                </p>
              </div>
            </section>

            {rec.strategy.rejected_strategies.length > 0 && (
              <section>
                <SectionTitle>Why not other strategies</SectionTitle>
                <ul className="mt-2 space-y-1">
                  {rec.strategy.rejected_strategies.map((r) => (
                    <li key={r} className="text-xs text-gray-400">
                      ✗ {r}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}

        {tab === "score" && (
          <section>
            <SectionTitle>Score breakdown</SectionTitle>
            <p className="mt-1 text-xs text-gray-500">
              Transparent ranking components used to place this trade in the top
              3
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Metric label="Base" value={rec.score_breakdown.base.toFixed(2)} />
              <Metric
                label="Strategy boost"
                value={`+${rec.score_breakdown.strategy_boost.toFixed(2)}`}
                tone="pass"
              />
              <Metric
                label="Liquidity boost"
                value={`+${rec.score_breakdown.liquidity_boost.toFixed(2)}`}
                tone="pass"
              />
              <Metric
                label="Spread penalty"
                value={`−${rec.score_breakdown.spread_penalty.toFixed(2)}`}
                tone="warn"
              />
              {(rec.score_breakdown.failure_memory_penalty ?? 0) > 0 && (
                <Metric
                  label="Failure-memory"
                  value={`−${(rec.score_breakdown.failure_memory_penalty ?? 0).toFixed(2)} conf`}
                  tone="warn"
                />
              )}
            </div>
            <div className="mt-4 rounded border border-surface-border/60 px-4 py-3">
              <div className="flex items-baseline justify-between">
                <span className="text-xs text-gray-500">Total score</span>
                <span className="font-mono text-xl text-white">
                  {rec.score_breakdown.total.toFixed(3)}
                </span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded bg-surface-border">
                <div
                  className="h-full rounded bg-accent"
                  style={{
                    width: `${Math.min(100, rec.score_breakdown.total * 100)}%`,
                  }}
                />
              </div>
            </div>
            <ul className="mt-4 space-y-1">
              {rec.score_breakdown.components.map((c) => (
                <li key={c} className="font-mono text-xs text-gray-400">
                  {c}
                </li>
              ))}
            </ul>
          </section>
        )}

        {tab === "gates" && (
          <section>
            <SectionTitle>
              Parameter gates ({gatesPassed}/{gatesTotal} pass)
            </SectionTitle>
            <ul className="mt-3 space-y-2">
              {rec.parameter_gates.map((g) => (
                <li
                  key={g.gate_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-surface-border/50 px-3 py-2 text-sm"
                >
                  <span className={g.passed ? "text-gray-300" : "text-status-fail"}>
                    {g.passed ? "✓" : "✗"} {g.gate_id}: {g.label}
                  </span>
                  <span className="font-mono text-xs text-gray-500">
                    {g.detail}
                    {g.parameter_ref ? ` · ${g.parameter_ref}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {tab === "logic" && (
          <section>
            <SectionTitle>Complete decision logic</SectionTitle>
            <ol className="mt-3 space-y-2">
              {rec.complete_logic.map((step, i) => (
                <li
                  key={i}
                  className="rounded border border-surface-border/40 px-3 py-2 font-mono text-xs text-gray-400"
                >
                  {step}
                </li>
              ))}
            </ol>
            {rec.alternative_considered && (
              <p className="mt-3 text-xs text-gray-600">
                Top alternative rejected: {rec.alternative_considered}
              </p>
            )}
          </section>
        )}

        {tab === "plan" && (
          <div className="grid gap-4 sm:grid-cols-3">
            <MiniBlock title="Exit plan (P1.7)" items={[rec.exit_plan]} />
            <MiniBlock title="Event risks (P1.8)" items={rec.event_risks} />
            <MiniBlock title="Failure modes (P1.9)" items={rec.failure_modes} />
          </div>
        )}

        {tab === "learning" && (
          <section className="space-y-4">
            <SectionTitle>Continual learning (§12)</SectionTitle>
            {!rec.learning ? (
              <p className="text-sm text-gray-500">
                No learning overlay on this packet yet.
              </p>
            ) : (
              <>
                <p className="text-sm text-gray-300">
                  {rec.learning.learning_note}
                </p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Metric
                    label="Confidence before"
                    value={formatPct(rec.learning.confidence_before, 0)}
                  />
                  <Metric
                    label="Penalty"
                    value={
                      rec.learning.confidence_penalty > 0
                        ? `−${formatPct(rec.learning.confidence_penalty, 0)}`
                        : "None"
                    }
                    tone={
                      rec.learning.confidence_penalty > 0 ? "warn" : undefined
                    }
                  />
                  <Metric
                    label="Confidence after"
                    value={formatPct(rec.learning.confidence_after, 0)}
                    tone={
                      rec.learning.confidence_penalty > 0 ? "warn" : "pass"
                    }
                  />
                  <Metric
                    label="Module trades"
                    value={String(rec.learning.module_trade_count)}
                  />
                </div>
                {rec.learning.module_win_rate != null && (
                  <p className="text-xs text-gray-500">
                    Module win rate{" "}
                    {formatPct(rec.learning.module_win_rate, 0)}
                    {rec.learning.module_expectancy_inr != null &&
                      ` · expectancy ${formatInr(rec.learning.module_expectancy_inr)}`}
                  </p>
                )}
                {rec.learning.failure_matches.length > 0 ? (
                  <div className="space-y-3">
                    <SectionTitle>
                      Similar past losses (
                      {rec.learning.failure_matches.length})
                    </SectionTitle>
                    {rec.learning.failure_matches.map((m) => (
                      <div
                        key={m.failure_id}
                        className="rounded border border-status-fail/40 px-3 py-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-white">
                            {m.underlying_symbol}
                          </span>
                          <Badge variant="fail">{m.strategy}</Badge>
                          <span className="font-mono text-xs text-gray-500">
                            sim {formatPct(m.similarity, 0)}
                          </span>
                          <span className="font-mono text-xs text-status-fail">
                            {formatInr(m.loss_pnl_inr)}
                          </span>
                        </div>
                        <p className="mt-2 text-xs text-gray-400">
                          {m.summary}
                        </p>
                        <p className="mt-2 text-xs text-status-warn">
                          Lesson: {m.lesson}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">
                    No similar failure-memory contexts for this setup.
                  </p>
                )}
              </>
            )}
          </section>
        )}

        {tab === "checklist" && (
          <section>
            <SectionTitle>Insight completeness (P1)</SectionTitle>
            <p className="mt-1 text-xs text-gray-500">
              Confirms every Pre-Approval Packet field is present for this
              recommendation
            </p>
            <ul className="mt-3 space-y-1">
              {rec.insight_checklist.map((item) => (
                <li key={item} className="text-sm text-gray-300">
                  ✓ {item}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* Execution footer */}
      <div className="border-t border-surface-border px-5 py-3 text-sm text-gray-400">
        {executionResult ? (
          <>
            {execStatus === "succeeded" && attempt?.trade_id && (
              <span className="text-status-pass">
                Autonomous open: {attempt.trade_id} ({attempt.order_status})
              </span>
            )}
            {execStatus === "failed" && attempt?.error && (
              <span className="text-status-fail">{attempt.error}</span>
            )}
            {execStatus === "skipped" && (
              <span>Higher-ranked recommendation opened successfully</span>
            )}
            {execStatus === "pending" && <span>Not opened in this cycle</span>}
          </>
        ) : (
          <span>
            Insight packet ready — execution result attaches when{" "}
            <span className="font-mono">fully_autonomous</span>
          </span>
        )}
      </div>
    </Card>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-xs font-medium uppercase tracking-wide text-gray-500">
      {children}
    </h4>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pass" | "warn";
}) {
  return (
    <div className="rounded border border-surface-border/50 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className={
          tone === "pass"
            ? "mt-0.5 font-mono text-sm text-status-pass"
            : tone === "warn"
              ? "mt-0.5 font-mono text-sm text-status-warn"
              : "mt-0.5 font-mono text-sm text-white"
        }
      >
        {value}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:justify-between">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-200 sm:max-w-[65%] sm:text-right">{value}</dd>
    </div>
  );
}

function MiniBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded border border-surface-border/50 px-3 py-3">
      <h5 className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {title}
      </h5>
      <ul className="mt-2 space-y-1">
        {items.map((item) => (
          <li key={item} className="text-xs text-gray-400">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
