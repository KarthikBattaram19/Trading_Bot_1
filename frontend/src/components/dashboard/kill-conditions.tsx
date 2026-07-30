interface KillConditionsProps {
  conditions: string[];
}

export function KillConditions({ conditions }: KillConditionsProps) {
  return (
    <details className="rounded border border-surface-border/50">
      <summary className="cursor-pointer px-3 py-2 text-sm text-gray-400 hover:text-gray-200">
        Abort if (kill conditions)
      </summary>
      <ul className="list-inside list-disc space-y-1 border-t border-surface-border/50 px-3 py-2 text-sm text-gray-500">
        {conditions.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </details>
  );
}

const DEFAULT_KILL_CONDITIONS = [
  "Liquidity collapses or spreads blow out beyond limits",
  "A hedge leg becomes unavailable",
  "Model input is stale or corrupted",
  "Earnings or news event the setup was not designed to absorb",
  "Required neutrality cannot be restored within cost limits",
  "Core strategy assumption no longer holds",
];

export function SharedKillConditions() {
  return <KillConditions conditions={DEFAULT_KILL_CONDITIONS} />;
}
