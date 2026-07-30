"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { refreshRecommendations } from "@/lib/api";
import type { RecommendationResponse } from "@/types/recommendations";
import type { AutonomousExecutionResult } from "@/types/trades";
import { FeedStatusPanel } from "@/components/recommendations/feed-status";
import { NewsPanel } from "@/components/recommendations/news-panel";
import { RecommendationCard } from "@/components/recommendations/recommendation-card";
import { AutonomousTradeExecutor } from "@/components/recommendations/autonomous-trade-executor";
import { Top3Comparison } from "@/components/recommendations/top3-comparison";
import { Button, Icon, Panel } from "@/components/ui/primitives";
import { formatTime } from "@/lib/utils";

export function RecommendationsView({
  initial,
}: {
  initial: RecommendationResponse;
}) {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executionResult, setExecutionResult] =
    useState<AutonomousExecutionResult | null>(
      initial.autonomous_execution ?? null,
    );

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await refreshRecommendations();
      setData(next);
      setExecutionResult(next.autonomous_execution ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <main className="flex-1 overflow-y-auto p-margin-page">
      <div className="mx-auto flex max-w-container-max flex-col gap-6">
        {/* Page header */}
        <div className="flex flex-col justify-between gap-4 border-b border-outline-variant pb-6 md:flex-row md:items-end">
          <div>
            <h1 className="text-headline-lg text-on-surface">
              Top 3 trade recommendations
            </h1>
            <p className="mt-2 max-w-2xl text-body-md text-on-surface-variant">
              Complete insight packets generated from multi-gate volatility
              analysis — market condition, strategy fit, score, gates, hedge,
              economics, exit plan, event risks, and learning overlay.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3 font-mono text-data-sm text-on-surface-variant opacity-80">
              <span className="flex items-center gap-1">
                <Icon name="schedule" className="text-[14px]" />
                Generated {formatTime(data.generated_at)} IST
              </span>
              <span>·</span>
              <span>{data.universe_scanned} scanned</span>
              <span>·</span>
              <span>{data.candidates_passing_gates} passed gates</span>
            </div>
          </div>
          <Button variant="primary" disabled={loading} onClick={handleRefresh}>
            <Icon name="refresh" className="text-[18px]" />
            {loading ? "Analyzing…" : "Refresh analysis"}
          </Button>
        </div>

        {error && (
          <div className="rounded-md border border-error/50 bg-error/10 p-3 text-data-md text-error">
            {error}
          </div>
        )}

        <AutonomousTradeExecutor executionResult={executionResult} />

        {/* Bento grid */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left: context */}
          <div className="flex flex-col gap-6 lg:col-span-4">
            <Panel
              title={
                <h3 className="text-label-caps uppercase text-on-surface">
                  Feed Sources
                </h3>
              }
              action={
                <Icon name="sensors" className="text-[18px] text-on-surface-variant" />
              }
            >
              <FeedStatusPanel sources={data.feed_sources} />
            </Panel>

            <NewsPanel news={data.market_news} />

            <div className="rounded-md border border-l-4 border-outline-variant border-l-primary bg-surface p-4">
              <h3 className="text-label-caps uppercase text-on-surface">
                Continual Learning Loop
              </h3>
              <p className="mt-2 text-data-md text-on-surface-variant">
                Each rank includes a Learning tab with failure-memory matches and
                confidence adjustments. Close opened trades on the Learning page
                so wins/losses reshape the next ranking cycle.
              </p>
              <Link
                href="/learning"
                className="mt-3 inline-flex items-center gap-1 text-data-md text-primary hover:underline"
              >
                Open learning cockpit
                <Icon name="arrow_forward" className="text-[16px]" />
              </Link>
            </div>
          </div>

          {/* Right: recommendations */}
          <div className="flex flex-col gap-6 lg:col-span-8">
            <Top3Comparison recommendations={data.recommendations} />

            {data.analysis_notes.length > 0 && (
              <Panel
                title={
                  <h3 className="text-label-caps uppercase text-on-surface">
                    Analysis Notes
                  </h3>
                }
              >
                <ul className="space-y-1">
                  {data.analysis_notes.map((note) => (
                    <li key={note} className="text-data-md text-on-surface-variant">
                      {note}
                    </li>
                  ))}
                </ul>
              </Panel>
            )}

            <div>
              <h2 className="text-headline-md text-on-surface">
                Complete insight packets
              </h2>
              <p className="mt-1 text-data-md text-on-surface-variant">
                Drill into each rank — overview, score, gates, logic trail, plan
                &amp; risks, learning, P1 checklist.
              </p>
            </div>

            {data.recommendations.length === 0 ? (
              <div className="rounded-md border border-outline-variant bg-surface p-8 text-center text-data-md text-on-surface-variant">
                No instruments met the ≥85% confidence floor (after gates,
                strategy fit, and learning penalties). Check analysis notes, feed
                freshness, and failure-memory hits.
              </div>
            ) : (
              <div className="flex flex-col gap-6">
                {data.recommendations.map((rec) => (
                  <RecommendationCard
                    key={rec.underlying_symbol}
                    rec={rec}
                    executionResult={executionResult}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 py-2 text-data-sm text-on-surface-variant">
          <Icon name="check_circle" className="text-[16px] text-secondary" filled />
          Insight packets ready and cached
        </div>
      </div>
    </main>
  );
}
