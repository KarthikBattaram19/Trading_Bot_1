import { getBotStatus } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { DecisionsLoader } from "@/components/decisions/decisions-loader";

export const dynamic = "force-dynamic";

/**
 * Shell renders immediately. Decision log is client-fetched so navigation does
 * not block on a cold recommendation enrich cycle.
 */
export default async function DecisionsPage() {
  const status = await getBotStatus();
  return (
    <>
      <SituationalBar status={status} />
      <DecisionsLoader oneTradeLocked={Boolean(status.one_trade_locked)} />
    </>
  );
}
