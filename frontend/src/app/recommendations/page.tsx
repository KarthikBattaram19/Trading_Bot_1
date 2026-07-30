import { getBotStatus, getRecommendations } from "@/lib/api";
import { RecommendationsView } from "@/components/recommendations/recommendations-view";
import { SituationalBar } from "@/components/dashboard/situational-bar";

export default async function RecommendationsPage() {
  const [data, status] = await Promise.all([
    getRecommendations(),
    getBotStatus(),
  ]);
  return (
    <>
      <SituationalBar status={status} />
      <RecommendationsView initial={data} />
    </>
  );
}
