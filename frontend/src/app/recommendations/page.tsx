import { getRecommendations } from "@/lib/api";
import { RecommendationsView } from "@/components/recommendations/recommendations-view";

export default async function RecommendationsPage() {
  const data = await getRecommendations();
  return <RecommendationsView initial={data} />;
}
