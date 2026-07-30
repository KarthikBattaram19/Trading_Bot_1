import { getBotStatus, getLearningDashboard } from "@/lib/api";
import { LearningView } from "@/components/learning/learning-view";
import { SituationalBar } from "@/components/dashboard/situational-bar";

export default async function LearningPage() {
  const [data, status] = await Promise.all([
    getLearningDashboard(),
    getBotStatus(),
  ]);
  return (
    <>
      <SituationalBar status={status} />
      <LearningView initial={data} />
    </>
  );
}
