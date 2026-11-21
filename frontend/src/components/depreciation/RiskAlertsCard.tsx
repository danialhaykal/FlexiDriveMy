import type { RiskAlert } from "../../types/depreciation";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

// UC006 step 9's risk alerts - evaluates declared mileage/projected
// equity against plan thresholds. Styled by severity using the same
// warning/info tone conventions as the model_degraded banner above (see
// TcoReportView.tsx) and Badge's own documented tone usage.

interface RiskAlertsCardProps {
  // Live-walkthrough finding: `undefined` for real, not just a defensive
  // type - a scenario saved before Batch 6C added this field has no
  // `risk_alerts` key at all in its stored payload (SavedScenarioPage.tsx
  // renders whatever was actually saved, unchanged).
  alerts: RiskAlert[] | undefined;
}

const SEVERITY_STYLES: Record<RiskAlert["severity"], { border: string; background: string; text: string }> = {
  warning: { border: "border-warning-200", background: "bg-warning-50", text: "text-warning-700" },
  info: { border: "border-primary-200", background: "bg-primary-50", text: "text-primary-700" },
};

export function RiskAlertsCard({ alerts }: RiskAlertsCardProps) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <Card>
      <h2 className="text-h3 font-semibold text-ink">Risk alerts</h2>
      <div className="mt-4 flex flex-col gap-3">
        {alerts.map((alert) => {
          const style = SEVERITY_STYLES[alert.severity];
          return (
            <div
              key={alert.code}
              className={`flex items-start gap-3 rounded-md border ${style.border} ${style.background} p-3`}
            >
              <Badge tone={alert.severity === "warning" ? "warning" : "neutral"}>
                {alert.severity === "warning" ? "Warning" : "Info"}
              </Badge>
              <p className={`text-small ${style.text}`}>{alert.message}</p>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
