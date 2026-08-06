"use client";

import { useEffect, useState } from "react";
import { getRecommendations } from "@/lib/api";
import type { RecommendationResponse } from "@/types/recommendations";
import { RecommendationsView } from "@/components/recommendations/recommendations-view";
import { Icon } from "@/components/ui/primitives";

export function RecommendationsLoader({
  supervisionMode,
}: {
  supervisionMode: string;
}) {
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getRecommendations();
        if (!cancelled) setData(next);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load recommendations");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto max-w-container-max rounded-md border border-error/50 bg-error/10 p-4 text-data-md text-error">
          Could not load recommendations: {error}
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="flex flex-1 items-center justify-center p-margin-page">
        <div className="flex items-center gap-3 text-body-md text-on-surface-variant">
          <Icon name="progress_activity" className="animate-spin text-[22px]" />
          Analyzing live feeds for top-3 recommendations…
        </div>
      </main>
    );
  }

  return <RecommendationsView initial={data} supervisionMode={supervisionMode} />;
}
