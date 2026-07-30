import type { InstrumentRecommendation } from "@/types/recommendations";
import { STRATEGY_TYPE_LABELS } from "@/types/recommendations";
import { Badge, Card } from "@/components/ui/primitives";
import { formatPct } from "@/lib/utils";

/** At-a-glance comparison of the top-3 ranked trades. */
export function Top3Comparison({
  recommendations,
}: {
  recommendations: InstrumentRecommendation[];
}) {
  if (recommendations.length === 0) return null;

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-surface-border px-5 py-3">
        <h2 className="text-sm font-medium text-white">Top 3 at a glance</h2>
        <p className="mt-0.5 text-xs text-gray-500">
          Compare score, strategy fit, and key vol signals before drilling into
          each insight packet
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-gray-500">
              <th className="px-4 py-2 font-medium">Rank</th>
              <th className="px-4 py-2 font-medium">Symbol</th>
              <th className="px-4 py-2 font-medium">Strategy</th>
              <th className="px-4 py-2 font-medium">Score</th>
              <th className="px-4 py-2 font-medium">Conf.</th>
              <th className="px-4 py-2 font-medium">IV vs GARCH</th>
              <th className="px-4 py-2 font-medium">IV z</th>
              <th className="px-4 py-2 font-medium">Primary signal</th>
            </tr>
          </thead>
          <tbody>
            {recommendations.map((rec) => {
              const cheap = rec.parameters.iv_annualized < rec.parameters.garch_forecast;
              return (
                <tr
                  key={rec.underlying_symbol}
                  className="border-b border-surface-border/60 last:border-0"
                >
                  <td className="px-4 py-3">
                    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/20 font-mono text-xs font-bold text-accent">
                      #{rec.rank}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-semibold text-white">
                    {rec.underlying_symbol}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="pass">
                      {STRATEGY_TYPE_LABELS[rec.strategy.selected_strategy]}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-white">
                    {rec.score.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 font-mono text-status-pass">
                    {formatPct(rec.confidence, 0)}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    <span className={cheap ? "text-status-pass" : "text-status-warn"}>
                      {formatPct(rec.parameters.iv_annualized)} /{" "}
                      {formatPct(rec.parameters.garch_forecast)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-300">
                    {rec.parameters.iv_z_score != null
                      ? rec.parameters.iv_z_score.toFixed(2)
                      : "—"}
                  </td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-xs text-gray-400">
                    {rec.strategy.primary_signal}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
