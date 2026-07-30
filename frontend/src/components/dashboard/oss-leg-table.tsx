import type { OptionLeg } from "@/types/decisions";
import { formatGreek } from "@/lib/utils";

interface OssLegTableProps {
  legs: OptionLeg[];
  totals: {
    total_delta: number;
    total_gamma: number;
    total_theta: number;
    total_vega: number;
  };
}

export function OssLegTable({ legs, totals }: OssLegTableProps) {
  return (
    <div className="overflow-hidden rounded-md border border-outline-variant">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-data-md">
          <thead>
            <tr className="border-b border-outline-variant bg-surface-container-low text-label-caps uppercase text-on-surface-variant">
              <th className="p-3 font-normal">Leg</th>
              <th className="p-3 font-normal">Type</th>
              <th className="p-3 text-right font-normal">Qty</th>
              <th className="p-3 text-right font-normal">Strike</th>
              <th className="p-3 font-normal">Exp</th>
              <th className="p-3 text-right font-normal">Mid</th>
              <th className="p-3 text-right font-normal">Δ</th>
              <th className="p-3 text-right font-normal">Γ</th>
              <th className="p-3 text-right font-normal">ν</th>
              <th className="p-3 text-right font-normal">Θ</th>
            </tr>
          </thead>
          <tbody className="font-mono text-on-surface">
            {legs.map((leg) => (
              <tr
                key={leg.leg_id}
                className="border-b border-outline-variant transition-colors hover:bg-surface-container-high"
              >
                <td className="p-3">{leg.leg_id}</td>
                <td className="p-3 font-sans capitalize text-on-surface-variant">
                  {leg.type}
                </td>
                <td className="p-3 text-right">{leg.position}</td>
                <td className="p-3 text-right">{leg.strike ?? "—"}</td>
                <td className="p-3 text-data-sm text-on-surface-variant">
                  {leg.expiration ?? "—"}
                </td>
                <td className="p-3 text-right">
                  {leg.mid_price?.toFixed(2) ?? "—"}
                </td>
                <td className="p-3 text-right">{formatGreek(leg.delta)}</td>
                <td className="p-3 text-right">{formatGreek(leg.gamma)}</td>
                <td className="p-3 text-right">{formatGreek(leg.vega)}</td>
                <td className="p-3 text-right">{formatGreek(leg.theta)}</td>
              </tr>
            ))}
            <tr className="bg-surface-container-low font-mono font-semibold text-on-surface">
              <td colSpan={6} className="p-3 text-right text-on-surface-variant">
                Totals
              </td>
              <td className="p-3 text-right">{formatGreek(totals.total_delta)}</td>
              <td className="p-3 text-right">{formatGreek(totals.total_gamma)}</td>
              <td className="p-3 text-right">{formatGreek(totals.total_vega)}</td>
              <td className="p-3 text-right">{formatGreek(totals.total_theta)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
