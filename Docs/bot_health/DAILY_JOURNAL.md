# Recommendation Engine — Daily Journal

Append-only record of what the bot did and what changed, newest entry first.
Written by the `recommendation-engine-analyst` agent after each session.

Entry format — the agent inserts each new `## <YYYY-MM-DD>` section directly
below the `<!-- ENTRIES BELOW -->` marker at the bottom of this preamble, so the
newest entry is always first and this format spec always stays above them:

- **Session summary** — cycles run, recommendations published, trades
  opened/closed, session P&L.
- **Decisions** — every decision the bot made and why (strategy, confidence,
  gates passed/failed).
- **Changes landed** — in-scope commits that day, with SHA and pipeline stage.
- **Recommendations implemented** — pulled from `recommendation_ledger.jsonl`,
  with SHA and current measurement status.
- **Recommended today** — new recommendations, plus running status of all open
  prior ones.

<!-- ENTRIES BELOW -->
