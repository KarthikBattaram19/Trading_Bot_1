import Link from "next/link";
import { notFound } from "next/navigation";
import { getBotStatus, getDecision } from "@/lib/api";
import { SituationalBar } from "@/components/dashboard/situational-bar";
import { ApprovalCard } from "@/components/dashboard/approval-card";
import { SharedKillConditions } from "@/components/dashboard/kill-conditions";
import { Icon } from "@/components/ui/primitives";

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
      <main className="flex-1 overflow-y-auto p-margin-page">
        <div className="mx-auto flex max-w-4xl flex-col gap-6">
          <div>
            <Link
              href="/decisions"
              className="mb-3 inline-flex items-center gap-1 text-data-sm text-on-surface-variant hover:text-on-surface"
            >
              <Icon name="arrow_back" className="text-[16px]" />
              Back to Decisions
            </Link>
            <h1 className="text-headline-lg text-on-surface">
              Pre-approval packet
            </h1>
            <p className="mt-1 font-mono text-data-sm text-on-surface-variant">
              {decision.decision_id}
            </p>
          </div>
          <ApprovalCard decision={decision} expanded />
          <SharedKillConditions />
        </div>
      </main>
    </>
  );
}
