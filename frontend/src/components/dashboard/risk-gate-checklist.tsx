import type { RiskGate } from "@/types/decisions";
import { Badge } from "@/components/ui/primitives";

interface RiskGateChecklistProps {
  gates: RiskGate[];
  compact?: boolean;
}

export function RiskGateChecklist({ gates, compact }: RiskGateChecklistProps) {
  const failed = gates.filter((g) => g.status === "fail").length;
  const passed = gates.filter((g) => g.status === "pass").length;
  const approveBlocked = failed > 0;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-label-caps uppercase text-on-surface">
          Pre-flight checklist
        </h3>
        <span className="text-data-sm text-on-surface-variant">
          {passed}/{gates.length} pass
          {approveBlocked && (
            <span className="ml-2 text-error">Approve disabled</span>
          )}
        </span>
      </div>
      <ul className={compact ? "grid gap-2 sm:grid-cols-2" : "space-y-2"}>
        {gates.map((gate) => (
          <li
            key={gate.id}
            className="flex items-start justify-between gap-2 rounded-md border border-outline-variant bg-surface-container-low px-3 py-2 text-data-md"
          >
            <span className="text-on-surface">{gate.label}</span>
            <div className="flex shrink-0 items-center gap-2">
              {gate.detail && (
                <span className="font-mono text-data-sm text-on-surface-variant">
                  {gate.detail}
                </span>
              )}
              <Badge
                variant={
                  gate.status === "pass"
                    ? "pass"
                    : gate.status === "fail"
                      ? "fail"
                      : "warn"
                }
              >
                {gate.status}
              </Badge>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function gatesAllowApprove(gates: RiskGate[]): boolean {
  return !gates.some((g) => g.status === "fail");
}
