import type { FeedSource } from "@/types/recommendations";
import { StatusPill } from "@/components/ui/primitives";
import { formatTime } from "@/lib/utils";

/** ICICI Direct + Market_News feed health (no MCP copy — plan §1 / 0.3). */
export function FeedStatusPanel({ sources }: { sources: FeedSource[] }) {
  if (!sources?.length) {
    return (
      <p className="text-data-sm text-on-surface-variant">
        No feed sources reported.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {sources.map((src) => (
        <li
          key={src.source_id}
          className="flex flex-wrap items-start justify-between gap-2 rounded-md border border-outline-variant bg-surface-container-low px-3 py-2"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={
                  src.status === "active"
                    ? "h-2 w-2 shrink-0 rounded-full bg-secondary"
                    : src.status === "stub"
                      ? "h-2 w-2 shrink-0 rounded-full bg-tertiary"
                      : "h-2 w-2 shrink-0 rounded-full bg-error"
                }
              />
              <span className="font-medium text-on-surface">
                {src.source_name}
              </span>
              <StatusPill
                tone={
                  src.status === "active"
                    ? "success"
                    : src.status === "stub"
                      ? "warning"
                      : "danger"
                }
              >
                {src.status}
              </StatusPill>
              <StatusPill
                tone={
                  src.health === "fresh"
                    ? "info"
                    : src.health === "stale"
                      ? "warning"
                      : "danger"
                }
              >
                {src.health}
              </StatusPill>
            </div>
            <div className="mt-1 text-data-sm text-on-surface-variant">
              {src.capabilities.join(" · ")}
            </div>
            {src.detail && (
              <div className="mt-1 text-data-sm text-outline">{src.detail}</div>
            )}
          </div>
          {src.last_fetch_at && (
            <span className="font-mono text-data-sm text-outline">
              {formatTime(src.last_fetch_at)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
