import type { StrategyContext } from "@/types/decisions";
import { formatPct } from "@/lib/utils";

export function StatArbPanel({ ctx }: { ctx: StrategyContext }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Item label="Pair Y (long leg)" value={ctx.pair_y ?? "—"} />
      <Item label="Pair X (short leg)" value={ctx.pair_x ?? "—"} />
      <Item label="Residual z-score" value={ctx.residual_z_score?.toFixed(2) ?? "—"} highlight />
      <Item label="Hedge ratio (slope)" value={ctx.hedge_ratio?.toFixed(3) ?? "—"} />
      <Item label="Half-life (days)" value={ctx.half_life_days?.toString() ?? "—"} />
      <Item
        label="Cointegrated windows"
        value={ctx.cointegrated_windows != null ? `${ctx.cointegrated_windows} / 12` : "—"}
      />
      <Item
        label="Economics aligned"
        value={ctx.economics_aligned ? "Yes" : "No — review"}
        warn={ctx.economics_aligned === false}
        pass={ctx.economics_aligned === true}
      />
    </dl>
  );
}

export function VolatilityPanel({ ctx }: { ctx: StrategyContext }) {
  const cheap =
    ctx.iv_annualized != null &&
    ctx.garch_forecast != null &&
    ctx.iv_annualized < ctx.garch_forecast;

  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Item label="IV (annualized)" value={ctx.iv_annualized != null ? `${ctx.iv_annualized}%` : "—"} />
      <Item label="GARCH forecast" value={ctx.garch_forecast != null ? `${ctx.garch_forecast}%` : "—"} />
      <Item label="Cheap vol signal" value={cheap ? "IV < GARCH ✓" : "—"} pass={cheap} />
      <Item
        label="Γ–Θ breakeven"
        value={ctx.gamma_theta_breakeven_pct != null ? formatPct(ctx.gamma_theta_breakeven_pct / 100, 2) : "—"}
      />
      <Item label="Greek target" value="Δ≈0 · Γ+ · V+ · Θ−" />
      <Item label="Horizon" value="D+0 / D+1" />
    </dl>
  );
}

export function GammaPanel({ ctx }: { ctx: StrategyContext }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Item label="Entry mode" value={ctx.entry_mode?.replace(/_/g, " ") ?? "—"} highlight />
      <Item label="IV vs GARCH" value={`${ctx.iv_annualized}% vs ${ctx.garch_forecast}%`} />
      <Item
        label="Term structure"
        value={ctx.term_structure_ok ? "OK" : "Distorted — caution"}
        pass={ctx.term_structure_ok}
        warn={ctx.term_structure_ok === false}
      />
      <Item
        label="Vega neutral at entry"
        value={ctx.vega_neutral_at_entry ? "Yes" : "No"}
        pass={ctx.vega_neutral_at_entry}
      />
      <Item
        label="Γ–Θ breakeven"
        value={ctx.gamma_theta_breakeven_pct != null ? `${ctx.gamma_theta_breakeven_pct}%` : "—"}
      />
      <Item label="Greek target" value="Δ≈0 · V≈0 · Γ+ · Θ−" />
    </dl>
  );
}

export function VegaPanel({ ctx }: { ctx: StrategyContext }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Item label="Intraday IV z-score" value={ctx.intraday_iv_z_score?.toFixed(2) ?? "—"} highlight />
      <Item label="Entry rule" value="Long vol at −2σ below intraday mean only" />
      <Item
        label="Same-day flatten"
        value={ctx.must_flatten_same_day ? "Required" : "—"}
        warn={ctx.must_flatten_same_day}
      />
      <Item label="Stop" value="3σ–4σ below intraday mean" />
      <Item label="Theta" value="Largely ignored (intraday)" />
    </dl>
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
