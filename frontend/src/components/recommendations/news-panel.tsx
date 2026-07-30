import type { MarketNewsSummary } from "@/types/recommendations";
import { Icon, Panel, StatusPill } from "@/components/ui/primitives";

function sentimentTone(label: string): "success" | "warning" | "danger" | "neutral" {
  const l = label.toLowerCase();
  if (l.includes("bull") || l.includes("positive")) return "success";
  if (l.includes("bear") || l.includes("negative")) return "danger";
  if (l.includes("neutral") || l.includes("caution")) return "warning";
  return "neutral";
}

export function NewsPanel({ news }: { news: MarketNewsSummary }) {
  return (
    <Panel
      title={
        <h3 className="text-label-caps uppercase text-on-surface">
          Market News Analysis
        </h3>
      }
      action={
        <StatusPill tone={sentimentTone(news.dominant_sentiment)}>
          {news.dominant_sentiment}
        </StatusPill>
      }
    >
      <p className="text-data-sm leading-relaxed text-on-surface-variant">
        {news.interpretation}
      </p>

      {news.macro_risk_flags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {news.macro_risk_flags.map((flag) => (
            <span
              key={flag}
              className="rounded border border-tertiary/30 bg-tertiary/15 px-2 py-1 text-[10px] font-medium uppercase text-tertiary"
            >
              {flag}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 flex gap-4 text-data-sm text-on-surface-variant">
        <span>{news.headline_count} headlines</span>
        <span>{news.earnings_mentions} earnings-related</span>
      </div>

      <ul className="mt-4 max-h-72 space-y-3 overflow-y-auto pr-1">
        {news.items.map((item) => (
          <li key={item.title} className="flex flex-col gap-1">
            <div className="flex items-start justify-between gap-2">
              <span className="truncate text-data-sm text-on-surface">
                {item.title}
              </span>
              <span
                className={
                  sentimentTone(item.sentiment_label) === "success"
                    ? "shrink-0 text-[10px] font-semibold uppercase text-secondary"
                    : sentimentTone(item.sentiment_label) === "danger"
                      ? "shrink-0 text-[10px] font-semibold uppercase text-error"
                      : "shrink-0 text-[10px] font-semibold uppercase text-tertiary"
                }
              >
                {item.sentiment_label}
              </span>
            </div>
            <p className="line-clamp-2 text-[11px] text-on-surface-variant opacity-80">
              {item.summary}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {item.tickers.map((t) => (
                <span key={t} className="font-mono text-[10px] text-primary">
                  {t}
                </span>
              ))}
              {item.relevance_to_trade && (
                <span className="flex items-center gap-1 text-[10px] text-tertiary">
                  <Icon name="arrow_forward" className="text-[12px]" />
                  {item.relevance_to_trade}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
