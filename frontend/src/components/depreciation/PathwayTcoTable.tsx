import type { PathwayTco, PathwayTcoKey } from "../../types/depreciation";
import { formatCurrency } from "../../lib/formatCurrency";
import { Card } from "../ui/Card";
import { InfoExpander } from "../ui/InfoExpander";
import { cn } from "../ui/cn";

// Run 1 fix batch 4 (UC006 step 6): total cost of ownership for every
// pathway, straight from the API's `pathway_tco` - every figure is the
// server's; this only labels and formats them. Owners are compared over 60
// months (resale credited), returners and subscribers over their term, so
// "net cost per month of use" is the fair column to compare.
//
// Redesign UI-3: ONE table (one copy of every figure in the page). From md it
// is a normal table; below md the same rows are restyled as stacked cards -
// the header row is visually hidden (still read by screen readers) and each
// figure shows its column name before it (the cell's data-label).

const ROWS: { key: PathwayTcoKey; label: string; keepsCar: boolean }[] = [
  { key: "hire_purchase", label: "Hire Purchase", keepsCar: true },
  { key: "gfv_retain", label: "GFV - pay the balloon and keep the car", keepsCar: true },
  { key: "gfv_return", label: "GFV - hand the car back", keepsCar: false },
  { key: "subscription", label: "Subscription", keepsCar: false },
];

const COLUMNS = ["What you pay", "What you get back", "Net cost", "Net cost per month of use"] as const;

export const PATHWAY_TCO_NOTE =
  "Net cost per month of use divides each net cost by how long you have the car: 60 months when you keep it, the contract term when it goes back - so the pathways compare fairly.";

function horizonNote(months: number, keepsCar: boolean): string {
  return keepsCar ? `over ${months} months, you keep the car` : `over ${months} months, car returned`;
}

const HEADER_CELL = "px-4 py-2.5 text-caption font-semibold text-ink-muted";
const FIGURE_CELL = cn(
  "flex items-baseline justify-between gap-4 py-1 text-small font-semibold tabular-nums text-ink",
  "before:text-caption before:font-medium before:text-ink-muted before:content-[attr(data-label)]",
  "md:table-cell md:px-4 md:py-3.5 md:text-right md:before:content-none",
);

export function PathwayTcoTable({
  pathwayTco,
  resaleViewsNote,
}: {
  pathwayTco: PathwayTco;
  // Run 2 fix batch 2 (E3): the server's sentence on why the lender's GFV
  // residual and the predicted market value differ. Absent/null renders nothing.
  resaleViewsNote?: string | null;
}) {
  return (
    <Card padding="none">
      <div className="p-4 pb-2 sm:p-6 sm:pb-2">
        <h2 className="text-h3 font-semibold text-ink">Total cost by pathway</h2>
        <p className="mt-1 text-small text-ink-muted">
          What you pay (including running costs), what you get back at the end, and the difference.
        </p>
        {resaleViewsNote && (
          <InfoExpander summary="GFV residual vs. predicted market value" className="mt-2">
            <p>{resaleViewsNote}</p>
          </InfoExpander>
        )}
      </div>
      <table className="w-full border-collapse text-small max-md:block">
        <thead className="border-b border-border max-md:sr-only">
          <tr>
            <th scope="col" className={cn(HEADER_CELL, "text-left")}>
              Pathway
            </th>
            {COLUMNS.map((column) => (
              <th key={column} scope="col" className={cn(HEADER_CELL, "text-right tabular-nums")}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="max-md:flex max-md:flex-col max-md:gap-3 max-md:px-4 max-md:pb-2 md:divide-y md:divide-border">
          {ROWS.map(({ key, label, keepsCar }) => {
            const entry = pathwayTco[key];
            const figures =
              entry.available &&
              entry.gross !== null &&
              entry.amount_back !== null &&
              entry.net !== null &&
              entry.net_per_month !== null
                ? [entry.gross, entry.amount_back, entry.net, entry.net_per_month]
                : null;
            return (
              <tr
                key={key}
                className="max-md:block max-md:rounded-control max-md:border max-md:border-border max-md:bg-page-bg max-md:p-3"
              >
                <td className="text-left max-md:block max-md:pb-1 md:px-4 md:py-3.5">
                  <span className="font-semibold text-ink">{label}</span>
                  {/* Run 1 fix batch 5: an unavailable row shows only its reason,
                      not a horizon the buyer can't actually have. */}
                  {entry.available && (
                    <span className="block text-caption text-ink-muted">{horizonNote(entry.horizon_months, keepsCar)}</span>
                  )}
                </td>
                {figures ? (
                  figures.map((value, index) => (
                    <td key={COLUMNS[index]} data-label={COLUMNS[index]} className={FIGURE_CELL}>
                      {formatCurrency(value)}
                    </td>
                  ))
                ) : (
                  <td colSpan={4} className="max-md:block md:px-4 md:py-3.5">
                    <span className="text-small text-ink-muted">
                      Not available: {entry.unavailable_reason ?? "not offered for this request."}
                    </span>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="px-4 pb-4 pt-2 sm:px-6 sm:pb-6">
        <InfoExpander summary="What is net cost per month of use?">
          <p>{PATHWAY_TCO_NOTE}</p>
        </InfoExpander>
      </div>
    </Card>
  );
}
