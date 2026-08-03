import { getBotStatus } from "@/lib/api";
import { RecommendationsLoader } from "@/components/recommendations/recommendations-loader";
import { SituationalBar } from "@/components/dashboard/situational-bar";

export const dynamic = "force-dynamic";

/**
 * Shell renders immediately (bot status is fast). Recommendation packets are
 * fetched client-side so soft-nav never stalls on a cold enrich cycle.
 */
export default async function RecommendationsPage() {
  const status = await getBotStatus();
  return (
    <>
      <SituationalBar status={status} />
      <RecommendationsLoader />
    </>
  );
}
