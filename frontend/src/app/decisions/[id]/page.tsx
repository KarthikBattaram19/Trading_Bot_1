import { notFound } from "next/navigation";
import { getBotStatus, getDecision } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { ApprovalCard } from "@/components/dashboard/approval-card";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function DecisionDetailPage({ params }: PageProps) {
  const { id } = await params;
  const [status, decision] = await Promise.all([
    getBotStatus(),
    getDecision(id),
  ]);

  if (!decision) notFound();

  return (
    <>
      <SituationalBar status={status} />
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-white">Pre-approval packet</h1>
          <p className="mt-1 font-mono text-sm text-gray-500">{decision.decision_id}</p>
        </div>
        <ApprovalCard decision={decision} expanded />
        <SharedKillConditions />
      </div>
    </>
  );
}
