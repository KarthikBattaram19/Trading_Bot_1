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
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-border text-xs text-gray-500">
            <th className="py-2 pr-4">Leg</th>
            <th className="py-2 pr-4">Type</th>
            <th className="py-2 pr-4">Qty</th>
            <th className="py-2 pr-4">Strike</th>
            <th className="py-2 pr-4">Exp</th>
            <th className="py-2 pr-4">Mid</th>
            <th className="py-2 pr-4">Δ</th>
            <th className="py-2 pr-4">Γ</th>
            <th className="py-2 pr-4">V</th>
            <th className="py-2">Θ</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg) => (
            <tr key={leg.leg_id} className="border-b border-surface-border/50">
              <td className="py-2 pr-4 font-mono">{leg.leg_id}</td>
              <td className="py-2 pr-4 capitalize">{leg.type}</td>
              <td className="py-2 pr-4 font-mono">{leg.position}</td>
              <td className="py-2 pr-4 font-mono">{leg.strike ?? "—"}</td>
              <td className="py-2 pr-4 font-mono text-xs">{leg.expiration ?? "—"}</td>
              <td className="py-2 pr-4 font-mono">{leg.mid_price?.toFixed(2) ?? "—"}</td>
              <td className="py-2 pr-4 font-mono">{formatGreek(leg.delta)}</td>
              <td className="py-2 pr-4 font-mono">{formatGreek(leg.gamma)}</td>
              <td className="py-2 pr-4 font-mono">{formatGreek(leg.vega)}</td>
              <td className="py-2 font-mono">{formatGreek(leg.theta)}</td>
            </tr>
          ))}
          <tr className="font-medium text-white">
            <td colSpan={6} className="py-2 pr-4 text-right text-gray-500">
              Totals
            </td>
            <td className="py-2 pr-4 font-mono">{formatGreek(totals.total_delta)}</td>
            <td className="py-2 pr-4 font-mono">{formatGreek(totals.total_gamma)}</td>
            <td className="py-2 pr-4 font-mono">{formatGreek(totals.total_vega)}</td>
            <td className="py-2 font-mono">{formatGreek(totals.total_theta)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
