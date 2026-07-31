import { Icon } from "@/components/ui/primitives";

interface KillConditionsProps {
  conditions: string[];
  title?: string;
}

export function KillConditions({
  conditions,
  title = "Abort if (kill conditions)",
}: KillConditionsProps) {
  return (
    <details className="group rounded-md border border-outline-variant bg-surface-container">
      <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-label-caps uppercase text-on-surface-variant outline-none">
        {title}
        <Icon
          name="expand_more"
          className="transition-transform group-open:rotate-180"
        />
      </summary>
      <ul className="list-inside list-disc space-y-1 border-t border-outline-variant px-4 py-3 text-data-sm text-on-surface">
        {conditions.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </details>
  );
}

/** Matches Docs/Trading_Strategies.md Shared Kill Conditions. */
const DEFAULT_KILL_CONDITIONS = [
  "liquidity collapses or spreads blow out beyond limits",
  "a hedge leg becomes unavailable",
  "the model input is stale or clearly corrupted",
  "an earnings or news event appears that the setup was not designed to absorb",
  "required neutrality cannot be restored within cost limits",
  "residual delta or vega exposure exceeds portfolio limits",
  "the strategy's core assumption no longer holds",
];

export function SharedKillConditions({
  conditions,
}: {
  conditions?: string[];
} = {}) {
  const list = conditions && conditions.length > 0 ? conditions : DEFAULT_KILL_CONDITIONS;
  return (
    <KillConditions conditions={list} title="Shared Kill Conditions" />
  );
}
