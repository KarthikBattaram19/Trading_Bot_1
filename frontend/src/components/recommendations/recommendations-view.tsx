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
import { Button, Card } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/utils";

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
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white">
            Top 3 trade recommendations
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Complete insight packets for each ranked trade — market condition,
            strategy fit, score breakdown, gates, hedge, economics, exit plan,
            event risks, failure modes, and continual-learning overlay
            (Trading_Parameters P1 + architecture §12)
          </p>
          <p className="mt-1 font-mono text-xs text-gray-600">
            Generated {formatDateTime(data.generated_at)} ·{" "}
            {data.universe_scanned} scanned · {data.candidates_passing_gates}{" "}
            passed gates
          </p>
        </div>
        <Button variant="primary" disabled={loading} onClick={handleRefresh}>
          {loading ? "Analyzing…" : "Refresh analysis"}
        </Button>
      </header>

      {error && (
        <Card className="border-status-fail/50 bg-status-fail/10 p-3 text-sm text-status-fail">
          {error}
        </Card>
      )}

      <AutonomousTradeExecutor executionResult={executionResult} />

      <Card className="border-l-4 border-accent p-4">
        <h2 className="text-sm font-medium text-white">
          Continual learning loop
        </h2>
        <p className="mt-1 text-sm text-gray-400">
          Each rank includes a Learning tab with failure-memory matches and
          confidence adjustments. Close opened trades on the Learning page so
          wins/losses reshape the next ranking cycle.
        </p>
        <Link
          href="/learning"
          className="mt-3 inline-block text-sm text-accent hover:underline"
        >
          Open learning cockpit →
        </Link>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-3 text-sm font-medium text-white">Feed sources</h2>
          <FeedStatusPanel sources={data.feed_sources} />
        </Card>
        <NewsPanel news={data.market_news} />
      </div>

      {data.analysis_notes.length > 0 && (
        <Card className="p-4">
          <h2 className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Analysis notes
          </h2>
          <ul className="mt-2 space-y-1">
            {data.analysis_notes.map((note) => (
              <li key={note} className="text-sm text-gray-400">
                {note}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Top3Comparison recommendations={data.recommendations} />

      <section className="space-y-6">
        <div>
          <h2 className="text-lg font-medium text-white">
            Complete insight packets
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Drill into each rank — overview, score, gates, logic trail, plan
            &amp; risks, learning from past outcomes, P1 checklist
          </p>
        </div>

        {data.recommendations.length === 0 ? (
          <Card className="p-8 text-center text-gray-500">
            No instruments met the ≥85% confidence floor (after gates, strategy
            fit, and learning penalties). Check analysis notes, feed freshness,
            and failure-memory hits.
          </Card>
        ) : (
          data.recommendations.map((rec) => (
            <RecommendationCard
              key={rec.underlying_symbol}
              rec={rec}
              executionResult={executionResult}
            />
          ))
        )}
      </section>
    </div>
  );
}
