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

const DEFAULT_KILL_CONDITIONS = [
  "India VIX spikes > 25% within 5 minutes",
  "Broker API latency exceeds 2000ms for 3 consecutive pings",
  "Combined portfolio drawdown exceeds 15%",
  "A hedge leg becomes unavailable",
  "Model input is stale or corrupted",
  "Required neutrality cannot be restored within cost limits",
];

export function SharedKillConditions() {
  return (
    <KillConditions
      conditions={DEFAULT_KILL_CONDITIONS}
      title="Shared Kill Conditions"
    />
  );
}
