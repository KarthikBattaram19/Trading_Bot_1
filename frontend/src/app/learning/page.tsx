import { getLearningDashboard } from "@/lib/api";
import { LearningView } from "@/components/learning/learning-view";

export default async function LearningPage() {
  const data = await getLearningDashboard();
  return <LearningView initial={data} />;
}
