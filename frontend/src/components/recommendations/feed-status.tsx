import type { FeedSource } from "@/types/recommendations";
import { Badge } from "@/components/ui/primitives";
import { formatTime } from "@/lib/utils";

/** ICICI Direct + Market_News feed health (no MCP copy — plan §1 / 0.3). */
export function FeedStatusPanel({ sources }: { sources: FeedSource[] }) {
  if (!sources?.length) {
    return (
      <p className="text-sm text-gray-500">No feed sources reported.</p>
    );
  }

  return (
    <ul className="space-y-3">
      {sources.map((src) => (
        <li
          key={src.source_id}
          className="flex flex-wrap items-start justify-between gap-2 rounded border border-surface-border px-3 py-2"
        >
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-white">{src.source_name}</span>
              <Badge
                variant={
                  src.status === "active"
                    ? "pass"
                    : src.status === "stub"
                      ? "warn"
                      : "fail"
                }
              >
                {src.status}
              </Badge>
              <Badge
                variant={
                  src.health === "fresh"
                    ? "pass"
                    : src.health === "stale"
                      ? "warn"
                      : "fail"
                }
              >
                {src.health}
              </Badge>
            </div>
            <div className="mt-1 text-xs text-gray-500">
              {src.capabilities.join(" · ")}
            </div>
            {src.detail && (
              <div className="mt-1 text-xs text-gray-400">{src.detail}</div>
            )}
          </div>
          {src.last_fetch_at && (
            <span className="font-mono text-xs text-gray-600">
              {formatTime(src.last_fetch_at)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
