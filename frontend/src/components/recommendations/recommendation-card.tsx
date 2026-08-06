"use client";

import { useState } from "react";
import Link from "next/link";
import type { InstrumentRecommendation } from "@/types/recommendations";
import type { AutonomousExecutionResult } from "@/types/trades";
import { rankStatusFromResult } from "@/types/trades";
import {
  ENTRY_MODE_LABELS,
  STRATEGY_TYPE_LABELS,
} from "@/types/recommendations";
import { Icon, StatusPill } from "@/components/ui/primitives";
import { cn, formatPct, liveDecisionId } from "@/lib/utils";
import { StrategyInsightPanel } from "@/components/recommendations/strategy-insight-panel";

const RANK_ACCENT = [
  "border-l-primary",
  "border-l-secondary",
  "border-l-outline",
];

type PillTone = "success" | "warning" | "danger" | "info" | "neutral";

const EXECUTION_BADGE: Record<
  ReturnType<typeof rankStatusFromResult>,
  { label: string; tone: PillTone }
> = {
  pending: { label: "Not executed", tone: "neutral" },
  attempting: { label: "Attempting…", tone: "warning" },
  succeeded: { label: "Trade opened", tone: "success" },
  failed: { label: "Open failed — trying next rank", tone: "danger" },
  skipped: { label: "Skipped (earlier rank succeeded)", tone: "neutral" },
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
  generatedAt,
  supervisionMode,
}: {
  rec: InstrumentRecommendation;
  executionResult?: AutonomousExecutionResult | null;
  /** Response's `generated_at` — needed to build the same `dec_{symbol}_{day}` id the live decision log uses. */
  generatedAt?: string;
  /** Current `SUPERVISION_MODE` — determines whether this packet needs manual approval. */
  supervisionMode?: string;
}) {
  const [tab, setTab] = useState<InsightTab>("overview");
  const rankAccent = RANK_ACCENT[rec.rank - 1] ?? "border-l-outline";
  const strategyLabel = STRATEGY_TYPE_LABELS[rec.strategy.selected_strategy];
  const entryLabel = rec.strategy.entry_mode
    ? ENTRY_MODE_LABELS[rec.strategy.entry_mode] ?? rec.strategy.entry_mode
    : null;

  const gatesPassed = rec.parameter_gates.filter((g) => g.passed).length;
  const gatesTotal = rec.parameter_gates.length;

  const execStatus = rankStatusFromResult(rec.rank, executionResult, false);
  const execBadge = EXECUTION_BADGE[execStatus];
  const attempt = executionResult?.attempts.find((a) => a.rank === rec.rank);

  const cheap = rec.parameters.iv_annualized < rec.parameters.garch_forecast;

  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-md border border-l-4 border-outline-variant bg-surface",
        rankAccent
      )}
    >
      <div className="pointer-events-none absolute right-0 top-0 -z-0 h-64 w-64 -translate-y-1/2 translate-x-1/4 rounded-full bg-primary/5 blur-3xl" />

      {/* Header */}
      <div className="relative border-b border-outline-variant px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 font-mono text-sm font-bold text-primary">
              #{rec.rank}
            </span>
            <div>
              <h3 className="text-lg font-semibold text-on-surface">
                {rec.underlying_symbol}
              </h3>
              <div className="mt-1 flex flex-wrap gap-2">
                <StatusPill tone="info">{strategyLabel}</StatusPill>
                {entryLabel && <StatusPill tone="warning">{entryLabel}</StatusPill>}
                <StatusPill tone="neutral">{rec.strategy.scenario_tag}</StatusPill>
                {executionResult && (
                  <StatusPill tone={execBadge.tone}>{execBadge.label}</StatusPill>
                )}
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">
              Confidence
            </div>
            <div className="font-mono text-lg font-bold text-secondary">
              {formatPct(rec.confidence, 0)}
            </div>
            <div className="font-mono text-[11px] text-outline">
              score {rec.score.toFixed(2)} · gates {gatesPassed}/{gatesTotal}
            </div>
          </div>
        </div>
        <p className="mt-3 text-data-md text-on-surface">{rec.entry_rationale}</p>
        <p className="mt-2 text-data-sm text-primary">{rec.why_this_rank}</p>
      </div>

      {/* Tab bar — underline style (Stitch) */}
      <div className="flex overflow-x-auto border-b border-outline-variant px-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              "whitespace-nowrap border-b-2 px-4 py-3 text-[11px] font-bold uppercase tracking-wider transition-colors",
              tab === t.id
                ? "border-primary text-primary"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-5 p-5">
        {tab === "overview" && (
          <>
            <section>
              <SectionTitle>Market condition (P1.3)</SectionTitle>
              <p className="mt-2 text-data-md text-on-surface">
                {rec.market_summary}
              </p>
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
                <Metric label="Spread" value={`${rec.parameters.spread_pct}%`} />
              </div>
            </section>

            <section>
              <SectionTitle>Strategy fit (Table SH-4)</SectionTitle>
              <div className="mt-2">
                <StrategyInsightPanel rec={rec} />
              </div>
              <p className="mt-3 text-data-sm text-on-surface-variant">
                Matrix: {rec.strategy.cross_strategy_matrix_ref}
              </p>
              {rec.strategy.news_impact && (
                <p className="mt-1 text-data-sm text-tertiary">
                  News: {rec.strategy.news_impact}
                </p>
              )}
            </section>

            <section className="grid gap-4 sm:grid-cols-2">
              <div>
                <SectionTitle>Hedge construction (P1.5)</SectionTitle>
                <dl className="mt-2 space-y-1 text-data-md">
                  <Row label="Method" value={rec.hedge.method} />
                  <Row label="Greek targets" value={rec.hedge.greek_targets} />
                  <Row label="Structure" value={rec.hedge.structure_note} />
                </dl>
              </div>
              <div>
                <SectionTitle>Economics (P1.6)</SectionTitle>
                <dl className="mt-2 space-y-1 text-data-md">
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
                <p className="mt-2 text-data-sm text-on-surface-variant">
                  {rec.economics.net_edge_note}
                </p>
              </div>
            </section>

            {rec.strategy.rejected_strategies.length > 0 && (
              <section>
                <SectionTitle>Why not other strategies</SectionTitle>
                <ul className="mt-2 space-y-1">
                  {rec.strategy.rejected_strategies.map((r) => (
                    <li key={r} className="text-data-sm text-on-surface-variant">
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
            <p className="mt-1 text-data-sm text-on-surface-variant">
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
            <div className="mt-4 rounded-md border border-outline-variant bg-surface-container-low px-4 py-3">
              <div className="flex items-baseline justify-between">
                <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                  Total score
                </span>
                <span className="font-mono text-xl text-on-surface">
                  {rec.score_breakdown.total.toFixed(3)}
                </span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-container-high">
                <div
                  className="h-full rounded-full bg-secondary"
                  style={{
                    width: `${Math.min(100, rec.score_breakdown.total * 100)}%`,
                  }}
                />
              </div>
            </div>
            <ul className="mt-4 space-y-1">
              {rec.score_breakdown.components.map((c) => (
                <li key={c} className="font-mono text-data-sm text-on-surface-variant">
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
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-outline-variant bg-surface-container-low px-3 py-2 text-data-md"
                >
                  <span
                    className={g.passed ? "text-on-surface" : "text-error"}
                  >
                    {g.passed ? "✓" : "✗"} {g.gate_id}: {g.label}
                  </span>
                  <span className="font-mono text-data-sm text-on-surface-variant">
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
                  className="rounded-md border border-outline-variant bg-surface-container-low px-3 py-2 font-mono text-data-sm text-on-surface-variant"
                >
                  {step}
                </li>
              ))}
            </ol>
            {rec.alternative_considered && (
              <p className="mt-3 text-data-sm text-outline">
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
              <p className="text-data-md text-on-surface-variant">
                No learning overlay on this packet yet.
              </p>
            ) : (
              <>
                <p className="text-data-md text-on-surface">
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
                    tone={rec.learning.confidence_penalty > 0 ? "warn" : "pass"}
                  />
                  <Metric
                    label="Module trades"
                    value={String(rec.learning.module_trade_count)}
                  />
                </div>
                {rec.learning.module_win_rate != null && (
                  <p className="text-data-sm text-on-surface-variant">
                    Module win rate {formatPct(rec.learning.module_win_rate, 0)}
                    {rec.learning.module_expectancy_inr != null &&
                      ` · expectancy ${formatInr(rec.learning.module_expectancy_inr)}`}
                  </p>
                )}
                {rec.learning.failure_matches.length > 0 ? (
                  <div className="space-y-3">
                    <SectionTitle>
                      Similar past losses ({rec.learning.failure_matches.length})
                    </SectionTitle>
                    {rec.learning.failure_matches.map((m) => (
                      <div
                        key={m.failure_id}
                        className="rounded-md border border-error/40 bg-error/5 px-3 py-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-on-surface">
                            {m.underlying_symbol}
                          </span>
                          <StatusPill tone="danger">{m.strategy}</StatusPill>
                          <span className="font-mono text-data-sm text-on-surface-variant">
                            sim {formatPct(m.similarity, 0)}
                          </span>
                          <span className="font-mono text-data-sm text-error">
                            {formatInr(m.loss_pnl_inr)}
                          </span>
                        </div>
                        <p className="mt-2 text-data-sm text-on-surface-variant">
                          {m.summary}
                        </p>
                        <p className="mt-2 text-data-sm text-tertiary">
                          Lesson: {m.lesson}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-data-md text-on-surface-variant">
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
            <p className="mt-1 text-data-sm text-on-surface-variant">
              Confirms every Pre-Approval Packet field is present for this
              recommendation
            </p>
            <ul className="mt-3 space-y-1">
              {rec.insight_checklist.map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-2 text-data-md text-on-surface"
                >
                  <Icon name="check_circle" className="text-[16px] text-secondary" filled />
                  {item}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* Execution footer */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-outline-variant px-5 py-3 text-data-md text-on-surface-variant">
        <div className="flex items-center gap-2">
          {executionResult ? (
            <>
              {execStatus === "succeeded" && attempt?.trade_id && (
                <span className="flex items-center gap-2 text-secondary">
                  <Icon name="check_circle" className="text-[16px]" filled />
                  Autonomous open: {attempt.trade_id} ({attempt.order_status})
                </span>
              )}
              {execStatus === "failed" && attempt?.error && (
                <span className="text-error">{attempt.error}</span>
              )}
              {execStatus === "skipped" && (
                <span>Higher-ranked recommendation opened successfully</span>
              )}
              {execStatus === "pending" && <span>Not opened in this cycle</span>}
            </>
          ) : supervisionMode === "fully_autonomous" ? (
            <span className="flex items-center gap-2">
              <Icon name="check_circle" className="text-[16px] text-secondary" filled />
              Insight packet ready — execution result attaches when{" "}
              <span className="font-mono">fully_autonomous</span>
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <Icon name="pending_actions" className="text-[16px] text-tertiary" filled />
              Supervision mode <span className="font-mono">{supervisionMode ?? "supervised"}</span> —
              this trade needs manual approval to open
            </span>
          )}
        </div>

        {!executionResult && supervisionMode !== "fully_autonomous" && generatedAt && (
          <Link
            href={`/decisions/${liveDecisionId(rec.underlying_symbol, generatedAt)}`}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary-container px-4 py-2 text-sm font-medium text-white transition-colors hover:brightness-110"
          >
            <Icon name="fact_check" className="text-[16px]" />
            Review &amp; approve
          </Link>
        )}
      </div>
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
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
    <div className="rounded-md border border-outline-variant bg-surface-container-low px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-on-surface-variant">
        {label}
      </div>
      <div
        className={
          tone === "pass"
            ? "mt-0.5 font-mono text-sm text-secondary"
            : tone === "warn"
              ? "mt-0.5 font-mono text-sm text-tertiary"
              : "mt-0.5 font-mono text-sm text-on-surface"
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
      <dt className="text-on-surface-variant">{label}</dt>
      <dd className="text-on-surface sm:max-w-[65%] sm:text-right">{value}</dd>
    </div>
  );
}

function MiniBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border border-outline-variant bg-surface-container-low px-3 py-3">
      <h5 className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
        {title}
      </h5>
      <ul className="mt-2 space-y-1">
        {items.map((item) => (
          <li key={item} className="text-data-sm text-on-surface-variant">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
