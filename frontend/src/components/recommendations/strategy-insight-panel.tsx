import type { InstrumentRecommendation } from "@/types/recommendations";
import { formatPct } from "@/lib/utils";

/** Strategy-family insight panel for recommendation packets (UI_Dashboard strategy panels). */
export function StrategyInsightPanel({
  rec,
}: {
  rec: InstrumentRecommendation;
}) {
  const p = rec.parameters;
  const st = rec.strategy.selected_strategy;

  if (st === "vega_scalping") {
    return (
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Item
          label="Intraday IV z-score"
          value={p.iv_z_score != null ? p.iv_z_score.toFixed(2) : "—"}
          highlight
        />
        <Item label="Entry rule" value="Long vol at −2σ below intraday mean only" />
        <Item label="Same-day flatten" value="Required (N6.5)" warn />
        <Item label="Stop" value="3σ–4σ below intraday mean" />
        <Item label="IV (mark)" value={formatPct(p.iv_annualized)} />
        <Item label="Theta" value="Largely ignored (intraday)" />
      </dl>
    );
  }

  if (st === "gamma_scalping") {
    return (
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Item
          label="Entry mode"
          value={(rec.strategy.entry_mode ?? "—").replace(/_/g, " ")}
          highlight
        />
        <Item
          label="IV vs GARCH"
          value={`${formatPct(p.iv_annualized)} vs ${formatPct(p.garch_forecast)}`}
        />
        <Item
          label="Term structure"
          value={p.garch_distorted ? "Distorted — caution" : "OK"}
          pass={!p.garch_distorted}
          warn={p.garch_distorted}
        />
        <Item label="Vega neutral at entry" value="Target V≈0" pass />
        <Item
          label="Days to earnings"
          value={p.days_to_earnings != null ? `${p.days_to_earnings}d` : "—"}
        />
        <Item label="Greek target" value="Δ≈0 · V≈0 · Γ+ · Θ−" />
      </dl>
    );
  }

  if (st === "simple_volatility") {
    const cheap = p.iv_annualized < p.garch_forecast;
    return (
      <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Item label="IV (annualized)" value={formatPct(p.iv_annualized)} />
        <Item label="GARCH forecast" value={formatPct(p.garch_forecast)} />
        <Item
          label="Cheap vol signal"
          value={cheap ? "IV < GARCH ✓" : "Not cheap"}
          pass={cheap}
          warn={!cheap}
        />
        <Item label="Greek target" value="Δ≈0 · Γ+ · V+ · Θ−" />
        <Item label="Horizon" value="D+0 / D+1" />
        <Item label="DTE" value={`${p.dte}d`} />
      </dl>
    );
  }

  return (
    <p className="text-data-md text-error">Strategy blocked — do not trade.</p>
  );
}

function Item({
  label,
  value,
  highlight,
  pass,
  warn,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  pass?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="rounded-md border border-outline-variant bg-surface-container-low px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wider text-on-surface-variant">
        {label}
      </dt>
      <dd
        className={
          warn
            ? "mt-0.5 font-medium text-tertiary"
            : pass
              ? "mt-0.5 font-medium text-secondary"
              : highlight
                ? "mt-0.5 font-mono font-medium text-on-surface"
                : "mt-0.5 text-on-surface"
        }
      >
        {value}
      </dd>
    </div>
  );
}
