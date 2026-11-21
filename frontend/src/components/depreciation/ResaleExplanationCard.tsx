import type { ExplanationAmount, ResaleValueExplanation } from "../../types/depreciation";
import { ChevronDown } from "lucide-react";
import { formatCurrency } from "../../lib/formatCurrency";
import { Card } from "../ui/Card";

// F012 explainability add-on: a simple waterfall from the car's new price
// through each factor's SHAP-based contribution (computed server-side) to
// the predicted resale value at the end of the user's selected term. Render
// only when resale_value_explanation is present - TcoReportView renders
// nothing (not an error) when it's null, the same graceful-degradation
// UX already used for the model_degraded badge.
//
// Usage: {report.resale_value_explanation && (
//   <ResaleExplanationCard explanation={report.resale_value_explanation} />
// )}
//
// Run 2 fix batch 3: the factors are always read in this order (the same order
// as the PDF block) - a saved snapshot comes back from a JSON column with its
// keys in a different one, so the order is fixed here rather than taken from the
// object. A factor that reads RM 0.00 is left out, and one an older snapshot
// doesn't have is skipped. The amounts are shown exactly as the server sent them.
//
// Run 3 fix batch 5 (F-03): the server now sends 2-dp strings ("-108726.02");
// a comparison saved earlier holds numbers (-108726.02). Both are read as text -
// the sign from a leading "-", the amount from the rest - so they show the same
// words and no arithmetic is done on them here.

interface ResaleExplanationCardProps {
  explanation: ResaleValueExplanation;
}

type Factor = keyof ResaleValueExplanation["contributions"];

const FACTORS: { key: Factor; label: string }[] = [
  { key: "vehicle_age", label: "Age" },
  { key: "mileage", label: "Mileage" },
  { key: "brand_code", label: "Brand tier" },
  { key: "engine_litres", label: "Engine size" },
  { key: "body_type", label: "Body type" },
  { key: "recond", label: "Recond import" },
];

const ZERO = formatCurrency("0");

// A number (older snapshot) or a 2-dp string (current API) as {negative, magnitude text}; null if it
// isn't an amount at all (missing from an older snapshot, or not a number).
function readAmount(value: ExplanationAmount | undefined): { negative: boolean; magnitude: string } | null {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  if (text === "" || Number.isNaN(Number(text))) return null;
  const negative = text.startsWith("-");
  return { negative, magnitude: text.replace(/^[-+]/, "") };
}

export function ResaleExplanationCard({ explanation }: ResaleExplanationCardProps) {
  const { base_value, contributions, predicted_value } = explanation;
  const rows = FACTORS.flatMap(({ key, label }) => {
    const amount = readAmount(contributions[key]);
    if (amount === null) return [];
    if (formatCurrency(amount.magnitude) === ZERO) return [];
    return [{ key, label, ...amount }];
  });

  // Redesign UI-3: a disclosure, folded by default (native <details>, so it opens
  // with a click, Enter or Space). Every row stays in the page while folded.
  return (
    <Card>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
          <h2 className="text-h3 font-semibold text-ink">Why this predicted value?</h2>
          <ChevronDown className="h-5 w-5 shrink-0 text-ink-muted transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
      <p className="mt-2 text-small text-ink-muted">
        How much each factor moved the value from the new price (worked out on a log scale and shared
        in proportion).
      </p>

      <div className="mt-4 flex flex-col">
        <div className="flex items-center justify-between border-b border-border py-2">
          <span className="text-small text-ink-muted">New price</span>
          <span className="text-small font-medium tabular-nums text-ink">
            {formatCurrency(String(base_value))}
          </span>
        </div>

        {rows.map(({ key, label, negative, magnitude }) => {
          const isPositive = !negative;
          return (
            <div key={key} className="flex items-center justify-between border-b border-border py-2">
              <span className="text-small text-ink-muted">{label}</span>
              <span
                className={
                  isPositive
                    ? "text-small font-medium tabular-nums text-positive-700"
                    : "text-small font-medium tabular-nums text-danger-700"
                }
              >
                {isPositive ? "+" : "-"}
                {formatCurrency(magnitude)}
              </span>
            </div>
          );
        })}

        <div className="flex items-center justify-between pt-2">
          <span className="text-small font-semibold text-ink">Predicted resale value</span>
          <span className="text-body font-semibold tabular-nums text-ink">
            {formatCurrency(String(predicted_value))}
          </span>
        </div>
      </div>
      </details>
    </Card>
  );
}
