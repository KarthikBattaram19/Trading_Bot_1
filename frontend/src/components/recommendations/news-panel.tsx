import type { MarketNewsSummary } from "@/types/recommendations";
import { Badge, Card } from "@/components/ui/primitives";

export function NewsPanel({ news }: { news: MarketNewsSummary }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-white">Market news analysis</h2>
        <Badge variant="default">{news.dominant_sentiment}</Badge>
      </div>
      <p className="mt-2 text-sm text-gray-400">{news.interpretation}</p>

      {news.macro_risk_flags.length > 0 && (
        <ul className="mt-3 space-y-1">
          {news.macro_risk_flags.map((flag) => (
            <li key={flag} className="text-xs text-status-warn">
              ⚠ {flag}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex gap-4 text-xs text-gray-500">
        <span>{news.headline_count} headlines</span>
        <span>{news.earnings_mentions} earnings-related</span>
      </div>

      <ul className="mt-4 max-h-64 space-y-3 overflow-y-auto">
        {news.items.map((item) => (
          <li
            key={item.title}
            className="border-l-2 border-accent/40 pl-3 text-sm"
          >
            <div className="font-medium text-gray-200">{item.title}</div>
            <p className="mt-1 line-clamp-2 text-xs text-gray-500">
              {item.summary}
            </p>
            <div className="mt-1 flex flex-wrap gap-2 text-xs">
              <Badge variant="default">{item.sentiment_label}</Badge>
              {item.tickers.map((t) => (
                <span key={t} className="font-mono text-accent">
                  {t}
                </span>
              ))}
              {item.relevance_to_trade && (
                <span className="text-status-pending">
                  → {item.relevance_to_trade}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
