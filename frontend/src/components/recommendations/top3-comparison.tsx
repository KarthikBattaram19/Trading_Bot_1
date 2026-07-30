import type { InstrumentRecommendation } from "@/types/recommendations";
import { STRATEGY_TYPE_LABELS } from "@/types/recommendations";
import { Icon } from "@/components/ui/primitives";
import { formatPct } from "@/lib/utils";

/** At-a-glance comparison of the top-3 ranked trades (Stitch: "Top 3 at a glance"). */
export function Top3Comparison({
  recommendations,
}: {
  recommendations: InstrumentRecommendation[];
}) {
  if (recommendations.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-md border border-outline-variant bg-surface">
      <div className="flex items-center justify-between border-b border-outline-variant bg-surface-container-low px-4 py-3">
        <h3 className="text-label-caps uppercase text-on-surface">
          Top 3 at a glance
        </h3>
        <Icon name="table_chart" className="text-[18px] text-on-surface-variant" />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] border-collapse text-left">
          <thead>
            <tr className="bg-surface-container-low">
              {["Rank", "Symbol", "Strategy", "Score", "Conf.", "IV v GARCH", "IV z", "Primary signal"].map(
                (h, i) => (
                  <th
                    key={h}
                    className={`border-b border-outline-variant px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-on-surface-variant ${
                      i >= 3 && i <= 6 ? "text-right" : ""
                    }`}
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody className="font-mono text-[12px]">
            {recommendations.map((rec) => {
              const cheap =
                rec.parameters.iv_annualized < rec.parameters.garch_forecast;
              const top = rec.rank === 1;
              return (
                <tr
                  key={rec.underlying_symbol}
                  className={`border-b border-outline-variant transition-colors last:border-0 hover:bg-surface-container-high ${
                    top ? "bg-primary/5" : ""
                  }`}
                >
                  <td
                    className={`px-3 py-3 font-bold ${top ? "text-primary" : "text-on-surface-variant"}`}
                  >
                    #{rec.rank}
                  </td>
                  <td className="px-3 py-3 text-on-surface">
                    {rec.underlying_symbol}
                  </td>
                  <td className="px-3 py-3">
                    <span className="rounded border border-primary-container/50 bg-primary-container/20 px-2 py-0.5 text-[10px] text-primary">
                      {STRATEGY_TYPE_LABELS[rec.strategy.selected_strategy]}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-bold text-on-surface">
                    {rec.score.toFixed(2)}
                  </td>
                  <td className="px-3 py-3 text-right text-secondary">
                    {formatPct(rec.confidence, 0)}
                  </td>
                  <td
                    className={`px-3 py-3 text-right ${cheap ? "text-secondary" : "text-tertiary"}`}
                  >
                    {formatPct(rec.parameters.iv_annualized)} /{" "}
                    {formatPct(rec.parameters.garch_forecast)}
                  </td>
                  <td className="px-3 py-3 text-right text-on-surface">
                    {rec.parameters.iv_z_score != null
                      ? rec.parameters.iv_z_score.toFixed(2)
                      : "—"}
                  </td>
                  <td className="max-w-[200px] truncate px-3 py-3 text-on-surface-variant">
                    {rec.strategy.primary_signal}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
